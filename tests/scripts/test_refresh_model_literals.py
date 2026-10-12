"""Tests for ``scripts/refresh_model_literals.py``.

Controller ruling (frontier-model-refresh, Task 8, 2026-09-04): the sweep
must SKIP files that legitimately contain retired ids — the catalog and
upgrade-map source itself, legacy pricing/routing tables old receipts
still resolve through, tests that assert retired ids on purpose, and the
script's own source. That skip list lives in ``SKIP_PATHS`` and is matched
by path suffix so it works regardless of the cwd the sweep runs from.

Fix round 1 (2026-09-05): two Important findings from review — (1)
``--check`` output was non-deterministic (``rglob`` discovery order), now
fixed by sorting scanned files and offenders; (2) the historical-allowlist
membership check compared a raw (possibly cwd- or absolute-path-flavored)
string against repo-relative allowlist entries, now fixed by normalizing
both sides to repo-root-relative POSIX paths via ``REPO_ROOT``.

The allowlist-normalization test loads the script as a module (rather than
via subprocess against the real repo) and monkeypatches its ``REPO_ROOT``
to a throwaway tmp_path tree. This repo's own dev checkout lives under a
directory literally named ``.worktrees`` (see ``SKIP_DIRS`` in the script),
so a subprocess run with a genuinely absolute --paths into the real repo
used to get zero files back regardless of the allowlist fix — an
unrelated, pre-existing SKIP_DIRS hazard flagged in fix-round-1 and fixed
in fix-round-2 (below).

Fix round 2 (2026-09-05): the flagged SKIP_DIRS hazard was itself the
Important finding this round — SKIP_DIRS membership was tested against
each file's raw (as-given) path parts, so an ancestor directory *above*
the --paths scan root (e.g. this checkout's own ``.worktrees`` parent, or
a ``.venv`` somewhere upstream) could false-positive and silently zero
out an absolute-path scan. Fixed by checking SKIP_DIRS only against parts
*relative to* the scan root; see ``test_skip_dirs_apply_only_below_the_scan_root``.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path("scripts/refresh_model_literals.py")


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)


def _load_module() -> Any:
    """Load scripts/refresh_model_literals.py as a fresh, isolated module."""
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "refresh_model_literals.py"
    spec = importlib.util.spec_from_file_location("refresh_model_literals_under_test", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load spec for {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_rewrites_bare_and_openrouter_spellings(tmp_path: Path) -> None:
    f = tmp_path / "x.py"
    f.write_text('A = "gpt-4o"\nB = "anthropic/claude-fable-5"\nC = "claude-fable-5-1"\n')
    r = _run("--paths", str(tmp_path), "--write", "--allowlist", str(tmp_path / "none.txt"))
    assert r.returncode == 0, r.stderr
    # gpt-4o upgrades to the VALUE row, not the flagship (round-4
    # re-review of finding C-P3 on #9989).
    assert f.read_text() == (
        'A = "gpt-5.6-terra"\nB = "anthropic/claude-fable-5.1"\nC = "claude-fable-5-1"\n'
    )


def test_check_fails_on_retired_literal_and_respects_allowlist(tmp_path: Path) -> None:
    f = tmp_path / "old.md"
    f.write_text("we shipped gpt-4 in 2024\n")
    allow = tmp_path / "allow.txt"
    allow.write_text("")
    assert _run("--paths", str(tmp_path), "--check", "--allowlist", str(allow)).returncode == 1
    allow.write_text(f"{f}\n")
    assert _run("--paths", str(tmp_path), "--check", "--allowlist", str(allow)).returncode == 0


def test_does_not_touch_lockfiles_or_git(tmp_path: Path) -> None:
    (tmp_path / "package-lock.json").write_text('{"x":"gpt-4"}')
    r = _run("--paths", str(tmp_path), "--write", "--allowlist", str(tmp_path / "none.txt"))
    assert r.returncode == 0 and (tmp_path / "package-lock.json").read_text() == '{"x":"gpt-4"}'


def test_skip_paths_are_never_rewritten_or_reported(tmp_path: Path) -> None:
    """Files at known SKIP_PATHS suffixes must be left alone entirely.

    These are the catalog/upgrade-map source, legacy pricing/routing
    tables, tests/models/, and the sweep script itself — see the
    SKIP_PATHS comment in scripts/refresh_model_literals.py for why each
    one legitimately contains retired ids on purpose.
    """
    skip_files = {
        tmp_path / "aragora" / "models" / "catalog.py": 'RETIRED = "gpt-4o"\n',
        tmp_path / "aragora" / "billing" / "usage.py": 'LEGACY = "gpt-4"\n',
        tmp_path / "tests" / "models" / "test_retired_on_purpose.py": 'OLD = "grok-3"\n',
        tmp_path / "scripts" / "refresh_model_literals.py": 'SELF = "claude-3-opus"\n',
    }
    for path, content in skip_files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    r = _run("--paths", str(tmp_path), "--write", "--allowlist", str(tmp_path / "none.txt"))
    assert r.returncode == 0, r.stderr
    for path, content in skip_files.items():
        assert path.read_text() == content, f"{path} was rewritten but should be skipped"

    r = _run("--paths", str(tmp_path), "--check", "--allowlist", str(tmp_path / "none.txt"))
    assert r.returncode == 0, f"skip-path files were reported as offenders: {r.stdout}"


def test_check_output_is_deterministic_and_sorted_by_path(tmp_path: Path) -> None:
    """Two --check runs over the same tree must print byte-identical,
    path-sorted output — not whatever order the filesystem/rglob happens
    to discover files in.
    """
    for name in ("zeta.py", "alpha.py", "mu.py", "beta.py"):
        (tmp_path / name).write_text('X = "gpt-4"\n')

    r1 = _run("--paths", str(tmp_path), "--check", "--allowlist", str(tmp_path / "none.txt"))
    r2 = _run("--paths", str(tmp_path), "--check", "--allowlist", str(tmp_path / "none.txt"))
    assert r1.returncode == 1 and r2.returncode == 1
    assert r1.stdout == r2.stdout, "identical --check runs produced different output"

    offender_lines = [ln for ln in r1.stdout.splitlines() if ": retired model id " in ln]
    assert len(offender_lines) == 4
    reported_paths = [ln.split(":", 1)[0] for ln in offender_lines]
    assert reported_paths == sorted(reported_paths), (
        f"offenders not sorted by path: {reported_paths}"
    )


def test_allowlist_matches_regardless_of_cwd_or_absolute_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The historical allowlist stores repo-relative paths (generated via
    ``git ls-files`` from the repo root). Membership must still match when
    the sweep is invoked from an unrelated cwd with an absolute --paths —
    not just when run from the repo root with relative --paths.

    Exercises this against a throwaway fake repo root (monkeypatched onto
    the loaded module) rather than the real one, so the test is hermetic
    and not confounded by this checkout's own SKIP_DIRS(".worktrees")
    layout — see the module docstring above.
    """
    module = _load_module()
    fake_repo_root = (tmp_path / "fake_repo").resolve()
    fixture_file = fake_repo_root / "tests" / "scripts" / "offender.py"
    fixture_file.parent.mkdir(parents=True)
    fixture_file.write_text('X = "gpt-4"\n')
    repo_relative = fixture_file.relative_to(fake_repo_root).as_posix()
    assert repo_relative == "tests/scripts/offender.py"

    monkeypatch.setattr(module, "REPO_ROOT", fake_repo_root)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    empty_allow = tmp_path / "empty_allow.txt"
    empty_allow.write_text("")
    sanity = module.main(["--paths", str(fixture_file), "--check", "--allowlist", str(empty_allow)])
    assert sanity == 1, "fixture should be a genuine offender without an allowlist entry"

    allow = tmp_path / "allow.txt"
    allow.write_text(f"{repo_relative}\n")
    result = module.main(["--paths", str(fixture_file), "--check", "--allowlist", str(allow)])
    assert result == 0, (
        "repo-relative allowlist entry did not match a file given as an "
        "absolute path while running from an unrelated cwd"
    )


