"""SwarmSpec: structured specification from interrogation to orchestration."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from aragora.swarm.mission import normalize_context_policies
from aragora.agents.semantic_extraction import ExtractionProvider, extract_json_object_llm_first

logger = logging.getLogger(__name__)

_FILE_SCOPE_HINT_RE = re.compile(r"(?:\./)?(?:[A-Za-z0-9_*?\[\]{}.-]+/)+[A-Za-z0-9_*?\[\]{}.-]+/?")
_EXACT_FILE_SCOPE_RE = re.compile(r"(?:\./)?(?:[A-Za-z0-9_*?\[\]{}.-]+/)*[A-Za-z0-9_*?\[\]{}.-]+/?")
_URL_RE = re.compile(r"https?://\S+")
# English phrases with "/" that the path regex matches but are not file paths.
_FALSE_POSITIVE_SCOPE_HINTS = frozenset(
    {
        "plugin/callback",
        "new/changed",
        "true/false",
        "yes/no",
        "pass/fail",
        "read/write",
        "input/output",
        "before/after",
        "start/stop",
        "open/close",
        "client/server",
        "request/response",
        "success/failure",
        "enable/disable",
        "add/remove",
        "create/delete",
        "push/pull",
        "sync/async",
        "public/private",
        "internal/external",
        "i/o",
    }
)
_PATH_WRAPPER_CHARS = "`'\".,;:()[]{}<>"
_DIRECT_GOAL_TRACK_HINTS = frozenset({"sme", "developer", "self_hosted", "qa", "core", "security"})
_DIRECT_GOAL_COMPLEXITIES = frozenset({"low", "medium", "high"})
_DIRECT_GOAL_OPENROUTER_MODEL = "anthropic/claude-opus-5"
_DIRECT_GOAL_SPEC_PROMPT = """\
You are refining a developer's direct goal into a dispatch-bounded swarm spec.

Goal:
{raw_goal}

Return ONLY a JSON object with these fields:
{{
  "refined_goal": "<clearer 1-2 sentence goal>",
  "acceptance_criteria": ["<success condition>", "..."],
  "constraints": ["<boundary to preserve>", "..."],
  "track_hints": ["sme" | "developer" | "self_hosted" | "qa" | "core" | "security"],
  "file_scope_hints": ["<relative repo path>", "..."],
  "estimated_complexity": "low" | "medium" | "high"
}}

