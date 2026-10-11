#!/usr/bin/env python3
"""Extract and LLM-rank user intent prompts from Claude Code sessions.

Phase 1: Heuristic pre-filter (fast, gets ~4k down to ~200-500)
Phase 2: LLM scoring via subagent batches (accurate ranking)
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path


def clean_text(text: str) -> str:
    """Remove system tags and noise."""
    text = re.sub(r"<system-reminder>.*?</system-reminder>", "", text, flags=re.DOTALL)
    text = re.sub(r"<command-\w+>.*?</command-\w+>", "", text, flags=re.DOTALL)
    text = re.sub(r"<local-command-\w+>.*?</local-command-\w+>", "", text, flags=re.DOTALL)
    text = re.sub(r"<task-notification>.*?</task-notification>", "", text, flags=re.DOTALL)
    text = re.sub(r"<claude-mem-context>.*?</claude-mem-context>", "", text, flags=re.DOTALL)
    text = re.sub(r"<teammate-message.*?</teammate-message>", "", text, flags=re.DOTALL)
    text = re.sub(r"<.*?>.*?</.*?>", "", text, flags=re.DOTALL)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_user_text(message: dict) -> str | None:
    """Extract plain text from a user message object."""
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(part.get("text", ""))
            elif isinstance(part, str):
                parts.append(part)
        return "\n".join(parts)
    return None


def is_system_generated(text: str) -> bool:
    """Detect system-generated content (session continuations, compaction, etc.)."""
    markers = [
        "This session is being continued from a previous conversation",
        "Conversation compacted",
        "✻ Conversation compacted",
        "Called the Read tool with the following input",
        "Result of calling the Read tool",
        "SessionStart:compact hook",
        "SessionStart hook additional context",
        "UserPromptSubmit hook success",
    ]
    for m in markers:
        if m in text[:500]:
            return True
    return False


def is_low_content(text: str) -> bool:
    """Filter low-content messages."""
    clean = text.strip()
    if len(clean) < 40:
        return True

    patterns = [
        r"^(yes|no|ok|okay|sure|thanks|proceed|continue|go ahead|do it)[\.\!\s]*$",
        r"^(yes to all|yes to all in best order|all of them|sounds good)[\.\!\s]*$",
        r"^(what is (current )?status|what are (best )?next steps)[\.\?\s]*$",
        r"^(now continue|keep going|carry on|move on|next)[\.\!\s]*$",
        r"^/\w+",
        r"^compact$",
        r"^❯\s*$",
    ]
    for pat in patterns:
        if re.match(pat, clean, re.IGNORECASE):
            return True
    return False


def is_codex_relay(text: str) -> bool:
    """Detect messages that are primarily relaying Codex output."""
    lower = text.lower()
    # Check if message is primarily Codex content
    codex_markers = [
        "codex says",
        "here is what codex",
        "codex's analysis",
        "codex identified",
        "codex found",
        "codex verified",
    ]
    has_codex_marker = any(m in lower[:200] for m in codex_markers)
    if not has_codex_marker:
        return False

    # If the user adds their own commentary (> 100 chars of non-Codex text), keep it
    # Simple heuristic: if user's own text is < 20% of total, it's a relay
    lines = text.split("\n")
    user_lines = 0
    codex_lines = 0
    in_codex = False

    for line in lines:
        l = line.strip().lower()
        if any(m in l for m in codex_markers):
            in_codex = True
        elif l.startswith(
            (
                "i want",
                "i'd like",
                "i think",
                "instead",
                "yes.",
                "my ",
                "we should",
                "the goal",
                "is there anything",
                "can you",
                "please",
            )
        ):
            in_codex = False

        if in_codex:
            codex_lines += 1
        else:
            user_lines += 1

    total = user_lines + codex_lines
    if total > 0 and codex_lines / total > 0.7:
        return True
    return False


def extract_user_voice(text: str) -> str:
    """Extract only the user's own words from a message that may contain quotes."""
    # Remove common quote patterns
    # Session continuation summaries
    text = re.sub(r"This session is being continued.*?(?=\n\n[A-Z]|\Z)", "", text, flags=re.DOTALL)

    # Remove "Codex says: ..." blocks (keep user's framing)
    lines = text.split("\n")
    result_lines = []
    skip_until_user = False

    for line in lines:
        lower = line.strip().lower()

        # Start skipping at Codex quote
        if any(
            m in lower
            for m in [
                "codex says:",
                "here is what codex said:",
                "codex's analysis:",
                "here's what codex says:",
                "claude's direction is",
            ]
        ):
            skip_until_user = True
            continue

        # Resume at user's own voice
        if skip_until_user and any(
            lower.startswith(p)
            for p in [
                "i want",
                "i would",
                "i think",
                "instead",
                "my ",
                "yes.",
                "the goal",
                "is there",
                "can you",
                "please",
                "we should",
                "i'd like",
                "i need",
                "let's",
                "what if",
                "how about",
                "that said",
                "however",
                "but ",
                "also",
                "and ",
            ]
        ):
            skip_until_user = False

        if not skip_until_user:
            result_lines.append(line)

    return "\n".join(result_lines).strip()