def test_skip_dirs_apply_only_below_the_scan_root(tmp_path: Path) -> None:
    """SKIP_DIRS (e.g. ".worktrees", ".venv") must only ever exclude
    directories *below* the scan root passed via --paths — never an
    ancestor directory *above* it. A checkout nested under a directory
    literally named ".worktrees" (as this repo's own dev checkouts are)
    must still be scanned when --paths points at or below that directory;
    ".worktrees" should only cause a skip when it appears *inside* the
    scanned tree, i.e. below the given root.
    """
    offender = tmp_path / ".worktrees" / "wt" / "pkg" / "x.py"
    offender.parent.mkdir(parents=True)
    offender.write_text('X = "gpt-4"\n')

    # ".worktrees" is part of the scan root itself here (an ancestor of
    # the file, but AT the root, not below it) — the offender must still
    # be scanned and reported.
    r = _run(
        "--paths",
        str(tmp_path / ".worktrees" / "wt"),
        "--check",
        "--allowlist",
        str(tmp_path / "none.txt"),
    )
    assert r.returncode == 1, f"offender under an absolute scan root was not reported: {r.stdout}"
    assert "x.py" in r.stdout

    # Scanning from tmp_path instead, ".worktrees" is now BELOW the scan
    # root, so SKIP_DIRS correctly excludes it as before.
    r = _run("--paths", str(tmp_path), "--check", "--allowlist", str(tmp_path / "none.txt"))
    assert r.returncode == 0, (
        f"'.worktrees' below the scan root should still be skipped: {r.stdout}"
    )


# ---------------------------------------------------------------------------
# Unresolvable literals (2026-09-05 merge-gate fix wave, finding C-P3 on
# #9989; generalized by the wave-6 ruling, sweep gap 3): a BARE literal whose
# successor row is served by a DIFFERENT provider than the literal's own
# native API has no real native id to be rewritten to. ``ModelSpec.direct_id``
# is a documented placeholder on such a row, so rewriting the bare literal to
# it would swap a working native model code for one the native endpoint has
# never been shown to accept.
# ---------------------------------------------------------------------------


def test_replacement_returns_none_when_the_successor_has_no_native_transport() -> None:
    mod = _load_module()
    # All three resolve to rows whose provider is "openrouter" -- no native
    # transport at all, so direct_id is a placeholder.
    assert mod.replacement("deepseek-v4-pro") is None
    assert mod.replacement("qwen3-coder") is None
    # Moonshot's own legacy code: KimiLegacyAgent sends it to api.moonshot.cn,
    # and the kimi-k3 row it upgrades to is reached only through OpenRouter.
    assert mod.replacement("moonshot-v1-8k") is None
    # And the OpenRouter-slug SHAPE always rewrites, native transport or not.
    assert mod.replacement("deepseek/deepseek-v4-pro") == "deepseek/deepseek-v4-pro-0813"
    # A bare literal whose successor IS natively served still rewrites.
    assert mod.replacement("gpt-4o") == "gpt-5.6-terra"
    assert mod.replacement("o1-mini") == "gpt-5.6-terra"


def test_replacement_returns_none_across_a_provider_change() -> None:
    """The guard is provider-vs-provider, not a hardcoded "openrouter" test.

    ``qwen3.7-max`` has a catalog row of its own on Alibaba, so the sweep can
    see that it is a NATIVE Alibaba code; its successor row is served by
    OpenRouter, so no rewrite of it can stay a working Alibaba code.
    """
    from aragora.models.catalog import CATALOG, spec_or_none
    from aragora.models.upgrade_map import UPGRADES

    mod = _load_module()
    assert mod._native_provider("qwen3.7-max") == "alibaba"
    assert CATALOG[UPGRADES["qwen3.7-max"]].provider == "openrouter"
    assert mod.replacement("qwen3.7-max") is None
    # A spelling the catalog does not record at all yields no evidence of a
    # conflict, so it keeps rewriting.
    assert spec_or_none("gpt-4o") is None
    assert mod._native_provider("gpt-4o") is None


def test_write_leaves_bare_literals_without_a_native_successor_untouched(tmp_path: Path) -> None:
    f = tmp_path / "cli.py"
    original = (
        'DEEPSEEK = "deepseek-v4-pro"\n'
        'QWEN = "qwen3-coder"\n'
        'KIMI = "moonshot-v1-8k"\n'
        'SLUG = "deepseek/deepseek-v4-pro"\n'
    )
    f.write_text(original)
    r = _run("--paths", str(tmp_path), "--write", "--allowlist", str(tmp_path / "none.txt"))
    assert r.returncode == 0, r.stderr
    assert f.read_text() == (
        'DEEPSEEK = "deepseek-v4-pro"\n'
        'QWEN = "qwen3-coder"\n'
        'KIMI = "moonshot-v1-8k"\n'
        'SLUG = "deepseek/deepseek-v4-pro-0813"\n'
    )


