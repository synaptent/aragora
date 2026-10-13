#!/usr/bin/env python3
"""Extract user INTENT prompts — the substantive requests that reveal
what the user is trying to achieve with Aragora.

Much stricter than extract_user_prompts.py:
- Filters out Codex-relayed technical status messages
- Filters out CI/git operational messages
- Filters out "here's what X says" relay messages (keeps only user's own words)
- Focuses on: vision, features, architecture, priorities, decisions
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path


def clean_text(text: str) -> str:
    """Remove system tags, hook outputs, and noise."""
    text = re.sub(r"<system-reminder>.*?</system-reminder>", "", text, flags=re.DOTALL)
    text = re.sub(r"<command-\w+>.*?</command-\w+>", "", text, flags=re.DOTALL)
    text = re.sub(r"<local-command-\w+>.*?</local-command-\w+>", "", text, flags=re.DOTALL)
    text = re.sub(r"<task-notification>.*?</task-notification>", "", text, flags=re.DOTALL)
    text = re.sub(r"<claude-mem-context>.*?</claude-mem-context>", "", text, flags=re.DOTALL)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_user_portion(text: str) -> str:
    """When user relays Codex output, extract only the user's own words.

    Pattern: user says something, then quotes Codex's analysis.
    We want the user's framing, not the quoted content.
    """
    # If message starts with "Codex says:" or "here is what codex says:",
    # the user's intent is AROUND the quote, not IN it
    lines = text.split("\n")
    user_lines = []
    in_codex_quote = False

    for line in lines:
        lower = line.strip().lower()
        # Detect start of Codex/assistant quote
        if any(
            marker in lower
            for marker in [
                "codex says",
                "here is what codex",
                "codex's analysis",
                "here's what codex",
                "claude says",
                "here is what claude",
            ]
        ):
            in_codex_quote = True
            # Keep the user's framing line
            user_lines.append(line)
            continue

        # Detect end of quoted section (user's own voice returns)
        if in_codex_quote and (
            lower.startswith(
                (
                    "i want",
                    "i would",
                    "i think",
                    "my ",
                    "we should",
                    "is there",
                    "can you",
                    "please",
                    "what if",
                    "the goal",
                    "yes.",
                    "no.",
                    "instead",
                    "i'd like",
                    "i need",
                    "let's",
                )
            )
        ):
            in_codex_quote = False

        if not in_codex_quote:
            user_lines.append(line)

    return "\n".join(user_lines).strip()


def is_operational_noise(text: str) -> bool:
    """Filter out CI/git/operational messages that don't reveal intent."""
    lower = text.lower()

    # CI/git operational patterns
    noise_patterns = [
        r"^(git (status|diff|log|push|pull|rebase|merge|checkout|branch|stash))",
        r"^(gh pr (view|list|merge|create|close|ready|checks))",
        r"^(make |npm |pip |pytest |ruff |mypy )",
        r"^(running |checking |installing |building |deploying )",
        r"pr #\d+ (is |has |shows |merged|closed|blocked|ready)",
        r"^(the (lint|typecheck|sdk-parity|openapi|ci|workflow|check|test))",
        r"^(fix(ed|ing)? (the |ci |lint |type|test|build))",
    ]

    for pat in noise_patterns:
        if re.match(pat, lower):
            return True

    # Messages that are mostly technical status
    tech_keywords = [
        "merge conflict",
        "cherry-pick",
        "rebase",
        "workflow",
        "pull request",
        "branch protection",
        "required check",
        "cancel-in-progress",
        "dependabot",
        "path filter",
    ]
    tech_count = sum(1 for kw in tech_keywords if kw in lower)

    # If >40% of content is technical CI/git terminology, it's operational
    words = lower.split()
    if len(words) > 10 and tech_count >= 3:
        # But keep if there's clear intent language
        intent_words = [
            "want",
            "should",
            "goal",
            "aim",
            "vision",
            "priority",
            "improve",
            "better",
            "feature",
            "design",
            "architecture",
            "user",
            "experience",
            "value",
            "solve",
            "problem",
        ]
        if not any(w in lower for w in intent_words):
            return True

    return False


def is_low_content(text: str) -> bool:
    """Check if message is too short or repetitive to be substantive."""
    clean = text.strip()
    if len(clean) < 40:
        return True

    patterns = [
        r"^(yes|no|ok|okay|sure|thanks|proceed|continue|go ahead|do it)",
        r"^(yes to all|all of them|sounds good|agreed|makes sense)",
        r"^(what is (current )?status|what are (best )?next steps)",
        r"^(now continue|keep going|carry on|move on)",
        r"^/\w+",
        r"^compact$",
    ]

    for pat in patterns:
        if re.match(pat, clean, re.IGNORECASE):
            return True

    return False


