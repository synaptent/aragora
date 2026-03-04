#!/usr/bin/env python3
"""Generate comprehensive essay summaries from each frontier model via OpenRouter.

Sends the Oracle's foundational essay to each frontier model, asking each to
produce a ~40K-token analysis/summary. Each model interprets the essay through
its own training lens, producing a unique intellectual artifact.

Usage:
    python scripts/generate_essay_summaries.py
    python scripts/generate_essay_summaries.py --dry-run
    python scripts/generate_essay_summaries.py --models claude,gpt,grok
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
ESSAY_PATH = REPO_ROOT / "aragora" / "server" / "handlers" / "oracle_essay.md"
OUTPUT_DIR = REPO_ROOT / "aragora" / "server" / "handlers" / "essay_summaries"

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

MODELS: dict[str, str] = {
    "claude": "anthropic/claude-opus-4.6",
    "gpt": "openai/gpt-5.3",
    "grok": "x-ai/grok-4.1-fast",
    "deepseek": "deepseek/deepseek-v3.2",
    "gemini": "google/gemini-3.1-pro-preview",
    "mistral": "mistralai/mistral-large-2512",
}

MAX_TOKENS = 32_000
MAX_RETRIES = 2
INITIAL_BACKOFF_SECONDS = 5.0

SYSTEM_PROMPT = (
    "You are tasked with producing a comprehensive, deeply analytical summary of the\n"
    "following essay. Your summary should be approximately 40,000 tokens \u2014 this is NOT\n"
    "a condensation but an EXPANSION that includes:\n"
    "\n"
    "1. Complete coverage of all 25 sections with key arguments preserved\n"
    "2. Your own analysis and connections between sections\n"
    "3. Steel-manned counterarguments to the essay's claims\n"
    "4. Concrete examples and analogies that illuminate the essay's frameworks\n"
    "5. Connections to your own training knowledge (history, science, philosophy)\n"
    "6. What the essay gets right, what it gets wrong, and what it leaves out\n"
    "7. Practical implications the author may not have considered\n"
    "\n"
    "The result should read as a standalone intellectual artifact \u2014 a model-specific\n"
    "interpretation that captures both the essay AND your unique analytical perspective."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def read_essay() -> str:
    """Read the Oracle's foundational essay from disk.

    Returns:
        The full essay text.

    Raises:
        FileNotFoundError: If the essay file does not exist.
    """
    if not ESSAY_PATH.exists():
        raise FileNotFoundError(f"Essay not found at {ESSAY_PATH}")
    return ESSAY_PATH.read_text(encoding="utf-8")


def build_payload(model_id: str, essay_text: str) -> dict[str, Any]:
    """Build the OpenRouter API request payload.

    Args:
        model_id: The OpenRouter model identifier (e.g. ``anthropic/claude-opus-4.6``).
        essay_text: The full essay to include in the user message.

    Returns:
        A dictionary suitable for JSON serialization as the request body.
    """
    user_content = f"{SYSTEM_PROMPT}\n\n<essay>\n{essay_text}\n</essay>"
    return {
        "model": model_id,
        "max_tokens": MAX_TOKENS,
        "messages": [
            {"role": "user", "content": user_content},
        ],
    }


def call_openrouter(
    api_key: str,
    model_id: str,
    essay_text: str,
) -> str:
    """Send the essay to a single model via the OpenRouter API.

    Implements exponential-backoff retries on transient failures.

    Args:
        api_key: The OpenRouter API key.
        model_id: The OpenRouter model identifier.
        essay_text: The full essay text.

    Returns:
        The model's response text.

    Raises:
        RuntimeError: If all retry attempts are exhausted.
    """
    payload = build_payload(model_id, essay_text)
    data = json.dumps(payload).encode("utf-8")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://aragora.ai",
        "X-Title": "Aragora Essay Summary Generator",
    }

    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        if attempt > 0:
            backoff = INITIAL_BACKOFF_SECONDS * (2 ** (attempt - 1))
            logger.info("  Retry %d/%d after %.1fs backoff...", attempt, MAX_RETRIES, backoff)
            time.sleep(backoff)

        try:
            req = Request(OPENROUTER_URL, data=data, headers=headers, method="POST")
            # 10-minute timeout — these are long-generation requests
            with urlopen(req, timeout=600) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            choices = body.get("choices", [])
            if not choices:
                raise RuntimeError(f"Empty choices in response: {json.dumps(body, indent=2)}")
            return choices[0]["message"]["content"]
        except HTTPError as exc:
            last_error = exc
            status = exc.code
            # Retry on 429 (rate limit) and 5xx (server errors)
            if status == 429 or status >= 500:
                logger.warning("  HTTP %d from OpenRouter: %s", status, exc.reason)
                continue
            # Non-retryable HTTP error
            response_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"OpenRouter returned HTTP {status}: {exc.reason}\n{response_body}"
            ) from exc
        except URLError as exc:
            last_error = exc
            logger.warning("  Network error: %s", exc.reason)
            continue
        except (json.JSONDecodeError, KeyError, IndexError) as exc:
            last_error = exc
            logger.warning("  Malformed response: %s", exc)
            continue

    raise RuntimeError(f"All {MAX_RETRIES + 1} attempts failed for model {model_id}: {last_error}")


def generate_summary(
    model_name: str,
    model_id: str,
    essay_text: str,
    api_key: str,
    dry_run: bool = False,
) -> Path:
    """Generate and save a summary for a single model.

    Args:
        model_name: Short name (e.g. ``claude``, ``gpt``).
        model_id: Full OpenRouter model identifier.
        essay_text: The essay text to summarize.
        api_key: OpenRouter API key.
        dry_run: If True, skip the API call and write nothing.

    Returns:
        The path where the summary was (or would be) saved.
    """
    output_path = OUTPUT_DIR / f"{model_name}_summary.md"

    if dry_run:
        print(f"  [DRY RUN] Would generate {output_path.name}")
        print(f"            Model: {model_id}")
        print(f"            Max tokens: {MAX_TOKENS}")
        print(f"            Output: {output_path}")
        return output_path

    print(f"  Calling {model_id}...")
    start = time.monotonic()
    summary = call_openrouter(api_key, model_id, essay_text)
    elapsed = time.monotonic() - start
    print(f"  Received response ({len(summary):,} chars, {elapsed:.1f}s)")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path.write_text(summary, encoding="utf-8")
    print(f"  Saved to {output_path}")
    return output_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Parsed namespace with ``dry_run`` and ``models`` attributes.
    """
    parser = argparse.ArgumentParser(
        description="Generate frontier-model essay summaries via OpenRouter.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s                          # all models\n"
            "  %(prog)s --dry-run                 # preview without API calls\n"
            "  %(prog)s --models claude,gpt       # specific models only\n"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be generated without making API calls.",
    )
    parser.add_argument(
        "--models",
        type=str,
        default=None,
        help=(
            "Comma-separated list of model names to run. "
            f"Available: {', '.join(sorted(MODELS))}. Default: all."
        ),
    )
    return parser.parse_args(argv)


