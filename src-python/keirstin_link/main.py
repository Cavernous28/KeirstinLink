"""Entry point for KeirstinLink backend."""

import argparse
import signal
import sys

import uvicorn

from .api import app, set_discovery_service
from .config import HOST, PORT
from .discovery import DiscoveryService


def main() -> None:
    parser = argparse.ArgumentParser(description="KeirstinLink Python backend")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--no-discovery", action="store_true")
    args = parser.parse_args()

    discovery = DiscoveryService(port=args.port)
    if not args.no_discovery:
        discovery.start()
        set_discovery_service(discovery)

    def shutdown(signum, frame) -> None:
        set_discovery_service(None)
        discovery.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
