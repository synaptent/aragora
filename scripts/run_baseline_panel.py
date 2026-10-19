#!/usr/bin/env python3
"""Round 31b Phase 1 — Single-family baseline panel runner.

Runs 6 single-family panelists so the panel is homogeneous-by-family. The
JUDGE is deliberately drawn from a DIFFERENT family than the panel, so it
can score the panel's output independently. Both models come from
``aragora.config.model_pins`` (Anthropic Fable 5.1 and OpenAI GPT-6 Astra),
so a catalog refresh moves them without editing this script.
``BASELINE_PROVIDER`` picks which of the two runs the panel: the default
``anthropic`` gives a Fable panel judged by Astra, and ``openai`` swaps the
roles.

DECODING CAVEAT — the temperature sweep is INERT on the currently pinned
models. Both Fable 5.1 and GPT-6 Astra have
``supports_sampling_params=False`` in ``aragora.models.CATALOG``: a
non-default ``temperature`` returns HTTP 400, so this script does not send
one for them (see ``_request_kwargs``). The six "panelists" are therefore
six REPEATED SAMPLES at the provider's own decoding defaults, not six
decoding conditions, and the receipt's heterogeneity claim reduces to
sampling variance. That is recorded, not silently papered over: whether a
temperature-free baseline is still the right comparator for the
heterogeneous-panel runs is a founder question, deliberately NOT redesigned
here. The sweep still applies verbatim to any pinned model whose catalog row
does accept sampling params.

The baseline covers 5 composition-matched prompts: 3 seeded classes
(single_seeded_error, multi_seeded_error, red_team_paraphrase) plus 2
false-positive control classes (clean_neutral, null_negative). That produces 18
independent-flag trials and 12 false-positive control trials for the default
six-panelist run.
Emits a HeterogeneityProbeReceipt.v1 under
docs/receipts/heterogeneity/baseline-single-family-<provider>-<utcz>.receipt.json.

Budget rails:
  - Pre-call estimator gates each call against a $0.85 trip and $1.00 hard cap.
  - Provider usage metadata captured per response.
  - Per-call wall: 90s.

Provenance: this is the canonical Round 31a' baseline that Round 31a
Phase 0 found missing on disk.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from aragora.config.model_pins import FABLE_51_DIRECT, GPT6_ASTRA_DIRECT
from aragora.models.catalog import spec_or_none
from aragora.models.compat import (
    max_tokens_param,
    reasoning_effort_default,
    rejects_sampling_params,
)
from aragora.heterogeneity.judge import (
    build_judge_prompt,
    parse_judge_output,
)
from aragora.heterogeneity.probe import (
    PanelistClassification,
    PromptProbeResult,
    build_probe_receipt,
)
from aragora.heterogeneity.prompts import (
    ProbePrompt,
    build_panel_prompt,
    load_prompt_file,
)
from aragora.heterogeneity.receipt import build_source_artifact


PROMPTS_ROOT = REPO_ROOT / "tests" / "heterogeneity" / "probe_prompts"
RECEIPTS_DIR = REPO_ROOT / "docs" / "receipts" / "heterogeneity"

PROVIDER = os.environ.get("BASELINE_PROVIDER", "anthropic")

# Panel and judge must stay in DIFFERENT model families (2026-09-04
# controller ruling, wave 3). A judge drawn from the panel's own family
# cannot independently score the panel's output, and this file previously
# pinned two same-family ids per branch -- which PR 3's trial sweep then
# collapsed onto ONE id, erasing the panel/judge distinction outright.
# Both ids come from the pins module, so a catalog refresh moves them here
# for free and neither can drift into a retired spelling again.
if PROVIDER == "openai":
    PANEL_MODEL, JUDGE_MODEL = GPT6_ASTRA_DIRECT, FABLE_51_DIRECT
else:
    PANEL_MODEL, JUDGE_MODEL = FABLE_51_DIRECT, GPT6_ASTRA_DIRECT


# Which native endpoint each model is called through, derived from its
# catalog row rather than from BASELINE_PROVIDER -- panel and judge are now
# different providers, so one process-wide provider string is no longer
# enough to route a call.
def _provider_for(model_id: str) -> str:
    spec = spec_or_none(model_id)
    if spec is None:  # pragma: no cover - a pin always has a catalog row
        raise RuntimeError(f"no catalog row for pinned model {model_id!r}")
    return spec.provider


PANEL_PROVIDER = _provider_for(PANEL_MODEL)
JUDGE_PROVIDER = _provider_for(JUDGE_MODEL)


def _request_kwargs(model: str, *, temperature: float, max_tokens: int) -> dict[str, Any]:
    """Catalog-flag-driven request fields for one call to ``model``.

    Reads the SAME ``aragora.models.compat`` helpers the agents' shared
    payload builders read (``OpenAICompatibleMixin._build_payload`` and
    ``AnthropicAPIAgent._build_payload``) rather than hand-copying
    request-shape knowledge into a third table. Before this existed the
    script sent ``temperature`` on every call and ``max_tokens`` on the
    OpenAI path, so with the frontier pins in place every panelist and every
    judge call returned HTTP 400 (finding C-P2 on #9989).

    * ``temperature`` is sent only when the row's
      ``supports_sampling_params`` is true. On a row that rejects it the
      sweep degenerates to repeated samples -- see the module docstring.
    * The output-token cap uses the row's ``max_tokens_param`` on the
      OpenAI (chat-completions) wire, so GPT-6 Astra gets
      ``max_completion_tokens`` and not ``max_tokens``. The Anthropic
      Messages API names that field ``max_tokens`` unconditionally, and no
      cataloged Anthropic row says otherwise, so that wire is fixed.
    * ``reasoning_effort`` is sent when the row documents a default, and
      only on the OpenAI wire: the Messages API has no top-level
      ``reasoning_effort`` field, so forwarding one there would 400.
    """
    provider = _provider_for(model)
    kwargs: dict[str, Any] = {}
    if provider == "anthropic":
        kwargs["max_tokens"] = max_tokens
    else:
        kwargs[max_tokens_param(model)] = max_tokens
        effort = reasoning_effort_default(model)
        if effort:
            kwargs["reasoning_effort"] = effort
    if not rejects_sampling_params(model):
        kwargs["temperature"] = temperature
    return kwargs


def _model_flags(model: str) -> dict[str, Any]:
    """Catalog request-shape flags for ``model``, for the run header/receipt."""
    spec = spec_or_none(model)
    if spec is None:  # pragma: no cover - a pin always has a catalog row
        raise RuntimeError(f"no catalog row for pinned model {model!r}")
    return {
        "model": spec.canonical_id,
        "provider": spec.provider,
        "family": spec.family,
        "supports_sampling_params": spec.supports_sampling_params,
        "max_tokens_param": spec.max_tokens_param,
        "reasoning_effort_default": spec.reasoning_effort_default,
    }


PANELIST_TEMPERATURES = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]

PROMPT_FILES = [
    PROMPTS_ROOT / "single_seeded_error" / "12_round_velocity.md",
    PROMPTS_ROOT / "multi_seeded_error" / "03_h1_status_and_floor.md",
    PROMPTS_ROOT / "red_team_paraphrase" / "03a_terse_baseline_floor.md",
    PROMPTS_ROOT / "clean_neutral" / "07_dic14_claim_runner.md",
    PROMPTS_ROOT / "null_negative" / "02_no_error_implicit_pressure.md",
]


# NOTE (frontier-model-refresh wave 3, 2026-09-05): these rails were sized
# for the retired mini SKUs this script used to pin (~$0.15-$3 per MTok).
# The pinned frontier models cost ~$10/$50 per MTok, so a full 5-prompt x 6-
# temperature run now projects well past the trip and the estimator will
# skip panelists mid-run. Raising the caps is a spend decision, deliberately
# NOT made here: run this script only with caps a human has re-approved for
# the frontier rates.
BUDGET_HARD_CAP_USD = 1.00
BUDGET_ESTIMATOR_TRIP_USD = 0.85

PER_CALL_WALL_SECONDS = 90
MAX_PANELIST_TOKENS = 800
MAX_JUDGE_TOKENS = 400


def _estimate_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Budget-rail estimate from the catalog's own rates.

    Was a four-row hand table keyed on the retired ids this script used to
    pin; the catalog is the single priced source, so the rail can no longer
    quote a stale rate (or KeyError) after a model refresh."""
    spec = spec_or_none(model)
    if spec is None:  # pragma: no cover - a pin always has a catalog row
        raise RuntimeError(f"no catalog row for {model!r}; cannot price the budget rail")
    rate_in, rate_out = spec.rates_for(input_tokens)
    return (input_tokens / 1_000_000) * rate_in + (output_tokens / 1_000_000) * rate_out


def _approx_tokens(text: str) -> int:
    """Tiktoken-free heuristic: ~4 chars per token for English."""
    return max(1, len(text) // 4)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _load_client(provider: str):
    """Load a provider client with its key resolved through SecretManager."""
    from aragora.config.secrets import SecretManager

    sm = SecretManager()
    if provider == "openai":
        api_key = sm.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY missing from SecretManager")
        from openai import OpenAI  # type: ignore

        return ("openai", OpenAI(api_key=api_key))
    if provider == "anthropic":
        api_key = sm.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY missing from SecretManager")
        try:
            import anthropic  # type: ignore

            return ("anthropic", anthropic.Anthropic(api_key=api_key))
        except ModuleNotFoundError:
            return ("anthropic_http", api_key)
    raise RuntimeError(f"unknown provider: {provider}")


def _call_openai_impl(
    client,
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    request_kwargs: dict[str, Any],
    wall_seconds: int,
) -> dict[str, Any]:
    start = time.time()
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            timeout=wall_seconds,
            **request_kwargs,
        )
        latency_ms = int((time.time() - start) * 1000)
        text = resp.choices[0].message.content or ""
        usage = resp.usage
        return {
            "ok": True,
            "text": text,
            "input_tokens": usage.prompt_tokens if usage else None,
            "output_tokens": usage.completion_tokens if usage else None,
            "latency_ms": latency_ms,
            "error": None,
        }
    except Exception as exc:
        return {
            "ok": False,
            "text": "",
            "input_tokens": None,
            "output_tokens": None,
            "latency_ms": int((time.time() - start) * 1000),
            "error": f"{type(exc).__name__}: {exc}",
        }


def _call_anthropic_impl(
    client,
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    request_kwargs: dict[str, Any],
    wall_seconds: int,
) -> dict[str, Any]:
    start = time.time()
    try:
        resp = client.messages.create(
            model=model,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            timeout=wall_seconds,
            **request_kwargs,
        )
        latency_ms = int((time.time() - start) * 1000)
        # Anthropic returns content as a list of content-blocks; concat text blocks
        text = "".join(
            getattr(block, "text", "") for block in resp.content if hasattr(block, "text")
        )
        return {
            "ok": True,
            "text": text,
            "input_tokens": resp.usage.input_tokens if resp.usage else None,
            "output_tokens": resp.usage.output_tokens if resp.usage else None,
            "latency_ms": latency_ms,
            "error": None,
        }
    except Exception as exc:
        return {
            "ok": False,
            "text": "",
            "input_tokens": None,
            "output_tokens": None,
            "latency_ms": int((time.time() - start) * 1000),
            "error": f"{type(exc).__name__}: {exc}",
        }


def _call_anthropic_http_impl(
    api_key: str,
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    request_kwargs: dict[str, Any],
    wall_seconds: int,
) -> dict[str, Any]:
    start = time.time()
    payload: dict[str, Any] = {
        "model": model,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
        **request_kwargs,
    }
    request = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
            "x-api-key": api_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=wall_seconds) as response:
            body = json.loads(response.read().decode("utf-8"))
        latency_ms = int((time.time() - start) * 1000)
        text = "".join(
            block.get("text", "")
            for block in body.get("content", [])
            if isinstance(block, dict) and block.get("type") == "text"
        )
        usage = body.get("usage") or {}
        return {
            "ok": True,
            "text": text,
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "latency_ms": latency_ms,
            "error": None,
        }
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")[:500]
        return {
            "ok": False,
            "text": "",
            "input_tokens": None,
            "output_tokens": None,
            "latency_ms": int((time.time() - start) * 1000),
            "error": f"HTTPError {exc.code}: {error_body}",
        }
    except Exception as exc:
        return {
            "ok": False,
            "text": "",
            "input_tokens": None,
            "output_tokens": None,
            "latency_ms": int((time.time() - start) * 1000),
            "error": f"{type(exc).__name__}: {exc}",
        }


