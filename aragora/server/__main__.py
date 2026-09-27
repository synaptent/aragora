"""Entry point for running aragora.server as a module.

Usage:
    python -m aragora.server --port 8080
    python -m aragora.server --workers 4  # Production: 4 worker processes
"""

import argparse
import asyncio
import multiprocessing
import os
import signal
import sys
from pathlib import Path

from aragora.server.unified_server import run_unified_server

# Default to localhost for security; use ARAGORA_BIND_HOST=0.0.0.0 for external access
DEFAULT_BIND_HOST = os.environ.get("ARAGORA_BIND_HOST", "127.0.0.1")
LOCAL_DEMO_HANDLER_TIERS = "core,extended,optional"
_PROVIDER_API_KEYS = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "MISTRAL_API_KEY",
    "GEMINI_API_KEY",
    "XAI_API_KEY",
)


def _hydrate_runtime_secrets() -> None:
    from aragora.config.secrets import hydrate_env_from_secrets

    hydrate_env_from_secrets(overwrite=True)


def _detect_api_keys() -> list[str]:
    from aragora.config.secrets import get_secret_presence, is_secret_presence_available

    return [
        name
        for name in _PROVIDER_API_KEYS
        if is_secret_presence_available(get_secret_presence(name))
    ]


def _configure_logging() -> None:
    """Configure structured logging for the server.

    Uses JSON format in production (ARAGORA_ENV=production or ARAGORA_LOG_FORMAT=json),
    text format otherwise for easier local development.
    """
    from aragora.server.middleware.structured_logging import configure_structured_logging

    env = os.environ.get("ARAGORA_ENV", "development")
    log_format = os.environ.get("ARAGORA_LOG_FORMAT", "")
    log_level = os.environ.get("ARAGORA_LOG_LEVEL", "INFO")

    # Use JSON format in production or if explicitly set
    use_json = log_format == "json" or (not log_format and env == "production")

    configure_structured_logging(
        level=log_level,
        json_output=use_json,
        service_name="aragora",
    )


def _print_startup_banner(args, workers: int) -> None:
    """Print a startup banner with connection info."""
    offline = getattr(args, "offline", False)
    host = args.host
    http_port = args.http_port
    ws_port = args.port
    db_backend = os.environ.get("ARAGORA_DB_BACKEND", "sqlite" if offline else "auto")
    env = os.environ.get("ARAGORA_ENV", "development")
    mode = f"{env} (offline)" if offline else env

    print()
    print("=" * 64)
    print("  ARAGORA SERVER")
    print("=" * 64)
    print()
    if workers > 1:
        print(f"  HTTP API:     http://{host}:{http_port}-{http_port + workers - 1}")
        print(f"  WebSocket:    ws://{host}:{ws_port}-{ws_port + workers - 1}/ws")
        print(f"  Workers:      {workers}")
    else:
        print(f"  HTTP API:     http://{host}:{http_port}")
        print(f"  WebSocket:    ws://{host}:{ws_port}/ws")
    print(f"  Health:       http://{host}:{http_port}/healthz")
    print(f"  Mode:         {mode}")
    print(f"  Database:     {db_backend}")
    if offline:
        print()
        print("  No API keys needed in offline mode.")
    print()
    print("  Dashboard:    cd aragora/live && npm run dev")
    print("  Docs:         https://docs.aragora.ai")
    print()
    print("  Press Ctrl+C to stop.")
    print("=" * 64)
    print()


def _configure_runtime_environment(offline: bool, api_keys: list[str], logger) -> None:
    """Apply local runtime defaults before starting the server."""
    if offline:
        os.environ.setdefault("ARAGORA_OFFLINE", "true")
        os.environ.setdefault("ARAGORA_DEMO_MODE", "true")
        os.environ.setdefault("ARAGORA_DB_BACKEND", "sqlite")
        os.environ.setdefault("ARAGORA_ENV", "development")
        # Keep optional handlers in local demo/offline mode so dashboard
        # surfaces can exercise the same API families they call in production.
        os.environ.setdefault("ARAGORA_HANDLER_TIERS", LOCAL_DEMO_HANDLER_TIERS)
        logger.info("[server] OFFLINE mode: SQLite backend, demo data for unavailable services")
        return

    if not api_keys:
        # No API keys found — auto-enable demo mode for zero-config startup.
        os.environ.setdefault("ARAGORA_DEMO_MODE", "true")
        os.environ.setdefault("ARAGORA_DB_BACKEND", "sqlite")
        # Keep optional handlers available in local demo mode. They back
        # dashboard surfaces such as usage/ROI/budget widgets.
        os.environ.setdefault("ARAGORA_HANDLER_TIERS", LOCAL_DEMO_HANDLER_TIERS)
        logger.info(
            "[server] No API keys detected. Starting in DEMO mode with mock agents. "
            "Set ANTHROPIC_API_KEY or OPENAI_API_KEY for real AI debates."
        )
        return

    logger.info("[server] API keys detected: %s", ", ".join(api_keys))


