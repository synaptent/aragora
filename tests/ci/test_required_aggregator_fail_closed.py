"""Guard the required-check aggregators against fail-OPEN conclusions.

Every required context in this repo is produced by the same three-job shape::

    changes / scope   -> classifies whether the work is in scope (a boolean output)
    <name>-run        -> the real worker, gated on `if: needs.<classifier>.outputs.<flag> == 'true'`
    <name>            -> the *required* aggregator, `if: always()`, reporting the verdict

The aggregator is the job whose name lands on the branch-protection list, so it
alone decides whether the required context is green. Historically each one
rejected a single worker result::

    if [[ "${{ needs.typecheck-run.result }}" == "failure" ]]; then exit 1; fi

That is fail-OPEN. GitHub's `needs.<job>.result` is one of `success`, `failure`,
`cancelled`, or `skipped`, and a job that is cancelled, timed out, or never
scheduled reports something *other* than `failure` — so it was converted into a
green required context.

This is not hypothetical. Issue #9084 records the exact instance: PR #8939 at head
`f8335380d1c7b25f2a6cb433e786e3e2b343a130`, Lint run 29059352439, where worker job
86257629023 was cancelled mid-typecheck and required aggregator job 86257810837
still succeeded. The typecheck the PR existed to validate never ran, and the gate
said it had.

The `skipped` result is the subtle half. A skip is legitimate *only* when the
classifier explicitly said the worker was out of scope. A skip while the
classifier said `true` means the worker was required and never ran — which must
be red, not green. So the aggregator has to consult the classifier's output, not
just the worker's result; the classifier is already in `needs` but its verdict
was never read.

## Why this test executes the script instead of matching it

Two guards in this repo shipped green while blind to the very thing they guarded:
the merge-quorum vocabulary guard (#9640) matched assignment syntax and missed the
dict-literal form, and the ssh-stdin guard matched `-n` inside a *remote* command
(`tail -n 1`) and so passed against the un-fixed workflow. Both were string
matching a proxy for the behavior.

This guard runs the aggregator's actual shell body under simulated `needs`
results and asserts the exit status, so it tests the semantics that GitHub will
execute. It is deliberately agnostic about *how* the fix is written: it resolves
`${{ }}` expressions whether they appear inline in `run:` or in the step's `env:`
block, so a rewrite that moves interpolation into `env:` (which is also the safer
quoting posture) stays covered.

## Detection scope of the coverage sweep

The sweep at the bottom detects the required-context aggregator shape exactly: a
literal `if: always()` guard and exactly two `needs` (worker + classifier). That
is the shape every required context uses. Aggregator-shaped jobs OUTSIDE that
shape — compound `if:` expressions that embed `always()` (e.g.
security-gate.yml::security-summary), or `needs` counts other than two (e.g.
backup-verification.yml::summary) — are not detected here. At least one such job
repeats the #9084 pattern today: security-summary's `validate_gate_result` maps
`cancelled` to OK, a pre-existing fail-open in a non-required context that
predates this guard (2026-02-25). That hole, and generalizing the sweep to
compound-`if`/arbitrary-`needs` aggregators, are owned by the follow-up feature
misc-security-gate-cancelled-tolerance-fix — deliberately not fixed in this PR.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"


@dataclass(frozen=True)
class Aggregator:
    """One required-check aggregator and the classifier contract it must honor."""

    workflow: str
    job: str
    worker: str
    classifier: str
    scope_flag: str
    required_context: bool
    # quality-smoke additionally gates its worker on `!github.event.pull_request.draft`,
    # so on a *draft* PR an in-scope skip is legitimate there and nowhere else.
    defers_on_draft: bool = False


AGGREGATORS: tuple[Aggregator, ...] = (
    Aggregator("lint.yml", "lint", "lint-run", "changes", "python", True),
    Aggregator("lint.yml", "typecheck", "typecheck-run", "changes", "python", True),
    Aggregator("openapi.yml", "generate", "generate-run", "scope", "run_openapi", True),
    Aggregator("sdk-parity.yml", "sdk-parity", "sdk-parity-run", "changes", "relevant", True),
    Aggregator(
        "sdk-test.yml", "typescript-sdk", "typescript-sdk-run", "changes", "run_typescript", True
    ),
    Aggregator(
        "quality-smoke.yml",
        "quality-smoke",
        "quality-smoke-run",
        "changes",
        "quality",
        required_context=False,
        defers_on_draft=True,
    ),
)

# GitHub only ever reports these four in `needs.<job>.result`, but a required gate
# should also refuse anything it does not recognize rather than defaulting to green.
NON_SUCCESS_WORKER_RESULTS = ("failure", "cancelled", "timed_out", "action_required", "stale")
MALFORMED_SCOPE_FLAGS = (
    "",
    " ",
    "\t",
    "TRUE",
    "False",
    " true",
    "false ",
    "yes",
    "unexpected",
)

_EXPRESSION = re.compile(r"\$\{\{\s*(?P<body>[^}]+?)\s*\}\}")
_RESULT_REF = re.compile(r"^needs\.(?P<job>[A-Za-z0-9_-]+)\.result$")
_OUTPUT_REF = re.compile(r"^needs\.(?P<job>[A-Za-z0-9_-]+)\.outputs\.(?P<name>[A-Za-z0-9_-]+)$")
# The one non-`needs` signal an aggregator may legitimately read: whether the PR is a
# draft. Matching the whole `event_name == 'pull_request' && ....draft || 'false'`
# idiom rather than the bare field keeps any *other* github-context read unsupported,
# so a future aggregator cannot smuggle in an unsimulated input.
_DRAFT_REF = re.compile(
    r"^github\.event_name == 'pull_request' &&\s*"
    r"github\.event\.pull_request\.draft \|\| 'false'$"
)


def _load_job(spec: Aggregator) -> dict:
    workflow = yaml.safe_load((WORKFLOWS_DIR / spec.workflow).read_text(encoding="utf-8"))
    jobs = workflow["jobs"]
    assert spec.job in jobs, f"{spec.workflow}: aggregator job '{spec.job}' is gone"
    return jobs[spec.job]


def _resolve(
    expression: str,
    spec: Aggregator,
    worker_result: str,
    classifier_result: str,
    scope_flag: str,
    is_draft: str,
) -> str:
    """Resolve a single `${{ ... }}` body against the simulated run state."""
    if _DRAFT_REF.match(" ".join(expression.split())):
        assert spec.defers_on_draft, (
            f"{spec.workflow}::{spec.job} reads the draft flag but is not declared "
            "defers_on_draft — a gate that silently defers on drafts is a fail-open path."
        )
        return is_draft

    result_match = _RESULT_REF.match(expression)
    if result_match:
        job = result_match.group("job")
        if job == spec.worker:
            return worker_result
        if job == spec.classifier:
            return classifier_result
        raise AssertionError(
            f"{spec.workflow}::{spec.job} reads needs.{job}.result, which this guard "
            "does not simulate — extend the Aggregator spec so the new dependency is covered."
        )

    output_match = _OUTPUT_REF.match(expression)
    if output_match:
        job, name = output_match.group("job"), output_match.group("name")
        if job == spec.classifier and name == spec.scope_flag:
            return scope_flag
        raise AssertionError(
            f"{spec.workflow}::{spec.job} reads needs.{job}.outputs.{name}, which this guard "
            "does not simulate — extend the Aggregator spec so the new signal is covered."
        )

    raise AssertionError(
        f"{spec.workflow}::{spec.job} uses unsupported expression '{expression}'. "
        "A required aggregator must decide only from its dependencies' results and outputs."
    )


def _run_aggregator(
    spec: Aggregator,
    *,
    worker_result: str,
    classifier_result: str,
    scope_flag: str,
    is_draft: str = "false",
) -> subprocess.CompletedProcess[str]:
    """Execute the aggregator's real shell body under a simulated run state."""
    job = _load_job(spec)
    steps = [step for step in job.get("steps", []) if "run" in step]
    assert steps, f"{spec.workflow}::{spec.job} has no run steps to evaluate"

    def resolve_all(text: str) -> str:
        return _EXPRESSION.sub(
            lambda m: _resolve(
                m.group("body"), spec, worker_result, classifier_result, scope_flag, is_draft
            ),
            text,
        )

    # Each `run:` is a separate shell; GitHub stops the job at the first non-zero
    # step, so `&&`-chaining reproduces that short-circuit faithfully.
    script_parts: list[str] = []
    env: dict[str, str] = {"GITHUB_STEP_SUMMARY": "/dev/null", "PATH": "/usr/bin:/bin"}
    for step in steps:
        for key, value in (step.get("env") or {}).items():
            env[key] = resolve_all(str(value))
        script_parts.append(resolve_all(step["run"]))

    script = "\n".join(f"(\n{part}\n) || exit $?" for part in script_parts)
    return subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, env=env, timeout=60
    )


