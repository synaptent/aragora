"""Run migrations after reading only DATABASE_URL from mounted custody."""

from __future__ import annotations

import os
import socket
import sys
import time
from urllib.parse import urlsplit

from aragora.config.secrets import SecretManager, SecretsConfig
from aragora.migrations.runner import apply_migrations


def wait_for_database(database_url: str, timeout_seconds: float) -> None:
    parsed = urlsplit(database_url)
    host = parsed.hostname
    try:
        port = parsed.port or 5432
    except ValueError as exc:
        raise RuntimeError("DATABASE_URL has an invalid network port") from exc
    if not host:
        raise RuntimeError("DATABASE_URL has no network host")
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while True:
        try:
            with socket.create_connection((host, port), timeout=2.0):
                return
        except OSError as exc:
            if time.monotonic() >= deadline:
                raise RuntimeError("database did not become reachable before timeout") from exc
            time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))


def main() -> int:
    manager = SecretManager(SecretsConfig.from_env())
    directory_fd = manager._open_secrets_directory()  # noqa: SLF001
    try:
        database_url = manager._read_mounted_secret(directory_fd, "DATABASE_URL")  # noqa: SLF001
    finally:
        os.close(directory_fd)
    if not database_url:
        raise RuntimeError("DATABASE_URL was not loaded from managed custody")
    try:
        wait_seconds = float(os.environ.get("ARAGORA_DB_WAIT_SECONDS", "60"))
    except ValueError:
        wait_seconds = 60.0
    wait_for_database(database_url, wait_seconds)
    applied = apply_migrations(database_url=database_url)
    sys.stdout.write(f"Applied {len(applied)} migration(s)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
