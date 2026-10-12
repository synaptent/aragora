#!/usr/bin/env python3
"""Rewrite retired model-ID literals to their current ids, or check that none remain.

Consumes ``UPGRADES`` and ``RETIRED_PATTERN`` from
``aragora.models.upgrade_map`` and ``CATALOG`` from
``aragora.models.catalog`` to map a retired literal to its current
spelling: a literal that was an OpenRouter slug (contains ``/``) is
rewritten to the new OpenRouter slug, a bare id to the new direct id.

``RETIRED_PATTERN`` is already built with token-boundary lookarounds (see
``aragora/models/upgrade_map.py``) so a retired key that is a literal
prefix of a longer active spelling — e.g. ``"claude-fable-5"`` inside
active ``"claude-fable-5-1"`` — never falsely matches. This script reuses
that pattern directly rather than re-wrapping it in another boundary
layer.

ADVISORY, not enforcing, at this commit: nothing in ``.github/`` invokes this
script, and ``--check`` still reports thousands of retired literals outside
the allowlist. Landing the ``--write`` sweep is PR 3's scope and wiring the
check into CI is PR 4's; until then a non-zero exit here is information, not
a gate.

Period vs. hyphen is BY DESIGN, not a bug: the same retired literal maps to
two different new spellings depending on the SHAPE it was written in. A bare
match rewrites to ``ModelSpec.direct_id`` (Anthropic's own API code, the
hyphen form ``claude-fable-5-1``); a ``provider/model`` slug match rewrites
to ``ModelSpec.openrouter_id`` (the OpenRouter slug, the dotted form
``anthropic/claude-fable-5.1``). A file that names the same model both ways
therefore ends up with both spellings, and each is correct for the endpoint
it addresses. A test that asserts on a rendered label must match whichever
form the code under test actually builds.

Three classes of retired literal are deliberately NOT rewritten, each
reported by ``--check`` in its own section that does NOT affect the exit
code (only "offenders" do):

* **unresolvable** — a bare (native-shaped) spelling whose current row is
  served by a DIFFERENT provider than the literal's own native API: the
  row is reachable only through OpenRouter, or the literal's own catalog
  row names another native provider. Either way there is no real native id
  to rewrite to. ``--write`` leaves it exactly as written. See
  ``replacement()``.
* **collision** — a rewrite that would collapse two pieces of text in one
  file onto a single id: either two DISTINCT retired spellings that share
  a replacement, or ONE retired spelling whose replacement id is ALREADY
  written in that file. Both collapse hand-written ``dict``/``set``/list
  literals onto one entry, so ``--write`` rewrites NONE of the listed
  spellings anywhere in that file. See ``_collisions()``.
* **guarded** — text that was never a model id: a raw string, a
  ``re.``-call or ``pattern=`` regex source, an alternative inside a
  ``|``-separated string that also carries a regex metacharacter, or a
  ``SHORT_BARE_KEYS`` token outside model-id quoting. These are dropped
  silently (not even reported), because calling them offenders would make
  ``--check`` unfixable by construction. See ``_is_guarded()``.
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, NamedTuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from aragora.models.catalog import CATALOG, spec_or_none  # noqa: E402
from aragora.models.upgrade_map import RETIRED_PATTERN, TOKEN_CHAR, UPGRADES  # noqa: E402

SKIP_DIRS = {".git", "node_modules", ".worktrees", "__pycache__", ".venv", "dist", "build"}
SKIP_SUFFIXES = {".lock", ".png", ".jpg", ".pdf", ".ico", ".woff", ".woff2", ".pyc"}
SKIP_NAMES = {
    "package-lock.json",
    "uv.lock",
    "yarn.lock",
    "pnpm-lock.yaml",
    "catalog_snapshot.json",
    "upgrade_map.py",
}

# Repo-relative paths that legitimately contain retired model-id literals
# on purpose, and must therefore never be rewritten by --write or reported
# as offenders by --check. Matched by path SUFFIX (a trailing "/" entry
# matches anything under that directory), so this works regardless of the
# cwd the sweep is invoked from.
#
#   - aragora/models/catalog.py, upgrade_map.py, catalog_snapshot.json,
#     pricing_mirror.py: these ARE the retired-id source of truth — the
#     catalog rows with retired=True, the UPGRADES map itself (keyed by
#     the very literals this script hunts for), its generated JSON
#     mirror, and the pricing table that old receipts still resolve
#     through by their original spelling.
#   - aragora/billing/usage.py, aragora/billing/debate_costs.py,
#     aragora/services/metering_models.py, aragora/pdb/real_invoker.py,
#     aragora/routing/provider_config.py,
#     aragora/server/handlers/debates/cost_estimation.py: legacy pricing
#     keys and static routing hand-rows that old receipts and in-flight
#     cost estimates still resolve through by their original spelling.
#   - tests/models/: unit tests that assert retired ids on purpose (e.g.
#     RETIRED_PATTERN / UPGRADES coverage tests in
#     tests/models/test_upgrade_map.py).
#   - scripts/refresh_model_literals.py: this script's own source, which
#     necessarily names retired ids in comments, constants, and its test.
#   - tests/scripts/test_refresh_model_literals.py: not in the original
#     skip list, added deliberately — this test's fixtures are retired-id
#     string literals embedded in the test *source* (not just written at
#     runtime), so a --write pass over "tests" would rewrite them in
#     place and silently gut what the test verifies, the same hazard
#     tests/models/ and this script's own source are protected against.
#   - aragora/documents/models.py, aragora/documents/chunking/
#     context_manager.py, aragora/billing/optimizer.py,
#     aragora/workflow/resource_tracker.py, aragora/workflow/engine_v2.py,
#     aragora/server/handlers/agents/recommendations.py,
#     aragora/server/handlers/debates/diagnostics.py: the OTHER frozen-table
#     family -- a hand-written ``_LEGACY_*`` dict (token limits, pricing,
#     tier bands, agent cost estimates, provider maps) merged with rows
#     generated from the catalog. The legacy half exists precisely to keep
#     answering lookups written in the historical spellings, so sweeping it
#     deletes the only reason it is there; the generated half already
#     carries the current ids. Each is reverted-and-listed rather than
#     swept in the 2026-09-05 repo-wide re-sweep (wave-6 ruling, frozen
#     sources, on #9989).
#   - every test file that exercises one of the frozen sources above,
#     enumerated per source in FROZEN_PRICING_SOURCE_TESTS below:
#     a frozen table is keyed on its historical spellings, so its test must
#     look those spellings up EXACTLY. PR 3's trial sweep left the sources
#     frozen but swept their tests, breaking every ``PROVIDER_PRICING[model]``
#     / ``_PRICE_PER_MTOK[model]`` lookup against them (2026-09-04 controller
#     ruling, Class 6). Skipping the source without its test is only half a
#     freeze.
# {frozen pricing source: the test files that look its historical spellings
# up EXACTLY}. THE single definition of that pairing: SKIP_PATHS below is
# built from it and tests/scripts/test_refresh_model_literals.py imports it,
# so a frozen source added here without its tests, or with a test that is
# never listed, fails there instead of quietly shipping half a freeze
# (2026-09-05 merge-gate addendum on #9989). Adding a source to SKIP_PATHS
# by hand without a pairing entry is still possible for tables that have no
# spelling-exact test -- the routing hand-rows -- which is why the pairing
# map is separate from, rather than equal to, SKIP_PATHS.
FROZEN_PRICING_SOURCE_TESTS: dict[str, tuple[str, ...]] = {
    "aragora/billing/usage.py": (
        "tests/billing/test_usage.py",
        "tests/billing/test_billing_usage.py",
        "tests/e2e/test_billing_accuracy_e2e.py",
    ),
    "aragora/billing/debate_costs.py": ("tests/billing/test_debate_costs.py",),
    "aragora/services/metering_models.py": (
        "tests/services/test_usage_metering.py",
        "tests/services/test_usage_metering_service.py",
    ),
    "aragora/pdb/real_invoker.py": ("tests/pdb/test_real_invoker.py",),
    "aragora/server/handlers/debates/cost_estimation.py": (
        "tests/handlers/debates/test_cost_estimation.py",
    ),
    # The _LEGACY_* table family (see the comment block above).
    "aragora/documents/models.py": (
        "tests/documents/test_models.py",
        "tests/documents/test_chunking.py",
    ),
    "aragora/documents/chunking/context_manager.py": ("tests/documents/test_context_manager.py",),
    "aragora/billing/optimizer.py": ("tests/billing/test_optimizer.py",),
    "aragora/workflow/resource_tracker.py": ("tests/workflow/test_executor_protocol.py",),
    "aragora/workflow/engine_v2.py": ("tests/workflow/test_engine_v2.py",),
    "aragora/server/handlers/agents/recommendations.py": (
        "tests/handlers/agents/test_recommendations.py",
    ),
    "aragora/server/handlers/debates/diagnostics.py": (
        "tests/handlers/debates/test_diagnostics.py",
    ),
}

# Frozen paths with no spelling-exact test to pair (the catalog and its
# generated mirrors, the routing hand-rows, this script and its own test,
# and tests/models/).
_UNPAIRED_SKIP_PATHS: tuple[str, ...] = (
    "aragora/models/catalog.py",
    "aragora/models/upgrade_map.py",
    "aragora/models/catalog_snapshot.json",
    "aragora/models/pricing_mirror.py",
    "aragora/routing/provider_config.py",
    "tests/models/",
    "scripts/refresh_model_literals.py",
    "tests/scripts/test_refresh_model_literals.py",
)


def _skip_paths() -> tuple[str, ...]:
    """``_UNPAIRED_SKIP_PATHS`` plus every source and test in the pairing map.

    Order is deterministic (unpaired first, then each source immediately
    followed by its tests) so ``--check`` output and this tuple's own
    diffability do not depend on dict iteration accidents.
    """
    out: list[str] = list(_UNPAIRED_SKIP_PATHS)
    for source, tests in FROZEN_PRICING_SOURCE_TESTS.items():
        out.append(source)
        out.extend(tests)
    return tuple(dict.fromkeys(out))


SKIP_PATHS: tuple[str, ...] = _skip_paths()

DEFAULT_ALLOWLIST = REPO_ROOT / "scripts" / "baselines" / "retired_model_literals_allowlist.txt"


# Retired keys that are BOTH hyphen-free and shorter than
# ``_SHORT_TOKEN_MIN_LEN`` characters. A bare occurrence of one of these is
# far more often an ordinary Python identifier (``o1 = _make_org(...)``) or a
# word in prose ("GPT-4o, o1, o3") than a model id, and rewriting it produced
# a hard ``SyntaxError`` in one test file during PR 3's trial sweep.
# ``gpt-4`` is hyphenated and therefore deliberately NOT in this set. See
# ``_is_guarded``.
#
# CURRENTLY EMPTY: ``o1``/``o3`` were the only members and the wave-6 ruling
# (sweep gap 4, #9989) dropped them from ``UPGRADES`` outright, because the
# quoting rule below still admitted the shape a placeholder id is written in
# -- a complete string body -- and rewrote 25 files where the text was an
# org/plan/route id rather than a model. The derivation stays as the standing
# rule for any future hyphen-free short key rather than being deleted with
# its last member.
_SHORT_TOKEN_MIN_LEN = 6
SHORT_BARE_KEYS: frozenset[str] = frozenset(
    k for k in UPGRADES if "-" not in k and len(k) < _SHORT_TOKEN_MIN_LEN
)

# Regex metacharacters OTHER than "|". A ``|``-separated string counts as a
# regex only if it also carries one of these (or sits in a raw-string /
# ``re.``-call / ``pattern=`` context, both handled separately): Aragora's own
# agent-spec DSL writes real model ids as ``"provider|model"``, e.g.
# ``"anthropic|claude-sonnet-4"``, and treating every pipe as a regex made
# the sweep silently drop 15 genuine occurrences from both --write and
# --check (2026-09-05 merge-gate addendum on #9989).
_REGEX_METACHARS = frozenset("\\()[]*+?^${")

# Regex-source contexts a match may sit in on the same line. ``re.compile(``
# alone was too narrow: ``re.match``/``re.search``/``re.sub``/... and an
# explicit ``pattern=`` keyword are the same thing.
_REGEX_CONTEXT = re.compile(r"\bre\.[A-Za-z_]+\s*\(|\bpattern\s*=")

# One single-line string literal, with its optional prefix (so ``r"..."`` /
# ``r'...'`` raw strings are recognisable) and its BODY captured separately.
# Deliberately line-scoped: a match spanning a triple-quoted block would need
# a real tokenizer, and the guards below only ever need to answer "is this
# match inside a quoted string on this line, and is that string raw?".
_STRING_LITERAL = re.compile(
    r"""(?<![A-Za-z0-9_])(?P<prefix>[rRbBuUfF]{0,2})(?P<quote>["'])"""
    r"""(?P<body>(?:\\.|(?!(?P=quote))[^\\])*)(?P=quote)"""
)


def _string_spans(line: str) -> list[tuple[int, int, bool]]:
    """``(body_start, body_end, is_raw)`` for each single-line string literal."""
    return [
        (m.start("body"), m.end("body"), "r" in m.group("prefix").lower())
        for m in _STRING_LITERAL.finditer(line)
    ]


def _enclosing_string(
    spans: list[tuple[int, int, bool]], start: int, end: int
) -> tuple[int, int, bool] | None:
    for body_start, body_end, is_raw in spans:
        if body_start <= start and end <= body_end:
            return (body_start, body_end, is_raw)
    return None


def _is_guarded(
    line: str,
    spans: list[tuple[int, int, bool]],
    literal: str,
    start: int,
    end: int,
    in_regex_call: bool,
) -> bool:
    """True when this match is NOT a model-id occurrence at all.

    A guarded match is neither rewritten by ``--write`` nor reported by
    ``--check``: the point of the guard is that the text was never a model
    id, so calling it an "offender" would make the sweep unfixable by
    construction. Three guards apply to EVERY retired key (2026-09-04
    controller ruling, Class 3a/3b):

    * inside a RAW string literal (``r"gpt|o1|o3"``) -- raw strings in this
      repo are regex sources, never model ids;
    * anywhere on a line containing a regex-source context: an ``re.``
      call (``re.compile(``, ``re.match(``, ``re.sub(``, ...) or an
      explicit ``pattern=`` keyword;
    * as an alternative inside a ``|``-separated string that ALSO carries a
      regex metacharacter (``"gpt(-4)?|o1"``), i.e. the match is bounded on
      both sides by a ``|`` or by the string's own boundary AND the body
      looks like a pattern rather than a plain pipe-joined value.

    The metacharacter condition on that third guard is load-bearing.
    Aragora's own agent-spec DSL writes model ids as ``"provider|model"``
    (``"anthropic|claude-sonnet-4"``, ``"openai|gpt-4o"``), so a bare
    "contains a pipe" test classified 15 genuine ids across production code,
    tests and docs as regex alternatives and dropped them from both --write
    and --check -- the sweep reported them as neither rewritten nor
    outstanding (2026-09-05 merge-gate addendum on #9989).

    A fourth guard applies only to ``SHORT_BARE_KEYS``: the match must sit
    inside a quoted string AND be either the COMPLETE string body (``"o1"``)
    or immediately followed by ``-``/``.``/``:`` (``"o1-preview"``,
    ``'o3:'``). A bare identifier or a word in prose is therefore never
    rewritten.
    """
    if in_regex_call:
        return True
    enclosing = _enclosing_string(spans, start, end)
    if enclosing is not None:
        body_start, body_end, is_raw = enclosing
        if is_raw:
            return True
        body = line[body_start:body_end]
        if "|" in body and _REGEX_METACHARS.intersection(body):
            bounded_left = start == body_start or line[start - 1] == "|"
            bounded_right = end == body_end or line[end] == "|"
            if bounded_left and bounded_right:
                return True
    if literal in SHORT_BARE_KEYS:
        if enclosing is None:
            return True
        body_start, body_end, _raw = enclosing
        complete_literal = start == body_start and end == body_end
        followed_by_id_sep = end < body_end and line[end] in "-.:"
        if not (complete_literal or followed_by_id_sep):
            return True
    return False


def _native_provider(
    old: str,
    *,
    spec_lookup: Callable[[str], Any] | None = None,
) -> str | None:
    """The provider whose OWN API is known to accept ``old`` as a model code.

    ``None`` when the catalog has no row for the spelling at all, which is
    the usual case for a retired id (``gpt-4o``, ``o1-mini``): the sweep then
    has no evidence of a conflict and treats the literal as a native code of
    its target row's provider, exactly as it always did.

    ``spec_lookup`` exists so a test can exercise the provider-vs-provider
    leg against a FIXTURE row instead of whichever real row happens to have
    two providers today; see ``replacement``.
    """
    spec = (spec_lookup or spec_or_none)(old)
    return None if spec is None else spec.provider


def replacement(
    old: str,
    *,
    catalog: Mapping[str, Any] | None = None,
    upgrades: Mapping[str, str] | None = None,
    spec_lookup: Callable[[str], Any] | None = None,
) -> str | None:
    """Current literal for a retired spelling, or ``None`` when the retired
    literal has no honest replacement in the SHAPE it was written in.

    An OpenRouter slug (contains ``/``) is rewritten to the new slug; a bare
    id to the new direct id — but ONLY when the target row is served by the
    same provider whose native API the literal addresses. ``ModelSpec.
    direct_id`` is a real native code only on a row a native endpoint
    actually serves; everywhere else it is a documented placeholder, "NOT a
    code any native endpoint would accept" (see the field's docstring in
    aragora/models/catalog.py). Two ways the providers disagree:

    * the target row's ``provider`` is ``"openrouter"`` — the row has no
      native transport at all, so rewriting e.g. the deliberately-kept
      ``deepseek-cli`` default ``deepseek-v4-pro`` to
      ``deepseek-v4-pro-0813`` would swap a working native model code for a
      slug that 400s on the native API (2026-09-05 merge-gate finding C-P3
      on #9989), and rewriting Moonshot's own ``moonshot-v1-8k`` onto
      ``kimi-k3`` does the same to the one agent that calls api.moonshot.cn
      directly (wave-6 ruling, sweep gap 3);
    * the literal's OWN catalog row names a DIFFERENT native provider than
      its successor row does — ``qwen3.7-max`` is an Alibaba code whose
      successor Aragora reaches through OpenRouter, so no rewrite of it can
      stay a working Alibaba code.

    Such a literal is left exactly as written by ``--write`` and reported by
    ``--check`` as UNRESOLVABLE rather than as an offender: it is a real gap
    (the catalog owes that family a native row), but it is not something
    this sweep can fix, so it must not gate the sweep.

    ``catalog`` / ``upgrades`` / ``spec_lookup`` default to the real tables
    and exist only so a test can pin the second bullet -- the
    provider-vs-provider leg -- to FIXTURE rows. Reading it off the live
    catalog means the test asserts about whichever row happens to straddle
    two providers today: the day ``qwen3.7-max`` gains a native successor
    row, that assertion still passes while exercising nothing (wave-6
    re-review, minor 1).
    """
    catalog = CATALOG if catalog is None else catalog
    upgrades = UPGRADES if upgrades is None else upgrades
    spec = catalog[upgrades[old]]
    if "/" in old:
        return spec.openrouter_id
    if spec.provider == "openrouter":
        return None
    native = _native_provider(old, spec_lookup=spec_lookup)
    if native is not None and native != spec.provider:
        return None
    return spec.direct_id


def _sub_one(
    match: "re.Match[str]",
    line: str,
    spans: list[tuple[int, int, bool]],
    frozen: frozenset[str],
    in_regex_call: bool,
) -> str:
    """Replacement text for one ``RETIRED_PATTERN`` match on ``line``.

    Returns the literal UNCHANGED (i.e. no rewrite) in three cases:

    * it has no honest native replacement (see ``replacement``);
    * it is one of this file's ``frozen`` spellings, because rewriting it
      would collapse two distinct retired keys onto one id (see
      ``_collisions``);
    * ``_is_guarded`` says the text was never a model id in the first place.
    """
    literal = match.group(0)
    if literal in frozen or _is_guarded(
        line, spans, literal, match.start(), match.end(), in_regex_call
    ):
        return literal
    new = replacement(literal)
    return literal if new is None else new


def _scan_line(line: str) -> list[tuple[str, str | None]]:
    """``(literal, replacement)`` for every UNGUARDED match on ``line``.

    ``replacement`` is ``None`` for an unresolvable literal. Guarded matches
    are dropped entirely: they are not model-id occurrences, so they are
    neither rewritten nor reported. See ``_is_guarded``.
    """
    spans = _string_spans(line)
    in_regex_call = bool(_REGEX_CONTEXT.search(line))
    out: list[tuple[str, str | None]] = []
    for m in RETIRED_PATTERN.finditer(line):
        literal = m.group(0)
        if _is_guarded(line, spans, literal, m.start(), m.end(), in_regex_call):
            continue
        out.append((literal, replacement(literal)))
    return out


def _rewrite_line(line: str, frozen: frozenset[str]) -> str:
    """``line`` with every rewritable retired literal replaced.

    Line-scoped because the guards need the line as context (a raw-string
    span, an ``re.compile(`` call) and because rejoining ``splitlines
    (keepends=True)`` output preserves the file byte-for-byte otherwise."""
    spans = _string_spans(line)
    in_regex_call = bool(_REGEX_CONTEXT.search(line))

    def _replace(match: "re.Match[str]") -> str:
        return _sub_one(match, line, spans, frozen, in_regex_call)

    return RETIRED_PATTERN.sub(_replace, line)


class Collision(NamedTuple):
    """One replacement id this file must NOT be rewritten onto.

    ``olds`` are the retired spellings frozen because of it; they are frozen
    everywhere in the file, not only on the colliding line (see
    ``_collisions``). ``already_present`` distinguishes the two ways a
    rewrite collapses text:

    * ``False`` -- two or more DISTINCT retired spellings in this file share
      one replacement, so rewriting both merges them;
    * ``True`` -- ONE retired spelling whose replacement id is ALREADY
      written in this file, so rewriting it merges the two.

    ``paired_tests`` are the test files frozen ALONG WITH this source (see
    ``_paired_tests``); it is empty for a collision in a test file or in a
    module with no paired test.
    """

    new_id: str
    olds: tuple[str, ...]
    already_present: bool
    paired_tests: tuple[str, ...] = ()

    def describe(self) -> str:
        """The ``--check`` collision line's payload."""
        line = f"{','.join(self.olds)} -> {self.new_id}"
        if self.already_present:
            line += " (already present)"
        if self.paired_tests:
            line += f" (frozen with it: {', '.join(self.paired_tests)})"
        return line


def _mentions(text: str, ident: str) -> bool:
    """True when ``ident`` occurs in ``text`` as a whole model-id token.

    Uses ``upgrade_map.TOKEN_CHAR`` -- the same boundary rule
    ``RETIRED_PATTERN`` is built with -- so "already present" and "is a
    retired literal" cannot disagree about where an id starts and ends: a
    plain ``in`` test would count ``claude-sonnet-5`` as present inside
    ``claude-sonnet-5-preview``.
    """
    return re.search(rf"(?<!{TOKEN_CHAR}){re.escape(ident)}(?!{TOKEN_CHAR})", text) is not None


def _collisions(lines: list[str]) -> tuple[Collision, ...]:
    """Every replacement id this file would collapse text onto, sorted by id.

    Two ways a rewrite collapses a hand-written
    ``dict``/``set``/``enum``/list literal onto a single entry (Python keeps
    the last one), which PR 3's trial sweep did to ~20 real tables --
    including price tables where last-definition-wins left an arbitrary
    alias's rate under the live model's key:

    1. two DISTINCT retired spellings in this file share one replacement;
    2. a single retired spelling whose replacement id is ALREADY written in
       this file -- ``{"claude-sonnet-4": ..., "claude-sonnet-5": ...}``
       collapses exactly as hard as ``{"claude-sonnet-4": ...,
       "claude-sonnet-4-6": ...}`` does, and the pre-sweep text is the only
       place that evidence exists. Case 2 was invisible to this function
       until the 2026-09-05 repo-wide re-sweep hit it five times, once as a
       hard ``F601`` duplicate dict key in ``aragora/analysis/nl_query.py``
       (wave-6 ruling, sweep gap 1, on #9989).

    The over-approximation is deliberately FILE-level (2026-09-04 controller
    ruling, Class 2): proving two spellings share a container literal needs a
    parser per file format, while "this file names both" is cheap and never
    wrong in the unsafe direction. No listed spelling is rewritten anywhere
    in the file.
    """
    by_new: dict[str, set[str]] = {}
    for line in lines:
        for literal, new in _scan_line(line):
            if new is not None:
                by_new.setdefault(new, set()).add(literal)
    text = "".join(lines)
    out: list[Collision] = []
    for new_id, olds in sorted(by_new.items()):
        already_present = _mentions(text, new_id)
        if len(olds) > 1 or already_present:
            out.append(Collision(new_id, tuple(sorted(olds)), already_present))
    return tuple(out)


def _is_test_module(f: Path) -> bool:
    """True for a ``tests/**/test_*.py`` file."""
    return f.suffix == ".py" and f.name.startswith("test_") and "tests" in f.resolve().parts


def _module_dotted(f: Path) -> str | None:
    """``aragora.pkg.mod`` for a module inside the ``aragora`` package, else None.

    Matched on the LAST ``aragora`` path component so a checkout that itself
    lives under a directory named ``aragora`` (this repo's worktrees do)
    still yields the package-relative dotted name.
    """
    if f.suffix != ".py":
        return None
    parts = f.resolve().parts
    if "aragora" not in parts:
        return None
    idx = len(parts) - 1 - parts[::-1].index("aragora")
    tail = list(parts[idx:-1])
    if f.stem != "__init__":
        tail.append(f.stem)
    return ".".join(tail) if len(tail) > 1 else None


def _mirrors(module: Path, test: Path) -> bool:
    """True when ``test`` sits at ``module``'s mirrored location.

    ``aragora/<pkg path>/<mod>.py`` mirrors to
    ``tests/<pkg path>/test_<mod>*.py``: the package root maps onto the
    ``tests/`` root, so ``aragora/harnesses/codex.py`` pairs with
    ``tests/harnesses/test_codex.py`` and with nothing else named
    ``test_codex*.py`` elsewhere in the tree. A module outside the package
    keeps its own first component (``scripts/consult_claude.py`` ->
    ``tests/scripts/test_consult_claude.py``).

    Both paths are read relative to their COMMON ANCESTOR rather than to
    ``REPO_ROOT`` or to a path component literally named ``aragora``: the
    sweep accepts ``--paths`` anywhere (its own tests scan a tmp tree), and
    this checkout itself lives under a directory named ``aragora``, so
    scanning for the component would put every non-package module several
    directories "inside" the package.
    """
    m, t = module.resolve(), test.resolve()
    try:
        root = Path(os.path.commonpath([m, t]))
        module_dirs = m.relative_to(root).parts[:-1]
        test_dirs = t.relative_to(root).parts[:-1]
    except ValueError:
        return False
    if not test_dirs or test_dirs[0] != "tests":
        return False
    if module_dirs[:1] == ("aragora",):
        module_dirs = module_dirs[1:]
    return test_dirs[1:] == module_dirs


def _references_module(text: str, dotted: str) -> bool:
    """True when ``text`` really REFERENCES the module ``dotted``.

    Parsed, not grepped. A raw ``dotted in text`` also fired on a mention in
    a comment or a docstring, and on any longer dotted path that merely
    starts with this one -- ``aragora.pkg.mod`` matching a file that only
    names ``aragora.pkg.model`` (wave-6 re-review, minor 2). Two forms count:

    * an ``import``/``from`` statement that pulls in the module itself or a
      name out of it;
    * a string CONSTANT passed as a call argument that names the module or
      an attribute of it -- ``patch("aragora.pkg.mod.thing")``, the way a
      test binds itself to a module without importing it. Restricted to call
      arguments so a docstring that happens to name the module does not
      count.

    A file that will not parse falls back to the substring test: this
    over-approximates in the SAFE direction (freezing a test that did not
    need it leaves a literal as written; the unsafe direction breaks a
    lookup), and a syntactically broken test is not the place to get clever.
    """
    prefix = f"{dotted}."
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return dotted in text
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == dotted or alias.name.startswith(prefix) for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if base == dotted or base.startswith(prefix):
                return True
            # ``from aragora.pkg import mod`` -- the module is the NAME.
            if any(f"{base}.{alias.name}" == dotted for alias in node.names):
                return True
        elif isinstance(node, ast.Call):
            for arg in [*node.args, *(kw.value for kw in node.keywords)]:
                if (
                    isinstance(arg, ast.Constant)
                    and isinstance(arg.value, str)
                    and (arg.value == dotted or arg.value.startswith(prefix))
                ):
                    return True
    return False


def _paired_tests(module: Path, dotted: str, test_texts: dict[Path, str]) -> tuple[Path, ...]:
    """Test files that must freeze together with ``module``.

    A collision freeze is per FILE, so freezing ``aragora/harnesses/codex.py``
    without ``tests/harnesses/test_codex.py`` left the test asserting a
    default the source no longer had -- the source kept its historical
    spellings while its test was swept to the frontier ones (2026-09-05
    repo-wide re-sweep, reported as sweep gap 2; wave-6 ruling on #9989).

    Two pairings:

    * MIRRORED PATH -- ``tests/<package path>/test_<mod>*.py`` (see
      ``_mirrors``). Name alone was too loose:
      ``aragora/server/openapi/endpoints/debates.py`` dragged in every
      ``test_debates*.py`` in the tree -- the client's, the SDK's, the
      FastAPI routes' -- none of which asserts anything that module's
      collision freeze protects (wave-6 re-review, minor 2);
    * IMPORT -- a test that really references the module, verified by
      parsing it rather than by substring (see ``_references_module``).

    Both still over-approximate in the SAFE direction: a test that imports
    the module for one unrelated helper is frozen too, which only ever
    leaves a literal as written.

    Only tests that themselves contain a retired literal are candidates
    (``test_texts`` is built from those): a test with nothing to rewrite has
    nothing to freeze.
    """
    prefix = f"test_{module.stem}"
    paired = [
        t
        for t, text in test_texts.items()
        if (t.name.startswith(prefix) and _mirrors(module, t)) or _references_module(text, dotted)
    ]
    return tuple(sorted(paired, key=lambda p: p.as_posix()))


def _is_skip_path(f: Path) -> bool:
    """True if ``f`` matches a SKIP_PATHS entry by suffix.

    ``f.resolve().as_posix()`` is always an absolute path, so a directory
    entry (trailing "/") is matched as "/<entry>" appearing anywhere in
    that path, and a file entry is matched as an exact path suffix.
    """
    posix = f.resolve().as_posix()
    for skip in SKIP_PATHS:
        if skip.endswith("/"):
            if f"/{skip}" in posix:
                return True
        elif posix == skip or posix.endswith(f"/{skip}"):
            return True
    return False


def _allowlist_key(f: Path) -> str:
    """Normalize ``f`` to the form allowlist entries are written in.

    The allowlist (``scripts/baselines/retired_model_literals_allowlist.txt``)
    is generated via ``git ls-files`` from the repo root, so its entries are
    repo-root-relative POSIX paths regardless of the cwd or --paths spelling
    (relative or absolute) the sweep happens to be invoked with. Normalize
    the scanned file the same way — relative to REPO_ROOT when it is under
    the repo, else its absolute POSIX path — so membership testing doesn't
    silently no-op just because the sweep ran from a different directory.
    """
    resolved = f.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def iter_files(paths: list[str]) -> list[Path]:
    found: list[Path] = []
    for p in paths:
        root = Path(p)
        if root.is_file():
            # A file root has no "below the scan root" hierarchy at all, so
            # the SKIP_DIRS check below (which only ever excludes
            # directories *below* a scanned root) does not apply here.
            f = root
            if f.name in SKIP_NAMES or f.suffix in SKIP_SUFFIXES:
                continue
            if _is_skip_path(f):
                continue
            found.append(f)
            continue
        for f in root.rglob("*"):
            if not f.is_file() or f.name in SKIP_NAMES or f.suffix in SKIP_SUFFIXES:
                continue
            # SKIP_DIRS must only ever exclude directories *below* the scan
            # root that was passed in --paths (e.g. a nested node_modules/
            # or .venv/ found while walking that root) — never an ancestor
            # *above* it. Checking f.parts directly (as an earlier version
            # of this script did) inspects the WHOLE path, including
            # whatever lies above the scan root; if that ancestry happens
            # to include a directory named e.g. ".worktrees" (as this
            # repo's own dev checkouts do) or ".venv", an absolute --paths
            # would silently scan nothing. Relative-to-root parts contain
            # only what's actually below the given root.
            rel_parts = f.relative_to(root).parts
            if any(part in SKIP_DIRS for part in rel_parts):
                continue
            if _is_skip_path(f):
                continue
            found.append(f)
    # Deterministic order: --check output and --write iteration order must
    # not depend on filesystem/rglob discovery order (which varies by OS,
    # directory entry layout, and run-to-run).
    found.sort(key=lambda f: f.as_posix())
    return found


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--paths",
        nargs="+",
        default=["aragora", "scripts", "sdk", "docs", "docs-site", "tests", "README.md"],
    )
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--allowlist", default=str(DEFAULT_ALLOWLIST))
    a = ap.parse_args(argv)
    if a.write == a.check:
        print("choose exactly one of --write / --check", file=sys.stderr)
        return 2

    allow: set[str] = set()
    allow_path = Path(a.allowlist)
    if allow_path.exists():
        allow = {
            ln.strip()
            for ln in allow_path.read_text().splitlines()
            if ln.strip() and not ln.startswith("#")
        }

    offenders: list[tuple[str, int, str]] = []
    # Retired literals this sweep deliberately cannot rewrite: a bare
    # (native-shaped) spelling of a row Aragora reaches only through
    # OpenRouter. Reported separately and NEVER counted as an offender —
    # see replacement().
    unresolvable: list[tuple[str, int, str]] = []
    # Files where a rewrite would collapse text onto one id — two distinct
    # retired spellings sharing a replacement, or a replacement that is
    # already written in the file. Reported separately and NEVER counted as
    # an offender — see _collisions(). One entry per (file, target id).
    collisions: list[tuple[str, Collision]] = []
    changed = 0

    # Read every scanned file ONCE and keep only the ones that name a retired
    # literal at all: a module's collision can freeze spellings in its paired
    # TESTS (see _paired_tests), which is a decision about one file that
    # depends on other files, so the whole candidate set has to be in hand
    # before any of it is rewritten. Insertion order is iter_files()'s sorted
    # order, so --check output stays deterministic.
    candidates: dict[Path, list[str]] = {}
    for f in iter_files(a.paths):
        try:
            text = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if _allowlist_key(f) in allow:
            continue
        if not RETIRED_PATTERN.search(text):
            continue
        # ``keepends`` so --write can rejoin the file byte-for-byte: line
        # endings (and the presence or absence of a trailing newline) must
        # survive a rewrite that touches only some lines.
        candidates[f] = text.splitlines(keepends=True)

    # Collisions per file, then the source -> paired-test freezes they imply.
    test_texts = {f: "".join(lines) for f, lines in candidates.items() if _is_test_module(f)}
    collided_by_file: dict[Path, tuple[Collision, ...]] = {}
    inherited: dict[Path, set[str]] = {}
    for f, lines in candidates.items():
        collided = _collisions(lines)
        dotted = None if _is_test_module(f) else _module_dotted(f)
        if collided and dotted is not None:
            paired = _paired_tests(f, dotted, test_texts)
            spellings = {lit for c in collided for lit in c.olds}
            for t_path in paired:
                inherited.setdefault(t_path, set()).update(spellings)
            collided = tuple(
                c._replace(paired_tests=tuple(str(t_path) for t_path in paired)) for c in collided
            )
        collided_by_file[f] = collided

    for f, lines in candidates.items():
        collided = collided_by_file[f]
        frozen = frozenset(lit for c in collided for lit in c.olds) | inherited.get(f, set())
        collisions.extend((str(f), c) for c in collided)
        if a.check:
            for i, line in enumerate(lines, 1):
                for literal, new_literal in _scan_line(line):
                    if literal in frozen:
                        continue
                    bucket = offenders if new_literal is not None else unresolvable
                    bucket.append((str(f), i, literal))
        else:
            rewritten = [_rewrite_line(line, frozen) for line in lines]
            new = "".join(rewritten)
            if new != "".join(lines):
                f.write_text(new, encoding="utf-8")
                changed += 1

    if a.check:
        offenders.sort(key=lambda o: (o[0], o[1], o[2]))
        unresolvable.sort(key=lambda o: (o[0], o[1], o[2]))
        collisions.sort()
        for path, ln, lit in offenders:
            print(f"{path}:{ln}: retired model id {lit}")
        if unresolvable:
            print("unresolvable: bare spelling with no native id on its successor row")
            for path, ln, lit in unresolvable:
                print(f"{path}:{ln}: unresolvable model id {lit}")
        if collisions:
            print("collision: a rewrite that would collapse text onto one id")
            for path, collision in collisions:
                print(f"{path}: collision: {collision.describe()}")
        print(f"{len(offenders)} retired literal(s) outside allowlist")
        print(f"{len(unresolvable)} unresolvable literal(s) (not counted as offenders)")
        print(f"{len(collisions)} collision(s) (not counted as offenders)")
        # Exit code is deliberately driven by OFFENDERS only.
        return 1 if offenders else 0

    print(f"rewrote {changed} file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