def _ids(specs: tuple[Aggregator, ...]) -> list[str]:
    return [f"{s.workflow}::{s.job}" for s in specs]


@pytest.mark.parametrize("spec", AGGREGATORS, ids=_ids(AGGREGATORS))
def test_in_scope_success_is_green(spec: Aggregator) -> None:
    """The honest pass: classifier says in scope, worker succeeded."""
    proc = _run_aggregator(
        spec, worker_result="success", classifier_result="success", scope_flag="true"
    )
    assert proc.returncode == 0, (
        f"{spec.workflow}::{spec.job} rejected a legitimate success "
        f"(exit {proc.returncode}).\n{proc.stdout}\n{proc.stderr}"
    )


@pytest.mark.parametrize("spec", AGGREGATORS, ids=_ids(AGGREGATORS))
def test_out_of_scope_skip_is_green(spec: Aggregator) -> None:
    """The honest skip: classifier explicitly said the worker was not required."""
    proc = _run_aggregator(
        spec, worker_result="skipped", classifier_result="success", scope_flag="false"
    )
    assert proc.returncode == 0, (
        f"{spec.workflow}::{spec.job} rejected a legitimate scope skip "
        f"(exit {proc.returncode}).\n{proc.stdout}\n{proc.stderr}"
    )


@pytest.mark.parametrize("spec", AGGREGATORS, ids=_ids(AGGREGATORS))
@pytest.mark.parametrize("scope_flag", MALFORMED_SCOPE_FLAGS, ids=repr)
def test_successful_classifier_with_malformed_scope_fails_closed(
    spec: Aggregator, scope_flag: str
) -> None:
    """A successful classifier must still publish an exact boolean verdict.

    Missing output is represented by the empty string in GitHub expressions. The
    other cases cover whitespace, mixed case, and arbitrary values that must not be
    mistaken for an explicit out-of-scope decision merely because they are not
    equal to ``"true"``.
    """
    proc = _run_aggregator(
        spec,
        worker_result="skipped",
        classifier_result="success",
        scope_flag=scope_flag,
    )
    assert proc.returncode != 0, (
        f"{spec.workflow}::{spec.job} reported SUCCESS after its classifier succeeded "
        f"but published malformed scope output {scope_flag!r}.\n{proc.stdout}"
    )


