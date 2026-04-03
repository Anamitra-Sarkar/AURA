"""CLI entry point for aura-client."""

from __future__ import annotations

import argparse
import asyncio

from .connection import ClientConnection


def main() -> None:
    parser = argparse.ArgumentParser(description="Connect to AURA cloud brain")
    parser.add_argument("--server", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--user-id", default="local")
    args = parser.parse_args()
    asyncio.run(ClientConnection(args.server, args.token, args.user_id).run())


if __name__ == "__main__":
    main()