def _run_worker(http_port: int, ws_port: int, host: str, static_dir, nomic_dir):
    """Run a single server worker process."""
    # Configure logging for this worker process
    _configure_logging()

    asyncio.run(
        run_unified_server(
            http_port=http_port,
            ws_port=ws_port,
            http_host=host,
            ws_host=host,
            static_dir=static_dir,
            nomic_dir=nomic_dir,
        )
    )


def main():
    parser = argparse.ArgumentParser(
        description="Aragora Unified Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Production deployment with multiple workers:
    python -m aragora.server --workers 4 --host 0.0.0.0

    For best results, use a load balancer (nginx, haproxy) in front of workers.
    Each worker runs on a different port: base_port, base_port+1, ...
        """,
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_BIND_HOST,
        help="Host to bind to (default: 127.0.0.1, use ARAGORA_BIND_HOST env var)",
    )
    parser.add_argument("--port", type=int, default=8765, help="WebSocket port")
    parser.add_argument("--http-port", type=int, default=8080, help="HTTP API port")
    parser.add_argument("--ws-port", type=int, help="Alias for --port")
    parser.add_argument("--api-port", type=int, help="Alias for --http-port")
    parser.add_argument("--static-dir", type=Path, help="Static files directory")
    parser.add_argument("--nomic-dir", type=Path, help="Nomic state directory")
    parser.add_argument(
        "--workers",
        "-w",
        type=int,
        default=1,
        help="Number of worker processes (default: 1). For production, use 2-4x CPU cores.",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Run in offline mode (SQLite + in-memory stores, demo data for unavailable services)",
    )

    args = parser.parse_args()
    if args.ws_port is not None:
        args.port = args.ws_port
    if args.api_port is not None:
        args.http_port = args.api_port

    workers = max(1, args.workers)

    # Configure logging before starting server
    _configure_logging()

    _print_startup_banner(args, workers)

    # Auto-detect available API keys and configure accordingly
    import logging

    _logger = logging.getLogger(__name__)
    _hydrate_runtime_secrets()
    _api_keys = _detect_api_keys()

    # Apply runtime defaults before starting any workers.
    _configure_runtime_environment(args.offline, _api_keys, _logger)

    # Default to SQLite if no database URL configured
    if not os.environ.get("DATABASE_URL") and not os.environ.get("ARAGORA_POSTGRES_DSN"):
        os.environ.setdefault("ARAGORA_DB_BACKEND", "sqlite")

    if workers == 1:
        # Single worker mode - run directly
        asyncio.run(
            run_unified_server(
                http_port=args.http_port,
                ws_port=args.port,
                http_host=args.host,
                ws_host=args.host,
                static_dir=args.static_dir,
                nomic_dir=args.nomic_dir,
            )
        )
    else:
        # Multi-worker mode - spawn worker processes

        processes = []

        def shutdown_workers(signum, frame):
            """Gracefully shutdown all workers."""
            for p in processes:
                if p.is_alive():
                    p.terminate()
            sys.exit(0)

        signal.signal(signal.SIGINT, shutdown_workers)
        signal.signal(signal.SIGTERM, shutdown_workers)

        for i in range(workers):
            http_port = args.http_port + i
            ws_port = args.port + i
            p = multiprocessing.Process(
                target=_run_worker,
                args=(http_port, ws_port, args.host, args.static_dir, args.nomic_dir),
                name=f"aragora-worker-{i}",
            )
            p.start()
            processes.append(p)

        # Wait for all workers
        try:
            for p in processes:
                p.join()
        except KeyboardInterrupt:
            shutdown_workers(None, None)


if __name__ == "__main__":
    main()