@pytest.mark.parametrize("spec", AGGREGATORS, ids=_ids(AGGREGATORS))
@pytest.mark.parametrize("worker_result", ("success", *NON_SUCCESS_WORKER_RESULTS))
def test_out_of_scope_requires_worker_to_be_skipped(spec: Aggregator, worker_result: str) -> None:
    """Exact false is green only when the worker was actually skipped."""
    proc = _run_aggregator(
        spec,
        worker_result=worker_result,
        classifier_result="success",
        scope_flag="false",
    )
    assert proc.returncode != 0, (
        f"{spec.workflow}::{spec.job} reported SUCCESS for exact out-of-scope output "
        f"while its worker concluded '{worker_result}'.\n{proc.stdout}"
    )


@pytest.mark.parametrize("spec", AGGREGATORS, ids=_ids(AGGREGATORS))
@pytest.mark.parametrize("worker_result", NON_SUCCESS_WORKER_RESULTS)
def test_incomplete_worker_fails_closed(spec: Aggregator, worker_result: str) -> None:
    """A worker that did not succeed must never yield a green required context.

    `cancelled` is the #9084 instance verbatim; `timed_out` and the rest are the
    same hole with a different label.
    """
    proc = _run_aggregator(
        spec, worker_result=worker_result, classifier_result="success", scope_flag="true"
    )
    assert proc.returncode != 0, (
        f"{spec.workflow}::{spec.job} reported SUCCESS while its worker "
        f"'{spec.worker}' was '{worker_result}'. A required gate that passes without "
        f"checking is worse than no gate (#9084).\n{proc.stdout}"
    )


