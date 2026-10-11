#!/usr/bin/env python3
"""
Run nomic loop with live streaming dashboard.

This script starts both the unified server (HTTP + WebSocket) and the nomic loop,
with the nomic loop events streaming to connected clients in real-time.

Usage:
    python scripts/run_nomic_with_stream.py run --cycles 3
    python scripts/run_nomic_with_stream.py run --cycles 3 --port 8080
"""

import argparse
import asyncio
import atexit
import logging
import os
import signal
import sys
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from threading import Thread

# Add aragora to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from aragora.server.stream import AiohttpUnifiedServer
from scripts.nomic_loop import NomicLoop
from scripts.nomic.config import NOMIC_AUTO_COMMIT


_CRASH_LOG_PATH: Path | None = None
_CRASH_LOGGER: logging.Logger | None = None


def _init_crash_logger(aragora_path: Path) -> None:
    global _CRASH_LOG_PATH, _CRASH_LOGGER
    _CRASH_LOG_PATH = aragora_path / ".nomic" / "nomic_crash.log"
    _CRASH_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("nomic_crash")
    logger.setLevel(logging.INFO)
    handler = logging.FileHandler(_CRASH_LOG_PATH, encoding="utf-8")
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    _CRASH_LOGGER = logger
    logger.info("Crash logger initialized")


def _log_crash(msg: str, exc: BaseException | None = None) -> None:
    logger = _CRASH_LOGGER
    if logger is None:
        return
    if exc is None:
        logger.error(msg)
        return
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    logger.error("%s\n%s", msg, tb)


def _install_exit_hooks() -> None:
    def _excepthook(exc_type, exc, tb):
        _log_crash("Uncaught exception", exc)
        sys.__excepthook__(exc_type, exc, tb)

    def _signal_handler(signum, _frame):
        _log_crash(f"Received signal {signum}")
        raise SystemExit(128 + signum)

    sys.excepthook = _excepthook
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        try:
            signal.signal(sig, _signal_handler)
        except Exception:
            pass

    def _on_exit():
        if _CRASH_LOGGER:
            _CRASH_LOGGER.info("Process exiting (atexit)")

    atexit.register(_on_exit)


def find_available_port(start_port: int = 8080, max_attempts: int = 10) -> int:
    """Find an available port, starting from start_port.

    Tries ports sequentially until one is available.
    This prevents "address already in use" errors when restarting the server.

    Args:
        start_port: The preferred port to start with
        max_attempts: Maximum number of ports to try

    Returns:
        An available port number

    Raises:
        RuntimeError: If no available port found in range
    """
    import socket

    for offset in range(max_attempts):
        port = start_port + offset
        try:
            # Try to bind to the port
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("0.0.0.0", port))  # noqa: S104 - port availability check
            sock.close()
            return port
        except OSError:
            # Port is in use, try next one
            continue

    raise RuntimeError(
        f"No available ports in range {start_port}-{start_port + max_attempts - 1}. "
        f"Try killing existing processes or use a different port range."
    )


