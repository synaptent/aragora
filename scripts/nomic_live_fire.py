#!/usr/bin/env python3
"""Nomic Loop Live Fire Test — standalone runner bypassing ChaosTheater.

Calls API agents directly, runs debate without Arena (avoiding ChaosTheater),
then applies changes and verifies.
"""

import asyncio
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


async def call_claude(prompt: str, system: str = "") -> str:
    """Direct Anthropic API call — Claude Opus 4.6."""
    import anthropic

    client = anthropic.AsyncAnthropic()
    msgs = [{"role": "user", "content": prompt}]
    kwargs = {"model": "claude-opus-4-6", "max_tokens": 16000, "messages": msgs}
    if system:
        kwargs["system"] = system
    resp = await client.messages.create(**kwargs)
    return resp.content[0].text


def _resolve_openrouter_key() -> str:
    """Resolve OpenRouter API key: env → dedicated AWS secret → bundled secret."""
    import os

    # 1. Environment variable (fastest)
    key = os.getenv("OPENROUTER_API_KEY", "")
    if key and not key.startswith("new-key"):
        return key

    # 2. Dedicated AWS secret at aragora/api/openrouter
    try:
        import boto3

        client = boto3.client("secretsmanager")
        resp = client.get_secret_value(SecretId="aragora/api/openrouter")
        key = resp["SecretString"].strip()
        if key:
            return key
    except Exception:
        pass

    # 3. Bundled production secret
    try:
        from aragora.config.secrets import get_secret

        key = get_secret("OPENROUTER_API_KEY") or ""
        if key and not key.startswith("new-key"):
            return key
    except Exception:
        pass

    msg = "OPENROUTER_API_KEY not found in env, AWS (aragora/api/openrouter), or bundled secrets"
    raise RuntimeError(msg)


async def call_openrouter(prompt: str, system: str = "", model: str = "openai/gpt-5.2") -> str:
    """OpenRouter API call — supports GPT-5.2, Gemini 3.1, Grok 4."""
    import aiohttp

    api_key = _resolve_openrouter_key()
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": prompt})
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "messages": msgs, "max_tokens": 8000},
        ) as resp:
            data = await resp.json()
            if "error" in data:
                raise RuntimeError(f"OpenRouter error: {data['error']}")
            return data["choices"][0]["message"]["content"]


async def phase_debate(task: str) -> str:
    """Phase 1: Two API agents propose, then synthesizer merges."""
    print("\n" + "=" * 70)
    print("PHASE 1: DEBATE")
    print("=" * 70)

    system = "You are a senior software architect. Be concrete: specify exact files and changes."

    # Call three proposers in parallel: Claude Opus 4.6, GPT-5.2, Gemini 3.1 Pro
    print("  Calling Claude Opus 4.6, GPT-5.2, and Gemini 3.1 Pro...")
    claude_resp, gpt_resp, gemini_resp = await asyncio.gather(
        call_claude(task, system),
        call_openrouter(task, system, model="openai/gpt-5.2"),
        call_openrouter(task, system, model="google/gemini-3.1-pro-preview"),
        return_exceptions=True,
    )

    proposals = []
    for name, resp in [
        ("Claude Opus 4.6", claude_resp),
        ("GPT-5.2", gpt_resp),
        ("Gemini 3.1", gemini_resp),
    ]:
        if isinstance(resp, Exception):
            print(f"  WARNING: {name} failed: {resp}")
        else:
            print(f"  {name} responded ({len(resp)} chars)")
            proposals.append((name, resp[:3000]))

    if not proposals:
        raise RuntimeError("All agents failed!")

    # Synthesize
    print("  Calling Claude Opus 4.6 (synthesizer)...")
    proposals_text = "\n\n".join(f"PROPOSAL ({name}):\n{text}" for name, text in proposals)
    synthesis_prompt = f"""{len(proposals)} software architects proposed improvements. Synthesize the best plan.

{proposals_text}

Pick the best ideas and produce a SINGLE concrete implementation plan.
Output the exact code changes needed (file paths, code blocks, test code)."""

    synthesis = await call_claude(
        synthesis_prompt, "You produce actionable implementation plans with exact code."
    )

    print(f"  Synthesis complete ({len(synthesis)} chars)")
    print("\n--- DEBATE RESULT ---")
    print(synthesis[:500])
    print("..." if len(synthesis) > 500 else "")

    return synthesis