@pytest.mark.parametrize("spec", AGGREGATORS, ids=_ids(AGGREGATORS))
def test_skip_while_in_scope_fails_closed(spec: Aggregator) -> None:
    """A skip is only honest when the classifier said out-of-scope.

    Worker skipped while the scope flag is 'true' on a non-draft PR means the check was
    required and never ran — the failure mode #9084's acceptance criteria calls out
    explicitly. Draft deferral is covered separately below.
    """
    proc = _run_aggregator(
        spec,
        worker_result="skipped",
        classifier_result="success",
        scope_flag="true",
        is_draft="false",
    )
    assert proc.returncode != 0, (
        f"{spec.workflow}::{spec.job} reported SUCCESS while '{spec.worker}' was skipped "
        f"even though the classifier said it was in scope.\n{proc.stdout}"
    )


@pytest.mark.parametrize(
    "spec",
    [s for s in AGGREGATORS if s.defers_on_draft],
    ids=_ids(tuple(s for s in AGGREGATORS if s.defers_on_draft)),
)
def test_draft_deferral_is_green_but_only_for_drafts(spec: Aggregator) -> None:
    """The one legitimate in-scope skip: the worker itself declines to run on drafts."""
    proc = _run_aggregator(
        spec,
        worker_result="skipped",
        classifier_result="success",
        scope_flag="true",
        is_draft="true",
    )
    assert proc.returncode == 0, (
        f"{spec.workflow}::{spec.job} rejected a legitimate draft deferral "
        f"(exit {proc.returncode}).\n{proc.stdout}\n{proc.stderr}"
    )


@pytest.mark.parametrize(
    "spec",
    [s for s in AGGREGATORS if s.defers_on_draft],
    ids=_ids(tuple(s for s in AGGREGATORS if s.defers_on_draft)),
)
def test_draft_does_not_excuse_an_incomplete_worker(spec: Aggregator) -> None:
    """Draft deferral must not become a blanket amnesty.

    If the worker actually ran and was cancelled, `draft` is not the reason it is
    missing, and the gate must still fail closed.
    """
    proc = _run_aggregator(
        spec,
        worker_result="cancelled",
        classifier_result="success",
        scope_flag="true",
        is_draft="true",
    )
    assert proc.returncode != 0, (
        f"{spec.workflow}::{spec.job} reported SUCCESS for a cancelled worker just "
        f"because the PR is a draft.\n{proc.stdout}"
    )


