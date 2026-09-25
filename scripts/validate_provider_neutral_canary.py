#!/usr/bin/env python3
"""Validate provider-neutral canary inputs without reading secret values."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
from pathlib import Path

_IMAGE_RE = re.compile(r"^[a-z0-9][a-z0-9./:_-]*@sha256:[0-9a-f]{64}$")
_REQUIRED_FILES = frozenset(
    {
        "DATABASE_URL",
        "REDIS_URL",
        "ARAGORA_API_TOKEN",
        "ARAGORA_JWT_SECRET",
        "ARAGORA_ENCRYPTION_KEY",
        "odr-signing-key.pem",
    }
)
_PROVIDER_FILES = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "XAI_API_KEY",
        "GROK_API_KEY",
        "MISTRAL_API_KEY",
    }
)
_MAX_FILE_BYTES = 64 * 1024


def validate_image(image: str) -> list[str]:
    if not _IMAGE_RE.fullmatch(image):
        return ["ARAGORA_IMAGE must be an immutable registry reference with @sha256:<64 hex>"]
    repository, digest = image.rsplit("@sha256:", 1)
    if "/" not in repository or set(digest) == {"0"}:
        return ["ARAGORA_IMAGE must name a registry repository and a non-placeholder digest"]
    return []


def _open_directory(path: Path, runtime_uid: int, runtime_gid: int) -> int:
    if os.name != "posix" or os.open not in os.supports_dir_fd:
        raise RuntimeError("canary custody validation requires POSIX descriptor safety")
    components = [part for part in str(path).split(os.path.sep) if part]
    if not components:
        raise RuntimeError("ARAGORA_SECRETS_DIR_HOST must not be the filesystem root")
    if any(part in {".", ".."} for part in components):
        raise RuntimeError("ARAGORA_SECRETS_DIR_HOST must not contain dot components")
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0)
    trusted_ancestor_uids = {0, os.geteuid(), runtime_uid}
    try:
        current_fd = os.open(os.path.sep, flags)
    except OSError as exc:
        raise RuntimeError("filesystem root could not be opened safely") from exc
    try:
        for index, component in enumerate(components):
            next_fd = os.open(component, flags | os.O_NOFOLLOW, dir_fd=current_fd)
            try:
                metadata = os.fstat(next_fd)
                mode = stat.S_IMODE(metadata.st_mode)
                final = index == len(components) - 1
                if not stat.S_ISDIR(metadata.st_mode):
                    raise RuntimeError("ARAGORA_SECRETS_DIR_HOST is not a directory")
                if metadata.st_uid not in trusted_ancestor_uids:
                    raise RuntimeError("custody path component has untrusted ownership")
                if mode & 0o022 and (final or not mode & stat.S_ISVTX):
                    raise RuntimeError("custody path component is writable by peers")
                if final and (metadata.st_uid != runtime_uid or metadata.st_gid != runtime_gid):
                    raise RuntimeError("custody directory ownership does not match runtime UID/GID")
                if final and mode != 0o700:
                    raise RuntimeError("custody directory permissions must be 0700")
            except (OSError, RuntimeError):
                os.close(next_fd)
                raise
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except OSError as exc:
        os.close(current_fd)
        raise RuntimeError("custody directory could not be opened without symlinks") from exc
    except Exception:
        os.close(current_fd)
        raise


def _validate_file(directory_fd: int, name: str, runtime_uid: int, runtime_gid: int) -> list[str]:
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(name, flags, dir_fd=directory_fd)
    except FileNotFoundError:
        return [f"missing required custody file: {name}"]
    except OSError:
        return [f"custody file could not be opened safely: {name}"]
    try:
        metadata = os.fstat(fd)
        mode = stat.S_IMODE(metadata.st_mode)
        errors: list[str] = []
        if not stat.S_ISREG(metadata.st_mode):
            errors.append(f"custody file is not regular: {name}")
        if metadata.st_nlink != 1:
            errors.append(f"custody file is not single-link: {name}")
        if metadata.st_uid != runtime_uid or metadata.st_gid != runtime_gid:
            errors.append(f"custody file ownership does not match runtime UID/GID: {name}")
        if not mode & stat.S_IRUSR or mode & ~0o600:
            errors.append(f"custody file permissions are not owner-readable/owner-only: {name}")
        if metadata.st_size <= 0 or metadata.st_size > _MAX_FILE_BYTES:
            errors.append(f"custody file size is outside 1..{_MAX_FILE_BYTES} bytes: {name}")
        return errors
    finally:
        os.close(fd)


def validate_secrets_directory(
    path_text: str,
    *,
    runtime_uid: int | None = None,
    runtime_gid: int | None = None,
) -> tuple[list[str], list[str]]:
    path = Path(path_text)
    if not path.is_absolute():
        return ["ARAGORA_SECRETS_DIR_HOST must be absolute"], []
    uid = os.geteuid() if runtime_uid is None else runtime_uid
    gid = os.getegid() if runtime_gid is None else runtime_gid
    try:
        directory_fd = _open_directory(path, uid, gid)
    except RuntimeError as exc:
        return [str(exc)], []
    try:
        present = sorted(os.listdir(directory_fd))
        errors: list[str] = []
        for name in sorted(_REQUIRED_FILES):
            errors.extend(_validate_file(directory_fd, name, uid, gid))
        provider_names = sorted(_PROVIDER_FILES.intersection(present))
        if not provider_names:
            errors.append("at least one managed AI provider key file is required")
        else:
            for name in provider_names:
                errors.extend(_validate_file(directory_fd, name, uid, gid))
        return errors, present
    except OSError:
        return ["ARAGORA_SECRETS_DIR_HOST cannot be enumerated"], []
    finally:
        os.close(directory_fd)


def build_report(
    image: str,
    secrets_dir: str,
    *,
    runtime_uid: int | None = None,
    runtime_gid: int | None = None,
) -> dict[str, object]:
    errors = validate_image(image)
    secret_errors, present = validate_secrets_directory(
        secrets_dir, runtime_uid=runtime_uid, runtime_gid=runtime_gid
    )
    errors.extend(secret_errors)
    return {
        "ok": not errors,
        "image_digest_pinned": not validate_image(image),
        "required_secret_names_present": sorted(_REQUIRED_FILES.intersection(present)),
        "provider_secret_names_present": sorted(_PROVIDER_FILES.intersection(present)),
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--secrets-dir", required=True)
    parser.add_argument("--runtime-uid", type=int, default=1000)
    parser.add_argument("--runtime-gid", type=int, default=1000)
    args = parser.parse_args(argv)
    report = build_report(
        args.image,
        args.secrets_dir,
        runtime_uid=args.runtime_uid,
        runtime_gid=args.runtime_gid,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
