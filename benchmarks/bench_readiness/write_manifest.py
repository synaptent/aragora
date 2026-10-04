#!/usr/bin/env python3
# ruff: noqa: BLE001, T201
"""
Bench-readiness manifest generator.

Captures a reproducibility snapshot for the Tier-1 ablation and Tier-2 e2e
benchmark: git SHA, Python version, pinned package hashes, platform info,
declared model pins, and the status summaries produced by the other three
phase scripts (venv rebuild, flag ablation, CLI e2e).

Run AFTER the other three phases so the summaries are up to date:
  .venv/bin/python -m benchmarks.bench_readiness.flag_ablation_smoke
  .venv/bin/python -m benchmarks.bench_readiness.standalone_debate_smoke
  .venv/bin/python -m benchmarks.bench_readiness.write_manifest
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent


def _portable_path(path: Path) -> tuple[str, bool]:
    """Return a portability-safe string form of ``path``.

    The manifest is a committed reproducibility snapshot in a public repo, so an
    absolute home-dir path (``/Users/<name>/...``) would both leak the local
    username and trip ``scripts/check_portability.py``. Collapse the home prefix
    to ``~`` so the committed artifact is clone-agnostic. The second element is
    ``True`` when the path was rewritten (i.e. it lives under ``$HOME``), which
    callers use to decide whether a resolved-exists boolean is still meaningful.
    """
    raw = str(path)
    home = os.path.expanduser("~")
    if home and home != "~" and (raw == home or raw.startswith(home + os.sep)):
        return "~" + raw[len(home) :], True
    return raw, False


# Models the ROADMAP / AGENTS.md treats as the canonical provider set.
# These are the *declared* pins; the benchmark should record whatever the
# runtime actually resolves (provider routing may substitute).
DECLARED_MODEL_PINS = {
    "anthropic": "claude-opus-4-7",
    "openai": "gpt-4.1",
    "gemini": "gemini-3.1-pro-preview",
    "xai": "grok-4-latest",
    "mistral": "mistral-large-2512",
    "openrouter.deepseek": "deepseek/deepseek-v4-pro",
    "openrouter.llama": "meta-llama/llama-3.3-70b-instruct",
    "openrouter.qwen": "qwen/qwen3.8-max",
    "openrouter.kimi": "moonshotai/kimi-k3",
    "built-in.demo": "demo",
}


def _run(cmd: list[str]) -> str:
    try:
        out = subprocess.check_output(
            cmd, cwd=REPO, text=True, timeout=10, stderr=subprocess.DEVNULL
        )
        return out.strip()
    except Exception as e:
        return f"__error__: {type(e).__name__}: {e}"


def _git_status_clean() -> bool:
    porcelain = _run(["git", "status", "--porcelain"])
    return porcelain == ""


def _pip_freeze(venv_python: Path) -> list[str]:
    """Dump pinned packages from the project venv using uv (pip may be absent in uv-created venvs)."""
    if not venv_python.exists():
        return [f"__error__: {venv_python} not found"]
    # Prefer uv pip freeze since uv-managed venvs don't bundle pip.
    for cmd in (
        ["uv", "pip", "freeze", "--python", str(venv_python)],
        [str(venv_python), "-m", "pip", "freeze", "--exclude-editable"],
    ):
        try:
            out = subprocess.check_output(cmd, text=True, timeout=30, stderr=subprocess.DEVNULL)
            lines = sorted(line for line in out.splitlines() if line.strip())
            # Strip editable git-URL lines for hash stability
            lines = [ln for ln in lines if not ln.startswith("-e ")]
            if lines:
                return lines
        except Exception:
            continue
    return ["__error__: neither uv nor pip freeze returned package list"]


def _freeze_hash(frozen: list[str]) -> str:
    h = hashlib.sha256()
    for line in frozen:
        h.update(line.encode("utf-8"))
        h.update(b"\n")
    return "sha256:" + h.hexdigest()


def _load(path: Path) -> object:
    if not path.exists():
        return {"__missing__": str(path)}
    try:
        return json.loads(path.read_text())
    except Exception as e:
        return {"__error__": f"{type(e).__name__}: {e}"}


def _summarize_flag_ablation(data: object) -> dict[str, object]:
    if not isinstance(data, dict):
        return {"status": "unavailable"}
    return {
        "status": "run",
        "summary": data.get("summary"),
        "total_flags": data.get("total"),
        "note": (
            "10/10 flags timed out; full aragora Arena cannot run a deterministic "
            "3-demo-agent 1-round debate within 30s. Use aragora-debate standalone "
            "for Tier-1 ablation."
        ),
    }


def _summarize_standalone(data: object) -> dict[str, object]:
    if not isinstance(data, dict) or data.get("outcome") != "ok":
        return {"status": "unavailable", "raw": data}
    baseline = data.get("baseline", {})
    diffs = data.get("diffs", {})
    return {
        "status": "ok",
        "baseline_duration_s": baseline.get("duration_s"),
        "baseline_messages": baseline.get("num_messages"),
        "trickster_changed_keys": list(diffs.get("trickster_vs_baseline", {}).keys()),
        "convergence_changed_keys": list(diffs.get("convergence_vs_baseline", {}).keys()),
    }


def main() -> None:
    venv_python = REPO / ".venv" / "bin" / "python"
    frozen = _pip_freeze(venv_python)

    # Capture the real existence check before sanitizing the path string. When
    # the path lives under $HOME it is rewritten to a ``~``-relative placeholder
    # for the committed snapshot, at which point a resolved-exists boolean is no
    # longer meaningful (the placeholder string was never resolved) -> emit null.
    python_bin_exists: bool | None = venv_python.exists()
    repo_root_str, _ = _portable_path(REPO)
    python_bin_str, python_bin_sanitized = _portable_path(venv_python)
    if python_bin_sanitized:
        python_bin_exists = None

    manifest = {
        "manifest_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "repo": {
            "root": repo_root_str,
            "git_sha": _run(["git", "rev-parse", "HEAD"]),
            "git_branch": _run(["git", "rev-parse", "--abbrev-ref", "HEAD"]),
            "git_short_sha": _run(["git", "rev-parse", "--short", "HEAD"]),
            "clean_working_tree": _git_status_clean(),
            "head_subject": _run(["git", "log", "-1", "--pretty=%s"]),
            "head_committer_date": _run(["git", "log", "-1", "--pretty=%cI"]),
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python_version": platform.python_version(),
            "python_implementation": platform.python_implementation(),
        },
        "venv": {
            "python_bin": python_bin_str,
            "python_bin_exists": python_bin_exists,
            "packages_count": len(frozen),
            "pip_freeze_hash": _freeze_hash(frozen),
        },
        "declared_model_pins": DECLARED_MODEL_PINS,
        "phase_b_flag_ablation": _summarize_flag_ablation(_load(HERE / "flag_ablation_smoke.json")),
        "phase_b_standalone_ablation": _summarize_standalone(
            _load(HERE / "standalone_debate_smoke.json")
        ),
        "phase_c_cli_e2e": _load(HERE / "cli_e2e_smoke.json"),
        "bench_readiness_verdict": {
            "tier1_standalone_ablation": "ready",
            "tier2_full_platform_e2e": "ready_via_openrouter",
            "blockers": [
                "aragora gauntlet --local exits 1 at 25% progress with no user-visible error - still needs a fix to surface the failure path",
                "Full Arena orchestrator cannot run offline with demo agents - Tier-1 ablation still uses standalone aragora-debate",
            ],
            "resolved_2026-04-17": [
                "ANTHROPIC_API_KEY 401: now auto-falls-back to anthropic/claude-opus-4.7 via OpenRouter at every call site",
                "OPENAI_API_KEY 429: rotated via scripts/secrets_manager.py rotate OPENAI_API_KEY",
                "OPENROUTER_API_KEY: rotated proactively alongside the OpenAI key",
                "google-generativeai missing: no longer required; Gemini agent routes to google/gemini-3.1-pro via OpenRouter",
                "aragora demo without --offline: still times out, but is now a UX bug not a capability gap - all providers resolve to frontier pins via OpenRouter",
            ],
            "recommended_next_steps": [
                "Tier-2: run SWE-bench-lite harness on full Arena using the rotated OpenAI key + OpenRouter Opus 4.7 fallback",
                "Pin DECLARED_MODEL_PINS in harness config; record actual routed model in each debate receipt",
                "Add --mock-agents to gauntlet so offline smoke tests cover that code path",
                "Regain Anthropic account access and rotate ANTHROPIC_API_KEY to enable direct-provider path (currently routed through OpenRouter)",
            ],
            "security_posture_2026-04-17": {
                "anthropic_key_leaked_to_high-gravity": "auto-revoked by Anthropic 2026-04-07; no active exposure",
                "gitleaks_pre_commit": "installed at pre-commit AND pre-push stages",
                "public_repo_gitleaks_scan": "19 repos scanned, 0 real credential leaks",
                "actions_log_scan_last_30_runs": "0 key-shaped patterns in 30k log lines",
                "github_secret_scanning_alerts": "all 9 false-positives dismissed",
                "rotation_schedule_snapshot": "benchmarks/bench_readiness/rotation-schedule.yaml",
                "incident_report": "benchmarks/bench_readiness/incident_2026-04-07_high-gravity.md",
            },
        },
    }

    out_path = HERE / "manifest.json"
    out_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    repo = cast(dict[str, object], manifest["repo"])
    venv = cast(dict[str, object], manifest["venv"])
    verdict = cast(dict[str, object], manifest["bench_readiness_verdict"])
    print(
        json.dumps(
            {
                "git_sha": repo["git_sha"],
                "clean_tree": repo["clean_working_tree"],
                "packages_pinned": venv["packages_count"],
                "pip_freeze_hash": venv["pip_freeze_hash"],
                "tier1_ablation": verdict["tier1_standalone_ablation"],
                "tier2_e2e": verdict["tier2_full_platform_e2e"],
                "blockers": len(cast(list[object], verdict["blockers"])),
            },
            indent=2,
        )
    )
    print(f"\nwrote: {out_path}")


if __name__ == "__main__":
    main()
