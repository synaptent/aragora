import json
import re
from fnmatch import fnmatchcase
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
LIVE_DIR = REPO_ROOT / "aragora" / "live"
NODE_RUNTIME_FILES = (
    LIVE_DIR / "Dockerfile",
    REPO_ROOT / "deploy" / "Dockerfile.frontend",
    REPO_ROOT / "docker-compose.dev.yml",
)
FRONTEND_DOCKERFILES = (
    LIVE_DIR / "Dockerfile",
    REPO_ROOT / "deploy" / "Dockerfile.frontend",
)
FRONTEND_COMPOSE_BUILDS = (
    (REPO_ROOT / "docker-compose.quickstart.yml", ".", "aragora/live/Dockerfile"),
    (
        REPO_ROOT / "deploy" / "self-hosted" / "docker-compose.yml",
        "../..",
        "aragora/live/Dockerfile",
    ),
)
SUPABASE_PACKAGES = (
    "node_modules/@supabase/auth-js",
    "node_modules/@supabase/functions-js",
    "node_modules/@supabase/postgrest-js",
    "node_modules/@supabase/realtime-js",
    "node_modules/@supabase/storage-js",
    "node_modules/@supabase/supabase-js",
)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _node_engine_floor(engine: str) -> tuple[int, int, int]:
    match = re.search(r">=\s*(\d+)(?:\.(\d+))?(?:\.(\d+))?", engine)
    assert match, f"unsupported node engine expression: {engine!r}"
    return (
        int(match.group(1)),
        int(match.group(2) or 0),
        int(match.group(3) or 0),
    )


def _node_image_versions(path: Path) -> list[tuple[int, int, int]]:
    text = path.read_text(encoding="utf-8")
    return [
        (
            int(match.group(1)),
            int(match.group(2) or 0),
            int(match.group(3) or 0),
        )
        for match in re.finditer(
            r"^\s*(?:FROM|image:)\s+node:(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[.\-]|$)",
            text,
            re.MULTILINE,
        )
    ]


def _dockerfile_stage_copies(path: Path) -> dict[str, list[str]]:
    stages: dict[str, list[str]] = {}
    current_stage = ""

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue

        from_match = re.match(r"FROM\s+\S+(?:\s+AS\s+([A-Za-z0-9_-]+))?", line, re.IGNORECASE)
        if from_match:
            current_stage = from_match.group(1) or f"stage_{len(stages)}"
            stages[current_stage] = []
            continue

        if current_stage and line.startswith("COPY "):
            stages[current_stage].append(line)

    return stages


