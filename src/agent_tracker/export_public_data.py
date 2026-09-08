"""Export the safe-to-commit public projection of a private tracker database."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from .build_site import build_statistics, export_public_data


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--db", required=True, type=Path, help="private SQLite catalog")
    root.add_argument(
        "--output", type=Path, default=Path("site/public-data.json"),
        help="safe-to-commit public-data JSON",
    )
    return root


def main() -> int:
    args = parser().parse_args()
    print(f"status: exporting public data from {args.db}")
    try:
        data = export_public_data(args.db, args.output)
    except (OSError, sqlite3.Error, ValueError) as error:
        print(f"status: failed: {error}", file=sys.stderr)
        return 1
    print(f"statistics: {build_statistics(data)}")
    print(f"status: generated {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