def test_check_reports_unresolvable_separately_and_does_not_fail(tmp_path: Path) -> None:
    f = tmp_path / "cli.py"
    f.write_text('DEEPSEEK = "deepseek-v4-pro"\nQWEN = "qwen3-coder"\n')
    r = _run("--paths", str(tmp_path), "--check", "--allowlist", str(tmp_path / "none.txt"))
    assert r.returncode == 0, f"unresolvable literals must not gate the sweep:\n{r.stdout}"
    assert "unresolvable: bare spelling with no native id on its successor row" in r.stdout
    assert "unresolvable model id deepseek-v4-pro" in r.stdout
    assert "unresolvable model id qwen3-coder" in r.stdout
    assert "0 retired literal(s) outside allowlist" in r.stdout
    assert "2 unresolvable literal(s) (not counted as offenders)" in r.stdout


def test_check_still_fails_when_a_real_offender_shares_the_file(tmp_path: Path) -> None:
    """The unresolvable bucket must not swallow a genuine offender."""
    f = tmp_path / "cli.py"
    f.write_text('OK = "deepseek-v4-pro"\nBAD = "gpt-4o"\n')
    r = _run("--paths", str(tmp_path), "--check", "--allowlist", str(tmp_path / "none.txt"))
    assert r.returncode == 1
    assert "retired model id gpt-4o" in r.stdout
    assert "1 retired literal(s) outside allowlist" in r.stdout
    assert "1 unresolvable literal(s) (not counted as offenders)" in r.stdout


def test_check_sees_every_match_on_a_line(tmp_path: Path) -> None:
    """An unresolvable literal earlier on the line must not hide an offender
    later on the same line."""
    f = tmp_path / "cli.py"
    f.write_text('MODELS = ["deepseek-v4-pro", "gpt-4o"]\n')
    r = _run("--paths", str(tmp_path), "--check", "--allowlist", str(tmp_path / "none.txt"))
    assert r.returncode == 1
    assert "retired model id gpt-4o" in r.stdout
    assert "1 retired literal(s) outside allowlist" in r.stdout


# ---------------------------------------------------------------------------
# Class 2 — duplicate-key collapse (2026-09-04 controller ruling, from PR 3's
# trial-sweep report). Two DISTINCT retired spellings that rewrite to the SAME
# id silently collapse a hand-written dict/set/list literal onto one entry.
# ---------------------------------------------------------------------------


def test_write_leaves_both_sides_of_a_collision_untouched(tmp_path: Path) -> None:
    """A dict literal with two retired keys that share a replacement keeps
    BOTH keys — the whole point of the table is one row per old spelling."""
    f = tmp_path / "tiers.py"
    original = (
        "MODEL_TIERS = {\n"
        '    "claude-opus-4": {"tier": 1},\n'
        '    "claude-opus-4-6": {"tier": 2},\n'
        "}\n"
    )
    f.write_text(original)
    r = _run("--paths", str(tmp_path), "--write", "--allowlist", str(tmp_path / "none.txt"))
    assert r.returncode == 0, r.stderr
    assert f.read_text() == original


def test_collision_freezes_the_whole_file_not_just_one_line(tmp_path: Path) -> None:
    """File-level is the accepted over-approximation: a colliding spelling is
    frozen everywhere in the file, but a NON-colliding spelling in the same
    file still rewrites."""
    f = tmp_path / "mixed.py"
    f.write_text(
        'A = "claude-opus-4"\n'
        'B = "claude-opus-4-6"\n'
        'FAR_BELOW = "claude-opus-4"\n'
        'UNRELATED = "gemini-2.5-pro"\n'
    )
    r = _run("--paths", str(tmp_path), "--write", "--allowlist", str(tmp_path / "none.txt"))
    assert r.returncode == 0, r.stderr
    assert f.read_text() == (
        'A = "claude-opus-4"\n'
        'B = "claude-opus-4-6"\n'
        'FAR_BELOW = "claude-opus-4"\n'
        'UNRELATED = "gemini-3.1-pro-preview"\n'
    )


def test_check_reports_collisions_separately_and_does_not_fail(tmp_path: Path) -> None:
    f = tmp_path / "tiers.py"
    f.write_text('A = "claude-opus-4"\nB = "claude-opus-4-6"\n')
    r = _run("--paths", str(tmp_path), "--check", "--allowlist", str(tmp_path / "none.txt"))
    assert r.returncode == 0, f"collisions must not gate the sweep:\n{r.stdout}"
    assert "collision: a rewrite that would collapse text onto one id" in r.stdout
    assert "collision: claude-opus-4,claude-opus-4-6 -> claude-fable-5-1" in r.stdout
    assert "0 retired literal(s) outside allowlist" in r.stdout
    assert "1 collision(s) (not counted as offenders)" in r.stdout
    # A colliding literal must NOT also be counted as an offender.
    assert "retired model id claude-opus-4" not in r.stdout


def test_collision_does_not_swallow_a_genuine_offender_in_the_same_file(
    tmp_path: Path,
) -> None:
    f = tmp_path / "mixed.py"
    f.write_text('A = "claude-opus-4"\nB = "claude-opus-4-6"\nC = "gemini-2.5-pro"\n')
    r = _run("--paths", str(tmp_path), "--check", "--allowlist", str(tmp_path / "none.txt"))
    assert r.returncode == 1
    assert "retired model id gemini-2.5-pro" in r.stdout
    assert "1 retired literal(s) outside allowlist" in r.stdout
    assert "1 collision(s) (not counted as offenders)" in r.stdout