@pytest.mark.parametrize("spec", AGGREGATORS, ids=_ids(AGGREGATORS))
@pytest.mark.parametrize("classifier_result", ["failure", "cancelled", "skipped", "timed_out"])
def test_broken_classifier_fails_closed(spec: Aggregator, classifier_result: str) -> None:
    """If classification did not complete, its scope verdict cannot be trusted.

    An empty scope flag is what GitHub actually supplies when the classifier never
    produced outputs, so a gate that treats "not 'true'" as "out of scope" would
    silently go green on classifier failure.
    """
    proc = _run_aggregator(
        spec, worker_result="skipped", classifier_result=classifier_result, scope_flag=""
    )
    assert proc.returncode != 0, (
        f"{spec.workflow}::{spec.job} reported SUCCESS while its classifier "
        f"'{spec.classifier}' was '{classifier_result}' and produced no scope verdict.\n"
        f"{proc.stdout}"
    )


# The five non-quorum required contexts on branch protection. The sixth required
# context, `aragora-merge-quorum`, judges the merge packet rather than `needs`
# results, so it is not an aggregator in this file's sense.
REQUIRED_CONTEXT_NAMES = frozenset(
    {"lint", "typecheck", "sdk-parity", "Generate & Validate", "TypeScript SDK Type Check"}
)


def _context_name(spec: Aggregator) -> str:
    """The status-context string branch protection sees: `name:` if set, else the job key."""
    job = _load_job(spec)
    return str(job.get("name") or spec.job)


def test_required_context_flags_match_branch_protection_names() -> None:
    """`required_context` must agree with the branch-protection context list.

    This pins two things: every spec marked required really produces one of the five
    protected non-quorum context names (so the executed guard above is exercising the
    actual gate), and the required specs collectively cover all five (so deleting a
    spec cannot silently drop a required gate from coverage).
    """
    for spec in AGGREGATORS:
        name = _context_name(spec)
        if spec.required_context:
            assert name in REQUIRED_CONTEXT_NAMES, (
                f"{spec.workflow}::{spec.job} is marked required_context=True but its "
                f"context name '{name}' is not on the branch-protection list "
                f"{sorted(REQUIRED_CONTEXT_NAMES)}. Fix the spec or the workflow name."
            )
        else:
            assert name not in REQUIRED_CONTEXT_NAMES, (
                f"{spec.workflow}::{spec.job} is marked required_context=False but "
                f"'{name}' IS a protected context — mark it required so a regression "
                "in this gate is treated as a regression in a required gate."
            )
    produced = {_context_name(s) for s in AGGREGATORS if s.required_context}
    assert produced == REQUIRED_CONTEXT_NAMES, (
        "The required aggregators no longer cover the protected context list exactly: "
        f"missing={sorted(REQUIRED_CONTEXT_NAMES - produced)}, "
        f"unexpected={sorted(produced - REQUIRED_CONTEXT_NAMES)}."
    )


# `aragora-review` is fail-open *on purpose*: it downgrades a non-success worker to a
# `::warning::` and exits 0, and it is not a required context. Excluding it keeps this
# guard focused on gates that claim to block. The exclusion is not free — the companion
# assertion below re-fires if the job ever stops declaring itself advisory, so it cannot
# quietly become a required gate while sitting on the exemption list.
ADVISORY_AGGREGATORS: dict[tuple[str, str], str] = {
    ("aragora-review-gate.yml", "aragora-review"): "not blocking merge",
}


@pytest.mark.parametrize(
    ("location", "advisory_marker"), sorted(ADVISORY_AGGREGATORS.items()), ids=lambda v: str(v)
)
def test_advisory_exemption_still_declares_itself_advisory(
    location: tuple[str, str], advisory_marker: str
) -> None:
    """An exempted aggregator must keep saying out loud that it does not block."""
    workflow_name, job_name = location
    workflow = yaml.safe_load((WORKFLOWS_DIR / workflow_name).read_text(encoding="utf-8"))
    job = workflow["jobs"][job_name]
    body = " ".join(str(step.get("run", "")) for step in job.get("steps", []))
    assert advisory_marker in body, (
        f"{workflow_name}::{job_name} is exempt from the fail-closed guard because it is "
        f"advisory, but it no longer says '{advisory_marker}'. If it now blocks merges, "
        "move it into AGGREGATORS instead of leaving it exempt."
    )