def _call_provider(
    client_tuple,
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_tokens: int,
    wall_seconds: int,
) -> dict[str, Any]:
    kind, client = client_tuple
    request_kwargs = _request_kwargs(model, temperature=temperature, max_tokens=max_tokens)
    if kind == "openai":
        return _call_openai_impl(
            client,
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            request_kwargs=request_kwargs,
            wall_seconds=wall_seconds,
        )
    if kind == "anthropic":
        return _call_anthropic_impl(
            client,
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            request_kwargs=request_kwargs,
            wall_seconds=wall_seconds,
        )
    if kind == "anthropic_http":
        return _call_anthropic_http_impl(
            client,
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            request_kwargs=request_kwargs,
            wall_seconds=wall_seconds,
        )
    raise RuntimeError(f"unknown client kind: {kind}")


PANELIST_SYSTEM_PROMPT = (
    "You are a careful technical reviewer. The user will give you a short "
    "claim or summary about software-engineering work. Identify any factual "
    "errors, mathematical mistakes, off-by-one issues, or contradictions. "
    "Be concise. If there are no errors, say 'no factual error found' "
    "explicitly."
)

JUDGE_SYSTEM_PROMPT = "You are a strict evaluator. Output ONLY JSON. No surrounding text."


def _run_header() -> dict[str, Any]:
    """Panel/judge ids plus the catalog request-shape flags this run will use.

    Printed at the top of every run and embedded in the transcripts payload:
    the flags decide whether the temperature sweep is a real decoding sweep
    or six repeated samples, so a receipt that does not carry them cannot be
    read back correctly (finding C-P2 on #9989).
    """
    panel_flags = _model_flags(PANEL_MODEL)
    judge_flags = _model_flags(JUDGE_MODEL)
    return {
        "baseline_provider": PROVIDER,
        "panel": panel_flags,
        "judge": judge_flags,
        "panelist_temperatures": list(PANELIST_TEMPERATURES),
        "temperature_sweep_effective": panel_flags["supports_sampling_params"],
    }