def test_retired_key_whose_replacement_is_already_present_is_frozen(tmp_path: Path) -> None:
    """A dict naming BOTH the retired spelling and its replacement collapses
    exactly as hard as two retired spellings do — Python keeps the last key.

    ``aragora/analysis/nl_query.py`` was a hard ``F601`` duplicate dict key
    after the 2026-09-05 re-sweep for precisely this reason (wave-6 ruling,
    sweep gap 1, on #9989).
    """
    f = tmp_path / "families.py"
    original = (
        'FAMILY = {\n    "claude-sonnet-4": "anthropic",\n    "claude-sonnet-5": "anthropic",\n}\n'
    )
    f.write_text(original)
    r = _run("--paths", str(tmp_path), "--write", "--allowlist", str(tmp_path / "none.txt"))
    assert r.returncode == 0, r.stderr
    assert f.read_text() == original


def test_check_reports_an_already_present_replacement_as_a_collision(tmp_path: Path) -> None:
    f = tmp_path / "families.py"
    f.write_text('OLD = "claude-sonnet-4"\nNEW = "claude-sonnet-5"\n')
    r = _run("--paths", str(tmp_path), "--check", "--allowlist", str(tmp_path / "none.txt"))
    assert r.returncode == 0, f"an already-present collision must not gate the sweep:\n{r.stdout}"
    assert "collision: claude-sonnet-4 -> claude-sonnet-5 (already present)" in r.stdout
    assert "0 retired literal(s) outside allowlist" in r.stdout
    assert "1 collision(s) (not counted as offenders)" in r.stdout
    # The frozen spelling must not ALSO be counted as an offender.
    assert "retired model id claude-sonnet-4" not in r.stdout


def test_already_present_check_uses_model_id_token_boundaries(tmp_path: Path) -> None:
    """The replacement id must occur as a whole token to count as present.

    A substring hit (``claude-sonnet-5`` inside ``claude-sonnet-5-preview``)
    is a different id and must not freeze a genuine rewrite.
    """
    f = tmp_path / "near_miss.py"
    f.write_text('OLD = "claude-sonnet-4"\nOTHER = "claude-sonnet-5-preview"\n')
    r = _run("--paths", str(tmp_path), "--write", "--allowlist", str(tmp_path / "none.txt"))
    assert r.returncode == 0, r.stderr
    assert f.read_text() == 'OLD = "claude-sonnet-5"\nOTHER = "claude-sonnet-5-preview"\n'


def test_two_spellings_with_different_targets_are_not_a_collision(tmp_path: Path) -> None:
    """Only a SHARED replacement is a collision. Two retired spellings that
    upgrade to different ids are both rewritten as normal."""
    f = tmp_path / "ok.py"
    f.write_text('A = "claude-opus-4"\nB = "gemini-2.5-pro"\n')
    r = _run("--paths", str(tmp_path), "--write", "--allowlist", str(tmp_path / "none.txt"))
    assert r.returncode == 0, r.stderr
    assert f.read_text() == 'A = "claude-fable-5-1"\nB = "gemini-3.1-pro-preview"\n'


# ---------------------------------------------------------------------------
# Class 3a/3b — bare short tokens and regex sources. ``o1``/``o3`` used to be
# the only UPGRADES keys that are both hyphen-free and shorter than six
# characters; the wave-6 ruling (sweep gap 4, #9989) dropped them from the map
# entirely, so RETIRED_PATTERN no longer matches them at all. ``gpt-4`` is
# hyphenated and deliberately unaffected.
# ---------------------------------------------------------------------------


def test_bare_o1_and_o3_are_not_retired_keys_but_their_siblings_are() -> None:
    """The bare two-character tokens are gone from the map; every hyphenated
    o-series spelling stays, because those ARE unambiguously model ids."""
    from aragora.models.upgrade_map import RETIRED_PATTERN, UPGRADES

    assert "o1" not in UPGRADES and "o3" not in UPGRADES
    assert not RETIRED_PATTERN.search("o1") and not RETIRED_PATTERN.search("o3")
    for hyphenated in ("o1-mini", "o3-mini", "o3-pro", "o4-mini"):
        assert hyphenated in UPGRADES, hyphenated
        assert RETIRED_PATTERN.search(hyphenated), hyphenated


def test_short_bare_keys_is_empty_now_that_o1_and_o3_are_gone() -> None:
    """The derivation stays as the standing rule for a future short key, but
    it currently has no members to guard."""
    mod = _load_module()
    assert mod.SHORT_BARE_KEYS == frozenset()


def test_bare_identifier_named_o1_is_never_rewritten(tmp_path: Path) -> None:
    """PR 3's trial sweep turned ``o1 = _make_org(...)`` into an invalid
    assignment target — a hard SyntaxError no test caught."""
    f = tmp_path / "test_store.py"
    original = "o1 = _make_org(name='acme')\nassert o1.id\n"
    f.write_text(original)
    r = _run("--paths", str(tmp_path), "--write", "--allowlist", str(tmp_path / "none.txt"))
    assert r.returncode == 0, r.stderr
    assert f.read_text() == original


def test_o1_in_prose_is_never_rewritten(tmp_path: Path) -> None:
    f = tmp_path / "feasibility.md"
    original = "The evaluation covered GPT-4o, o1, o3 and the Claude line.\n"
    f.write_text(original)
    r = _run("--paths", str(tmp_path), "--write", "--allowlist", str(tmp_path / "none.txt"))
    assert r.returncode == 0, r.stderr
    assert f.read_text() == original


def test_guarded_short_tokens_are_not_reported_as_offenders(tmp_path: Path) -> None:
    """A guarded match was never a model id, so --check must not name it —
    otherwise the sweep could never reach a clean exit."""
    f = tmp_path / "prose.md"
    f.write_text("we shipped o1 and o3 in 2024\n")
    r = _run("--paths", str(tmp_path), "--check", "--allowlist", str(tmp_path / "none.txt"))
    assert r.returncode == 0, r.stdout
    assert "0 retired literal(s) outside allowlist" in r.stdout
    assert "0 collision(s) (not counted as offenders)" in r.stdout


def test_bare_o1_and_o3_string_literals_are_left_alone(tmp_path: Path) -> None:
    """Quoting used to ADMIT a complete ``"o1"`` string body as a model id.
    That shape is exactly how a placeholder org/plan/route id is written, so
    25 files were rewritten where nothing was a model (wave-6 ruling, sweep
    gap 4). With the keys gone from UPGRADES the shape is no longer even
    matched."""
    f = tmp_path / "pins.py"
    original = 'MODEL = "o1"\nPREFIX = \'o3:reasoning\'\nORG = {"id": "o1"}\n'
    f.write_text(original)
    r = _run("--paths", str(tmp_path), "--write", "--allowlist", str(tmp_path / "none.txt"))
    assert r.returncode == 0, r.stderr
    assert f.read_text() == original