def _repo_root_dockerignore_patterns() -> list[str]:
    return [
        line.strip()
        for line in (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]


def _dockerignore_pattern_matches(pattern: str, relative_path: str) -> bool:
    pattern = pattern.replace("\\", "/")
    relative_path = relative_path.strip("/")
    anchored = pattern.startswith("/")
    directory_only = pattern.endswith("/")
    normalized_pattern = pattern.strip("/")
    path_parts = relative_path.split("/")

    if not normalized_pattern:
        return False

    if anchored:
        return (
            relative_path == normalized_pattern
            or (directory_only and relative_path.startswith(f"{normalized_pattern}/"))
            or (not directory_only and fnmatchcase(relative_path, normalized_pattern))
        )

    if "/" not in normalized_pattern:
        return any(fnmatchcase(part, normalized_pattern) for part in path_parts)

    return (
        relative_path == normalized_pattern
        or (directory_only and relative_path.startswith(f"{normalized_pattern}/"))
        or (not directory_only and fnmatchcase(relative_path, normalized_pattern))
    )


def _repo_root_dockerignore_excludes(relative_path: str) -> bool:
    excluded = False

    for pattern in _repo_root_dockerignore_patterns():
        negated = pattern.startswith("!")
        pattern_body = pattern[1:] if negated else pattern

        if _dockerignore_pattern_matches(pattern_body, relative_path):
            excluded = not negated

    return excluded


def test_live_supabase_version_is_exactly_pinned() -> None:
    package_json = _load_json(LIVE_DIR / "package.json")
    package_lock = _load_json(LIVE_DIR / "package-lock.json")

    spec = package_json["dependencies"]["@supabase/supabase-js"]
    locked = package_lock["packages"]["node_modules/@supabase/supabase-js"]["version"]

    assert re.fullmatch(r"\d+\.\d+\.\d+", spec), (
        "pin @supabase/supabase-js exactly so minor updates cannot silently raise "
        "the live Node runtime floor"
    )
    assert locked == spec


def test_live_npm_enforces_declared_node_engine() -> None:
    package_json = _load_json(LIVE_DIR / "package.json")
    package_lock = _load_json(LIVE_DIR / "package-lock.json")
    npmrc = (LIVE_DIR / ".npmrc").read_text(encoding="utf-8")

    assert "engine-strict=true" in npmrc.splitlines()
    assert package_lock["packages"][""]["engines"] == package_json["engines"]


def test_live_realtime_phoenix_dependency_is_locked() -> None:
    package_lock = _load_json(LIVE_DIR / "package-lock.json")
    packages = package_lock["packages"]
    realtime_dependencies = packages["node_modules/@supabase/realtime-js"]["dependencies"]
    phoenix_version = packages["node_modules/@supabase/phoenix"]["version"]

    assert realtime_dependencies["@supabase/phoenix"] == phoenix_version


def test_frontend_dockerfiles_install_from_lockfile_with_sdk_context() -> None:
    for dockerfile in FRONTEND_DOCKERFILES:
        text = dockerfile.read_text(encoding="utf-8")

        assert "COPY sdk/typescript/ /sdk/typescript/" in text
        assert "RUN cd /sdk/typescript && npm ci --no-audit --no-fund && npm run build" in text
        assert (
            "COPY aragora/live/package.json aragora/live/package-lock.json aragora/live/.npmrc /app/"
        ) in text
        assert "RUN cd /app && npm ci" in text
        assert "COPY aragora/live/ /app/" in text
        assert "RUN cd /app && npm run build:local" in text
        assert "--legacy-peer-deps" not in text
        assert "npm install --legacy-peer-deps" not in text
        assert "npm ci --only=production" not in text
        assert "sed -i" not in text
        assert "replaceAll(" not in text


def test_frontend_dockerfiles_build_sdk_before_frontend_install() -> None:
    for dockerfile in FRONTEND_DOCKERFILES:
        text = dockerfile.read_text(encoding="utf-8")

        sdk_copy = text.index("COPY sdk/typescript/ /sdk/typescript/")
        sdk_build = text.index(
            "RUN cd /sdk/typescript && npm ci --no-audit --no-fund && npm run build"
        )
        frontend_manifest_copy = text.index(
            "COPY aragora/live/package.json aragora/live/package-lock.json aragora/live/.npmrc /app/"
        )
        frontend_install = text.index("RUN cd /app && npm ci")
        frontend_source_copy = text.index("COPY aragora/live/ /app/")
        frontend_build = text.index("RUN cd /app && npm run build:local")

        assert (
            sdk_copy
            < sdk_build
            < frontend_manifest_copy
            < frontend_install
            < frontend_source_copy
            < frontend_build
        )


def test_live_npm_install_policy_matches_ci_peer_resolution() -> None:
    npmrc = (LIVE_DIR / ".npmrc").read_text(encoding="utf-8")
    assert "legacy-peer-deps=true" not in npmrc

    for dockerfile in FRONTEND_DOCKERFILES:
        text = dockerfile.read_text(encoding="utf-8")
        assert "RUN cd /app && npm ci" in text
        assert "legacy-peer-deps" not in text


def test_frontend_dockerfile_stages_preserve_local_sdk_link_targets() -> None:
    for dockerfile in FRONTEND_DOCKERFILES:
        stages = _dockerfile_stage_copies(dockerfile)

        for stage_name, copies in stages.items():
            receives_deps_node_modules = any(
                "--from=deps" in copy and "/app/node_modules" in copy for copy in copies
            )
            receives_deps_sdk = any(
                "--from=deps" in copy and "/sdk/typescript" in copy for copy in copies
            )

            assert not receives_deps_node_modules or receives_deps_sdk, (
                f"{dockerfile}:{stage_name} copies node_modules from deps without "
                "also copying /sdk/typescript, leaving @aragora/sdk dangling"
            )


def test_live_sdk_lock_path_matches_docker_context() -> None:
    package_json = _load_json(LIVE_DIR / "package.json")
    package_lock = _load_json(LIVE_DIR / "package-lock.json")

    assert package_json["dependencies"]["@aragora/sdk"] == "file:../../sdk/typescript"
    assert package_lock["packages"][""]["dependencies"]["@aragora/sdk"] == (
        "file:../../sdk/typescript"
    )
    assert package_lock["packages"]["node_modules/@aragora/sdk"]["resolved"] == (
        "../../sdk/typescript"
    )


def test_pre_deploy_rejects_sub_node20_frontend_runtime() -> None:
    text = (REPO_ROOT / "scripts" / "pre_deploy_check.sh").read_text(encoding="utf-8")

    assert '[[ "${NODE_VERSION%%.*}" -ge 20 ]]' in text
    assert 'print_fail "Node.js version $NODE_VERSION (required: 20+)"' in text
    assert "recommended: 20+" not in text


def test_deploy_frontend_workflow_uses_repo_root_docker_context() -> None:
    text = (REPO_ROOT / ".github" / "workflows" / "deploy-frontend.yml").read_text(encoding="utf-8")

    assert "context: ." in text
    assert "file: aragora/live/Dockerfile" in text
    assert "context: aragora/live" not in text


def test_frontend_compose_builds_use_repo_root_docker_context() -> None:
    for compose_file, expected_context, expected_dockerfile in FRONTEND_COMPOSE_BUILDS:
        compose = _load_yaml(compose_file)
        dashboard_build = compose["services"]["dashboard"]["build"]

        assert dashboard_build["context"] == expected_context
        assert dashboard_build["dockerfile"] == expected_dockerfile
        context_dir = (compose_file.parent / dashboard_build["context"]).resolve()

        assert context_dir == REPO_ROOT.resolve()
        assert (context_dir / dashboard_build["dockerfile"]).is_file()
        assert (context_dir / "sdk" / "typescript").is_dir()
        assert (context_dir / "aragora" / "live" / "package.json").is_file()
        assert (context_dir / "aragora" / "live" / "package-lock.json").is_file()
        assert (context_dir / "aragora" / "live" / ".npmrc").is_file()


def test_repo_root_dockerignore_excludes_frontend_context_churn() -> None:
    ignored = set(_repo_root_dockerignore_patterns())

    assert ".git" in ignored
    assert ".worktrees/" in ignored
    assert ".venv-scale/" in ignored
    assert "/lib/" in ignored
    assert "lib/" not in ignored
    assert ".env" in ignored
    assert ".env.*" in ignored
    assert "**/.env" in ignored
    assert "**/.env.*" in ignored
    assert ".envrc" in ignored
    assert "**/.envrc" in ignored
    assert "node_modules/" in ignored
    assert "aragora/live/node_modules/" in ignored
    assert "aragora/live/.next/" in ignored
    assert "sdk/typescript/node_modules/" in ignored


def test_repo_root_dockerignore_keeps_required_frontend_sources() -> None:
    assert _repo_root_dockerignore_excludes("lib/example.so")
    assert _repo_root_dockerignore_excludes("sdk/typescript/node_modules/.package-lock.json")
    assert _repo_root_dockerignore_excludes("aragora/live/node_modules/next/package.json")
    assert _repo_root_dockerignore_excludes("aragora/live/.next/cache/routes.json")

    assert not _repo_root_dockerignore_excludes("aragora/live/src/lib/backendUrls.ts")
    assert not _repo_root_dockerignore_excludes("aragora/live/src/lib/aragora-client/client.ts")


def test_frontend_dev_compose_mounts_local_sdk_dependency() -> None:
    compose = _load_yaml(REPO_ROOT / "docker-compose.dev.yml")
    volumes = compose["services"]["frontend-dev"]["volumes"]

    assert "./aragora/live:/app" in volumes
    assert "./sdk/typescript:/sdk/typescript:ro" in volumes


def test_live_supabase_node_engines_fit_docker_runtime() -> None:
    package_json = _load_json(LIVE_DIR / "package.json")
    package_lock = _load_json(LIVE_DIR / "package-lock.json")

    runtime_floors = {
        path: min(_node_image_versions(path))
        for path in NODE_RUNTIME_FILES
        if _node_image_versions(path)
    }
    assert runtime_floors.keys() == set(NODE_RUNTIME_FILES), (
        "live Node runtime files must use numeric node image tags so engine floors can be checked"
    )
    runtime_floor = min(runtime_floors.values())

    package_floor = _node_engine_floor(package_json["engines"]["node"])
    assert runtime_floor >= package_floor

    packages = package_lock["packages"]
    for package_name in SUPABASE_PACKAGES:
        engine = packages[package_name]["engines"]["node"]
        assert runtime_floor >= _node_engine_floor(engine), (
            f"{package_name} requires Node {engine}, but live runtime floor is {runtime_floor}"
        )