def test_new_required_shape_aggregator_is_covered() -> None:
    """Catch a new aggregator in the *required-context shape* being added unguarded.

    Without this, someone copies the three-job shape into a sixth required check and
    the guard above stays green purely because the new job is not in AGGREGATORS.

    Detection is bounded to the shape every required context uses: a literal
    `if: always()` and exactly two `needs`. Aggregator-shaped jobs outside that
    shape (compound `if:` such as security-gate.yml::security-summary, or other
    `needs` counts such as backup-verification.yml::summary) are NOT detected —
    see the module docstring; generalizing the sweep is owned by
    misc-security-gate-cancelled-tolerance-fix, together with the known
    pre-existing cancelled-tolerant fail-open it must close.
    """
    covered = {(s.workflow, s.job) for s in AGGREGATORS} | set(ADVISORY_AGGREGATORS)
    suspects: list[tuple[str, str]] = []
    for path in sorted(WORKFLOWS_DIR.glob("*.yml")):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(workflow, dict):
            continue
        for name, job in (workflow.get("jobs") or {}).items():
            if not isinstance(job, dict) or str(job.get("if", "")).strip() != "always()":
                continue
            needs = job.get("needs")
            if not isinstance(needs, list) or len(needs) != 2:
                continue
            body = " ".join(str(step.get("run", "")) for step in job.get("steps", []))
            if ".result" not in body and "_RESULT" not in body:
                continue
            if (path.name, name) not in covered:
                suspects.append((path.name, name))

    assert not suspects, (
        "Un-guarded always()/two-needs aggregator(s) that judge a dependency's result: "
        f"{suspects}. Add them to AGGREGATORS so their fail-closed behavior is proven."
    )


def test_known_out_of_shape_fail_open_debt_is_still_present() -> None:
    """Pin the known blind spot so it cannot silently rot in either direction.

    security-gate.yml::security-summary is an aggregator OUTSIDE the sweep's
    detection shape (compound `if:` embedding `always()`), and its
    `validate_gate_result` maps `cancelled` to OK — the same #9084 class this file
    exists to kill, pre-existing since 2026-02-25 in a non-required context. This
    PR documents it instead of fixing it; the fix belongs to
    misc-security-gate-cancelled-tolerance-fix.

    Two assertions, both load-bearing. First, the job still sits outside the
    sweep's shape (compound `if:` — if it migrates into the literal-always()/
    two-needs shape, the coverage sweep takes over and this pin is stale). Second,
    the cancelled-tolerant mapping is still present — when the follow-up closes
    the hole, this test fails and must be removed with it, so the debt record
    cannot outlive the debt.
    """
    workflow = yaml.safe_load((WORKFLOWS_DIR / "security-gate.yml").read_text(encoding="utf-8"))
    job = workflow["jobs"]["security-summary"]

    if_expression = str(job.get("if", "")).strip()
    assert "always()" in if_expression and if_expression != "always()", (
        "security-gate.yml::security-summary no longer uses a compound always() "
        "guard. It now matches (or nearly matches) the sweep's detection shape — "
        "add it to AGGREGATORS/ADVISORY_AGGREGATORS as appropriate and delete this "
        "debt pin."
    )

    body = "\n".join(str(step.get("run", "")) for step in job.get("steps", []))
    assert re.search(r"success\|cancelled\|skipped\)\s*return 0", body), (
        "security-gate.yml::security-summary no longer maps cancelled to OK — the "
        "known fail-open debt this test documents has been fixed (thank you, "
        "misc-security-gate-cancelled-tolerance-fix). Delete this test and extend "
        "AGGREGATORS coverage to the fixed job instead."
    )