def test_hyphenated_o_series_pins_are_still_rewritten(tmp_path: Path) -> None:
    """Dropping the bare keys must not stop a real o-series pin upgrading."""
    f = tmp_path / "pins.py"
    f.write_text('MODEL = "o1-mini"\nOTHER = "o3-pro"\n')
    r = _run("--paths", str(tmp_path), "--write", "--allowlist", str(tmp_path / "none.txt"))
    assert r.returncode == 0, r.stderr
    assert f.read_text() == 'MODEL = "gpt-5.6-terra"\nOTHER = "gpt-6-astra"\n'


def test_raw_string_regex_source_is_never_rewritten(tmp_path: Path) -> None:
    """``aragora/debate/provider_diversity.py``'s ``r"gpt|o1|o3|chatgpt"``
    matcher: sweeping it made ``detect_provider("o1-preview")`` return
    "unknown"."""
    f = tmp_path / "provider_diversity.py"
    original = 'PATTERNS = {"openai": [r"gpt|o1|o3|chatgpt"]}\n'
    f.write_text(original)
    r = _run("--paths", str(tmp_path), "--write", "--allowlist", str(tmp_path / "none.txt"))
    assert r.returncode == 0, r.stderr
    assert f.read_text() == original


def test_raw_string_guard_covers_hyphenated_keys_too(tmp_path: Path) -> None:
    """The raw-string guard is not restricted to short tokens: a raw string
    in this repo is a regex source, never a model id."""
    f = tmp_path / "matcher.py"
    original = 'FAMILY = r"^(claude-opus-4|gpt-4o)$"\n'
    f.write_text(original)
    r = _run("--paths", str(tmp_path), "--write", "--allowlist", str(tmp_path / "none.txt"))
    assert r.returncode == 0, r.stderr
    assert f.read_text() == original


def test_re_compile_line_is_never_rewritten(tmp_path: Path) -> None:
    f = tmp_path / "safety.py"
    original = 'RX = re.compile("gpt|o1|o3")\n'
    f.write_text(original)
    r = _run("--paths", str(tmp_path), "--write", "--allowlist", str(tmp_path / "none.txt"))
    assert r.returncode == 0, r.stderr
    assert f.read_text() == original


def test_pipe_separated_regex_shaped_string_is_not_rewritten(tmp_path: Path) -> None:
    """A ``|`` string that ALSO carries a regex metacharacter is a matcher."""
    f = tmp_path / "markers.py"
    original = 'OPENAI = "gpt(-4)?|o1|o3"\n'
    f.write_text(original)
    r = _run("--paths", str(tmp_path), "--write", "--allowlist", str(tmp_path / "none.txt"))
    assert r.returncode == 0, r.stderr
    assert f.read_text() == original


def test_pipe_separated_agent_spec_is_rewritten_like_any_literal(tmp_path: Path) -> None:
    """``provider|model`` is Aragora's own agent-spec DSL, not a regex.

    Treating every ``|``-containing string as a regex silently dropped 15
    genuine model ids from both --write and --check -- production code,
    tests and docs -- so the sweep reported them as neither rewritten nor
    outstanding (2026-09-05 merge-gate addendum on #9989). A pipe alone is
    no longer enough: the body must also carry a regex metacharacter, or
    sit in a raw-string / ``re.``-call / ``pattern=`` context.
    """
    f = tmp_path / "spec.py"
    f.write_text('SPEC = "anthropic|claude-sonnet-4"\nOTHER = "openai|gpt-4o"\n')
    r = _run("--paths", str(tmp_path), "--write", "--allowlist", str(tmp_path / "none.txt"))
    assert r.returncode == 0, r.stderr
    assert f.read_text() == 'SPEC = "anthropic|claude-sonnet-5"\nOTHER = "openai|gpt-5.6-terra"\n'


def test_pipe_separated_ids_are_counted_by_check(tmp_path: Path) -> None:
    """They must also stop being invisible to --check."""
    f = tmp_path / "spec.py"
    f.write_text('SPEC = "anthropic|claude-sonnet-4"\n')
    r = _run("--paths", str(tmp_path), "--check", "--allowlist", str(tmp_path / "none.txt"))
    assert r.returncode == 1
    assert "1 retired literal(s) outside allowlist" in r.stdout
    assert "claude-sonnet-4" in r.stdout


def test_regex_call_context_beyond_re_compile_is_guarded(tmp_path: Path) -> None:
    """``re.compile(`` was too narrow: any ``re.`` call or ``pattern=`` counts."""
    f = tmp_path / "pat.py"
    original = (
        "import re\n"
        'M = re.match("gpt-4o|o1", s)\n'
        'S = re.sub("gpt-4o|o1", "x", s)\n'
        'D = dict(pattern="gpt-4o|o1")\n'
    )
    f.write_text(original)
    r = _run("--paths", str(tmp_path), "--write", "--allowlist", str(tmp_path / "none.txt"))
    assert r.returncode == 0, r.stderr
    assert f.read_text() == original


def test_a_pipe_elsewhere_in_the_string_does_not_freeze_a_real_id(tmp_path: Path) -> None:
    """The alternation guard requires the match to be BOUNDED by ``|`` or by
    the string edge — a markdown table cell in a quoted string still
    rewrites."""
    f = tmp_path / "row.py"
    f.write_text('ROW = "model gpt-4o costs | see table"\n')
    r = _run("--paths", str(tmp_path), "--write", "--allowlist", str(tmp_path / "none.txt"))
    assert r.returncode == 0, r.stderr
    assert f.read_text() == 'ROW = "model gpt-5.6-terra costs | see table"\n'


# ---------------------------------------------------------------------------
# Class 6 — a frozen pricing source's test must be frozen with it.
# ---------------------------------------------------------------------------


