import json
import posixpath
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
NODE_IMAGE = "node:24.18-alpine"


def _compose() -> dict[str, object]:
    return yaml.safe_load((ROOT / "docker-compose.dev.yml").read_text(encoding="utf-8"))


def test_frontend_dev_builds_local_sdk_before_starting() -> None:
    compose = _compose()
    service = compose["services"]["frontend-dev"]
    volumes = service["volumes"]
    command = " ".join(service["command"].split())

    assert service["image"] == NODE_IMAGE
    assert "typescript-sdk-dev:/sdk/typescript" in volumes
    assert "frontend-dev-npm-cache:/root/.npm" in volumes
    assert {
        "./sdk/typescript/.npmrc:/sdk/typescript/.npmrc:ro",
        "./sdk/typescript/package.json:/sdk/typescript/package.json:ro",
        "./sdk/typescript/package-lock.json:/sdk/typescript/package-lock.json:ro",
        "./sdk/typescript/tsconfig.json:/sdk/typescript/tsconfig.json:ro",
        "./sdk/typescript/src:/sdk/typescript/src:ro",
    }.issubset(volumes)
    assert "typescript-sdk-dev" in compose["volumes"]
    assert "frontend-dev-npm-cache" in compose["volumes"]

    assert command == (
        'sh -c "npm --prefix /sdk/typescript ci --legacy-peer-deps && '
        'npm --prefix /sdk/typescript run build && npm install && npm run dev"'
    )


def test_frontend_sdk_dependency_resolves_to_compose_mount() -> None:
    package = json.loads((ROOT / "aragora/live/package.json").read_text(encoding="utf-8"))
    specifier = package["dependencies"]["@aragora/sdk"]

    assert specifier.startswith("file:")
    assert posixpath.normpath(posixpath.join("/app", specifier.removeprefix("file:"))) == (
        "/sdk/typescript"
    )


def _node_base_images(dockerfile: str) -> list[str]:
    """Image refs from each ``FROM`` line whose base image is the ``node`` repository.

    Non-node stages (nginx, distroless, scratch) are ignored on purpose so a
    legitimate multi-base build is not coupled to the node pin.
    """
    images: list[str] = []
    for line in dockerfile.splitlines():
        parts = line.strip().split()
        if len(parts) < 2 or parts[0].upper() != "FROM":
            continue
        image = parts[1]
        if image.split("@", 1)[0].rsplit(":", 1)[0] == "node":
            images.append(image)
    return images


def test_frontend_container_images_use_supported_node_lts() -> None:
    # deploy/Dockerfile.frontend is the single frontend image definition. The old
    # aragora/live/Dockerfile was deleted because it could never build: its
    # file:../../sdk/typescript dependency resolves outside an aragora/live-scoped
    # build context. Keep this list in sync if another frontend image is ever added.
    for relative_path in ("deploy/Dockerfile.frontend",):
        dockerfile = (ROOT / relative_path).read_text(encoding="utf-8")
        node_images = _node_base_images(dockerfile)

        assert node_images, f"{relative_path} declares no node base image"
        assert all(image == NODE_IMAGE for image in node_images)
