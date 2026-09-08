"""Export, validate, commit, and push a safe public release."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


PRIVATE_PATHS = {"next-steps.md", "simplify.md"}
PRIVATE_SUFFIXES = (".db", ".sqlite")
PUBLIC_PATHS = (
    ".env.sample",
    ".github",
    ".gitignore",
    "README.md",
    "CLAUDE.md",
    "pyproject.toml",
    "site",
    "src",
    "tests",
    "uv.lock",
)


def run(*command: str) -> None:
    print("+", " ".join(command))
    subprocess.run(command, check=True)


def staged_changes_are_public() -> None:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-status"],
        check=True,
        capture_output=True,
        text=True,
    )
    violations: list[str] = []
    for line in result.stdout.splitlines():
        status, path = line.split("\t", maxsplit=1)
        if status.startswith("D"):
            continue
        if (
            path.startswith("private/")
            or path in PRIVATE_PATHS
            or path.endswith(PRIVATE_SUFFIXES)
        ):
            violations.append(path)
    if violations:
        raise ValueError(
            "refusing to publish private paths: " + ", ".join(sorted(violations))
        )
    if not result.stdout:
        raise ValueError("nothing is staged for publication")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--message", "-m", required=True, help="Git commit message")
    root.add_argument("--remote", default="origin", help="Git remote to push")
    root.add_argument(
        "--branch",
        help="Git branch to push; defaults to the current branch's upstream",
    )
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        run(
            sys.executable,
            "-m",
            "agent_tracker.export_public_data",
            "--db",
            "private/partner-tracking.db",
            "--output",
            "site/public-data.json",
        )
        run(sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v")
        run(
            sys.executable,
            "-m",
            "agent_tracker.build_site",
            "--data",
            "site/public-data.json",
            "--output",
            "_site",
        )
        run(sys.executable, "-m", "agent_tracker.validate_site", "_site")
        run("git", "add", "--update")
        run("git", "add", "--", *PUBLIC_PATHS)
        run("git", "add", "--", "site/public-data.json")
        staged_changes_are_public()
        run("git", "diff", "--cached", "--check")
        run("git", "commit", "-m", args.message)
        push = ["git", "push", args.remote]
        if args.branch:
            push.append(args.branch)
        run(*push)
    except (subprocess.CalledProcessError, ValueError) as error:
        print(f"status: failed: {error}", file=sys.stderr)
        return 1
    print("status: published")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