def test_frozen_pricing_source_tests_are_in_skip_paths() -> None:
    """A SKIP_PATHS pricing table is keyed on its historical spellings, so
    the test that looks those spellings up EXACTLY must be skipped too.

    The pairing is DERIVED from the script's own
    ``FROZEN_PRICING_SOURCE_TESTS`` rather than restated here: a duplicated
    literal map let a future frozen source ship with no paired test and this
    test still pass, which is the failure mode it exists to prevent
    (2026-09-05 merge-gate addendum on #9989).
    """
    mod = _load_module()
    paired = mod.FROZEN_PRICING_SOURCE_TESTS
    assert paired, "the pairing map must not be empty"
    for source, tests in paired.items():
        assert source in mod.SKIP_PATHS, f"frozen source {source} is not skipped"
        assert tests, f"frozen source {source} declares no paired test"
        for t in tests:
            assert t in mod.SKIP_PATHS, f"{t} pairs with frozen {source} but is not skipped"
            assert t.startswith("tests/"), f"{t} is not a test path"


def test_every_frozen_pricing_source_declares_a_paired_test() -> None:
    """A frozen aragora/*pricing* source with no pairing entry is half a freeze.

    ``_UNPAIRED_SKIP_PATHS`` is the deliberate escape hatch (the catalog, its
    generated mirrors, the routing hand-rows, this script and its own test),
    so anything skipped OUTSIDE that tuple must come from the pairing map.
    """
    mod = _load_module()
    accounted = set(mod._UNPAIRED_SKIP_PATHS)
    for source, tests in mod.FROZEN_PRICING_SOURCE_TESTS.items():
        accounted.add(source)
        accounted.update(tests)
    assert set(mod.SKIP_PATHS) == accounted, (
        "SKIP_PATHS has entries that are neither an explicit unpaired skip "
        f"nor part of the pairing map: {sorted(set(mod.SKIP_PATHS) - accounted)}"
    )


def test_frozen_pricing_test_files_are_not_rewritten(tmp_path: Path) -> None:
    fixtures = {
        tmp_path / "tests" / "billing" / "test_usage.py": 'K = "gpt-4o"\n',
        tmp_path / "tests" / "pdb" / "test_real_invoker.py": 'K = "claude-opus-4"\n',
        tmp_path
        / "tests"
        / "handlers"
        / "debates"
        / "test_cost_estimation.py": 'K = "gemini-2.5-pro"\n',
        tmp_path / "tests" / "e2e" / "test_billing_accuracy_e2e.py": 'K = "grok-4"\n',
    }
    for path, content in fixtures.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    r = _run("--paths", str(tmp_path), "--write", "--allowlist", str(tmp_path / "none.txt"))
    assert r.returncode == 0, r.stderr
    for path, content in fixtures.items():
        assert path.read_text() == content, f"{path} was rewritten but pairs with a frozen source"


def test_module_docstring_documents_the_period_vs_hyphen_split() -> None:
    """The same literal maps to the hyphen form bare and the dotted form as a
    slug; that is by design and must be written down where the sweep's users
    look."""
    mod = _load_module()
    doc = mod.__doc__ or ""
    assert "direct_id" in doc and "openrouter_id" in doc
    assert "claude-fable-5-1" in doc and "anthropic/claude-fable-5.1" in doc


# ---------------------------------------------------------------------------
# Sweep gap 2 (wave-6 ruling on #9989) — a collision freeze is per FILE, so a
# frozen module used to be swept out of agreement with its own tests:
# aragora/harnesses/codex.py kept its historical default while
# tests/harnesses/test_codex.py was rewritten to the frontier one.
# ---------------------------------------------------------------------------


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_collision_in_a_module_freezes_its_mirrored_test(tmp_path: Path) -> None:
    """The name pairing is MIRRORED: ``aragora/<pkg>/<mod>.py`` freezes
    ``tests/<pkg>/test_<mod>*.py`` and nothing else of that name elsewhere
    (wave-6 re-review, minor 2)."""
    module = _write(
        tmp_path / "aragora" / "fixturepkg" / "aragora_fixture_mod.py",
        'FAMILY = {\n    "claude-sonnet-4": "anthropic",\n    "claude-sonnet-5": "anthropic",\n}\n',
    )
    paired = _write(
        tmp_path / "tests" / "fixturepkg" / "test_aragora_fixture_mod.py",
        'def test_default():\n    assert MOD.FAMILY["claude-sonnet-4"] == "anthropic"\n',
    )
    module_text, paired_text = module.read_text(), paired.read_text()

    r = _run("--paths", str(tmp_path), "--write", "--allowlist", str(tmp_path / "none.txt"))
    assert r.returncode == 0, r.stderr
    assert module.read_text() == module_text, "the colliding module was rewritten"
    assert paired.read_text() == paired_text, (
        "the module's paired test was swept out of agreement with the frozen module"
    )


def test_collision_in_a_module_freezes_a_test_that_imports_it(tmp_path: Path) -> None:
    """The pairing is not only by name: a test that imports the module by its
    dotted path looks its historical spellings up just as exactly."""
    _write(
        tmp_path / "aragora" / "aragora_fixture_mod.py",
        'FAMILY = {"claude-sonnet-4": "a", "claude-sonnet-5": "a"}\n',
    )
    importer = _write(
        tmp_path / "tests" / "fixture" / "test_unrelated_name.py",
        "from aragora.aragora_fixture_mod import FAMILY\n\n\ndef test_it():\n"
        '    assert FAMILY["claude-sonnet-4"] == "a"\n',
    )
    original = importer.read_text()

    r = _run("--paths", str(tmp_path), "--write", "--allowlist", str(tmp_path / "none.txt"))
    assert r.returncode == 0, r.stderr
    assert importer.read_text() == original


def test_an_unrelated_test_is_still_rewritten(tmp_path: Path) -> None:
    """The freeze follows the pairing, not the whole tests tree."""
    _write(
        tmp_path / "aragora" / "aragora_fixture_mod.py",
        'FAMILY = {"claude-sonnet-4": "a", "claude-sonnet-5": "a"}\n',
    )
    unrelated = _write(
        tmp_path / "tests" / "fixture" / "test_something_else.py",
        'MODEL = "claude-sonnet-4"\n',
    )

    r = _run("--paths", str(tmp_path), "--write", "--allowlist", str(tmp_path / "none.txt"))
    assert r.returncode == 0, r.stderr
    assert unrelated.read_text() == 'MODEL = "claude-sonnet-5"\n'


