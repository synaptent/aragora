"""Execute the shipped Action shell with offline CLI/GitHub stand-ins."""

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
ACTION = yaml.safe_load((ROOT / "action.yml").read_text())


def step(name):
    return next(s for s in ACTION["runs"]["steps"] if s["name"] == name)


def execute(name, directory, env):
    return subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", step(name)["run"]],
        cwd=directory,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )


@pytest.mark.parametrize("output_format", ["none", "json", "sarif"])
@pytest.mark.parametrize("exit_code", [0, 3])
def test_action_calls_review_once_and_does_not_execute_inputs(tmp_path, output_format, exit_code):
    cli = tmp_path / "aragora"
    cli.write_text("""#!/usr/bin/env python3
import json, os, pathlib, sys
p = pathlib.Path("aragora-artifacts")
with open("calls.jsonl", "a") as f: f.write(json.dumps(sys.argv[1:]) + "\\n")
(p / "comment.md").write_text("review")
(p / "review.sarif").write_text("{}")
(p / "review.json").write_text(json.dumps({"review_context": {"status": "complete" if os.environ["EXIT_CODE"] == "0" else "incomplete"}}))
sys.exit(int(os.environ["EXIT_CODE"]))
""")
    cli.chmod(0o755)
    env = {
        **os.environ,
        "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
        "GITHUB_ACTION_PATH": str(ROOT),
        "GITHUB_OUTPUT": str(tmp_path / "outputs"),
        "REVIEW_AGENTS": "anthropic-api,openai-api",
        "REVIEW_ROUNDS": "2",
        "REVIEW_FOCUS": "$(touch injected); security",
        "OUTPUT_FORMAT": output_format,
        "DIFF_TRUNCATED": "false",
        "HEAD_SHA": "a" * 40,
        "REPO": "example/repo",
        "PR": "7",
        "EXIT_CODE": str(exit_code),
    }
    result = execute("Run Aragora review", tmp_path, env)
    assert result.returncode == 0, result.stderr
    calls = [json.loads(line) for line in (tmp_path / "calls.jsonl").read_text().splitlines()]
    assert len(calls) == 1
    assert "--bundle" in calls[0]
    assert calls[0][calls[0].index("--focus") + 1] == env["REVIEW_FOCUS"]
    assert not (tmp_path / "injected").exists()
    outputs = dict(line.split("=", 1) for line in (tmp_path / "outputs").read_text().splitlines())
    assert outputs["review_generated"] == ("true" if exit_code == 0 else "false")
    assert (outputs["review_status"] == "complete") == (exit_code == 0)
    assert bool(outputs["sarif_path"]) == (output_format == "sarif" and exit_code == 0)


def test_changed_pr_is_not_commented_on(tmp_path):
    gh = tmp_path / "gh"
    gh.write_text(
        '#!/bin/sh\nif [ "$2" = "view" ]; then echo "new-head base"; else touch posted; fi\n'
    )
    gh.chmod(0o755)
    result = execute(
        "Post PR comment",
        tmp_path,
        {
            **os.environ,
            "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
            "PR": "7",
            "REVIEW_TARGET": "old-head base",
        },
    )
    assert result.returncode == 1
    assert not (tmp_path / "posted").exists()


def test_quorum_and_failure_gates_remain_separate():
    receipt = step("Emit decision receipt")
    assert "collect_quorum_evidence.py" in receipt["run"]
    assert 'd["head_sha"] == os.environ["REVIEW_HEAD"]' in receipt["run"]
    assert "--apply" not in receipt["run"].replace("(no --apply)", "")
    assert "review_generated == 'true'" in receipt["if"]
    assert step("Upload artifacts")["if"] == "always()"
    assert "review_status != 'complete'" in step("Check review execution")["if"]
    assert 'pip install "$GITHUB_ACTION_PATH"' in step("Install Aragora")["run"]


@pytest.mark.parametrize("corrupt", [False, True])
def test_receipt_attachment_refreshes_manifest_hashes(tmp_path, corrupt):
    import hashlib

    directory = tmp_path / "aragora-artifacts"
    directory.mkdir()
    (directory / "comment.md").write_text("original review")
    (directory / "comment.pending.md").write_text("review plus separate receipt summary")
    (directory / "decision-receipt.odr.json").write_text("{}")
    (directory / "bundle.json").write_text("bad" if corrupt else '{"files": {"comment.md": "old"}}')
    command = next(
        line.strip()
        for line in step("Emit decision receipt")["run"].splitlines()
        if line.strip().startswith("python3 -c ")
    )
    result = subprocess.run(
        ["bash", "-e", "-c", command], cwd=tmp_path, capture_output=True, text=True
    )
    if corrupt:
        assert result.returncode != 0
        assert (directory / "comment.md").read_text() == "original review"
        return
    assert result.returncode == 0, result.stderr
    for name, digest in json.loads((directory / "bundle.json").read_text())["files"].items():
        assert hashlib.sha256((directory / name).read_bytes()).hexdigest() == digest


def test_threshold_input_is_not_shell_code(tmp_path):
    result = execute(
        "Check failure threshold",
        tmp_path,
        {
            **os.environ,
            "ISSUE_COUNT": "1",
            "FAILURE_THRESHOLD": "$(touch injected)",
        },
    )
    assert result.returncode == 1
    assert not (tmp_path / "injected").exists()


@pytest.mark.parametrize(
    "head_repo,target_repo,pr,lookup_exit,code",
    [
        ("owner/repo", "owner/repo", "7", 0, 0),
        ("fork/repo", "fork/repo", "7", 0, 1),
        ("", "owner/repo", "7", 0, 0),
        ("", "fork/repo", "7", 0, 1),
        ("owner/repo", "fork/repo", "8", 0, 1),
        ("", "", "7", 0, 1),
        ("", "owner/repo", "7", 1, 1),
        ("", "owner/repo", "$(touch injected)", 0, 1),
    ],
)
def test_fork_stops_before_secret_bearing_steps(
    tmp_path, head_repo, target_repo, pr, lookup_exit, code
):
    assert ACTION["runs"]["steps"][0]["name"] == "Check review trust"
    gh = tmp_path / "gh"
    gh.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$*" > lookup\n'
        'printf "%s\\n" "$TARGET_REPO"\nexit "$LOOKUP_EXIT"\n'
    )
    gh.chmod(0o755)
    result = execute(
        "Check review trust",
        tmp_path,
        {
            **os.environ,
            "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
            "HEAD_REPO": head_repo,
            "REPO": "owner/repo",
            "EVENT_PR_NUMBER": "7",
            "INPUT_PR_NUMBER": pr,
            "TARGET_REPO": target_repo,
            "LOOKUP_EXIT": str(lookup_exit),
        },
    )
    assert result.returncode == code
    assert not (tmp_path / "injected").exists()
    if code == 0:
        assert f"repos/owner/repo/pulls/{pr}" in (tmp_path / "lookup").read_text()
    assert set(step("Check review trust")["env"]) == {
        "HEAD_REPO",
        "REPO",
        "GH_TOKEN",
        "EVENT_PR_NUMBER",
        "INPUT_PR_NUMBER",
    }
