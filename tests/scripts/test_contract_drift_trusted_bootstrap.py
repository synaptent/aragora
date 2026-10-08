from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / ".github/workflows/contract_drift_trusted_bootstrap.py"
WORKFLOW_PATH = ROOT / ".github/workflows/contract-drift-trusted-bootstrap.yml"
LAUNCHER_PATH = ROOT / ".github/workflows/contract_drift_trusted_launcher.py"
MANIFEST_PATH = ROOT / ".github/workflows/contract-drift-trusted-bootstrap-manifest.json"
# Sparse pack captured from the synaptent/aragora object database. It contains
# the five named commits, the tree objects on each asserted path, and only the
# blob bodies needed to execute the production bootstrap. Regeneration walks
# these exact commits/paths, hashes each object with `git cat-file`, and feeds
# the sorted object IDs to `git pack-objects --stdout`; the pack digest below
# and the content-addressed commit/tree/blob assertions authenticate the result.
REAL_NEXT_EVENT_PACK = ROOT / "tests/fixtures/contract_drift_trusted_bootstrap_real_next_event.pack"
REAL_NEXT_EVENT_PACK_SHA256 = "2e5436cd6d0fbbb692cd4a1fd289ae7e8d80b6594f49cc612f09c493c2414bb8"
REAL_NEXT_EVENT_COMMITS = {
    "h3": "1722a6145c0c23a2c1c0d20be5ed1329bb01d666",
    "repin_merge": "5080b125d3c9595efdca020db5e60266e01ac9c5",
    "h4": "f50902a19bdc6cce7049da87212dc27759f727a0",
    "absorption": "967b1c82a285affbd191b57bdaf08512d6e6e3f7",
    "final_merge": "d3e45fafe6dd04508882935c813f6896abc859d7",
}
REAL_NEXT_EVENT_TREES = {
    "h3": "5968bb1e02018a83b9da36b07d7dd33b6464c8bb",
    "repin_merge": "0764416df6fc7f2144b4194e577d69a542612fe7",
    "h4": "5968bb1e02018a83b9da36b07d7dd33b6464c8bb",
    "absorption": "c9da37c67d9b905d995feb4d773554f430074262",
    "final_merge": "c9da37c67d9b905d995feb4d773554f430074262",
}
REAL_NEXT_EVENT_PARENTS = {
    "h3": ("d4ab26e4b30b7f65956b4cdd9d738837b78ca4a3",),
    "repin_merge": ("e98e641b50ea89c46270454c6649bebd8059deda",),
    "h4": (REAL_NEXT_EVENT_COMMITS["h3"],),
    "absorption": (
        REAL_NEXT_EVENT_COMMITS["h4"],
        REAL_NEXT_EVENT_COMMITS["repin_merge"],
    ),
    "final_merge": (REAL_NEXT_EVENT_COMMITS["repin_merge"],),
}
REAL_NEXT_EVENT_TRUSTED_BLOBS = {
    ".github/workflows/contract-drift-trusted-bootstrap.yml": (
        "ca2b4e487c94805480b6654fb70f9423bf11b6bd",
        "1201a6df450583f9e35c8fe5d92907fa3d4f68e3",
    ),
    ".github/workflows/contract_drift_trusted_bootstrap.py": (
        "4a84a2d843f9d853f0a72e17609a0a5fe16a10a0",
        "f2596d975960e1ce18a0d3a988bc40eb16fda967",
    ),
    ".github/workflows/contract_drift_trusted_launcher.py": (
        "d4c3e0abf6821ecd45b8661b75add43e4dd0ef5b",
        "d4c3e0abf6821ecd45b8661b75add43e4dd0ef5b",
    ),
    ".github/workflows/contract-drift-trusted-bootstrap-manifest.json": (
        "cb13440ca5d98a885c9e3241f63f046faab6b8d6",
        "90f5a63ed23cbcd4a775625aa8568c10392d28b8",
    ),
}
REAL_NEXT_EVENT_OWNED_BLOBS = {
    ".github/workflows/contract-drift-governance.yml": ("59052ae3f3181bed86de7a00d835746993b22c96"),
    "scripts/baselines/contract_drift_inventory.json": ("fe67eb452614f69a2aea55f0efe6ed6814d57dfa"),
    "scripts/check_contract_drift_ratchet.py": ("2a3a1f7767869c8a3c57a811a82bb5aba9f1119e"),
    "scripts/generate_contract_drift_inventory.py": ("f446cdd18f5b60bf377bbc7a4f1fd8df8073c53d"),
    "tests/scripts/test_check_contract_drift_ratchet.py": (
        "345b745cd3e2ef37576868e424bff15c3336f638"
    ),
    "tests/scripts/test_contract_drift_workflow.py": ("672e357c9566056d426bf501b10e4eb6d9635f0e"),
}
SPEC = importlib.util.spec_from_file_location("contract_drift_trusted_bootstrap", MODULE_PATH)
assert SPEC and SPEC.loader
bootstrap = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = bootstrap
SPEC.loader.exec_module(bootstrap)


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


def _write(repo: Path, relative: str, data: bytes | str) -> None:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else data.encode())