def test_check_reports_the_pairing_on_the_collision_line(tmp_path: Path) -> None:
    _write(
        tmp_path / "aragora" / "fixturepkg" / "aragora_fixture_mod.py",
        'FAMILY = {"claude-sonnet-4": "a", "claude-sonnet-5": "a"}\n',
    )
    paired = _write(
        tmp_path / "tests" / "fixturepkg" / "test_aragora_fixture_mod.py",
        'MODEL = "claude-sonnet-4"\n',
    )

    r = _run("--paths", str(tmp_path), "--check", "--allowlist", str(tmp_path / "none.txt"))
    assert r.returncode == 0, f"a frozen pairing must not gate the sweep:\n{r.stdout}"
    assert "(already present) (frozen with it: " in r.stdout
    assert str(paired) in r.stdout
    # The inherited freeze must also keep the test out of the offender list.
    assert "0 retired literal(s) outside allowlist" in r.stdout


def test_legacy_table_sources_and_their_tests_are_frozen(tmp_path: Path) -> None:
    """The ``_LEGACY_*`` family (wave-6 ruling, frozen sources, #9989).

    Each of these merges a hand-written historical table with rows generated
    from the catalog. Sweeping the legacy half deletes the only reason it
    exists -- answering lookups written in the historical spellings -- so
    both the source and the tests that make those lookups stay frozen.
    """
    fixtures = {
        tmp_path / "aragora" / "documents" / "models.py": 'L = {"claude-3-opus": 200_000}\n',
        tmp_path
        / "aragora"
        / "documents"
        / "chunking"
        / "context_manager.py": 'P = {"gpt-4-turbo": 0.01}\n',
        tmp_path / "aragora" / "billing" / "optimizer.py": 'T = {"claude-opus-4": 1}\n',
        tmp_path / "aragora" / "workflow" / "resource_tracker.py": 'P = {"gpt-4": 0.03}\n',
        tmp_path / "aragora" / "workflow" / "engine_v2.py": 'P = {"gemini-pro": 0.001}\n',
        tmp_path
        / "aragora"
        / "server"
        / "handlers"
        / "agents"
        / "recommendations.py": 'C = {"gpt-4o": 0.01}\n',
        tmp_path
        / "aragora"
        / "server"
        / "handlers"
        / "debates"
        / "diagnostics.py": 'M = {"mistral-large": "mistral"}\n',
        tmp_path / "tests" / "documents" / "test_models.py": 'K = "claude-3-opus"\n',
        tmp_path / "tests" / "documents" / "test_chunking.py": 'K = "claude-3-opus"\n',
        tmp_path / "tests" / "documents" / "test_context_manager.py": 'K = "gpt-4-turbo"\n',
        tmp_path / "tests" / "billing" / "test_optimizer.py": 'K = "claude-opus-4"\n',
        tmp_path / "tests" / "workflow" / "test_executor_protocol.py": 'K = "gpt-4"\n',
        tmp_path / "tests" / "workflow" / "test_engine_v2.py": 'K = "gemini-pro"\n',
        tmp_path / "tests" / "handlers" / "agents" / "test_recommendations.py": 'K = "gpt-4o"\n',
        tmp_path
        / "tests"
        / "handlers"
        / "debates"
        / "test_diagnostics.py": 'K = "mistral-large"\n',
    }
    for path, content in fixtures.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    r = _run("--paths", str(tmp_path), "--write", "--allowlist", str(tmp_path / "none.txt"))
    assert r.returncode == 0, r.stderr
    for path, content in fixtures.items():
        assert path.read_text() == content, f"{path} was rewritten but is a frozen source or test"

    r = _run("--paths", str(tmp_path), "--check", "--allowlist", str(tmp_path / "none.txt"))
    assert r.returncode == 0, f"frozen _LEGACY_* paths were reported as offenders: {r.stdout}"


# ---------------------------------------------------------------------------
# The provider-vs-provider leg of replacement(), pinned to FIXTURE rows.
#
# Wave-6 re-review, minor 1: asserting it through whichever real row happens
# to straddle two providers today (``qwen3.7-max``) means the day the catalog
# gives that family a native successor, the assertion still passes while
# exercising nothing. These pin the branch itself.
# ---------------------------------------------------------------------------


def _fixture_spec(canonical_id: str, provider: str) -> Any:
    from aragora.models.catalog import ModelSpec

    return ModelSpec(
        canonical_id=canonical_id,
        provider=provider,
        direct_id=f"{canonical_id}-native",
        openrouter_id=f"{provider}/{canonical_id}",
        input_per_mtok=1.0,
        output_per_mtok=2.0,
        context_window=100_000,
        max_output_tokens=8_000,
        release_date="2026-01-01",
    )


def test_replacement_is_none_when_the_successor_changes_native_provider() -> None:
    """The literal is a native code of provider A; its successor is served
    natively by provider B. No rewrite of it can stay a working A code."""
    mod = _load_module()
    successor = _fixture_spec("newmodel", "othercorp")
    assert (
        mod.replacement(
            "oldmodel",
            catalog={"newmodel": successor},
            upgrades={"oldmodel": "newmodel"},
            spec_lookup=lambda _id: _fixture_spec("oldmodel", "acme"),
        )
        is None
    )


def test_replacement_rewrites_when_both_rows_name_the_same_provider() -> None:
    """The positive control for the same branch: same provider on both sides
    and the bare literal DOES rewrite, to the successor's native code."""
    mod = _load_module()
    successor = _fixture_spec("newmodel", "acme")
    assert (
        mod.replacement(
            "oldmodel",
            catalog={"newmodel": successor},
            upgrades={"oldmodel": "newmodel"},
            spec_lookup=lambda _id: _fixture_spec("oldmodel", "acme"),
        )
        == "newmodel-native"
    )


def test_replacement_rewrites_when_the_literal_has_no_row_of_its_own() -> None:
    """No row for the literal is no EVIDENCE of a conflict, so the sweep
    keeps rewriting -- the usual case for a retired id."""
    mod = _load_module()
    assert (
        mod.replacement(
            "oldmodel",
            catalog={"newmodel": _fixture_spec("newmodel", "acme")},
            upgrades={"oldmodel": "newmodel"},
            spec_lookup=lambda _id: None,
        )
        == "newmodel-native"
    )


