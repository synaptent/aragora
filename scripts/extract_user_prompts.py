#!/usr/bin/env python3
"""Extract substantive user prompts from Claude Code session transcripts.

Filters out:
- Very short messages (< 20 chars)
- Repetitive low-content messages ("proceed", "yes", "continue", etc.)
- System/hook messages
- Messages that are mostly quoted assistant output

Preserves:
- Feature requests and vision descriptions
- Technical questions and decisions
- Bug reports and issue descriptions
- Architecture and design discussions
- Any message with substantive intent
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Low-content patterns to filter
LOW_CONTENT_PATTERNS = [
    r"^(yes|no|ok|okay|sure|thanks|thank you|ty|thx|cool|great|nice|good|perfect|awesome|lgtm)\.?!?$",
    r"^(proceed|continue|go ahead|do it|let's go|go|next|yes to all)\.?!?$",
    r"^(yes to all in best order|yes all|all of them|all)\.?!?$",
    r"^(what is current status|what are best next steps|status|what's the status)\.?\??$",
    r"^(now continue|keep going|carry on|move on)\.?!?$",
    r"^(fix it|do that|sounds good|agreed|makes sense|right)\.?!?$",
    r"^/\w+",  # Slash commands like /compact, /help
    r"^compact$",
]

LOW_CONTENT_RE = [re.compile(p, re.IGNORECASE) for p in LOW_CONTENT_PATTERNS]


def is_low_content(text: str) -> bool:
    """Check if a message is low-content/repetitive."""
    clean = text.strip()
    # Very short
    if len(clean) < 20:
        return True
    # Match known patterns
    for pat in LOW_CONTENT_RE:
        if pat.match(clean):
            return True
    # Mostly whitespace or punctuation
    alpha_ratio = sum(1 for c in clean if c.isalpha()) / max(len(clean), 1)
    if alpha_ratio < 0.3:
        return True
    return False


def is_mostly_quoted(text: str) -> bool:
    """Check if message is mostly quoting assistant/system output."""
    lines = text.strip().split("\n")
    if not lines:
        return True
    # If >70% of lines start with common quote indicators
    quoted = sum(1 for line in lines if line.strip().startswith((">", "```", "---", "===", "|")))
    return quoted / len(lines) > 0.7


def extract_user_text(message: dict) -> str | None:
    """Extract plain text from a user message object."""
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        # Multi-part message
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(part.get("text", ""))
            elif isinstance(part, str):
                parts.append(part)
        return "\n".join(parts)
    return None


def clean_text(text: str) -> str:
    """Remove system reminders, hook outputs, and other noise."""
    # Remove system-reminder tags and content
    text = re.sub(r"<system-reminder>.*?</system-reminder>", "", text, flags=re.DOTALL)
    # Remove command tags
    text = re.sub(r"<command-\w+>.*?</command-\w+>", "", text, flags=re.DOTALL)
    text = re.sub(r"<local-command-\w+>.*?</local-command-\w+>", "", text, flags=re.DOTALL)
    # Remove task notifications
    text = re.sub(r"<task-notification>.*?</task-notification>", "", text, flags=re.DOTALL)
    # Clean up whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_prompts(
    sessions_dir: str,
    days_back: int = 14,
    min_length: int = 30,
    max_per_session: int = 50,
) -> list[dict]:
    """Extract substantive user prompts from recent sessions."""
    cutoff = datetime.now() - timedelta(days=days_back)
    sessions_path = Path(sessions_dir)

    all_prompts = []

    for jsonl_file in sorted(sessions_path.glob("*.jsonl")):
        # Check modification time
        mtime = datetime.fromtimestamp(jsonl_file.stat().st_mtime)
        if mtime < cutoff:
            continue

        session_id = jsonl_file.stem
        session_prompts = []

        with open(jsonl_file, "r") as f:
            for line_num, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Only user messages
                if obj.get("type") != "user":
                    continue

                msg = obj.get("message", {})
                if not msg:
                    continue

                text = extract_user_text(msg)
                if not text:
                    continue

                # Clean and filter
                text = clean_text(text)
                if not text or len(text) < min_length:
                    continue
                if is_low_content(text):
                    continue
                if is_mostly_quoted(text):
                    continue

                timestamp = obj.get("timestamp", "")

                session_prompts.append(
                    {
                        "session_id": session_id[:8],
                        "timestamp": timestamp,
                        "date": timestamp[:10] if timestamp else mtime.strftime("%Y-%m-%d"),
                        "length": len(text),
                        "text": text,
                    }
                )

                if len(session_prompts) >= max_per_session:
                    break

        all_prompts.extend(session_prompts)

    # Sort by timestamp
    all_prompts.sort(key=lambda x: x.get("timestamp", ""))
    return all_prompts


def deduplicate(prompts: list[dict], similarity_threshold: float = 0.8) -> list[dict]:
    """Remove near-duplicate prompts (same text repeated across sessions)."""
    seen_texts: list[str] = []
    unique = []

    for p in prompts:
        text = p["text"][:200].lower()  # Compare first 200 chars
        is_dup = False
        for seen in seen_texts:
            # Simple Jaccard on words
            words_a = set(text.split())
            words_b = set(seen.split())
            if not words_a or not words_b:
                continue
            jaccard = len(words_a & words_b) / len(words_a | words_b)
            if jaccard > similarity_threshold:
                is_dup = True
                break
        if not is_dup:
            seen_texts.append(text)
            unique.append(p)

    return unique


def summarize_prompt(text: str, max_len: int = 300) -> str:
    """Truncate long prompts while preserving the substantive beginning."""
    if len(text) <= max_len:
        return text
    # Try to cut at sentence boundary
    cut = text[:max_len]
    last_period = cut.rfind(".")
    last_newline = cut.rfind("\n")
    cut_at = max(last_period, last_newline)
    if cut_at > max_len // 2:
        return text[: cut_at + 1] + " [...]"
    return text[:max_len] + " [...]"


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Extract substantive user prompts from Claude Code sessions"
    )
    parser.add_argument("--days", type=int, default=14, help="Days back to search (default: 14)")
    parser.add_argument(
        "--min-length", type=int, default=30, help="Minimum prompt length (default: 30)"
    )
    parser.add_argument(
        "--max-summary", type=int, default=300, help="Max summary length (default: 300)"
    )
    parser.add_argument("--no-dedup", action="store_true", help="Skip deduplication")
    parser.add_argument("--full", action="store_true", help="Show full text instead of summaries")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--stats", action="store_true", help="Show statistics only")

    args = parser.parse_args()

    sessions_dir = os.path.expanduser("~/.claude/projects/-Users-armand-Development-aragora")

    prompts = extract_prompts(sessions_dir, days_back=args.days, min_length=args.min_length)

    if not args.no_dedup:
        before = len(prompts)
        prompts = deduplicate(prompts)
        deduped = before - len(prompts)
    else:
        deduped = 0

    if args.stats:
        dates = {}
        for p in prompts:
            d = p["date"]
            dates[d] = dates.get(d, 0) + 1

        print(f"Total substantive prompts: {len(prompts)}")
        print(f"Deduplicated: {deduped}")
        print(
            f"Date range: {prompts[0]['date'] if prompts else 'N/A'} to {prompts[-1]['date'] if prompts else 'N/A'}"
        )
        print(f"Avg length: {sum(p['length'] for p in prompts) // max(len(prompts), 1)} chars")
        print("\nPrompts per day:")
        for d in sorted(dates):
            print(f"  {d}: {dates[d]}")
        return

    if args.json:
        output = []
        for p in prompts:
            output.append(
                {
                    "session": p["session_id"],
                    "date": p["date"],
                    "length": p["length"],
                    "text": p["text"]
                    if args.full
                    else summarize_prompt(p["text"], args.max_summary),
                }
            )
        json.dump(output, sys.stdout, indent=2)
        print()
        return

    # Default: human-readable output
    print(f"# Substantive User Prompts ({len(prompts)} found, {deduped} duplicates removed)")
    print(f"# Period: last {args.days} days")
    print()

    current_date = None
    for i, p in enumerate(prompts, 1):
        if p["date"] != current_date:
            current_date = p["date"]
            print(f"\n## {current_date}")
            print()

        text = p["text"] if args.full else summarize_prompt(p["text"], args.max_summary)
        print(f"### [{p['session_id']}] ({p['length']} chars)")
        print(text)
        print()


if __name__ == "__main__":
    main()