def generate_loop_id() -> str:
    """Generate a unique loop ID."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    short_uuid = str(uuid.uuid4())[:8]
    return f"loop_{timestamp}_{short_uuid}"


def get_loop_name(aragora_path: Path) -> str:
    """Generate a human-readable loop name."""
    # Use hostname + path as identifier
    hostname = os.uname().nodename if hasattr(os, "uname") else "local"
    path_suffix = aragora_path.name
    return f"{hostname}:{path_suffix}"


async def run_with_streaming(
    cycles: int = 3,
    port: int = 8080,
    aragora_path: Path | None = None,
    auto_commit: bool = False,
):
    """Run nomic loop with streaming enabled."""
    aragora_path = aragora_path or Path(__file__).parent.parent

    # Find an available port (handles port conflicts gracefully)
    actual_port = find_available_port(start_port=port, max_attempts=10)
    if actual_port != port:
        print(f"Note: Port {port} was in use, using port {actual_port} instead")

    # Generate unique loop ID for multi-loop tracking
    loop_id = generate_loop_id()
    loop_name = get_loop_name(aragora_path)

    nomic_dir = aragora_path / ".nomic"

    # Create unified server (HTTP + WebSocket on same port)
    server = AiohttpUnifiedServer(
        port=actual_port,
        nomic_dir=nomic_dir,
    )

    # Get the emitter for the nomic loop and set loop_id for event tagging
    emitter = server.emitter
    emitter.set_loop_id(loop_id)  # Tag all events with this loop's ID

    print("=" * 60)
    print("ARAGORA NOMIC LOOP WITH LIVE STREAMING")
    print("=" * 60)
    print(f"Loop ID:      {loop_id}")
    print(f"Loop Name:    {loop_name}")
    print(f"Server:       http://localhost:{actual_port} (HTTP + WebSocket)")
    print("Live view:    https://aragora.ai")
    print(f"Cycles:       {cycles}")
    print(f"Auto-commit:  {'Yes' if auto_commit else 'No (requires confirmation)'}")
    print("=" * 60)
    print()

    # Create nomic loop with stream emitter
    loop = NomicLoop(
        aragora_path=aragora_path,
        max_cycles=cycles,
        stream_emitter=emitter,
        auto_commit=auto_commit,
        require_human_approval=not auto_commit,  # Disable approval when auto_commit is True
    )

    # Start server in background task
    async def run_server():
        await server.start()

    # Install asyncio exception handler for visibility
    async_loop = asyncio.get_running_loop()
    async_loop.set_exception_handler(
        lambda _loop, context: _log_crash(
            f"Asyncio exception: {context.get('message')}", context.get("exception")
        )
    )

    server_task = asyncio.create_task(run_server())

    # Give server time to start
    await asyncio.sleep(1)

    # Register this loop instance with the unified server
    server.register_loop(
        loop_id=loop_id,
        name=loop_name,
        path=str(aragora_path),
    )

    print("Server started. Running nomic loop...")
    print(f"This loop is now visible at https://aragora.ai as '{loop_name}'")
    print()

    try:
        # Run the nomic loop
        await loop.run()
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        _log_crash("KeyboardInterrupt")
    except Exception as e:
        print(f"Error: {e}")
        _log_crash("Unhandled exception in run_with_streaming", e)
        raise
    finally:
        # Unregister the loop instance
        server.unregister_loop(loop_id)
        # Stop server
        server.stop()
        # Cancel server task
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass

    print()
    print("Nomic loop complete!")


def main():
    parser = argparse.ArgumentParser(
        description="Run nomic loop with live streaming dashboard",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Run command
    run_parser = subparsers.add_parser("run", help="Run nomic loop with streaming")
    run_parser.add_argument(
        "--cycles",
        "-c",
        type=int,
        default=3,
        help="Number of cycles to run (default: 3)",
    )
    run_parser.add_argument(
        "--port",
        "-p",
        type=int,
        default=8080,
        help="Port for unified server (HTTP + WebSocket) (default: 8080)",
    )
    # Legacy arguments for backwards compatibility
    run_parser.add_argument(
        "--http-port",
        type=int,
        default=None,
        help="(Deprecated) Use --port instead",
    )
    run_parser.add_argument(
        "--ws-port",
        type=int,
        default=None,
        help="(Deprecated) Ignored - unified server uses single port",
    )
    run_parser.add_argument(
        "--aragora-path",
        type=Path,
        default=None,
        help="Path to aragora root (default: auto-detect)",
    )
    run_parser.add_argument(
        "--auto",
        action="store_true",
        help="Auto-commit without human approval",
    )

    args = parser.parse_args()

    if getattr(args, "auto", False) and not NOMIC_AUTO_COMMIT:
        print("=" * 70)
        print("AUTO-COMMIT SAFETY GATE")
        print("=" * 70)
        print("Auto-commit requires explicit opt-in via NOMIC_AUTO_COMMIT=1.")
        print("Set NOMIC_AUTO_COMMIT=1 and re-run with --auto if you intend")
        print("to allow unattended commits.")
        print("=" * 70)
        sys.exit(2)

    if args.command == "run":
        aragora_path = args.aragora_path or Path(__file__).parent.parent
        _init_crash_logger(aragora_path)
        _install_exit_hooks()
        # Support legacy --http-port
        port = args.http_port if args.http_port else args.port
        try:
            asyncio.run(
                run_with_streaming(
                    cycles=args.cycles,
                    port=port,
                    aragora_path=aragora_path,
                    auto_commit=args.auto,
                )
            )
        except Exception as e:
            _log_crash("Fatal error in main()", e)
            raise
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
