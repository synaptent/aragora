"""Old aragora.services spam paths re-export the objects that moved to aragora.moderation.spam."""

from __future__ import annotations

import ast
import importlib
import inspect
import os
import subprocess
import sys
from pathlib import Path

import pytest

import aragora.moderation.spam as new_spam
import aragora.services.spam as old_spam
import aragora.services.spam_classifier as old_compat

REPO_ROOT = Path(__file__).resolve().parents[2]

# Public names of each aragora/services/spam/<name>.py before the move (none had __all__).
SUBMODULE_NAMES = {
    "classifier": (
        "SpamClassifier",
        "classify_email",
        "classify_email_spam",
        "classify_emails_batch",
    ),
    "features": ("SpamFeatures",),
    "model": ("NaiveBayesClassifier",),
    "models": (
        "EmailFeatures",
        "SpamCategory",
        "SpamClassificationResult",
        "SpamClassifierConfig",
        "SpamFeedback",
    ),
    "patterns": (
        "DANGEROUS_EXTENSIONS",
        "FREE_EMAIL_PROVIDERS",
        "KNOWN_SPAM_DOMAINS",
        "MONEY_WORDS",
        "PROMOTIONAL_PATTERNS",
        "REQUIRED_HEADERS",
        "SPAM_WORDS",
        "SUSPICIOUS_TLDS",
        "URGENCY_WORDS",
        "URL_SHORTENERS",
    ),
    "scoring": (
        "check_phishing",
        "determine_category",
        "score_attachments",
        "score_content",
        "score_headers",
        "score_patterns",
        "score_sender",
        "score_subject",
        "score_urls",
    ),
}
# Names each old submodule also exposed because it imported them from a sibling spam module.
SUBMODULE_SIBLING_NAMES = {
    "classifier": (
        "NaiveBayesClassifier",
        "PROMOTIONAL_PATTERNS",
        "SpamCategory",
        "SpamClassificationResult",
        "SpamClassifierConfig",
        "SpamFeatures",
        "determine_category",
        "score_attachments",
        "score_content",
        "score_headers",
        "score_patterns",
        "score_sender",
        "score_subject",
        "score_urls",
    ),
    "features": (
        "DANGEROUS_EXTENSIONS",
        "EmailFeatures",
        "FREE_EMAIL_PROVIDERS",
        "KNOWN_SPAM_DOMAINS",
        "MONEY_WORDS",
        "REQUIRED_HEADERS",
        "SPAM_WORDS",
        "SUSPICIOUS_TLDS",
        "URGENCY_WORDS",
        "URL_SHORTENERS",
    ),
    "scoring": ("EmailFeatures", "SpamCategory", "SpamClassifierConfig"),
}
# __all__ of aragora/services/spam/__init__.py before the move.
PACKAGE_NAMES = (
    "SpamClassifier",
    "SpamClassifierConfig",
    "SpamClassificationResult",
    "SpamCategory",
    "SpamFeatures",
    "EmailFeatures",
    "NaiveBayesClassifier",
    "SpamFeedback",
    "classify_email",
    "classify_email_spam",
    "classify_emails_batch",
    "SPAM_WORDS",
    "URGENCY_WORDS",
    "MONEY_WORDS",
    "SUSPICIOUS_TLDS",
    "KNOWN_SPAM_DOMAINS",
    "FREE_EMAIL_PROVIDERS",
    "URL_SHORTENERS",
    "DANGEROUS_EXTENSIONS",
    "PROMOTIONAL_PATTERNS",
    "REQUIRED_HEADERS",
)

PAIRS = (
    [
        (f"aragora.services.spam.{sub}", f"aragora.moderation.spam.{sub}", name)
        for sub, names in SUBMODULE_NAMES.items()
        for name in names
    ]
    + [
        (f"aragora.services.spam.{sub}", f"aragora.moderation.spam.{sub}", name)
        for sub, names in SUBMODULE_SIBLING_NAMES.items()
        for name in names
    ]
    + [("aragora.services.spam", "aragora.moderation.spam", name) for name in PACKAGE_NAMES]
    + [
        ("aragora.services.spam_classifier", "aragora.moderation.spam", name)
        for name in PACKAGE_NAMES
    ]
)


@pytest.mark.parametrize(("old", "new", "name"), PAIRS)
def test_old_path_reexports_identical_object(old: str, new: str, name: str) -> None:
    value = getattr(importlib.import_module(old), name)
    assert value is getattr(importlib.import_module(new), name)
    if inspect.isclass(value) or inspect.isfunction(value):
        home = inspect.getmodule(value)
        assert home is not None and home.__name__.startswith("aragora.moderation.spam.")