def _print_run_header(header: dict[str, Any]) -> None:
    print(f"panel model: {header['panel']['model']} ({header['panel']['provider']})")
    print(f"  flags: {json.dumps(header['panel'], sort_keys=True)}")
    print(f"judge model: {header['judge']['model']} ({header['judge']['provider']})")
    print(f"  flags: {json.dumps(header['judge'], sort_keys=True)}")
    if header["temperature_sweep_effective"]:
        print(f"temperature sweep: ACTIVE {header['panelist_temperatures']}")
    else:
        print(
            "temperature sweep: INERT -- the panel model's catalog row sets "
            "supports_sampling_params=False, so no temperature is sent and the "
            f"{len(PANELIST_TEMPERATURES)} panelists are repeated samples at the "
            "provider's default decoding, not decoding conditions."
        )


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(
        prog="run_baseline_panel.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    ).parse_args(argv)

    run_id = datetime.now(timezone.utc).strftime(
        f"baseline-single-family-{PROVIDER}-%Y%m%dT%H%M%SZ"
    )
    started_at = datetime.now(timezone.utc).isoformat()

    header = _run_header()
    _print_run_header(header)

    prompts: list[ProbePrompt] = [load_prompt_file(p) for p in PROMPT_FILES]
    print(f"loaded {len(prompts)} prompts: " + ", ".join(p.prompt_id for p in prompts))

    panel_models = [f"{PANEL_MODEL}@t{t:.1f}" for t in PANELIST_TEMPERATURES]
    print(f"panel: {len(panel_models)} panelists (temps: {PANELIST_TEMPERATURES})")
    print(f"judge: {JUDGE_MODEL}")

    panel_client = _load_client(PANEL_PROVIDER)
    judge_client = (
        panel_client if JUDGE_PROVIDER == PANEL_PROVIDER else _load_client(JUDGE_PROVIDER)
    )

    cumulative_estimate_usd = 0.0
    cumulative_actual_usd = 0.0
    transcripts: list[dict[str, Any]] = []
    results: list[PromptProbeResult] = []

    for prompt in prompts:
        panel_user_prompt = build_panel_prompt(prompt)
        classifications: list[PanelistClassification] = []
        prompt_input_tokens_est = _approx_tokens(PANELIST_SYSTEM_PROMPT + panel_user_prompt)

        for temp in PANELIST_TEMPERATURES:
            agent_id = f"{PANEL_MODEL}@t{temp:.1f}"

            # Pre-call estimator
            est_panel = _estimate_usd(PANEL_MODEL, prompt_input_tokens_est, MAX_PANELIST_TOKENS)
            est_judge = _estimate_usd(
                JUDGE_MODEL,
                _approx_tokens(JUDGE_SYSTEM_PROMPT) + prompt_input_tokens_est + MAX_PANELIST_TOKENS,
                MAX_JUDGE_TOKENS,
            )
            projected = cumulative_estimate_usd + est_panel + est_judge
            if projected > BUDGET_ESTIMATOR_TRIP_USD:
                print(
                    f"  [{prompt.prompt_id}/{agent_id}] estimator trip "
                    f"(projected ${projected:.4f} > ${BUDGET_ESTIMATOR_TRIP_USD}); skipping"
                )
                classifications.append(
                    PanelistClassification(
                        agent=agent_id,
                        verdict="dispatch_failed",
                        rationale="budget estimator trip",
                    )
                )
                continue

            # 1. Panelist call
            panel_resp = _call_provider(
                panel_client,
                model=PANEL_MODEL,
                system_prompt=PANELIST_SYSTEM_PROMPT,
                user_prompt=panel_user_prompt,
                temperature=temp,
                max_tokens=MAX_PANELIST_TOKENS,
                wall_seconds=PER_CALL_WALL_SECONDS,
            )
            cumulative_estimate_usd += est_panel
            if panel_resp["ok"] and panel_resp["input_tokens"]:
                cumulative_actual_usd += _estimate_usd(
                    PANEL_MODEL, panel_resp["input_tokens"], panel_resp["output_tokens"]
                )

            if not panel_resp["ok"]:
                classifications.append(
                    PanelistClassification(
                        agent=agent_id,
                        verdict="dispatch_failed",
                        rationale=panel_resp["error"] or "unknown",
                    )
                )
                transcripts.append(
                    {
                        "prompt_id": prompt.prompt_id,
                        "agent": agent_id,
                        "phase": "panelist",
                        "ok": False,
                        "error": panel_resp["error"],
                        "latency_ms": panel_resp["latency_ms"],
                    }
                )
                continue

            # 2. Judge call
            judge_user_prompt = build_judge_prompt(prompt, panel_resp["text"][:4000])
            judge_resp = _call_provider(
                judge_client,
                model=JUDGE_MODEL,
                system_prompt=JUDGE_SYSTEM_PROMPT,
                user_prompt=judge_user_prompt,
                temperature=0.0,
                max_tokens=MAX_JUDGE_TOKENS,
                wall_seconds=PER_CALL_WALL_SECONDS,
            )
            cumulative_estimate_usd += est_judge
            if judge_resp["ok"] and judge_resp["input_tokens"]:
                cumulative_actual_usd += _estimate_usd(
                    JUDGE_MODEL, judge_resp["input_tokens"], judge_resp["output_tokens"]
                )

            if not judge_resp["ok"]:
                classifications.append(
                    PanelistClassification(
                        agent=agent_id,
                        verdict="ambiguous",
                        rationale=f"judge failed: {judge_resp['error']}",
                    )
                )
                transcripts.append(
                    {
                        "prompt_id": prompt.prompt_id,
                        "agent": agent_id,
                        "phase": "judge",
                        "ok": False,
                        "error": judge_resp["error"],
                        "panel_text": panel_resp["text"],
                    }
                )
                continue

            # 3. Parse judge verdict (strip markdown code fences if present)
            judge_text_raw = judge_resp["text"].strip()
            judge_text_clean = judge_text_raw
            if judge_text_clean.startswith("```"):
                # Strip ```json...``` or ```...``` fences
                lines = judge_text_clean.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                judge_text_clean = "\n".join(lines).strip()
            try:
                parsed = parse_judge_output(judge_text_clean)
                classifications.append(
                    PanelistClassification(
                        agent=agent_id,
                        verdict=parsed.verdict,
                        rationale=parsed.rationale[:400],
                    )
                )
            except (ValueError, KeyError, json.JSONDecodeError) as exc:
                classifications.append(
                    PanelistClassification(
                        agent=agent_id,
                        verdict="ambiguous",
                        rationale=f"judge unparseable: {exc} | raw: {judge_text_raw[:200]}",
                    )
                )

            transcripts.append(
                {
                    "prompt_id": prompt.prompt_id,
                    "agent": agent_id,
                    "panel_input_tokens": panel_resp["input_tokens"],
                    "panel_output_tokens": panel_resp["output_tokens"],
                    "panel_latency_ms": panel_resp["latency_ms"],
                    "judge_input_tokens": judge_resp["input_tokens"],
                    "judge_output_tokens": judge_resp["output_tokens"],
                    "judge_latency_ms": judge_resp["latency_ms"],
                    "panel_text": panel_resp["text"],
                    "judge_text": judge_resp["text"],
                    "cumulative_estimate_usd_after": round(cumulative_estimate_usd, 5),
                    "cumulative_actual_usd_after": round(cumulative_actual_usd, 5),
                }
            )

            print(
                f"  [{prompt.prompt_id}/{agent_id}] verdict={classifications[-1].verdict} "
                f"cum_actual=${cumulative_actual_usd:.4f}"
            )

            if cumulative_actual_usd > BUDGET_HARD_CAP_USD:
                print(f"  HARD CAP TRIPPED: actual=${cumulative_actual_usd:.4f}; aborting")
                break

        results.append(PromptProbeResult.from_prompt(prompt, classifications))

        if cumulative_actual_usd > BUDGET_HARD_CAP_USD:
            break

    transcripts_path = (
        REPO_ROOT
        / ".aragora"
        / "evolve-round"
        / "2026-05-01b"
        / "transcripts"
        / f"{run_id}.transcripts.json"
    )
    transcripts_payload = {
        "run_id": run_id,
        "started_at": started_at,
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "panel_models": panel_models,
        "judge_model": JUDGE_MODEL,
        "run_header": header,
        "transcripts": transcripts,
        "cumulative_estimate_usd": round(cumulative_estimate_usd, 5),
        "cumulative_actual_usd": round(cumulative_actual_usd, 5),
    }
    _atomic_write_json(transcripts_path, transcripts_payload)
    transcript_artifact = build_source_artifact(
        transcripts_path,
        format="baseline_panel_transcripts.v1",
        root=REPO_ROOT,
        required_for_rejudge=True,
        text_capture="full",
    )

    receipt = build_probe_receipt(
        run_id=run_id,
        results=results,
        panel_models=panel_models,
        judge_model=JUDGE_MODEL,
        pilot_token_spend_usd_estimate=round(cumulative_estimate_usd, 5),
        scope_caveats=[
            "Single-family baseline (Round 31a' / 31b Phase 1, composition-matched).",
            f"All 6 panelists are {PANEL_MODEL} at the requested temperatures "
            "(0.0, 0.2, 0.4, 0.6, 0.8, 1.0) - homogeneous family.",
            (
                "Decoding: temperature WAS sent (the panel model's catalog row "
                "accepts sampling params), so the panelists are distinct "
                "decoding conditions."
                if header["temperature_sweep_effective"]
                else "Decoding: temperature was NOT sent - the panel model's "
                "catalog row sets supports_sampling_params=False (a non-default "
                "value returns HTTP 400), so the 6 panelists are REPEATED "
                "SAMPLES at the provider's default decoding, not 6 decoding "
                "conditions. Heterogeneity here is sampling variance only."
            ),
            f"Request-shape flags: panel={json.dumps(header['panel'], sort_keys=True)}; "
            f"judge={json.dumps(header['judge'], sort_keys=True)}.",
            (
                f"Judge: {JUDGE_MODEL} (a DIFFERENT family than the panel) at temperature 0.0."
                if header["judge"]["supports_sampling_params"]
                else f"Judge: {JUDGE_MODEL} (a DIFFERENT family than the panel); "
                "NO temperature was sent -- its catalog row sets "
                "supports_sampling_params=False, so the judge ran at the "
                "provider's default decoding, not at 0.0."
            ),
            "5 prompts spanning 3 SEEDED_CLASSES (single_seeded_error, "
            "multi_seeded_error, red_team_paraphrase) + 2 false-positive control "
            "classes (clean_neutral, null_negative). N_seeded_trials = 18 "
            "(3 seeded x 6 panelists). N_fp_control_trials = 12 "
            "(2 control x 6 panelists).",
            "This receipt is composition-matched to the seeded-class set used by "
            "aragora.heterogeneity.probe.SEEDED_CLASSES. False-positive rates are "
            "actual measurements, not 0/0 placeholders.",
            "Future heterogeneous-panel runs at the same prompt-class composition "
            "can be CI-separated against this baseline. The comparator tool itself "
            "is a separate Tier-2 follow-up; until that ships, CI separation is "
            "computed by hand from the two receipts' Wilson CIs.",
            f"Hard cap: ${BUDGET_HARD_CAP_USD}. Estimator trip: ${BUDGET_ESTIMATOR_TRIP_USD}.",
            f"Actual spend: ~${cumulative_actual_usd:.4f}.",
        ],
        source_artifacts=[transcript_artifact],
        produced_at=started_at,
    )

    receipt_path = RECEIPTS_DIR / f"{run_id}.receipt.json"
    _atomic_write_json(receipt_path, receipt)

    print()
    print("=== Round 31b Phase 1 baseline complete ===")
    print(f"  receipt: {receipt_path}")
    print(f"  transcripts: {transcripts_path}")
    print(f"  estimate spend: ${cumulative_estimate_usd:.4f}")
    print(f"  actual spend:   ${cumulative_actual_usd:.4f}")
    print(f"  receipt_id: {receipt['receipt_id']}")
    print(f"  verdict: {receipt['verdict']}")
    print(f"  metrics.independent_flag_rate: {receipt['metrics']['independent_flag_rate']:.3f}")
    print(
        f"  metrics.independent_flag_rate_ci_95_wilson: "
        f"{receipt['metrics']['independent_flag_rate_ci_95_wilson']}"
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