def _canonical(value: Any) -> bytes:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return (rendered + "\n").encode()


def _build_fixture(
    tmp_path: Path,
    mutation: str = "",
    *,
    checker_source: str | None = None,
    inventory_source: str = "VALUE = 1\n",
) -> SimpleNamespace:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Bootstrap Test")
    _write(repo, bootstrap.BASELINE_PATH, _canonical({"records": [], "schema": "test"}))
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "genesis")
    genesis = _git(repo, "rev-parse", "HEAD")

    _git(repo, "checkout", "-qb", "trusted-base")
    _write(repo, bootstrap.BOOTSTRAP_PATH, MODULE_PATH.read_bytes())
    _write(repo, bootstrap.WORKFLOW_PATH, WORKFLOW_PATH.read_bytes())
    _write(repo, bootstrap.LAUNCHER_PATH, LAUNCHER_PATH.read_bytes())
    _write(repo, bootstrap.MANIFEST_PATH, MANIFEST_PATH.read_bytes())
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "add base-owned bootstrap")
    base = _git(repo, "rev-parse", "HEAD")

    _git(repo, "checkout", "-qb", "candidate", base)
    if checker_source is not None:
        checker = checker_source
    elif mutation == "analyzer-rejected":
        checker = (
            "import json,os,sys\n"
            "print(json.dumps({'comparison':"
            "os.environ['CDG_FIRST_TRANSITION_COMPARISON_SHA256'],'status':'rejected'}))\n"
            "sys.exit(1)\n"
        )
    elif mutation == "analyzer-garbage":
        checker = "print('not-json')\n"
    else:
        checker = (
            "import json,os\n"
            "print(json.dumps({'authority_root':os.environ['CDG_AUTHORITY_ROOT'],"
            "'comparison':os.environ['CDG_FIRST_TRANSITION_COMPARISON_SHA256'],"
            "'launcher':os.environ['CDG_EXECUTED_LAUNCHER_SHA256'],'status':'pass'}))\n"
        )
    _write(repo, bootstrap.ANALYZER_FILES[0], checker)
    _write(repo, bootstrap.ANALYZER_FILES[1], inventory_source)
    _write(repo, bootstrap.ANALYZER_FILES[2], _canonical({"schema": "test-program"}))
    original_digests = tuple(
        hashlib.sha256((repo / path).read_bytes()).hexdigest() for path in bootstrap.ANALYZER_FILES
    )

    artifacts = {
        "original_cohort": {"records": [{"id": "cohort"}], "schema": "test-cohort"},
        "sdk_provenance": {"records": [{"id": "provenance"}], "schema": "test-provenance"},
    }
    bindings = tuple(
        bootstrap.ArtifactBinding(
            path=f"library/{artifact['schema']}.json",
            schema=artifact["schema"],
            sha256=hashlib.sha256(_canonical(artifact)).hexdigest(),
            byte_length=len(_canonical(artifact)),
        )
        for artifact in artifacts.values()
    )
    files = [
        {"path": path, "sha256": digest}
        for path, digest in zip(bootstrap.ANALYZER_FILES, original_digests, strict=True)
    ]
    authority: dict[str, Any] = {
        "active_inventory": [],
        "active_inventory_sha256": hashlib.sha256(b"[]").hexdigest(),
        "analyzer_bundle": {
            "dependencies": [],
            "files": files,
            "interpreter_flags": list(bootstrap.ANALYZER_FLAGS),
            "launcher_sha256": hashlib.sha256(bootstrap.HERMETIC_LAUNCHER).hexdigest(),
            "schema": "contract-drift-analyzer-bundle-v1",
        },
        "canonical_artifact_bindings": [
            {
                "byte_length": item.byte_length,
                "path": item.path,
                "sha256": item.sha256,
            }
            for item in bindings
        ],
        "canonical_artifacts": artifacts,
        "categories": list(bootstrap.ACCEPTED_CATEGORIES),
        "manifest_sha256": "1" * 64,
        "publication": {
            "authority": "future-immutable-github-release-capsule",
            "status": "pending-merge",
        },
        "schema": "contract-drift-accepted-authority-v1",
        "transition": {
            "accepted_transition_head": "bound-by-release-capsule",
            "base_sha": genesis,
            "historical_nonconforming": bootstrap.EXPECTED_HISTORICAL_NONCONFORMING,
            "kind": "authority_transition",
        },
    }
    authority["manifest_sha256"] = hashlib.sha256(
        json.dumps(
            {key: value for key, value in authority.items() if key != "manifest_sha256"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()

    if mutation == "workflow":
        _write(repo, bootstrap.WORKFLOW_PATH, "ref: refs/pull/1/merge\n")
    elif mutation == "trusted-launcher":
        _write(repo, bootstrap.BOOTSTRAP_PATH, "raise SystemExit('candidate')\n")
    elif mutation == "trusted-exec-launcher":
        _write(repo, bootstrap.LAUNCHER_PATH, "raise SystemExit('candidate launcher')\n")
    elif mutation == "delete-trusted-launcher":
        _git(repo, "rm", "-q", bootstrap.LAUNCHER_PATH)
    elif mutation == "delete-manifest":
        _git(repo, "rm", "-q", bootstrap.MANIFEST_PATH)
    elif mutation == "checker":
        _write(repo, bootstrap.ANALYZER_FILES[0], "raise SystemExit('substituted')\n")
        authority["analyzer_bundle"]["files"][0]["sha256"] = hashlib.sha256(
            (repo / bootstrap.ANALYZER_FILES[0]).read_bytes()
        ).hexdigest()
    elif mutation == "empty-bundle":
        authority["analyzer_bundle"]["files"] = []
    elif mutation == "partial-bundle":
        authority["analyzer_bundle"]["files"] = files[:2]
    elif mutation == "accepted-launcher":
        authority["analyzer_bundle"]["launcher_sha256"] = "2" * 64
    elif mutation == "wrong-digest":
        authority["analyzer_bundle"]["files"][0]["sha256"] = "3" * 64
    elif mutation == "wrong-transition-base":
        authority["transition"]["base_sha"] = base
    elif mutation == "authority-manifest":
        authority["manifest_sha256"] = "4" * 64
    elif mutation == "active-inventory-digest":
        authority["active_inventory_sha256"] = "5" * 64
    elif mutation == "historical-nonconforming":
        authority["transition"]["historical_nonconforming"] = []
    elif mutation == "self-signal":
        authority["comparison_signal"] = {
            "candidate_head_sha": "candidate-controlled",
            "status": "accepted",
        }
    if mutation not in {"authority-manifest", "self-signal"}:
        authority["manifest_sha256"] = hashlib.sha256(
            json.dumps(
                {key: value for key, value in authority.items() if key != "manifest_sha256"},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()

    baseline = {"accepted_authority": authority, "records": [], "schema": "test"}
    _write(repo, bootstrap.BASELINE_PATH, _canonical(baseline))
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", f"candidate {mutation or 'valid'}")
    head = _git(repo, "rev-parse", "HEAD")
    event_data = {
        "pull_request": {
            "base": {
                "ref": "develop" if mutation == "wrong-base-ref" else "main",
                "repo": {"full_name": "synaptent/aragora"},
                "sha": base,
            },
            "head": {
                "repo": {
                    "full_name": (
                        "attacker/aragora" if mutation == "fork-head" else "synaptent/aragora"
                    )
                },
                "sha": base if mutation == "wrong-ref" else head,
            },
        },
        "repository": {"full_name": "synaptent/aragora"},
    }
    event = tmp_path / "event.json"
    event.write_bytes(_canonical(event_data))
    policy = bootstrap.BootstrapPolicy(
        analyzer_digests=original_digests,
        analyzer_source_sha=head,
        artifact_bindings=bindings,
        expected_head_sha=head,
        transition_base_sha=genesis,
    )
    return SimpleNamespace(repo=repo, base=base, head=head, event=event, policy=policy)


def _run(fixture: SimpleNamespace, tmp_path: Path) -> dict[str, Any]:
    return bootstrap.run_bootstrap(
        repo=fixture.repo,
        event_path=fixture.event,
        base_sha=fixture.base,
        head_sha=fixture.head,
        output_dir=tmp_path / "output",
        policy=fixture.policy,
        executed_launcher=MODULE_PATH,
        run_provenance=bootstrap.RunProvenance(
            event_name="pull_request_target",
            repository="synaptent/aragora",
            run_attempt=1,
            run_id=12345,
            workflow_ref=(
                "synaptent/aragora/.github/workflows/"
                "contract-drift-trusted-bootstrap.yml@refs/heads/main"
            ),
        ),
    )


ISOLATION_CHECKER = (
    "import json,os,sys\n"
    "from scripts import generate_contract_drift_inventory as inventory\n"
    "try:\n"
    " from scripts import namespace_payload\n"
    "except ImportError:\n"
    " namespace_payload = None\n"
    "try:\n"
    " import pth_payload\n"
    "except ImportError:\n"
    " pth_payload = None\n"
    "print(json.dumps({"
    "'authority_root':os.environ['CDG_AUTHORITY_ROOT'],"
    "'checker_file':__file__,"
    "'cwd':os.getcwd(),"
    "'cwd_entries':sorted(os.listdir()),"
    "'inventory_file':inventory.__file__,"
    "'inventory_marker':inventory.AUTHORITY_MARKER,"
    "'inventory_version':inventory.__version__,"
    "'launcher':os.environ['CDG_EXECUTED_LAUNCHER_SHA256'],"
    "'namespace_payload':getattr(namespace_payload,'AUTHORITY_MARKER',None),"
    "'pth_payload':getattr(pth_payload,'AUTHORITY_MARKER',None),"
    "'status':'pass',"
    "'sys_path':sys.path"
    "}))\n"
)
BASE_INVENTORY = "__version__ = '1.0.0'\nAUTHORITY_MARKER = 'base-owned-bundle'\n"


def _build_isolation_fixture(tmp_path: Path) -> SimpleNamespace:
    return _build_fixture(
        tmp_path,
        checker_source=ISOLATION_CHECKER,
        inventory_source=BASE_INVENTORY,
    )


def _user_site(user_base: Path, *, interpreter: str | Path | None = None) -> Path:
    import os

    env = os.environ.copy()
    env["PYTHONUSERBASE"] = str(user_base)
    proc = subprocess.run(
        [
            str(interpreter or sys.executable),
            "-S",
            "-c",
            "import site; print(site.getusersitepackages())",
        ],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    result = Path(proc.stdout.strip())
    assert result.is_absolute()
    return result


def _real_next_event_repo(tmp_path: Path) -> Path:
    pack = REAL_NEXT_EVENT_PACK.read_bytes()
    assert hashlib.sha256(pack).hexdigest() == REAL_NEXT_EVENT_PACK_SHA256
    repo = tmp_path / "real-next-event"
    repo.mkdir()
    _git(repo, "init", "-q")
    subprocess.run(
        ["git", "-C", str(repo), "index-pack", "--stdin"],
        input=pack,
        check=True,
        capture_output=True,
    )
    return repo


def _commit_identity(repo: Path, sha: str) -> tuple[str, tuple[str, ...]]:
    raw = _git(repo, "cat-file", "commit", sha)
    headers = raw.split("\n\n", 1)[0].splitlines()
    tree = next(line.removeprefix("tree ") for line in headers if line.startswith("tree "))
    parents = tuple(line.removeprefix("parent ") for line in headers if line.startswith("parent "))
    return tree, parents


def _blob_oids(repo: Path, sha: str, paths: tuple[str, ...]) -> dict[str, str]:
    proc = subprocess.run(
        ["git", "-C", str(repo), "ls-tree", "-z", sha, "--", *paths],
        check=True,
        capture_output=True,
    )
    result: dict[str, str] = {}
    for raw in proc.stdout.rstrip(b"\0").split(b"\0"):
        metadata, path = raw.split(b"\t", 1)
        _mode, object_type, oid = metadata.split(b" ")
        assert object_type == b"blob"
        result[path.decode()] = oid.decode()
    assert set(result) == set(paths)
    return result


def _real_event(tmp_path: Path, base_sha: str, head_sha: str, label: str) -> Path:
    event = tmp_path / f"{label}.json"
    event.write_bytes(
        _canonical(
            {
                "pull_request": {
                    "base": {
                        "ref": "main",
                        "repo": {"full_name": "synaptent/aragora"},
                        "sha": base_sha,
                    },
                    "head": {
                        "repo": {"full_name": "synaptent/aragora"},
                        "sha": head_sha,
                    },
                },
                "repository": {"full_name": "synaptent/aragora"},
            }
        )
    )
    return event


def _run_real_next_event(
    repo: Path,
    tmp_path: Path,
    *,
    head_sha: str,
    label: str,
) -> dict[str, Any]:
    base_sha = REAL_NEXT_EVENT_COMMITS["repin_merge"]
    return bootstrap.run_bootstrap(
        repo=repo,
        event_path=_real_event(tmp_path, base_sha, head_sha, label),
        base_sha=base_sha,
        head_sha=head_sha,
        output_dir=tmp_path / f"{label}-output",
        policy=bootstrap.BootstrapPolicy(expected_head_sha=head_sha),
        executed_launcher=MODULE_PATH,
        run_provenance=bootstrap.RunProvenance(
            event_name="pull_request_target",
            repository="synaptent/aragora",
            run_attempt=1,
            run_id=12345,
            workflow_ref=(
                "synaptent/aragora/.github/workflows/"
                "contract-drift-trusted-bootstrap.yml@refs/heads/main"
            ),
        ),
    )


def _run_launcher_without_isolation(
    fixture: SimpleNamespace,
    tmp_path: Path,
    user_base: Path,
) -> dict[str, Any]:
    bundle_root = tmp_path / "unsafe-control-bundle"
    bootstrap._materialize_bundle(fixture.repo, fixture.head, bundle_root)
    empty_cwd = tmp_path / "unsafe-control-cwd"
    empty_cwd.mkdir()
    env = {
        "CDG_AUTHORITY_ROOT": str(bundle_root),
        "CDG_EXECUTED_LAUNCHER_SHA256": hashlib.sha256(LAUNCHER_PATH.read_bytes()).hexdigest(),
        "CDG_FIRST_TRANSITION_COMPARISON_SHA256": "a" * 64,
        "CDG_TRUSTED_BUNDLE": "unsafe-control",
        "HOME": str(tmp_path / "unsafe-home"),
        "PATH": "/usr/bin:/bin",
        "PYTHONUSERBASE": str(user_base),
    }
    proc = subprocess.run(
        [
            sys.executable,
            "-B",
            str(LAUNCHER_PATH),
            str(bundle_root),
            str(bundle_root / bootstrap.ANALYZER_FILES[0]),
        ],
        cwd=empty_cwd,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(proc.stdout)
    assert isinstance(result, dict)
    return result


def _assert_production_isolation(
    result: dict[str, Any],
    *hostile_roots: Path,
) -> None:
    assert result["status"] == "pass"
    analysis = result["analysis"]
    authority_root = Path(analysis["authority_root"]).resolve()
    assert analysis["inventory_marker"] == "base-owned-bundle"
    assert analysis["inventory_version"] == "1.0.0"
    assert analysis["namespace_payload"] is None
    assert analysis["pth_payload"] is None
    assert analysis["launcher"] == hashlib.sha256(LAUNCHER_PATH.read_bytes()).hexdigest()
    assert bootstrap.ANALYZER_FLAGS == ("-I", "-S", "-B")
    assert Path(analysis["cwd"]).resolve() == authority_root
    assert analysis["cwd_entries"] == [".github", "scripts"]
    checker_path = Path(analysis["checker_file"])
    if not checker_path.is_absolute():
        checker_path = Path(analysis["cwd"]) / checker_path
    assert checker_path.resolve() == authority_root / bootstrap.ANALYZER_FILES[0]
    assert Path(analysis["inventory_file"]).resolve() == (
        authority_root / bootstrap.ANALYZER_FILES[1]
    )

    sys_path = analysis["sys_path"]
    assert "" not in sys_path
    resolved_sys_path = [Path(entry).resolve() for entry in sys_path]
    assert resolved_sys_path[0] == authority_root
    assert resolved_sys_path.count(authority_root) == 1
    stdlib_roots = (Path(sys.base_prefix).resolve(), Path(sys.exec_prefix).resolve())
    for entry in resolved_sys_path[1:]:
        assert any(entry.is_relative_to(root) for root in stdlib_roots)
    for hostile_root in hostile_roots:
        resolved_hostile_root = hostile_root.resolve()
        assert all(not entry.is_relative_to(resolved_hostile_root) for entry in resolved_sys_path)


def test_same_version_global_package_shadow_isolated(tmp_path, monkeypatch):
    fixture = _build_isolation_fixture(tmp_path)
    user_base = tmp_path / "hostile-global"
    user_site = _user_site(user_base)
    _write(user_site, "scripts/__init__.py", "__version__ = '1.0.0'\n")
    _write(
        user_site,
        "scripts/generate_contract_drift_inventory.py",
        "__version__ = '1.0.0'\nAUTHORITY_MARKER = 'hostile-global-shadow'\n",
    )

    control = _run_launcher_without_isolation(fixture, tmp_path, user_base)
    assert control["inventory_version"] == "1.0.0"
    assert control["inventory_marker"] == "hostile-global-shadow"

    monkeypatch.setenv("PYTHONUSERBASE", str(user_base))
    result = _run(fixture, tmp_path)
    _assert_production_isolation(result, user_base)


def test_namespace_package_contribution_isolated(tmp_path, monkeypatch):
    fixture = _build_isolation_fixture(tmp_path)
    user_base = tmp_path / "hostile-namespace"
    user_site = _user_site(user_base)
    _write(
        user_site,
        "scripts/namespace_payload.py",
        "AUTHORITY_MARKER = 'hostile-namespace-contribution'\n",
    )

    control = _run_launcher_without_isolation(fixture, tmp_path, user_base)
    assert control["namespace_payload"] == "hostile-namespace-contribution"

    monkeypatch.setenv("PYTHONUSERBASE", str(user_base))
    result = _run(fixture, tmp_path)
    _assert_production_isolation(result, user_base)


def test_pth_injector_isolated(tmp_path, monkeypatch):
    fixture = _build_isolation_fixture(tmp_path)
    user_base = tmp_path / "hostile-pth"
    user_site = _user_site(user_base)
    injected = tmp_path / "pth-injected"
    marker = tmp_path / "pth-executed"
    _write(
        injected,
        "pth_payload.py",
        "AUTHORITY_MARKER = 'hostile-pth-injector'\n",
    )
    _write(
        user_site,
        "hostile-bootstrap.pth",
        f"import sys;sys.path.insert(0,{str(injected)!r});"
        f"open({str(marker)!r},'w').write('executed')\n",
    )

    control = _run_launcher_without_isolation(fixture, tmp_path, user_base)
    assert control["pth_payload"] == "hostile-pth-injector"
    assert marker.read_text() == "executed"
    marker.unlink()

    monkeypatch.setenv("PYTHONUSERBASE", str(user_base))
    result = _run(fixture, tmp_path)
    assert not marker.exists()
    _assert_production_isolation(result, user_base, injected)


def test_user_site_uses_selected_interpreter_site_module(tmp_path, monkeypatch):
    user_base = tmp_path / "user-base"
    reported = tmp_path / "framework-layout" / "site-packages"
    interpreter = tmp_path / "selected-python.exe"
    probe = "import site; print(site.getusersitepackages())"

    def _selected_python(command, **kwargs):
        assert command == [str(interpreter), "-S", "-c", probe]
        assert kwargs["env"]["PYTHONUSERBASE"] == str(user_base)
        return SimpleNamespace(stdout=f"{reported}\n")

    monkeypatch.setattr(subprocess, "run", _selected_python)

    assert _user_site(user_base, interpreter=interpreter) == reported


def test_real_next_event_fixture_binds_authentic_sequence_objects(tmp_path):
    repo = _real_next_event_repo(tmp_path)
    for label, sha in REAL_NEXT_EVENT_COMMITS.items():
        assert _git(repo, "rev-parse", "--verify", f"{sha}^{{commit}}") == sha
        assert _commit_identity(repo, sha) == (
            REAL_NEXT_EVENT_TREES[label],
            REAL_NEXT_EVENT_PARENTS[label],
        )

    all_paths = tuple(REAL_NEXT_EVENT_TRUSTED_BLOBS) + tuple(REAL_NEXT_EVENT_OWNED_BLOBS)
    blobs = {
        label: _blob_oids(
            repo,
            REAL_NEXT_EVENT_COMMITS[label],
            tuple(REAL_NEXT_EVENT_TRUSTED_BLOBS) if label == "repin_merge" else all_paths,
        )
        for label in REAL_NEXT_EVENT_COMMITS
    }
    for path, (pre_repin_blob, repinned_blob) in REAL_NEXT_EVENT_TRUSTED_BLOBS.items():
        assert blobs["h3"][path] == pre_repin_blob
        assert blobs["h4"][path] == pre_repin_blob
        for label in ("repin_merge", "absorption", "final_merge"):
            assert blobs[label][path] == repinned_blob
    assert {
        path
        for path, (pre_repin_blob, repinned_blob) in REAL_NEXT_EVENT_TRUSTED_BLOBS.items()
        if pre_repin_blob != repinned_blob
    } == {
        ".github/workflows/contract-drift-trusted-bootstrap.yml",
        ".github/workflows/contract_drift_trusted_bootstrap.py",
        ".github/workflows/contract-drift-trusted-bootstrap-manifest.json",
    }

    for path, expected_blob in REAL_NEXT_EVENT_OWNED_BLOBS.items():
        for label in ("h3", "h4", "absorption", "final_merge"):
            assert blobs[label][path] == expected_blob


def test_authentic_h4_rejects_then_absorption_admits_next_event(tmp_path):
    repo = _real_next_event_repo(tmp_path)
    with pytest.raises(
        bootstrap.BootstrapError,
        match=(
            "proposed tree overrides trusted surface: "
            r"\.github/workflows/contract-drift-trusted-bootstrap\.yml"
        ),
    ):
        _run_real_next_event(
            repo,
            tmp_path,
            head_sha=REAL_NEXT_EVENT_COMMITS["h4"],
            label="pre-absorption-h4",
        )

    result = _run_real_next_event(
        repo,
        tmp_path,
        head_sha=REAL_NEXT_EVENT_COMMITS["absorption"],
        label="post-absorption",
    )
    assert result["status"] == "pass"
    assert result["analysis"]["passing"] is True
    assert result["analysis"]["error_code"] == "authority_transition_required"
    assert result["trusted_base_sha"] == REAL_NEXT_EVENT_COMMITS["repin_merge"]
    assert result["candidate_head_sha"] == REAL_NEXT_EVENT_COMMITS["absorption"]


def test_workflow_uses_base_owned_python_without_merge_checkout():
    workflow = WORKFLOW_PATH.read_text()
    assert "pull_request_target:" in workflow
    assert 'python-version: "3.11"' in workflow
    assert "actions/checkout" not in workflow
    assert '"$BASE_SHA" "$HEAD_SHA" "$ANALYZER_SOURCE_SHA"' in workflow
    assert f"ANALYZER_SOURCE_SHA: {bootstrap.ANALYZER_SOURCE_SHA}" in workflow
    assert 'for path in "$BOOTSTRAP_PATH" "$LAUNCHER_PATH" "$MANIFEST_PATH"' in workflow
    assert 'show "$BASE_SHA:$path"' in workflow
    assert "python -I -S -B" in workflow
    assert "github.event.pull_request.merge_commit_sha" not in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "checks: write" not in workflow
    assert "statuses: write" not in workflow
    for path in bootstrap.TRUSTED_SURFACE_FILES + (bootstrap.MANIFEST_PATH,):
        assert f'      - "{path}"' in workflow


def test_workflow_emits_run_bound_comparison_and_admission_artifact():
    workflow = WORKFLOW_PATH.read_text()
    assert "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02" in workflow
    assert "contract-drift-trusted-bootstrap-${{ github.event.pull_request.head.sha }}" in workflow
    assert 'if-no-files-found: "error"' in workflow
    assert "GITHUB_RUN_ID" in workflow
    assert "GITHUB_RUN_ATTEMPT" in workflow
    assert "GITHUB_WORKFLOW_REF" in workflow


def test_base_manifest_closes_bootstrap_and_launcher_bytes():
    manifest = json.loads(MANIFEST_PATH.read_text())
    assert manifest["schema"] == "contract-drift-trusted-bootstrap-manifest-v1"
    bindings = {item["path"]: item for item in manifest["files"]}
    for path in (WORKFLOW_PATH, MODULE_PATH, LAUNCHER_PATH):
        relative = path.relative_to(ROOT).as_posix()
        raw = path.read_bytes()
        assert bindings[relative] == {
            "byte_length": len(raw),
            "path": relative,
            "sha256": hashlib.sha256(raw).hexdigest(),
        }


def test_intended_exact_pair_bootstrap_executes_after_comparison(tmp_path):
    fixture = _build_fixture(tmp_path)
    result = _run(fixture, tmp_path)
    assert result["status"] == "pass"
    assert result["candidate_head_sha"] == fixture.head
    assert result["analysis"]["status"] == "pass"
    assert result["analysis"]["comparison"] == result["comparison_signal_sha256"]
    assert result["analysis"]["launcher"] == hashlib.sha256(LAUNCHER_PATH.read_bytes()).hexdigest()
    assert Path(result["analysis"]["authority_root"]).name.startswith("cdg-bootstrap-")
    signal = json.loads((tmp_path / "output/first-transition-comparison.json").read_text())
    assert signal["payload"]["workflow_run"] == {
        "event_name": "pull_request_target",
        "repository": "synaptent/aragora",
        "run_attempt": 1,
        "run_id": 12345,
        "workflow_ref": (
            "synaptent/aragora/.github/workflows/"
            "contract-drift-trusted-bootstrap.yml@refs/heads/main"
        ),
    }
    analysis_path = tmp_path / "output/trusted-bootstrap-analysis.json"
    receipt = json.loads((tmp_path / "output/trusted-bootstrap-admission.json").read_text())
    assert receipt["payload"]["analysis_path"] == analysis_path.name
    assert (
        receipt["payload"]["analysis_sha256"]
        == hashlib.sha256(analysis_path.read_bytes()).hexdigest()
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "workflow",
        "trusted-launcher",
        "trusted-exec-launcher",
        "delete-trusted-launcher",
        "delete-manifest",
    ],
)
def test_candidate_cannot_replace_base_owned_bootstrap_surface(tmp_path, mutation):
    fixture = _build_fixture(tmp_path, mutation)
    with pytest.raises(bootstrap.BootstrapError, match="proposed tree|trusted surface"):
        _run(fixture, tmp_path)


def test_head_checker_substitution_fails_closed(tmp_path):
    fixture = _build_fixture(tmp_path, "checker")
    with pytest.raises(bootstrap.BootstrapError, match="analyzer digest"):
        _run(fixture, tmp_path)


@pytest.mark.parametrize("mutation", ["empty-bundle", "partial-bundle"])
def test_non_exact_analyzer_bundle_fails_closed(tmp_path, mutation):
    fixture = _build_fixture(tmp_path, mutation)
    with pytest.raises(bootstrap.BootstrapError, match="file set"):
        _run(fixture, tmp_path)


def test_accepted_launcher_substitution_fails_closed(tmp_path):
    fixture = _build_fixture(tmp_path, "accepted-launcher")
    with pytest.raises(bootstrap.BootstrapError, match="launcher"):
        _run(fixture, tmp_path)


def test_base_owned_analyzer_source_substitution_fails_closed(tmp_path):
    fixture = _build_fixture(tmp_path)
    _git(fixture.repo, "checkout", "-qb", "substituted-source", fixture.base)
    for path in bootstrap.ANALYZER_FILES:
        _write(fixture.repo, path, bootstrap._git_blob(fixture.repo, fixture.head, path))
    _write(fixture.repo, bootstrap.ANALYZER_FILES[0], "raise SystemExit('source substitute')\n")
    _git(fixture.repo, "add", ".")
    _git(fixture.repo, "commit", "-qm", "substituted analyzer source")
    source_sha = _git(fixture.repo, "rev-parse", "HEAD")
    fixture.policy = bootstrap.BootstrapPolicy(
        analyzer_digests=fixture.policy.analyzer_digests,
        analyzer_source_sha=source_sha,
        artifact_bindings=fixture.policy.artifact_bindings,
        expected_head_sha=fixture.head,
        transition_base_sha=fixture.policy.transition_base_sha,
    )
    with pytest.raises(bootstrap.BootstrapError, match="analyzer digest"):
        _run(fixture, tmp_path)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("wrong-ref", "event base/head"),
        ("wrong-base-ref", "event base/head"),
        ("fork-head", "event base/head"),
        ("wrong-digest", "analyzer digest"),
        ("wrong-transition-base", "transition base"),
        ("authority-manifest", "manifest digest"),
        ("active-inventory-digest", "active inventory digest"),
        ("historical-nonconforming", "self-authorization"),
    ],
)
def test_wrong_ref_or_digest_fails_closed(tmp_path, mutation, message):
    fixture = _build_fixture(tmp_path, mutation)
    with pytest.raises(bootstrap.BootstrapError, match=message):
        _run(fixture, tmp_path)


def test_missing_comparison_evidence_blocks_analyzer(tmp_path, monkeypatch):
    fixture = _build_fixture(tmp_path)
    missing = tmp_path / "missing-comparison.json"
    monkeypatch.setattr(bootstrap, "_write_comparison_signal", lambda *args, **kwargs: missing)
    with pytest.raises(bootstrap.BootstrapError, match="comparison signal"):
        _run(fixture, tmp_path)


def test_wrong_comparison_run_provenance_blocks_analyzer(tmp_path, monkeypatch):
    fixture = _build_fixture(tmp_path)
    write_signal = bootstrap._write_comparison_signal

    def _write_wrong_run(*args, **kwargs):
        path = write_signal(*args, **kwargs)
        envelope = json.loads(path.read_text())
        envelope["payload"]["workflow_run"]["run_id"] = 54321
        envelope["signal_sha256"] = hashlib.sha256(_canonical(envelope["payload"])).hexdigest()
        path.write_bytes(_canonical(envelope))
        return path

    monkeypatch.setattr(bootstrap, "_write_comparison_signal", _write_wrong_run)
    with pytest.raises(bootstrap.BootstrapError, match="comparison signal"):
        _run(fixture, tmp_path)


@pytest.mark.parametrize(
    ("event_name", "workflow_ref"),
    [
        (
            "pull_request",
            "synaptent/aragora/.github/workflows/"
            "contract-drift-trusted-bootstrap.yml@refs/heads/main",
        ),
        (
            "pull_request_target",
            "synaptent/aragora/.github/workflows/"
            "contract-drift-trusted-bootstrap.yml@refs/pull/1/merge",
        ),
    ],
)
def test_non_target_run_provenance_fails_closed(tmp_path, event_name, workflow_ref):
    fixture = _build_fixture(tmp_path)
    with pytest.raises(bootstrap.BootstrapError, match="workflow run provenance"):
        bootstrap.run_bootstrap(
            repo=fixture.repo,
            event_path=fixture.event,
            base_sha=fixture.base,
            head_sha=fixture.head,
            output_dir=tmp_path / "output",
            policy=fixture.policy,
            executed_launcher=MODULE_PATH,
            run_provenance=bootstrap.RunProvenance(
                event_name=event_name,
                repository="synaptent/aragora",
                run_attempt=1,
                run_id=12345,
                workflow_ref=workflow_ref,
            ),
        )


def test_analyzer_rejection_writes_nonpassing_admission(tmp_path):
    fixture = _build_fixture(tmp_path, "analyzer-rejected")
    result = _run(fixture, tmp_path)
    assert result["status"] == "analyzer-rejected"
    receipt = json.loads((tmp_path / "output/trusted-bootstrap-admission.json").read_text())
    assert receipt["payload"]["status"] == "analyzer-rejected"


def test_analyzer_invalid_output_fails_closed(tmp_path):
    fixture = _build_fixture(tmp_path, "analyzer-garbage")
    with pytest.raises(bootstrap.BootstrapError, match="did not emit JSON"):
        _run(fixture, tmp_path)


def test_existing_base_authority_writes_not_first_receipt(tmp_path):
    fixture = _build_fixture(tmp_path)
    _git(fixture.repo, "checkout", "-qb", "after-authority", fixture.head)
    _write(fixture.repo, "unrelated.txt", "next candidate\n")
    _git(fixture.repo, "add", ".")
    _git(fixture.repo, "commit", "-qm", "candidate after accepted authority")
    next_head = _git(fixture.repo, "rev-parse", "HEAD")
    event_data = json.loads(fixture.event.read_text())
    event_data["pull_request"]["base"]["sha"] = fixture.head
    event_data["pull_request"]["head"]["sha"] = next_head
    fixture.event.write_bytes(_canonical(event_data))
    fixture.base = fixture.head
    fixture.head = next_head
    fixture.policy = bootstrap.BootstrapPolicy(
        analyzer_digests=fixture.policy.analyzer_digests,
        analyzer_source_sha=fixture.policy.analyzer_source_sha,
        artifact_bindings=fixture.policy.artifact_bindings,
        expected_head_sha=next_head,
        transition_base_sha=fixture.policy.transition_base_sha,
    )
    result = _run(fixture, tmp_path)
    assert result["status"] == "not-first-transition"
    receipt = json.loads((tmp_path / "output/trusted-bootstrap-admission.json").read_text())
    assert receipt["payload"]["status"] == "not-first-transition"


def test_no_authority_candidate_writes_neutral_receipt(tmp_path):
    fixture = _build_fixture(tmp_path)
    _git(fixture.repo, "checkout", "-qb", "neutral-candidate", fixture.base)
    _write(fixture.repo, "unrelated.txt", "routine maintenance\n")
    _git(fixture.repo, "add", ".")
    _git(fixture.repo, "commit", "-qm", "routine candidate")
    neutral_head = _git(fixture.repo, "rev-parse", "HEAD")
    event_data = json.loads(fixture.event.read_text())
    event_data["pull_request"]["head"]["sha"] = neutral_head
    fixture.event.write_bytes(_canonical(event_data))
    fixture.head = neutral_head
    fixture.policy = bootstrap.BootstrapPolicy(
        analyzer_digests=fixture.policy.analyzer_digests,
        analyzer_source_sha=fixture.policy.analyzer_source_sha,
        artifact_bindings=fixture.policy.artifact_bindings,
        expected_head_sha=neutral_head,
        transition_base_sha=fixture.policy.transition_base_sha,
    )
    result = _run(fixture, tmp_path)
    assert result["status"] == "no-authority-proposed"
    receipt = json.loads((tmp_path / "output/trusted-bootstrap-admission.json").read_text())
    assert receipt["payload"]["status"] == "no-authority-proposed"


def test_self_authorized_first_transition_fails_closed(tmp_path):
    fixture = _build_fixture(tmp_path, "self-signal")
    with pytest.raises(bootstrap.BootstrapError, match="authority fields"):
        _run(fixture, tmp_path)