def deduplicate(prompts: list[dict], threshold: float = 0.65) -> list[dict]:
    """Remove near-duplicate prompts using word overlap."""
    seen: list[str] = []
    unique = []
    for p in prompts:
        text = p["text"][:400].lower()
        words_a = set(text.split())
        is_dup = False
        for s in seen:
            words_b = set(s.split())
            if not words_a or not words_b:
                continue
            overlap = len(words_a & words_b) / len(words_a | words_b)
            if overlap > threshold:
                is_dup = True
                break
        if not is_dup:
            seen.append(text)
            unique.append(p)
    return unique


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=28)
    parser.add_argument(
        "--max-text-len",
        type=int,
        default=2000,
        help="Max chars per prompt to output (default: 2000)",
    )
    parser.add_argument("--stats", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--full", action="store_true")

    args = parser.parse_args()

    sessions_dir = os.path.expanduser("~/.claude/projects/-Users-armand-Development-aragora")
    cutoff = datetime.now() - timedelta(days=args.days)
    sessions_path = Path(sessions_dir)

    all_prompts = []
    stats = {
        "total_lines": 0,
        "user_messages": 0,
        "system_filtered": 0,
        "low_content": 0,
        "codex_relay": 0,
        "too_short_after_clean": 0,
        "kept": 0,
    }

    for jsonl_file in sorted(sessions_path.glob("*.jsonl")):
        mtime = datetime.fromtimestamp(jsonl_file.stat().st_mtime)
        if mtime < cutoff:
            continue

        session_id = jsonl_file.stem

        with open(jsonl_file, "r") as f:
            for line in f:
                stats["total_lines"] += 1
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if obj.get("type") != "user":
                    continue
                stats["user_messages"] += 1

                msg = obj.get("message", {})
                text = extract_user_text(msg)
                if not text:
                    continue

                text = clean_text(text)

                # Filter system-generated
                if is_system_generated(text):
                    stats["system_filtered"] += 1
                    continue

                # Filter low content
                if is_low_content(text):
                    stats["low_content"] += 1
                    continue

                # Extract user's own voice from relay messages
                if is_codex_relay(text):
                    stats["codex_relay"] += 1
                    # Don't skip entirely — extract user's portion
                    text = extract_user_voice(text)

                # Recheck after extraction
                if not text or len(text) < 50:
                    stats["too_short_after_clean"] += 1
                    continue

                timestamp = obj.get("timestamp", "")
                stats["kept"] += 1

                all_prompts.append(
                    {
                        "session_id": session_id[:8],
                        "timestamp": timestamp,
                        "date": timestamp[:10] if timestamp else mtime.strftime("%Y-%m-%d"),
                        "length": len(text),
                        "text": text,
                    }
                )

    # Deduplicate
    before = len(all_prompts)
    all_prompts = deduplicate(all_prompts)
    deduped = before - len(all_prompts)
    all_prompts.sort(key=lambda x: x.get("timestamp", ""))

    if args.stats:
        print("Processing stats:")
        for k, v in stats.items():
            print(f"  {k}: {v}")
        print(f"\nAfter dedup: {len(all_prompts)} (removed {deduped})")
        print(
            f"Avg length: {sum(p['length'] for p in all_prompts) // max(len(all_prompts), 1)} chars"
        )

        # Length distribution
        buckets = {"< 100": 0, "100-500": 0, "500-2k": 0, "2k-10k": 0, "> 10k": 0}
        for p in all_prompts:
            l = p["length"]
            if l < 100:
                buckets["< 100"] += 1
            elif l < 500:
                buckets["100-500"] += 1
            elif l < 2000:
                buckets["500-2k"] += 1
            elif l < 10000:
                buckets["2k-10k"] += 1
            else:
                buckets["> 10k"] += 1
        print("\nLength distribution:")
        for b, c in buckets.items():
            print(f"  {b}: {c}")
        return

    if args.json:
        output = []
        for p in all_prompts:
            t = p["text"]
            if not args.full and len(t) > args.max_text_len:
                t = t[: args.max_text_len] + " [...]"
            output.append(
                {
                    "date": p["date"],
                    "length": p["length"],
                    "text": t,
                }
            )
        json.dump(output, sys.stdout, indent=2, ensure_ascii=False)
        print()
        return

    # Human-readable
    print(f"# User Prompts ({len(all_prompts)} after filtering + dedup)")
    print()
    for p in all_prompts:
        t = p["text"]
        if not args.full and len(t) > args.max_text_len:
            t = t[: args.max_text_len] + " [...]"
        print(f"### [{p['date']}] ({p['length']} chars)")
        print(t)
        print()


if __name__ == "__main__":
    main()