def score_intent(text: str) -> float:
    """Score how much a message reveals user intent/vision (0-1)."""
    lower = text.lower()
    score = 0.0

    # Vision/goal language
    vision_words = [
        "i want",
        "i'd like",
        "i need",
        "goal",
        "vision",
        "aim",
        "should be able to",
        "the purpose",
        "what aragora",
        "make aragora",
        "aragora should",
        "the platform",
        "we need",
        "priority",
        "focus on",
        "most important",
    ]
    for w in vision_words:
        if w in lower:
            score += 0.15

    # Feature/design language
    feature_words = [
        "feature",
        "design",
        "architecture",
        "interface",
        "gui",
        "pipeline",
        "workflow",
        "agent",
        "debate",
        "self-improv",
        "obsidian",
        "oracle",
        "landing",
        "playground",
        "experience",
    ]
    for w in feature_words:
        if w in lower:
            score += 0.1

    # Decision language
    decision_words = [
        "prefer",
        "instead",
        "rather",
        "choose",
        "option",
        "approach",
        "strategy",
        "trade-off",
        "versus",
        "vs",
        "i think",
        "my view",
        "in my opinion",
    ]
    for w in decision_words:
        if w in lower:
            score += 0.1

    # Problem statement language
    problem_words = [
        "problem",
        "issue",
        "challenge",
        "unsolved",
        "missing",
        "broken",
        "wrong",
        "better",
        "improve",
        "fix",
        "doesn't work",
        "needs to",
        "should not",
    ]
    for w in problem_words:
        if w in lower:
            score += 0.08

    # User/value language
    value_words = [
        "user",
        "customer",
        "value",
        "useful",
        "powerful",
        "unique",
        "differentiat",
        "competitive",
        "market",
        "enterprise",
        "sme",
        "founder",
        "cto",
    ]
    for w in value_words:
        if w in lower:
            score += 0.08

    # Length bonus (longer = more substantive, up to a point)
    if len(text) > 200:
        score += 0.1
    if len(text) > 500:
        score += 0.1

    return min(score, 1.0)


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


def deduplicate(prompts: list[dict], threshold: float = 0.7) -> list[dict]:
    """Remove near-duplicate prompts."""
    seen: list[str] = []
    unique = []
    for p in prompts:
        text = p["text"][:300].lower()
        words_a = set(text.split())
        is_dup = False
        for s in seen:
            words_b = set(s.split())
            if not words_a or not words_b:
                continue
            jaccard = len(words_a & words_b) / len(words_a | words_b)
            if jaccard > threshold:
                is_dup = True
                break
        if not is_dup:
            seen.append(text)
            unique.append(p)
    return unique


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Extract user intent prompts")
    parser.add_argument("--days", type=int, default=14, help="Days back (default: 14)")
    parser.add_argument(
        "--min-score", type=float, default=0.2, help="Min intent score (default: 0.2)"
    )
    parser.add_argument("--top", type=int, default=0, help="Show only top N by score")
    parser.add_argument("--full", action="store_true", help="Show full text")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--stats", action="store_true", help="Stats only")

    args = parser.parse_args()

    sessions_dir = os.path.expanduser("~/.claude/projects/-Users-armand-Development-aragora")
    cutoff = datetime.now() - timedelta(days=args.days)
    sessions_path = Path(sessions_dir)

    all_prompts = []

    for jsonl_file in sorted(sessions_path.glob("*.jsonl")):
        mtime = datetime.fromtimestamp(jsonl_file.stat().st_mtime)
        if mtime < cutoff:
            continue

        session_id = jsonl_file.stem

        with open(jsonl_file, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if obj.get("type") != "user":
                    continue

                msg = obj.get("message", {})
                if not msg:
                    continue

                text = extract_user_text(msg)
                if not text:
                    continue

                text = clean_text(text)
                if not text:
                    continue

                # Extract user's own words from relay messages
                text = extract_user_portion(text)
                if not text:
                    continue

                if is_low_content(text):
                    continue
                if is_operational_noise(text):
                    continue

                intent_score = score_intent(text)
                if intent_score < args.min_score:
                    continue

                timestamp = obj.get("timestamp", "")

                all_prompts.append(
                    {
                        "session_id": session_id[:8],
                        "timestamp": timestamp,
                        "date": timestamp[:10] if timestamp else mtime.strftime("%Y-%m-%d"),
                        "length": len(text),
                        "score": round(intent_score, 2),
                        "text": text,
                    }
                )

    # Deduplicate
    before = len(all_prompts)
    all_prompts = deduplicate(all_prompts)
    deduped = before - len(all_prompts)

    # Sort by score (highest first) if --top, otherwise by time
    if args.top:
        all_prompts.sort(key=lambda x: x["score"], reverse=True)
        all_prompts = all_prompts[: args.top]
    else:
        all_prompts.sort(key=lambda x: x.get("timestamp", ""))

    if args.stats:
        print(f"Intent prompts: {len(all_prompts)} (deduped {deduped})")
        print(f"Avg score: {sum(p['score'] for p in all_prompts) / max(len(all_prompts), 1):.2f}")
        print(
            f"Avg length: {sum(p['length'] for p in all_prompts) // max(len(all_prompts), 1)} chars"
        )

        # Score distribution
        buckets = {f"{i / 10:.1f}-{(i + 1) / 10:.1f}": 0 for i in range(0, 10)}
        for p in all_prompts:
            bucket = f"{int(p['score'] * 10) / 10:.1f}-{int(p['score'] * 10 + 1) / 10:.1f}"
            buckets[bucket] = buckets.get(bucket, 0) + 1
        print("\nScore distribution:")
        for b, c in sorted(buckets.items()):
            if c > 0:
                print(f"  {b}: {c}")
        return

    if args.json:
        output = []
        for p in all_prompts:
            t = (
                p["text"]
                if args.full
                else (p["text"][:500] + " [...]" if len(p["text"]) > 500 else p["text"])
            )
            output.append(
                {
                    "date": p["date"],
                    "score": p["score"],
                    "length": p["length"],
                    "text": t,
                }
            )
        json.dump(output, sys.stdout, indent=2)
        print()
        return

    # Human-readable
    print(f"# User Intent Prompts ({len(all_prompts)} found)")
    print()

    for i, p in enumerate(all_prompts, 1):
        text = (
            p["text"]
            if args.full
            else (p["text"][:500] + " [...]" if len(p["text"]) > 500 else p["text"])
        )
        print(f"### [{p['date']}] score={p['score']} ({p['length']} chars)")
        print(text)
        print()


if __name__ == "__main__":
    main()
