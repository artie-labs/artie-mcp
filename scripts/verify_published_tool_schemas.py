from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from published_contract import (
    PublishedContractError,
    add_published_schema_signatures,
    tool_schema_signatures,
    verify_published_schema_signatures,
)

_BUNDLE_DIR = Path(__file__).resolve().parent.parent / "contract"
_SNAPSHOT_PATH = _BUNDLE_DIR / "policy.contract.json"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    snapshot = json.loads(_SNAPSHOT_PATH.read_text())

    import server

    tools = asyncio.run(server.mcp.list_tools())
    signatures = tool_schema_signatures(tools)
    if arguments.write:
        updated_snapshot = add_published_schema_signatures(snapshot, signatures)
        _SNAPSHOT_PATH.write_text(json.dumps(updated_snapshot, indent=2) + "\n")
        return
    verify_published_schema_signatures(snapshot, signatures)


if __name__ == "__main__":
    try:
        main()
    except (OSError, json.JSONDecodeError, PublishedContractError) as error:
        raise SystemExit(str(error)) from error