Rules:
- Do not invent files, tests, or constraints that are not grounded in the goal.
- Keep arrays empty when the goal does not specify that field.
- file_scope_hints should only include concrete path-like hints from the goal.
- refined_goal should preserve the original intent while making it easier to dispatch.
"""


@dataclass
class SwarmSpec:
    """Structured specification produced by interrogation, consumed by orchestration.

    This is the contract between the user-facing interrogation phase and
    the technical orchestration phase. It captures user intent in a format
    that maps directly to ``HardenedOrchestrator.execute_goal_coordinated()``.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # User intent
    raw_goal: str = ""
    refined_goal: str = ""

    # Acceptance criteria
    acceptance_criteria: list[str] = field(default_factory=list)

    # Constraints
    constraints: list[str] = field(default_factory=list)
    budget_limit_usd: float | None = 5.0

    # Hints for decomposition
    track_hints: list[str] = field(default_factory=list)
    file_scope_hints: list[str] = field(default_factory=list)
    work_orders: list[dict[str, Any]] = field(default_factory=list)

    # Mission lineage (additive envelope over live execution contracts)
    mission_id: str = ""
    stage_id: str = ""
    assertion_ids: list[str] = field(default_factory=list)
    roadmap_refs: list[str] = field(default_factory=list)
    evidence_expectations: list[str] = field(default_factory=list)
    gate_expectations: dict[str, Any] = field(default_factory=dict)
    mission_context_policies: dict[str, Any] = field(default_factory=dict)

    # Risk assessment
    estimated_complexity: str = "medium"
    requires_approval: bool = False

    # Proactive suggestions from the interrogation
    proactive_suggestions: list[str] = field(default_factory=list)

    # Research pipeline context (Phase 3)
    research_context: dict[str, Any] = field(default_factory=dict)
    pipeline_stage: str = ""

    # Obsidian source (Phase 4)
    obsidian_source: str = ""

    # Truth-seeking scores (Phase 5)
    epistemic_scores: dict[str, Any] = field(default_factory=dict)

    # Metadata
    interrogation_turns: int = 0
    user_expertise: str = "non-developer"

    def __post_init__(self) -> None:
        self.raw_goal = str(self.raw_goal or "").strip()
        self.refined_goal = str(self.refined_goal or "").strip()
        self.acceptance_criteria = self._nonempty_strings(self.acceptance_criteria)
        self.constraints = self._nonempty_strings(self.constraints)
        self.track_hints = self._nonempty_strings(self.track_hints)
        self.file_scope_hints = self._nonempty_strings(self.file_scope_hints)
        self.work_orders = [dict(item) for item in self.work_orders if isinstance(item, dict)]
        self.mission_id = str(self.mission_id or "").strip()
        self.stage_id = str(self.stage_id or "").strip()
        self.assertion_ids = self._nonempty_strings(self.assertion_ids)
        self.roadmap_refs = self._nonempty_strings(self.roadmap_refs)
        self.evidence_expectations = self._nonempty_strings(self.evidence_expectations)
        self.gate_expectations = dict(self.gate_expectations or {})
        self.mission_context_policies = normalize_context_policies(
            self.mission_context_policies,
            file_scope=list(self.file_scope_hints),
            evidence_expectations=list(self.evidence_expectations),
        )

    @staticmethod
    def _nonempty_strings(values: list[str]) -> list[str]:
        return [str(item).strip() for item in values if str(item).strip()]

    @staticmethod
    def _ordered_unique_strings(values: list[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for value in values:
            text = str(value).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            ordered.append(text)
        return ordered

    @staticmethod
    def _normalize_exact_file_scope_hint(value: str) -> str | None:
        text = str(value or "").strip()
        if not text:
            return None
        clean = text.split("::", 1)[0].strip(_PATH_WRAPPER_CHARS)
        had_path_separator = "/" in clean
        clean = clean.removeprefix("./").rstrip("/")
        if not clean or re.search(r"\s", clean):
            return None
        if not had_path_separator and "." not in clean:
            return None
        if _EXACT_FILE_SCOPE_RE.fullmatch(clean) is None:
            return None
        if clean.lower() in _FALSE_POSITIVE_SCOPE_HINTS:
            return None
        return clean

    @classmethod
    def sanitize_file_scope_entry(cls, value: Any) -> str | None:
        exact = cls._normalize_exact_file_scope_hint(str(value or ""))
        if exact:
            return exact
        inferred = cls.infer_file_scope_hints(str(value or ""))
        return inferred[0] if inferred else None

    @classmethod
    def is_concrete_repo_path_hint(cls, value: str) -> bool:
        clean = cls._normalize_exact_file_scope_hint(value)
        if not clean or any(token in clean for token in ("*", "?", "[", "]", "{", "}")):
            return False
        name = clean.rsplit("/", 1)[-1]
        return "." in name

    @classmethod
    def infer_file_scope_hints(cls, text: str) -> list[str]:
        """Extract path-like hints from free-form prompt text.

        Uses regex extraction over the whole string so command wrappers like
        ``ast.parse(open('aragora/foo.py').read())`` yield the real repo path
        instead of the full wrapper fragment.
        """
        scrubbed = _URL_RE.sub(" ", text or "")
        hints: list[str] = []
        for match in _FILE_SCOPE_HINT_RE.finditer(scrubbed):
            normalized = cls._normalize_exact_file_scope_hint(match.group(0))
            if normalized:
                hints.append(normalized)
        return list(dict.fromkeys(hints))

    @staticmethod
    def infer_constraints(messages: list[str]) -> list[str]:
        """Extract obvious constraints from user language."""
        markers = (
            "do not ",
            "don't ",
            "must not ",
            "without ",
            "leave ",
            "only touch ",
            "should not ",
        )
        constraints: list[str] = []
        for message in messages:
            text = str(message).strip()
            lower = text.lower()
            if text and any(marker in lower for marker in markers):
                constraints.append(text)
        return list(dict.fromkeys(constraints))

    @staticmethod
    def infer_acceptance_criteria(messages: list[str]) -> list[str]:
        """Extract obvious success criteria from user language."""
        markers = (
            "done looks like",
            "done means",
            "works when",
            "success is",
            "should ",
            "must ",
            "passes ",
            "pass when",
        )
        criteria: list[str] = []
        for message in messages:
            text = str(message).strip()
            lower = text.lower()
            if len(text) >= 12 and any(marker in lower for marker in markers):
                criteria.append(text)
        return list(dict.fromkeys(criteria))

    @classmethod
    def _direct_goal_providers(cls) -> tuple[ExtractionProvider, ...]:
        # Frontier-first provider preference so the swarm uses Opus 5 / GPT-5.4
        # / Gemini 3.1 Pro wherever a direct key is available, and OpenRouter-Opus
        # when only the unified key is configured.
        return (
            ExtractionProvider(
                agent_type="anthropic-api",
                model="claude-opus-5",
                role="critic",
                name="swarm-direct-goal-refiner",
                env_vars=("ANTHROPIC_API_KEY",),
            ),
            ExtractionProvider(
                agent_type="openai-api",
                model="gpt-5.4",
                role="critic",
                name="swarm-direct-goal-refiner",
                env_vars=("OPENAI_API_KEY",),
            ),
            ExtractionProvider(
                agent_type="gemini",
                model="gemini-3.1-pro",
                role="critic",
                name="swarm-direct-goal-refiner",
                env_vars=("GEMINI_API_KEY", "GOOGLE_API_KEY"),
            ),
            ExtractionProvider(
                agent_type="openrouter",
                model=_DIRECT_GOAL_OPENROUTER_MODEL,
                role="critic",
                name="swarm-direct-goal-refiner",
                env_vars=("OPENROUTER_API_KEY",),
            ),
        )

    @classmethod
    def _direct_goal_provider_available(cls) -> bool:
        return any(provider.is_available() for provider in cls._direct_goal_providers())

    @classmethod
    def _normalize_direct_goal_payload(cls, parsed: dict[str, Any]) -> dict[str, Any] | None:
        refined_goal = str(parsed.get("refined_goal", "")).strip()
        acceptance_criteria = cls._ordered_unique_strings(
            cls._nonempty_strings(
                parsed.get("acceptance_criteria", [])
                if isinstance(parsed.get("acceptance_criteria", []), list)
                else []
            )
        )
        constraints = cls._ordered_unique_strings(
            cls._nonempty_strings(
                parsed.get("constraints", [])
                if isinstance(parsed.get("constraints", []), list)
                else []
            )
        )
        track_hints = cls._ordered_unique_strings(
            [
                str(track).strip()
                for track in parsed.get("track_hints", [])
                if str(track).strip() in _DIRECT_GOAL_TRACK_HINTS
            ]
            if isinstance(parsed.get("track_hints", []), list)
            else []
        )
        file_scope_hints = cls._ordered_unique_strings(
            [
                sanitized
                for sanitized in (
                    cls.sanitize_file_scope_entry(value)
                    for value in (
                        parsed.get("file_scope_hints", [])
                        if isinstance(parsed.get("file_scope_hints", []), list)
                        else []
                    )
                )
                if sanitized
            ]
        )
        estimated_complexity = str(parsed.get("estimated_complexity", "")).strip().lower()
        if estimated_complexity not in _DIRECT_GOAL_COMPLEXITIES:
            estimated_complexity = "medium"

        if not any([refined_goal, acceptance_criteria, constraints, track_hints, file_scope_hints]):
            return None

        return {
            "refined_goal": refined_goal,
            "acceptance_criteria": acceptance_criteria,
            "constraints": constraints,
            "track_hints": track_hints,
            "file_scope_hints": file_scope_hints,
            "estimated_complexity": estimated_complexity,
        }

    @classmethod
    def _build_direct_goal_heuristic_spec(
        cls,
        raw_goal: str,
        *,
        budget_limit_usd: float | None,
        requires_approval: bool,
        user_expertise: str,
    ) -> SwarmSpec:
        return cls(
            id=str(uuid.uuid4()),
            created_at=datetime.now(timezone.utc),
            raw_goal=raw_goal,
            refined_goal=raw_goal,
            acceptance_criteria=cls.infer_acceptance_criteria([raw_goal]),
            constraints=cls.infer_constraints([raw_goal]),
            budget_limit_usd=budget_limit_usd,
            file_scope_hints=cls.infer_file_scope_hints(raw_goal),
            requires_approval=requires_approval,
            interrogation_turns=0,
            user_expertise=user_expertise,
        )

    @classmethod
    async def from_direct_goal_async(
        cls,
        raw_goal: str,
        *,
        budget_limit_usd: float | None,
        requires_approval: bool,
        user_expertise: str,
        use_llm: bool = True,
        timeout: float = 15.0,
    ) -> SwarmSpec:
        spec = cls._build_direct_goal_heuristic_spec(
            raw_goal,
            budget_limit_usd=budget_limit_usd,
            requires_approval=requires_approval,
            user_expertise=user_expertise,
        )
        if not use_llm or not spec.raw_goal or not cls._direct_goal_provider_available():
            return spec

        result = await extract_json_object_llm_first(
            _DIRECT_GOAL_SPEC_PROMPT.format(raw_goal=spec.raw_goal[:3000]),
            providers=cls._direct_goal_providers(),
            normalizer=cls._normalize_direct_goal_payload,
            timeout=timeout,
            logger=logger,
            context="direct goal spec refinement",
        )
        if result.value is None:
            logger.debug(
                "Direct goal LLM refinement unavailable, using heuristics: source=%s error=%s",
                result.source,
                result.error,
            )
            return spec

        enriched = result.value
        spec.refined_goal = str(enriched.get("refined_goal", "")).strip() or spec.refined_goal
        spec.acceptance_criteria = cls._ordered_unique_strings(
            [*spec.acceptance_criteria, *enriched.get("acceptance_criteria", [])]
        )
        spec.constraints = cls._ordered_unique_strings(
            [*spec.constraints, *enriched.get("constraints", [])]
        )
        spec.track_hints = cls._ordered_unique_strings(
            [*spec.track_hints, *enriched.get("track_hints", [])]
        )
        spec.file_scope_hints = cls._ordered_unique_strings(
            [*spec.file_scope_hints, *enriched.get("file_scope_hints", [])]
        )
        spec.estimated_complexity = (
            str(enriched.get("estimated_complexity", spec.estimated_complexity)).strip().lower()
            or spec.estimated_complexity
        )
        return spec

    @classmethod
    def from_direct_goal(
        cls,
        raw_goal: str,
        *,
        budget_limit_usd: float | None,
        requires_approval: bool,
        user_expertise: str,
        use_llm: bool = True,
        timeout: float = 15.0,
    ) -> SwarmSpec:
        """Build a direct spec from a raw goal without conversational interrogation."""
        if not use_llm or not cls._direct_goal_provider_available():
            return cls._build_direct_goal_heuristic_spec(
                raw_goal,
                budget_limit_usd=budget_limit_usd,
                requires_approval=requires_approval,
                user_expertise=user_expertise,
            )
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                cls.from_direct_goal_async(
                    raw_goal,
                    budget_limit_usd=budget_limit_usd,
                    requires_approval=requires_approval,
                    user_expertise=user_expertise,
                    use_llm=use_llm,
                    timeout=timeout,
                )
            )
        logger.debug("Direct goal LLM refinement skipped because an event loop is already running")
        return cls._build_direct_goal_heuristic_spec(
            raw_goal,
            budget_limit_usd=budget_limit_usd,
            requires_approval=requires_approval,
            user_expertise=user_expertise,
        )

    def dispatch_bounds(self) -> dict[str, bool]:
        """Return which fields make this spec safe enough to dispatch."""
        return {
            "acceptance_criteria": bool(self._nonempty_strings(self.acceptance_criteria)),
            "constraints": bool(self._nonempty_strings(self.constraints)),
            "file_scope_hints": bool(self._nonempty_strings(self.file_scope_hints)),
            "work_orders": bool([item for item in self.work_orders if isinstance(item, dict)]),
        }

    def is_dispatch_bounded(self) -> bool:
        """Whether the spec has at least one concrete bound for dispatch."""
        return any(self.dispatch_bounds().values())

    def missing_dispatch_bounds(self) -> list[str]:
        """Human-readable names for missing dispatch-bounding fields."""
        labels = {
            "acceptance_criteria": "acceptance criterion",
            "constraints": "constraint",
            "file_scope_hints": "file-scope hint",
            "work_orders": "explicit work order",
        }
        return [labels[key] for key, present in self.dispatch_bounds().items() if not present]

    def dispatch_gate_reason(self) -> str:
        """Reason why this spec may or may not dispatch."""
        if self.is_dispatch_bounded():
            return "dispatch-bounded"
        return (
            "Swarm spec is under-specified for dispatch. Add at least one acceptance "
            "criterion, constraint, file-scope hint, or explicit work order."
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        data = asdict(self)
        data["created_at"] = self.created_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SwarmSpec:
        """Deserialize from dictionary."""
        data = dict(data)
        if isinstance(data.get("created_at"), str):
            data["created_at"] = datetime.fromisoformat(data["created_at"])
        if "work_orders" in data and isinstance(data["work_orders"], list):
            data["work_orders"] = [
                dict(item) for item in data["work_orders"] if isinstance(item, dict)
            ]
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_json(cls, text: str) -> SwarmSpec:
        """Deserialize from JSON string."""
        return cls.from_dict(json.loads(text))

    def to_yaml(self) -> str:
        """Serialize to YAML string."""
        try:
            import yaml  # type: ignore[import-untyped]

            data = self.to_dict()
            return yaml.safe_dump(data, default_flow_style=False, sort_keys=False)
        except ImportError:
            return self.to_json()

    @classmethod
    def from_yaml(cls, text: str) -> SwarmSpec:
        """Deserialize from YAML string."""
        try:
            import yaml  # type: ignore[import-untyped]

            data = yaml.safe_load(text)
        except ImportError:
            data = json.loads(text)
        return cls.from_dict(data)

    def summary(self) -> str:
        """Human-readable summary of the spec."""
        lines = [
            f"Goal: {self.refined_goal or self.raw_goal}",
            f"Complexity: {self.estimated_complexity}",
        ]
        if self.acceptance_criteria:
            lines.append(f"Acceptance criteria: {len(self.acceptance_criteria)} items")
        if self.constraints:
            lines.append(f"Constraints: {len(self.constraints)} items")
        if self.budget_limit_usd is not None:
            lines.append(f"Budget: ${self.budget_limit_usd:.2f}")
        if self.track_hints:
            lines.append(f"Tracks: {', '.join(self.track_hints)}")
        if self.file_scope_hints:
            lines.append(f"File scope: {', '.join(self.file_scope_hints[:5])}")
        if self.work_orders:
            lines.append(f"Explicit work orders: {len(self.work_orders)}")
        if self.mission_id:
            lines.append(f"Mission: {self.mission_id}")
        if self.stage_id:
            lines.append(f"Stage: {self.stage_id}")
        return "\n".join(lines)
