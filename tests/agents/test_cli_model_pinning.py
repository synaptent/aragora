"""``SENDS_MODEL_ON_WIRE`` is opt-IN, and the opt-ins are enumerated.

Wave-6 re-review, minor 4 (on #9989). The flag licenses a receipt to say
which model made a decision, so its default has to be the answer that is
safe when nobody thought about it. It used to default to True: a CLI agent
that never puts ``self.model`` on its command line -- one added later here,
or a subclass out of tree -- inherited the claim and had its answer
attributed to a model the CLI never received.

It now defaults to False, and each class that really sends the model says so
next to the code that sends it. That makes the True set finite and checkable,
which is what this module checks: over EVERY ``CLIAgent`` descendant defined
anywhere under ``aragora/``, not just the ones registered in
``aragora/agents/cli_agents.py``. ``aragora/audit/exploration/agents.py``
defines two (``ExplorationAgent``, ``VerifierAgent``) that no registry-scoped
guard would have seen, and one of them runs ``echo``.

The sweep is AST-based rather than import-based on purpose: importing every
module under ``aragora/`` to enumerate subclasses costs ~10s and initializes
half the product's on-disk state. It is also SOUND here -- with the base
defaulting to False, the only way any class can be True is a literal
assignment in some class body, so enumerating the assignments enumerates the
claims.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "aragora"

# Every class under aragora/ allowed to claim its model reaches the CLI, and
# the flag it puts on the command line. Adding a CLI agent that pins its
# model means adding it here; adding one that does NOT means changing
# nothing, because False is now what it inherits.
EXPECTED_PINNED: dict[str, str] = {
    "ClaudeAgent": "--model",
    "CodexAgent": "-m",
    "GeminiCLIAgent": "-m",
    "GrokCLIAgent": "-m",
    "AntigravityAgent": "--model",
    "OpenAIAgent": "-m",
}

# Declared False explicitly even though False is now the default: each one
# carries its own comment saying WHY its CLI is not pinned, and deleting the
# line would delete the reason.
EXPECTED_UNPINNED = {
    "DeepseekCLIAgent",
    "GrokBuildAgent",
    "KiloCodeAgent",
    "KimiCLIAgent",
    "QwenCLIAgent",
}

FLAG = "SENDS_MODEL_ON_WIRE"


def _assignments() -> dict[tuple[str, str], bool | None]:
    """Every ``SENDS_MODEL_ON_WIRE`` assignment under ``aragora/``.

    Keyed by ``(module path, enclosing class)``; the value is the assigned
    constant, or ``None`` when it is not a plain ``True``/``False`` literal
    (which the caller treats as a failure -- the flag has to be readable off
    the class, not computed).
    """
    found: dict[tuple[str, str], bool | None] = {}
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if FLAG not in text:
            continue
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for stmt in node.body:
                targets: list[ast.expr] = []
                if isinstance(stmt, ast.Assign):
                    targets = list(stmt.targets)
                elif isinstance(stmt, ast.AnnAssign):
                    targets = [stmt.target]
                if not any(isinstance(t, ast.Name) and t.id == FLAG for t in targets):
                    continue
                value = getattr(stmt, "value", None)
                literal = (
                    value.value
                    if isinstance(value, ast.Constant) and isinstance(value.value, bool)
                    else None
                )
                key = (path.relative_to(PACKAGE_ROOT.parent).as_posix(), node.name)
                found[key] = literal
    return found


def test_the_base_class_default_is_false() -> None:
    """The whole point: an agent nobody thought about claims nothing."""
    from aragora.agents.cli_agents import CLIAgent

    assert CLIAgent.SENDS_MODEL_ON_WIRE is False


def test_only_the_enumerated_classes_claim_a_wire_pin() -> None:
    """Drift guard. A new CLI agent that pins its model must be added here;
    one that does not needs no change at all, because it inherits False."""
    claiming = {cls for (_path, cls), value in _assignments().items() if value is True}
    assert claiming == set(EXPECTED_PINNED), (
        "SENDS_MODEL_ON_WIRE=True set drifted. Unexpected: "
        f"{sorted(claiming - set(EXPECTED_PINNED))}; missing: "
        f"{sorted(set(EXPECTED_PINNED) - claiming)}"
    )


def test_every_assignment_is_a_plain_boolean_literal() -> None:
    """A computed flag cannot be audited by reading the class."""
    computed = [key for key, value in _assignments().items() if value is None]
    assert not computed, f"SENDS_MODEL_ON_WIRE is not a literal at: {computed}"


def test_the_explicit_false_declarations_are_the_documented_ones() -> None:
    """These keep their redundant ``= False`` because each line carries the
    reason its CLI is not pinned; the base class itself declares the default."""
    declared_false = {cls for (_path, cls), value in _assignments().items() if value is False}
    assert declared_false == EXPECTED_UNPINNED | {"CLIAgent"}


@pytest.mark.parametrize(("attr", "flag"), sorted(EXPECTED_PINNED.items()))
def test_a_claiming_agent_really_puts_its_model_on_the_command_line(attr, flag) -> None:
    """The claim and the command builder are two statements of one fact.

    Read off the SOURCE of the class's own ``generate`` (the OpenAI CLI agent
    builds its argv inline, the others via a ``base_command`` list), so this
    fails if a builder stops sending the model while the flag stays True.
    """
    import inspect

    import aragora.agents.cli_agents as cli_agents

    source = inspect.getsource(getattr(cli_agents, attr).generate)
    assert "self.model" in source, f"{attr} claims a wire pin but never reads self.model"
    assert flag in source, f"{attr} claims a wire pin but never passes {flag}"


def test_every_cli_agent_descendant_is_accounted_for() -> None:
    """No CLIAgent descendant anywhere under aragora/ is unclassified.

    Found by resolving base-class names to a fixpoint, so a subclass of a
    subclass in another module (``VerifierAgent(ExplorationAgent)`` in
    ``aragora/audit/exploration/agents.py``) is caught too.
    """
    classes: dict[str, list[str]] = {}
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ClassDef):
                classes[node.name] = [b.id for b in node.bases if isinstance(b, ast.Name)]

    descendants = {"CLIAgent"}
    changed = True
    while changed:
        changed = False
        for name, bases in classes.items():
            if name not in descendants and descendants.intersection(bases):
                descendants.add(name)
                changed = True
    descendants.discard("CLIAgent")

    # Every descendant is either an enumerated claimer, an enumerated
    # exemption, or silent -- and silent now means False.
    unclassified = descendants - set(EXPECTED_PINNED) - EXPECTED_UNPINNED
    assert unclassified == {"ExplorationAgent", "VerifierAgent"}, (
        "a CLIAgent descendant appeared or vanished; classify it (True next to the "
        f"code that sends the model, or leave it to inherit False): {sorted(unclassified)}"
    )
    # ...and the two that inherit really do get False, which is the fix:
    # under the old default they claimed a wire pin while VerifierAgent runs
    # `echo`.
    from aragora.audit.exploration.agents import ExplorationAgent, VerifierAgent

    assert ExplorationAgent.SENDS_MODEL_ON_WIRE is False
    assert VerifierAgent.SENDS_MODEL_ON_WIRE is False