def test_replacement_is_none_when_the_successor_has_no_native_row_at_all() -> None:
    """The other unresolvable leg, also on fixtures: an openrouter-only
    successor has a placeholder direct_id, not a native code."""
    mod = _load_module()
    assert (
        mod.replacement(
            "oldmodel",
            catalog={"newmodel": _fixture_spec("newmodel", "openrouter")},
            upgrades={"oldmodel": "newmodel"},
            spec_lookup=lambda _id: None,
        )
        is None
    )
    # ...but the SLUG shape rewrites regardless of native transport.
    assert (
        mod.replacement(
            "vendor/oldmodel",
            catalog={"newmodel": _fixture_spec("newmodel", "openrouter")},
            upgrades={"vendor/oldmodel": "newmodel"},
        )
        == "openrouter/newmodel"
    )


# ---------------------------------------------------------------------------
# _paired_tests: mirrored path OR a parsed import, never a bare substring.
#
# Wave-6 re-review, minor 2. The old rule paired on file stem anywhere in the
# tree and on ``dotted in text``, so a module dragged in same-named tests of
# OTHER packages and any file that merely MENTIONED its dotted path.
# ---------------------------------------------------------------------------


def _paired_names(mod: Any, module: Path, dotted: str, tests: dict[Path, str]) -> set[str]:
    return {p.name for p in mod._paired_tests(module, dotted, tests)}


def test_paired_tests_matches_the_mirrored_path(tmp_path: Path) -> None:
    mod = _load_module()
    repo = (tmp_path / "repo").resolve()
    module = repo / "aragora" / "harnesses" / "codex.py"
    mirrored = repo / "tests" / "harnesses" / "test_codex.py"
    for p in (module, mirrored):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("")

    assert _paired_names(mod, module, "aragora.harnesses.codex", {mirrored: 'X = "gpt-4o"\n'}) == {
        "test_codex.py"
    }


def test_paired_tests_rejects_the_same_stem_in_another_package(tmp_path: Path) -> None:
    """The negative case: ``tests/cli/test_codex.py`` tests a DIFFERENT
    module that happens to share a name, and freezing it on the harness
    module's collision froze literals for no reason."""
    mod = _load_module()
    repo = (tmp_path / "repo").resolve()
    module = repo / "aragora" / "harnesses" / "codex.py"
    elsewhere = repo / "tests" / "cli" / "test_codex.py"
    for p in (module, elsewhere):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("")

    assert mod._paired_tests(module, "aragora.harnesses.codex", {elsewhere: 'X = "gpt-4o"\n'}) == ()


def test_paired_tests_mirrors_a_module_outside_the_package(tmp_path: Path) -> None:
    """``scripts/consult_claude.py`` mirrors to ``tests/scripts/`` -- the
    package-root strip must not swallow a non-package module's own dir."""
    mod = _load_module()
    repo = (tmp_path / "repo").resolve()
    module = repo / "scripts" / "consult_claude.py"
    mirrored = repo / "tests" / "scripts" / "test_consult_claude.py"
    for p in (module, mirrored):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("")

    assert _paired_names(mod, module, "scripts.consult_claude", {mirrored: 'X = "gpt-4o"\n'}) == {
        "test_consult_claude.py"
    }


def test_paired_tests_accepts_every_import_shape(tmp_path: Path) -> None:
    mod = _load_module()
    repo = (tmp_path / "repo").resolve()
    module = repo / "aragora" / "ml" / "agent_router.py"
    module.parent.mkdir(parents=True, exist_ok=True)
    module.write_text("")

    shapes = {
        "test_a.py": "import aragora.ml.agent_router\nX = 'gpt-4o'\n",
        "test_b.py": "from aragora.ml.agent_router import Router\nX = 'gpt-4o'\n",
        "test_c.py": "from aragora.ml import agent_router\nX = 'gpt-4o'\n",
        "test_d.py": "patch('aragora.ml.agent_router.Router')\nX = 'gpt-4o'\n",
    }
    texts = {}
    for name, text in shapes.items():
        p = repo / "tests" / "unrelated" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        texts[p] = text

    assert _paired_names(mod, module, "aragora.ml.agent_router", texts) == set(shapes)


def test_paired_tests_rejects_a_mere_mention(tmp_path: Path) -> None:
    """The negative case for the import leg. ``tests/unit/test_ml_module.py``
    only ever writes the dotted path inside ``assert "aragora.ml.agent_router"
    not in sys.modules`` -- an assertion that the module is NOT imported --
    and a comment or docstring mention is no reference either. A longer
    dotted path that merely starts with this one is a different module."""
    mod = _load_module()
    repo = (tmp_path / "repo").resolve()
    module = repo / "aragora" / "ml" / "agent_router.py"
    module.parent.mkdir(parents=True, exist_ok=True)
    module.write_text("")

    non_references = {
        "test_not_imported.py": (
            'import sys\nassert "aragora.ml.agent_router" not in sys.modules\nX = "gpt-4o"\n'
        ),
        "test_comment.py": "# see aragora.ml.agent_router for the mapping\nX = 'gpt-4o'\n",
        "test_docstring.py": '"""Mirrors aragora.ml.agent_router."""\nX = "gpt-4o"\n',
        "test_longer.py": "from aragora.ml.agent_router_legacy import R\nX = 'gpt-4o'\n",
    }
    texts = {}
    for name, text in non_references.items():
        p = repo / "tests" / "unit" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        texts[p] = text

    assert mod._paired_tests(module, "aragora.ml.agent_router", texts) == ()


def test_paired_tests_falls_back_to_substring_for_unparseable_text(tmp_path: Path) -> None:
    """A syntactically broken test still over-freezes -- the safe direction."""
    mod = _load_module()
    repo = (tmp_path / "repo").resolve()
    module = repo / "aragora" / "ml" / "agent_router.py"
    module.parent.mkdir(parents=True, exist_ok=True)
    module.write_text("")

    broken = repo / "tests" / "unit" / "test_broken.py"
    broken.parent.mkdir(parents=True, exist_ok=True)
    text = "def (:\nfrom aragora.ml.agent_router import R\nX = 'gpt-4o'\n"
    broken.write_text(text)

    assert _paired_names(mod, module, "aragora.ml.agent_router", {broken: text}) == {
        "test_broken.py"
    }
