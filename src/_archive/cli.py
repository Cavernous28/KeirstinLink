"""Minimal CLI entry point for KeirstinLink."""
from __future__ import annotations

import argparse

from . import master, slave


def main() -> None:
    parser = argparse.ArgumentParser(prog="keirstinlink")
    subparsers = parser.add_subparsers(dest="command")

    master_parser = subparsers.add_parser("master", help="Start the master bridge")
    master_parser.set_defaults(func=master.main)

    slave_parser = subparsers.add_parser("slave", help="Start a slave worker")
    slave_parser.set_defaults(func=slave.main)

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        raise SystemExit(1)
    args.func()


if __name__ == "__main__":
    main()