def test_old_path_all_lists_unchanged() -> None:
    assert old_spam.__all__ == list(PACKAGE_NAMES)
    assert new_spam.__all__ == list(PACKAGE_NAMES)
    for sub, names in SUBMODULE_NAMES.items():
        shim = importlib.import_module(f"aragora.services.spam.{sub}")
        expected = set(names) | set(SUBMODULE_SIBLING_NAMES.get(sub, ()))
        assert sorted(shim.__all__) == sorted(expected)


def test_fixed_input_scoring_at_both_paths() -> None:
    old_scoring = importlib.import_module("aragora.services.spam.scoring")
    new_scoring = importlib.import_module("aragora.moderation.spam.scoring")
    features = old_spam.EmailFeatures(
        subject_all_caps=True,
        subject_excessive_punctuation=True,
        subject_spam_words=2,
        subject_length=3,
    )
    assert old_scoring.score_subject(features) == pytest.approx(0.9)
    assert new_scoring.score_subject(features) == old_scoring.score_subject(features)

    config = new_spam.SpamClassifierConfig()
    old_reasons: list[str] = []
    new_reasons: list[str] = []
    old_result = old_scoring.determine_category(0.95, "hello", features, old_reasons, config)
    new_result = new_scoring.determine_category(0.95, "hello", features, new_reasons, config)
    assert old_result == new_result
    assert old_result[0] is new_spam.SpamCategory.SPAM
    assert old_reasons == new_reasons


def test_fixed_input_model_at_both_paths() -> None:
    old_model = importlib.import_module("aragora.services.spam.model").NaiveBayesClassifier()
    new_model = new_spam.NaiveBayesClassifier()
    for model in (old_model, new_model):
        model.train("win free money now claim your prize", is_spam=True)
        model.train("meeting agenda for the quarterly review", is_spam=False)
    assert old_model.predict("free money prize") == new_model.predict("free money prize")
    assert old_model.predict("free money prize")[0] is True


def _run(code: str) -> str:
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=env,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return result.stdout


@pytest.mark.parametrize(
    "first", ["aragora.services", "aragora.services.spam.classifier", "aragora.moderation"]
)
def test_identity_holds_in_every_import_order(first: str) -> None:
    out = _run(
        f"import importlib; importlib.import_module({first!r})\n"
        "import aragora.services.spam_classifier as c\n"
        "import aragora.services.spam.classifier as oc\n"
        "from aragora.moderation import spam as n\n"
        "from aragora.moderation.spam import classifier as nc\n"
        "assert c.SpamClassifier is oc.SpamClassifier is n.SpamClassifier is nc.SpamClassifier\n"
        "print('ok')\n"
    )
    assert out.strip() == "ok"


def test_moderation_spam_import_does_not_load_services() -> None:
    out = _run(
        "import sys\n"
        "import aragora.moderation.spam\n"
        "print(sorted(m for m in sys.modules if m.startswith('aragora.services')))\n"
    )
    assert out.strip() == "[]"


def _is_type_checking_guard(node: ast.If) -> bool:
    test = node.test
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


def _runtime_imports(path: Path) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []

    def visit(node: ast.AST) -> None:
        if isinstance(node, ast.If) and _is_type_checking_guard(node):
            for child in node.orelse:
                visit(child)
            return
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.append((node.lineno, node.module))
            if node.module == "aragora":
                found.extend((node.lineno, f"aragora.{alias.name}") for alias in node.names)
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in {"import_module", "__import__"} and isinstance(node.args[0].value, str):
                found.append((node.lineno, node.args[0].value))
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
    return found


MOVED_MODULES = [f"aragora/moderation/spam/{sub}.py" for sub in SUBMODULE_NAMES] + [
    "aragora/moderation/spam/__init__.py"
]
FLIPPED_SITES = ["aragora/moderation/spam_integration.py"]


@pytest.mark.parametrize("relative_path", MOVED_MODULES + FLIPPED_SITES)
def test_no_runtime_import_of_services(relative_path: str) -> None:
    offenders = [
        f"{relative_path}:{lineno} {module}"
        for lineno, module in _runtime_imports(REPO_ROOT / relative_path)
        if ".".join(module.split(".")[:2]) == "aragora.services"
    ]
    assert offenders == []