async def phase_implement(design: str) -> dict:
    """Phase 3: Extract and apply code changes from the design."""
    print("\n" + "=" * 70)
    print("PHASE 2: IMPLEMENT")
    print("=" * 70)

    # Ask Claude to extract exact file edits
    extract_prompt = f"""From this implementation plan, extract the exact file changes.

PLAN:
{design[:4000]}

For each file, output in this JSON format:
{{
  "changes": [
    {{"file": "path/to/file.py", "action": "modify", "search": "old code", "replace": "new code"}},
    {{"file": "path/to/new_file.py", "action": "create", "content": "full file content"}}
  ]
}}

Output ONLY valid JSON, no markdown fences."""

    response = await call_claude(
        extract_prompt, "You extract structured code changes. Output only valid JSON."
    )

    # Parse the JSON
    try:
        # Strip markdown fences if present
        text = response.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            text = text.rsplit("```", 1)[0]
        changes = json.loads(text)
    except json.JSONDecodeError as e:
        print(f"  ERROR: Could not parse changes JSON: {e}")
        print(f"  Raw response: {response[:500]}")
        return {"status": "failed", "error": str(e)}

    applied = 0
    for change in changes.get("changes", []):
        filepath = REPO / change["file"]
        action = change.get("action", "modify")

        if action == "create":
            filepath.parent.mkdir(parents=True, exist_ok=True)
            filepath.write_text(change["content"], encoding="utf-8")
            print(f"  CREATED {change['file']}")
            applied += 1
        elif action == "modify":
            if not filepath.exists():
                print(f"  SKIP {change['file']} (not found)")
                continue
            content = filepath.read_text(encoding="utf-8")
            search = change.get("search", "")
            replace = change.get("replace", "")
            if search and search in content:
                content = content.replace(search, replace, 1)
                filepath.write_text(content, encoding="utf-8")
                print(f"  MODIFIED {change['file']}")
                applied += 1
            else:
                print(f"  SKIP {change['file']} (search text not found)")

    print(f"\n  Applied {applied}/{len(changes.get('changes', []))} changes")
    return {"status": "implemented" if applied > 0 else "failed", "applied": applied}


def phase_verify() -> dict:
    """Phase 4: Run syntax check and tests."""
    print("\n" + "=" * 70)
    print("PHASE 3: VERIFY")
    print("=" * 70)

    checks = []

    # Syntax check on modified files
    result = subprocess.run(
        ["git", "diff", "--name-only"], capture_output=True, text=True, cwd=REPO
    )
    changed_files = [f for f in result.stdout.strip().split("\n") if f.endswith(".py")]

    for f in changed_files:
        try:
            with open(REPO / f) as fh:
                compile(fh.read(), f, "exec")
            checks.append({"name": f"syntax:{f}", "passed": True})
            print(f"  ✓ Syntax OK: {f}")
        except SyntaxError as e:
            checks.append({"name": f"syntax:{f}", "passed": False, "error": str(e)})
            print(f"  ✗ Syntax ERROR: {f}: {e}")

    # Run relevant tests
    test_result = subprocess.run(
        ["python", "-m", "pytest", "tests/nomic/", "-x", "-q", "--tb=short", "--timeout=60"],
        capture_output=True,
        text=True,
        cwd=REPO,
        timeout=300,
    )
    passed = test_result.returncode == 0
    checks.append({"name": "pytest:tests/nomic/", "passed": passed})
    print(f"  {'✓' if passed else '✗'} Tests: {test_result.stdout.strip().split(chr(10))[-1]}")
    if not passed:
        print(f"    stderr: {test_result.stderr[-300:]}")

    return {"checks": checks, "all_passed": all(c["passed"] for c in checks)}


def phase_commit() -> dict:
    """Phase 5: Commit changes."""
    print("\n" + "=" * 70)
    print("PHASE 4: COMMIT")
    print("=" * 70)

    result = subprocess.run(["git", "diff", "--stat"], capture_output=True, text=True, cwd=REPO)
    if not result.stdout.strip():
        print("  No changes to commit")
        return {"status": "no_changes"}

    print(f"  Changes:\n{result.stdout}")

    subprocess.run(["git", "add", "-A"], cwd=REPO)
    commit_result = subprocess.run(
        [
            "git",
            "commit",
            "-m",
            "feat(nomic): autonomous self-improvement via Nomic Loop live fire\n\n"
            "Changes proposed by multi-agent debate (Claude + GPT-4o),\n"
            "synthesized, implemented, verified, and committed autonomously.\n\n"
            "Co-Authored-By: Nomic Loop <nomic@aragora.ai>",
        ],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    if commit_result.returncode == 0:
        print("  ✓ Committed successfully")
        return {"status": "committed"}
    else:
        print(f"  ✗ Commit failed: {commit_result.stderr}")
        return {"status": "commit_failed", "error": commit_result.stderr}


async def main():
    task = (
        sys.argv[1]
        if len(sys.argv) > 1
        else (
            "Add strict mypy enforcement for aragora/nomic/meta_planner.py "
            "in pyproject.toml and add a test in tests/nomic/test_meta_planner.py "
            "that verifies all public methods have return type annotations"
        )
    )

    print("=" * 70)
    print("NOMIC LOOP LIVE FIRE TEST")
    print(f"Task: {task[:80]}...")
    print(f"Time: {datetime.now().isoformat()}")
    print("=" * 70)

    # Phase 1: Debate
    design = await phase_debate(task)

    # Phase 2: Implement
    impl = await phase_implement(design)
    if impl["status"] != "implemented":
        print("\n✗ Implementation failed. Aborting.")
        return

    # Phase 3: Verify
    verify = phase_verify()
    if not verify["all_passed"]:
        print("\n✗ Verification failed. Changes NOT committed.")
        print("  Run 'git checkout .' to revert.")
        return

    # Phase 4: Commit
    result = phase_commit()

    print("\n" + "=" * 70)
    print("LIVE FIRE TEST COMPLETE")
    print(f"Result: {result.get('status', 'unknown')}")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