def resolve_models(models_arg: str | None) -> dict[str, str]:
    """Resolve the ``--models`` argument into a name-to-id mapping.

    Args:
        models_arg: Comma-separated model names, or None for all.

    Returns:
        Dictionary mapping selected model names to their OpenRouter identifiers.

    Raises:
        SystemExit: If an unknown model name is provided.
    """
    if models_arg is None:
        return dict(MODELS)

    selected: dict[str, str] = {}
    for name in models_arg.split(","):
        name = name.strip()
        if name not in MODELS:
            print(f"Error: unknown model '{name}'. Available: {', '.join(sorted(MODELS))}")
            sys.exit(1)
        selected[name] = MODELS[name]
    return selected


def main(argv: list[str] | None = None) -> None:
    """Entry point for the essay summary generator."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    args = parse_args(argv)
    selected = resolve_models(args.models)

    # Validate API key (unless dry run)
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not args.dry_run and not api_key:
        print("Error: OPENROUTER_API_KEY environment variable is not set.")
        sys.exit(1)

    # Read essay
    print(f"Reading essay from {ESSAY_PATH}...")
    essay_text = read_essay()
    print(f"Essay loaded ({len(essay_text):,} chars)")

    # Generate summaries
    total = len(selected)
    print(f"\nGenerating summaries for {total} model(s):\n")

    results: list[tuple[str, Path, bool]] = []
    for i, (model_name, model_id) in enumerate(selected.items(), 1):
        print(f"[{i}/{total}] {model_name}")
        try:
            path = generate_summary(model_name, model_id, essay_text, api_key, args.dry_run)
            results.append((model_name, path, True))
        except RuntimeError as exc:
            logger.error("  Failed: %s", exc)
            results.append((model_name, OUTPUT_DIR / f"{model_name}_summary.md", False))
        print()

    # Summary
    succeeded = sum(1 for _, _, ok in results if ok)
    failed = total - succeeded
    print("=" * 60)
    if args.dry_run:
        print(f"Dry run complete. {total} model(s) would be processed.")
    else:
        print(f"Done. {succeeded} succeeded, {failed} failed.")
        for name, path, ok in results:
            status = "OK" if ok else "FAILED"
            print(f"  [{status}] {name}: {path}")


if __name__ == "__main__":
    main()
