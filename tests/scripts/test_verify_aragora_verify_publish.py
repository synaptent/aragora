from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def _load_module() -> Any:
    here = Path(__file__).resolve()
    script_path = here.parents[2] / "scripts" / "verify_aragora_verify_publish.py"
    spec = importlib.util.spec_from_file_location(
        "verify_aragora_verify_publish_under_test",
        script_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load spec for {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


verify_publish_script = _load_module()


def _completed(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


def test_verify_publish_installs_exact_version_and_runs_probe(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        assert kwargs["check"] is False
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        assert kwargs["timeout"] == 99
        if cmd[-1] == "--version":
            return _completed("aragora-verify 0.1.2\n")
        if cmd[-1].endswith("post_publish_probe.py"):
            return _completed(
                json.dumps(
                    {
                        "valid_receipt_exit": 0,
                        "spoofed_key_id_exit": 1,
                        "spoofed_signature_status": "fail",
                    }
                )
            )
        return _completed()

    monkeypatch.setattr(verify_publish_script.subprocess, "run", fake_run)

    result = verify_publish_script.verify_publish(
        version="0.1.2",
        python="/usr/bin/python3",
        work_dir=tmp_path,
        timeout=99,
    )

    venv_python = str(tmp_path / ".venv" / "bin" / "python")
    assert calls[:3] == [
        ["/usr/bin/python3", "-m", "venv", str(tmp_path / ".venv")],
        [venv_python, "-m", "pip", "install", "--upgrade", "pip"],
        [
            venv_python,
            "-m",
            "pip",
            "install",
            "--isolated",
            "--no-cache-dir",
            "--index-url",
            "https://pypi.org/simple",
            "aragora-verify==0.1.2",
        ],
    ]
    assert calls[3] == [venv_python, "-m", "aragora_verify", "--version"]
    assert calls[4] == [venv_python, str(tmp_path / "post_publish_probe.py")]
    assert result["ok"] is True
    assert result["version"] == "0.1.2"
    assert result["probe"] == {
        "valid_receipt_exit": 0,
        "spoofed_key_id_exit": 1,
        "spoofed_signature_status": "fail",
    }
    probe_source = (tmp_path / "post_publish_probe.py").read_text(encoding="utf-8")
    assert "spoofed-signer-label" in probe_source
    assert "aragora_verify" in probe_source


def test_verify_publish_fails_on_version_mismatch(monkeypatch: Any, tmp_path: Path) -> None:
    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if cmd[-1] == "--version":
            return _completed("aragora-verify 0.1.1\n")
        return _completed()

    monkeypatch.setattr(verify_publish_script.subprocess, "run", fake_run)

    try:
        verify_publish_script.verify_publish(
            version="0.1.2",
            python="/usr/bin/python3",
            work_dir=tmp_path,
        )
    except verify_publish_script.PublishVerificationError as exc:
        assert "version mismatch" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected PublishVerificationError")


def test_main_returns_one_on_failed_command(monkeypatch: Any, capsys: Any, tmp_path: Path) -> None:
    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="network down")

    monkeypatch.setattr(verify_publish_script.subprocess, "run", fake_run)

    rc = verify_publish_script.main(["--version", "0.1.2", "--work-dir", str(tmp_path)])

    assert rc == 1
    assert "network down" in capsys.readouterr().err


def test_published_install_is_isolated_from_runner_pip_config(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    """The gate must prove installability from *public* PyPI.

    A self-hosted runner carrying PIP_INDEX_URL / pip.conf / find-links could
    otherwise satisfy the install from a mirror or cache and report success
    while the published version is unreachable for real users.
    """
    install_cmd: list[str] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if cmd[-1] == "aragora-verify==0.1.2":
            install_cmd.extend(cmd)
        if cmd[-1] == "--version":
            return _completed("aragora-verify 0.1.2\n")
        if cmd[-1].endswith("post_publish_probe.py"):
            return _completed(
                json.dumps(
                    {
                        "valid_receipt_exit": 0,
                        "signed_receipt_exit": 0,
                        "spoofed_key_id_exit": 1,
                        "spoofed_signature_status": "fail",
                    }
                )
            )
        return _completed()

    monkeypatch.setattr(verify_publish_script.subprocess, "run", fake_run)

    verify_publish_script.verify_publish(
        version="0.1.2",
        python="/usr/bin/python3",
        work_dir=tmp_path,
    )

    assert "--isolated" in install_cmd
    assert install_cmd[install_cmd.index("--index-url") + 1] == "https://pypi.org/simple"


def test_index_url_is_overridable(monkeypatch: Any, tmp_path: Path) -> None:
    install_cmd: list[str] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if cmd[-1] == "aragora-verify==0.1.2":
            install_cmd.extend(cmd)
        if cmd[-1] == "--version":
            return _completed("aragora-verify 0.1.2\n")
        if cmd[-1].endswith("post_publish_probe.py"):
            return _completed(json.dumps({"valid_receipt_exit": 0}))
        return _completed()

    monkeypatch.setattr(verify_publish_script.subprocess, "run", fake_run)

    verify_publish_script.verify_publish(
        version="0.1.2",
        python="/usr/bin/python3",
        work_dir=tmp_path,
        index_url="https://test.pypi.org/simple",
    )

    assert install_cmd[install_cmd.index("--index-url") + 1] == "https://test.pypi.org/simple"


def test_install_retries_until_pypi_propagates(monkeypatch: Any, tmp_path: Path) -> None:
    """PyPI index propagation lag must not red the release workflow.

    The exact-version install runs after an irreversible upload, so a 404 from
    a not-yet-propagated index has to be retried rather than raised.
    """
    target = "aragora-verify==0.1.2"
    install_calls = 0
    slept: list[float] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        nonlocal install_calls
        if cmd[-1] == target:
            install_calls += 1
            if install_calls < 3:  # first two attempts: version not visible yet
                return subprocess.CompletedProcess(
                    args=cmd,
                    returncode=1,
                    stdout="",
                    stderr="ERROR: No matching distribution found for aragora-verify==0.1.2",
                )
            return _completed()
        if cmd[-1] == "--version":
            return _completed("aragora-verify 0.1.2\n")
        if cmd[-1].endswith("post_publish_probe.py"):
            return _completed(
                json.dumps(
                    {
                        "valid_receipt_exit": 0,
                        "spoofed_key_id_exit": 1,
                        "spoofed_signature_status": "fail",
                    }
                )
            )
        return _completed()

    monkeypatch.setattr(verify_publish_script.subprocess, "run", fake_run)
    monkeypatch.setattr(verify_publish_script.time, "sleep", slept.append)

    result = verify_publish_script.verify_publish(
        version="0.1.2",
        python="/usr/bin/python3",
        work_dir=tmp_path,
        install_backoff=5.0,
    )

    assert result["ok"] is True
    assert install_calls == 3
    assert result["install_attempts"] == 3
    # exponential backoff between the two failed attempts
    assert slept == [5.0, 10.0]


def test_install_gives_up_after_bounded_attempts(monkeypatch: Any, tmp_path: Path) -> None:
    slept: list[float] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if cmd[-1] == "aragora-verify==0.1.2":
            return subprocess.CompletedProcess(
                args=cmd, returncode=1, stdout="", stderr="404 not found"
            )
        return _completed()

    monkeypatch.setattr(verify_publish_script.subprocess, "run", fake_run)
    monkeypatch.setattr(verify_publish_script.time, "sleep", slept.append)

    try:
        verify_publish_script.verify_publish(
            version="0.1.2",
            python="/usr/bin/python3",
            work_dir=tmp_path,
            install_attempts=4,
            install_backoff=5.0,
        )
    except verify_publish_script.PublishVerificationError as exc:
        assert "after 4 attempt(s)" in str(exc)
        assert "404 not found" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected PublishVerificationError")

    assert len(slept) == 3  # no sleep after the final attempt


def test_install_backoff_is_capped(monkeypatch: Any, tmp_path: Path) -> None:
    slept: list[float] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if cmd[-1] == "aragora-verify==0.1.2":
            return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="nope")
        return _completed()

    monkeypatch.setattr(verify_publish_script.subprocess, "run", fake_run)
    monkeypatch.setattr(verify_publish_script.time, "sleep", slept.append)

    try:
        verify_publish_script.verify_publish(
            version="0.1.2",
            python="/usr/bin/python3",
            work_dir=tmp_path,
            install_attempts=8,
            install_backoff=5.0,
        )
    except verify_publish_script.PublishVerificationError:
        pass

    assert max(slept) == verify_publish_script.MAX_INSTALL_BACKOFF
    assert all(delay <= verify_publish_script.MAX_INSTALL_BACKOFF for delay in slept)


def test_install_retries_on_timeout(monkeypatch: Any, tmp_path: Path) -> None:
    """A hung index request is as transient as a 404 and must also retry."""
    install_calls = 0

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        nonlocal install_calls
        if cmd[-1] == "aragora-verify==0.1.2":
            install_calls += 1
            if install_calls == 1:
                raise subprocess.TimeoutExpired(cmd=cmd, timeout=1)
            return _completed()
        if cmd[-1] == "--version":
            return _completed("aragora-verify 0.1.2\n")
        if cmd[-1].endswith("post_publish_probe.py"):
            return _completed(
                json.dumps(
                    {
                        "valid_receipt_exit": 0,
                        "spoofed_key_id_exit": 1,
                        "spoofed_signature_status": "fail",
                    }
                )
            )
        return _completed()

    monkeypatch.setattr(verify_publish_script.subprocess, "run", fake_run)
    monkeypatch.setattr(verify_publish_script.time, "sleep", lambda _: None)

    result = verify_publish_script.verify_publish(
        version="0.1.2",
        python="/usr/bin/python3",
        work_dir=tmp_path,
    )

    assert result["ok"] is True
    assert install_calls == 2
