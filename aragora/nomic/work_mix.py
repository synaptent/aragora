"""
Work-mix classification and budget for the self-improvement loop.

Classifies merged work into product-core / product-proof / substrate /
maintenance from diff paths against a checked-in module map, computes the
rolling merged-work mix, and evaluates it against the work-mix budget
(product >= 50%, substrate <= 25% over a 7-day window). A budget breach
recommends the substrate-freeze marker that goal selection honors.

The deterministic path classifier here is the anti-gaming baseline: it is
computed from diff content, not labels or commit messages. Phase 2 (issue
#9045) layers an LLM classifier of record on top ("use real intelligence,
not regex"); disagreements between the two are surfaced for the weekly
spot-audit rather than silently resolved.

Plan: docs/plans/2026-07-08-vision-audit-and-work-mix-governor.md (section 4).
Part of epic #9039 (issue #9040). Advisory only: nothing in this module
changes gate or selection behavior.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum


class WorkClass(str, Enum):
    """The four work classes the mix budget is computed over."""

    PRODUCT_CORE = "product-core"
    PRODUCT_PROOF = "product-proof"
    SUBSTRATE = "substrate"
    MAINTENANCE = "maintenance"


# Longest-prefix wins. Order within this list does not matter; specificity does.
# Substrate = the machine that builds the product (gates, conductors, quorum
# tooling, loop meta-docs). Product-proof = externally consumable evidence
# (artifacts, specs, compliance packs, the standalone verifier docs).
_PREFIX_CLASSES: tuple[tuple[str, WorkClass], ...] = (
    # -- substrate: loop/gate machinery and its meta-docs
    ("scripts/", WorkClass.SUBSTRATE),
    ("aragora/swarm/", WorkClass.SUBSTRATE),
    ("aragora/nomic/", WorkClass.SUBSTRATE),
    ("aragora/missions/", WorkClass.SUBSTRATE),
    ("aragora/harnesses/", WorkClass.SUBSTRATE),
    ("aragora/worktree/", WorkClass.SUBSTRATE),
    (".github/", WorkClass.SUBSTRATE),
    ("docs/runbooks/", WorkClass.SUBSTRATE),
    ("docs/plans/", WorkClass.SUBSTRATE),
    ("docs/prompts/", WorkClass.SUBSTRATE),
    ("docs/strategy/", WorkClass.SUBSTRATE),
    # -- product-proof: evidence an outsider can consume
    ("docs/artifacts/", WorkClass.PRODUCT_PROOF),
    ("docs/specs/", WorkClass.PRODUCT_PROOF),
    ("docs/compliance/", WorkClass.PRODUCT_PROOF),
    ("docs/api/", WorkClass.PRODUCT_PROOF),
    ("docs/guides/", WorkClass.PRODUCT_PROOF),
    ("docs/verticals/", WorkClass.PRODUCT_PROOF),
    ("benchmarks/", WorkClass.PRODUCT_PROOF),
    ("aragora-verify/", WorkClass.PRODUCT_PROOF),
    # Published user-facing docs (Docusaurus site) are product output, not
    # repo maintenance (#9047 openai [P2] round 7).
    ("docs-site/", WorkClass.PRODUCT_PROOF),
    # -- maintenance: keeps the lights on, neither product nor loop
    ("tests/", WorkClass.MAINTENANCE),
    ("requirements", WorkClass.MAINTENANCE),
    ("pyproject.toml", WorkClass.MAINTENANCE),
    ("uv.lock", WorkClass.MAINTENANCE),
    (".pre-commit-config.yaml", WorkClass.MAINTENANCE),
    ("docs/", WorkClass.MAINTENANCE),
    # -- product-core: the runtime users touch (catch-all for aragora/)
    ("aragora/", WorkClass.PRODUCT_CORE),
    ("sdk/", WorkClass.PRODUCT_CORE),
)

# Markers that exempt a change from the budget entirely (always admissible):
# main-red repair, security fixes, reverts. Exemption is a gaming surface
# (an exempt merge is excluded from the mix), so it is deliberately narrow:
# security/incident exemption requires a LABEL (applied via repo tooling and
# auditable), never free-text title. Title prefixes are honored only for
# reverts and main-red repair, whose truthfulness is externally checkable
# (the reverted commit / the red run). Exempt merges stay in the ledger and
# are surfaced in the digest spot-audit.
_EXEMPT_LABELS = frozenset({"security", "main-red", "incident"})
_EXEMPT_TITLE_PREFIXES = ("revert", "fix(main-red)")


def classify_path(path: str) -> WorkClass:
    """Classify a single repo-relative path by longest matching prefix."""
    best: tuple[int, WorkClass] | None = None
    for prefix, work_class in _PREFIX_CLASSES:
        if path.startswith(prefix) and (best is None or len(prefix) > best[0]):
            best = (len(prefix), work_class)
    return best[1] if best else WorkClass.MAINTENANCE


@dataclass
class ClassifiedWork:
    """Classification of one unit of merged work (typically a PR)."""

    identifier: str
    work_class: WorkClass
    file_counts: dict[WorkClass, int]
    rationale: str
    exempt: bool = False
    # Set when an injected LLM classifier disagreed with the path baseline;
    # surfaced in the weekly spot-audit, never silently resolved.
    cross_check_disagreement: str | None = None


def classify_paths(
    paths: Sequence[str],
    *,
    identifier: str = "",
    title: str = "",
    labels: Iterable[str] = (),
    weights: Mapping[str, int] | None = None,
    llm_classifier: Callable[[Sequence[str], str], WorkClass | None] | None = None,
) -> ClassifiedWork:
    """Classify a set of changed paths into a single dominant work class.

    ``weights`` maps each path to its lines changed (additions + deletions).
    When provided, dominance is decided by lines rather than file count, so
    trivial one-line edits to product files cannot launder a substantive
    substrate change below the half guard. Without weights, each path counts
    as 1 (the file-count fallback).

    Ties and mixed changes resolve conservatively: if substrate weight is at
    least half the change, the change is substrate.

    ``llm_classifier`` (Phase 2) becomes the classifier of record when it
    returns a class; the path baseline is kept as the cross-check and any
    disagreement is recorded on the result.
    """
    counts: dict[WorkClass, int] = dict.fromkeys(WorkClass, 0)
    weighted: dict[WorkClass, int] = dict.fromkeys(WorkClass, 0)
    for path in paths:
        cls = classify_path(path)
        counts[cls] += 1
        # A zero-line file (e.g. rename) still counts as weight 1.
        weighted[cls] += max(1, (weights or {}).get(path, 1))
    total = sum(weighted.values())
    unit = "lines" if weights else "paths"

    label_set = {label.lower() for label in labels}
    exempt = bool(label_set & _EXEMPT_LABELS) or title.lower().startswith(_EXEMPT_TITLE_PREFIXES)

    if total == 0:
        baseline = WorkClass.MAINTENANCE
        rationale = "no changed paths"
    elif weighted[WorkClass.SUBSTRATE] * 2 >= total:
        baseline = WorkClass.SUBSTRATE
        rationale = f"substrate {unit} are {weighted[WorkClass.SUBSTRATE]}/{total} of the change"
    else:
        # Dominant class by weight; ties resolve toward substrate first
        # (conservative), then core, proof, maintenance.
        precedence = (
            WorkClass.SUBSTRATE,
            WorkClass.PRODUCT_CORE,
            WorkClass.PRODUCT_PROOF,
            WorkClass.MAINTENANCE,
        )
        baseline = max(precedence, key=lambda cls: (weighted[cls], -precedence.index(cls)))
        rationale = f"dominant class by {unit} ({weighted[baseline]}/{total})"

    work_class = baseline
    disagreement = None
    if llm_classifier is not None:
        llm_class = llm_classifier(paths, title)
        if llm_class is not None:
            work_class = llm_class
            if llm_class is not baseline:
                disagreement = f"llm={llm_class.value} vs path-baseline={baseline.value}"

    return ClassifiedWork(
        identifier=identifier,
        work_class=work_class,
        file_counts=counts,
        rationale=rationale,
        exempt=exempt,
        cross_check_disagreement=disagreement,
    )


@dataclass
class MixBudget:
    """The work-mix budget the rolling merged-PR mix must satisfy."""

    product_min: float = 0.50
    substrate_max: float = 0.25
    window_days: int = 7


@dataclass
class MixReport:
    """Shares of merged work by class over a window."""

    counts: dict[WorkClass, int]
    total: int
    window_days: int

    def share(self, work_class: WorkClass) -> float:
        return self.counts[work_class] / self.total if self.total else 0.0

    @property
    def product_share(self) -> float:
        return self.share(WorkClass.PRODUCT_CORE) + self.share(WorkClass.PRODUCT_PROOF)

    @property
    def substrate_share(self) -> float:
        return self.share(WorkClass.SUBSTRATE)


def compute_mix(
    classified: Iterable[ClassifiedWork],
    *,
    window_days: int = 7,
    exclude_exempt: bool = True,
) -> MixReport:
    """Compute the class mix over already-windowed classified work."""
    counts: dict[WorkClass, int] = dict.fromkeys(WorkClass, 0)
    for work in classified:
        if exclude_exempt and work.exempt:
            continue
        counts[work.work_class] += 1
    return MixReport(counts=counts, total=sum(counts.values()), window_days=window_days)


@dataclass
class BudgetVerdict:
    """Outcome of evaluating a mix against the budget."""

    ok: bool
    substrate_breach: bool
    product_shortfall: bool
    freeze_recommended: bool
    reasons: list[str] = field(default_factory=list)


def evaluate_budget(mix: MixReport, budget: MixBudget | None = None) -> BudgetVerdict:
    """Evaluate a mix report against the budget.

    A substrate breach recommends the freeze marker. A product shortfall is
    reported but does not by itself recommend a freeze on a single window —
    the two-consecutive-week kill switch lives in the ledger layer, which
    sees history.
    """
    budget = budget or MixBudget()
    reasons: list[str] = []
    if mix.total == 0:
        return BudgetVerdict(
            ok=True,
            substrate_breach=False,
            product_shortfall=False,
            freeze_recommended=False,
            reasons=["no countable merges in window"],
        )

    substrate_breach = mix.substrate_share > budget.substrate_max
    product_shortfall = mix.product_share < budget.product_min
    if substrate_breach:
        reasons.append(
            f"substrate share {mix.substrate_share:.0%} exceeds budget {budget.substrate_max:.0%}"
        )
    if product_shortfall:
        reasons.append(
            f"product share {mix.product_share:.0%} below target {budget.product_min:.0%}"
        )
    return BudgetVerdict(
        ok=not (substrate_breach or product_shortfall),
        substrate_breach=substrate_breach,
        product_shortfall=product_shortfall,
        freeze_recommended=substrate_breach,
        reasons=reasons,
    )
