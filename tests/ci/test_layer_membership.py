"""Pin the layer membership of the import-layer contract in `.importlinter`.

The contract is positional: ``scripts/ci/check_import_contracts.py`` zips the
``layers =`` lines onto ``LAYER_ORDER``, so the file must keep exactly five
colon-separated lines. Layering tranches only append names to the existing
lines; the exact expected set per layer is the original membership plus every
adopted tranche listed in ``_TRANCHES``.
"""

from __future__ import annotations

import configparser
import importlib.util
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_CONFIG = REPO_ROOT / ".importlinter"
_CHECKER_PATH = REPO_ROOT / "scripts" / "ci" / "check_import_contracts.py"
_CYCLES_BASELINE = REPO_ROOT / "scripts" / "baselines" / "import_cycles_baseline.json"

_LAYERS = ("interface", "application", "domain", "infrastructure", "foundation")

# Membership before any tranche, in declaration order. Tranches append after these.
_ORIGINAL: dict[str, tuple[str, ...]] = {
    "interface": (
        "server",
        "cli",
        "mcp",
        "gateway",
        "bots",
        "channels",
        "integrations",
        "connectors",
    ),
    "application": (
        "workflow",
        "pipeline",
        "nomic",
        "swarm",
        "gauntlet",
        "goals",
        "implement",
        "modes",
        "verticals",
        "autonomous",
        "broadcast",
        "canvas",
        "spectate",
    ),
    "domain": (
        "debate",
        "agents",
        "memory",
        "knowledge",
        "ranking",
        "reasoning",
        "evidence",
        "evaluation",
        "explainability",
        "learning",
        "ml",
    ),
    "infrastructure": (
        "storage",
        "resilience",
        "events",
        "observability",
        "security",
        "queue",
        "db",
        "caching",
        "billing",
        "backup",
        "migrations",
    ),
    "foundation": (
        "api_errors",
        "config",
        "core_types",
        "exceptions",
        "errors",
        "utils",
        "protocols",
        "types",
    ),
}

# Adopted tranches, in landing order.
_TRANCHES: dict[str, dict[str, tuple[str, ...]]] = {
    "T1": {
        "infrastructure": (
            "cache",
            "deletion_coordinator",
            "fabric",
            "maintenance",
            "monitoring",
            "performance",
            "resilience_config",
            "resilience_patterns",
            "runtime",
            "sandbox",
            "streaming",
            "telemetry",
            "transcription",
        ),
        "foundation": (
            "__version__",
            "_lazy_imports",
            "core_protocols",
            "docs_only",
            "http_client",
            "models",
            "serialization",
            "task_brief",
            "topic_handler",
            "topic_spec",
            "topics",
            "type_protocols",
        ),
    },
    "T2": {
        "infrastructure": (
            "auth",
            "logging_config",
            "notifications",
            "persistence",
            "privacy",
            "rbac",
            "tenancy",
        ),
        "foundation": ("shared",),
    },
    "T3": {
        "domain": (
            "advocates",
            "analysis",
            "audience",
            "blockchain",
            "compliance",
            "container",
            "core",
            "deliberation",
            "documents",
            "embeddings",
            "epistemic",
            "evolution",
            "genesis",
            "heterogeneity",
            "insights",
            "introspection",
            "metrics",
            "moderation",
            "prompts",
            "pulse",
            "replay",
            "reputation",
            "rlm",
            "routing",
            "templates",
            "tools",
            "tournaments",
            "training",
            "uncertainty",
            "verification",
            "visualization",
            "work",
        ),
    },
    "T4a": {
        "application": (
            "analytics",
            "audit",
            "control_plane",
            "golden",
            "inbox",
            "marketplace",
            "services",
            "skills",
            "stores",
        ),
    },
}

_SEAMS = {
    "aragora.exceptions -> aragora.connectors.exceptions",
    "aragora.exceptions -> aragora.server.handlers.exceptions",
    "aragora.utils.redis_cache -> aragora.caching.redis",
}


def _expected() -> dict[str, set[str]]:
    expected = {layer: set(names) for layer, names in _ORIGINAL.items()}
    for additions in _TRANCHES.values():
        for layer, names in additions.items():
            expected[layer].update(names)
    return expected


def _parser() -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(_CONFIG, encoding="utf-8")
    return parser


