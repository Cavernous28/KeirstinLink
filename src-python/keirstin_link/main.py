"""Entry point for KeirstinLink backend."""

import argparse
import os
import signal
import sys

import uvicorn

from .api import app, set_discovery_service
from .config import HOST, PID_FILE, PORT
from .discovery import DiscoveryService


def _write_pid() -> None:
    try:
        PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        pass


def _remove_pid() -> None:
    try:
        PID_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="KeirstinLink Python backend")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--no-discovery", action="store_true")
    args = parser.parse_args()

    _write_pid()

    discovery = DiscoveryService(port=args.port)
    if not args.no_discovery:
        discovery.start()
        set_discovery_service(discovery)

    def shutdown(signum, frame) -> None:
        _remove_pid()
        set_discovery_service(None)
        try:
            discovery.stop()
        except Exception:
            pass
        sys.exit(0)

    try:
        signal.signal(signal.SIGINT, shutdown)
        signal.signal(signal.SIGTERM, shutdown)
    except ValueError:
        # signal.signal can fail on Windows for non-main threads; ignore safely.
        pass

    try:
        uvicorn.run(app, host=args.host, port=args.port, log_config=None)
    finally:
        _remove_pid()
        set_discovery_service(None)
        try:
            discovery.stop()
        except Exception:
            pass


if __name__ == "__main__":
    main()