def _layers_section(parser: configparser.ConfigParser) -> str:
    sections = [
        s for s in parser.sections() if parser.get(s, "type", fallback="").strip() == "layers"
    ]
    assert len(sections) == 1, sections
    return sections[0]


def _layer_lines() -> list[str]:
    parser = _parser()
    raw = parser.get(_layers_section(parser), "layers")
    return [line.strip() for line in raw.splitlines() if line.strip()]


def _tokens_by_layer() -> dict[str, list[str]]:
    return {
        layer: [token.strip() for token in line.split(":")]
        for layer, line in zip(_LAYERS, _layer_lines(), strict=True)
    }


def _load_checker():
    spec = importlib.util.spec_from_file_location(
        "check_import_contracts_membership", _CHECKER_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_expected_tranche_tables_are_disjoint():
    seen: dict[str, str] = {}
    for layer, names in _ORIGINAL.items():
        for name in names:
            assert name not in seen, (name, seen.get(name), layer)
            seen[name] = layer
    for tranche, additions in _TRANCHES.items():
        for layer, names in additions.items():
            assert layer in _LAYERS, (tranche, layer)
            for name in names:
                assert name not in seen, (tranche, name, seen.get(name), layer)
                seen[name] = layer


def test_single_layers_contract_rooted_at_aragora():
    parser = _parser()
    section = _layers_section(parser)
    assert parser.get("importlinter", "root_package").strip() == "aragora"
    assert parser.get(section, "containers").split() == ["aragora"]


def test_exactly_five_colon_separated_layer_lines():
    lines = _layer_lines()
    assert len(lines) == len(_LAYERS), lines
    for line in lines:
        assert "|" not in line and "(" not in line and ")" not in line, line
        assert all(token.strip() for token in line.split(":")), line


def test_every_token_appears_exactly_once():
    tokens = [token for names in _tokens_by_layer().values() for token in names]
    duplicates = sorted({token for token in tokens if tokens.count(token) > 1})
    assert not duplicates, duplicates


def test_exact_membership_per_layer():
    actual = {layer: set(names) for layer, names in _tokens_by_layer().items()}
    expected = _expected()
    for layer in _LAYERS:
        missing = sorted(expected[layer] - actual[layer])
        extra = sorted(actual[layer] - expected[layer])
        assert not missing and not extra, (layer, missing, extra)


def test_original_names_keep_their_line_and_order():
    # Tranches append; the pre-tranche prefix of every line is unchanged.
    for layer, names in _tokens_by_layer().items():
        original = list(_ORIGINAL[layer])
        assert names[: len(original)] == original, (layer, names[: len(original)])


def test_every_layer_token_is_a_real_top_level_module():
    missing = sorted(
        token
        for names in _tokens_by_layer().values()
        for token in names
        if not (REPO_ROOT / "aragora" / f"{token}.py").is_file()
        and not (REPO_ROOT / "aragora" / token / "__init__.py").is_file()
    )
    assert not missing, missing


def test_checker_maps_every_token_to_its_expected_layer():
    membership = _load_checker().parse_layer_membership(_CONFIG)
    for layer, names in _expected().items():
        for name in names:
            assert membership.get(f"aragora.{name}") == layer, (
                name,
                membership.get(f"aragora.{name}"),
            )
            assert membership.get(name) == layer, name


def test_ignore_imports_holds_exactly_the_sanctioned_seams():
    parser = _parser()
    raw = parser.get(_layers_section(parser), "ignore_imports", fallback="")
    entries = {
        line.strip()
        for line in raw.splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    assert entries == _SEAMS, entries


def test_header_cycle_count_does_not_exceed_the_cycle_ratchet():
    # The header quotes a measured mutual-cycle count. It may lag a later shrink,
    # but a count above the shrink-only ratchet value is stale by construction.
    header = _CONFIG.read_text(encoding="utf-8").split("[importlinter]", 1)[0]
    prose = re.sub(r"\n#\s*", " ", header)
    counts = [int(n) for n in re.findall(r"(\d+) mutual cycles", prose)]
    assert counts, "the header no longer states the measured mutual-cycle count"
    ratchet = json.loads(_CYCLES_BASELINE.read_text(encoding="utf-8"))["value"]
    assert all(count <= ratchet for count in counts), (counts, ratchet)
