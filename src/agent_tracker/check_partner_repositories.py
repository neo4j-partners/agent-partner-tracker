"""Report recent changes to tracked GitHub repositories without changing SQLite."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

from .discovery_common import (
    PARTNERS,
    EnvSettings,
    read_partner_review_date,
    request_json,
    utc_now,
    write_report,
)
from .partner_tracker import read_only_connection


GITHUB_API_URL = "https://api.github.com"


def repository_coordinates(url: str) -> tuple[str, str] | None:
    parts = urlsplit(url)
    path = [segment for segment in parts.path.split("/") if segment]
    if parts.netloc.lower() != "github.com" or len(path) != 2:
        return None
    return path[0], path[1]


def tracked_repositories(db_path: Path, partner: str) -> list[dict[str, str]]:
    connection = read_only_connection(db_path)
    try:
        rows = connection.execute(
            """SELECT ci.title, ci.canonical_url
               FROM content_items ci
               JOIN partners p ON p.id = ci.partner_id
               WHERE p.name = ? AND ci.content_type = 'repository'
                 AND ci.status IN ('active', 'watch')
               ORDER BY ci.title""",
            (partner,),
        ).fetchall()
    finally:
        connection.close()
    return [dict(row) for row in rows if row["canonical_url"]]


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def changed_fields(
    repository: dict[str, Any], commit: dict[str, Any] | None,
    release: dict[str, Any] | None, cutoff: datetime
) -> list[str]:
    fields = {
        "repository_updated": repository.get("updated_at"),
        "repository_pushed": repository.get("pushed_at"),
        "latest_commit": (commit or {}).get("commit", {}).get("author", {}).get("date"),
        "latest_release": (release or {}).get("published_at"),
    }
    return [name for name, value in fields.items() if (timestamp := parse_timestamp(value)) and timestamp > cutoff]


def github_json(
    path: str, headers: dict[str, str], timeout: int
) -> dict[str, Any] | None:
    try:
        return request_json(f"{GITHUB_API_URL}{path}", {}, headers, timeout)
    except HTTPError as error:
        if error.code == 404:
            return None
        raise


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--partner", required=True, choices=PARTNERS)
    root.add_argument("--db", default="partner-tracking.db", type=Path)
    root.add_argument("--env-file", default=".env", type=Path)
    root.add_argument("--output", type=Path)
    return root


def main() -> int:
    command_parser = parser()
    args = command_parser.parse_args()
    try:
        settings = EnvSettings.load(args.env_file)
    except ValueError as error:
        command_parser.error(str(error))
    headers = {"Accept": "application/vnd.github+json"}
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    cutoff_date = read_partner_review_date(args.db, args.partner)
    cutoff = datetime.combine(cutoff_date, datetime.min.time(), timezone.utc) if cutoff_date else datetime.min.replace(tzinfo=timezone.utc)
    reports: list[dict[str, Any]] = []
    rate_limited = False
    for item in tracked_repositories(args.db, args.partner):
        coordinates = repository_coordinates(item["canonical_url"])
        if not coordinates:
            continue
        owner, repository_name = coordinates
        try:
            repository = github_json(f"/repos/{owner}/{repository_name}", headers, settings.timeout)
            if repository is None:
                reports.append({**item, "error": "repository not found"})
                continue
            default_branch = repository["default_branch"]
            commit = github_json(
                f"/repos/{owner}/{repository_name}/commits/{default_branch}",
                headers,
                settings.timeout,
            )
            release = github_json(
                f"/repos/{owner}/{repository_name}/releases/latest",
                headers,
                settings.timeout,
            )
            reports.append(
                {
                    **item,
                    "repository": f"{owner}/{repository_name}",
                    "default_branch": default_branch,
                    "updated_at": repository.get("updated_at"),
                    "pushed_at": repository.get("pushed_at"),
                    "latest_commit": (commit or {}).get("sha"),
                    "latest_commit_date": (commit or {}).get("commit", {})
                    .get("author", {})
                    .get("date"),
                    "latest_release": (release or {}).get("tag_name"),
                    "latest_release_date": (release or {}).get("published_at"),
                    "changed_fields": changed_fields(repository, commit, release, cutoff),
                }
            )
        except (HTTPError, URLError) as error:
            reports.append(
                {
                    **item,
                    "repository": f"{owner}/{repository_name}",
                    "error": str(error),
                }
            )
            if isinstance(error, HTTPError) and error.code == 403:
                rate_limited = True
                break
    report = {
        "partner": args.partner,
        "cutoff_date": cutoff_date.isoformat() if cutoff_date else None,
        "generated_at": utc_now(),
        "database_write": False,
        "rate_limited": rate_limited,
        "repositories": reports,
    }
    output = (
        args.output or settings.output_dir / f"{args.partner.lower()}-repositories.json"
    )
    write_report(output, report)
    changed = sum(bool(item.get("changed_fields")) for item in reports)
    print(f"wrote {len(reports)} repositories, {changed} changed, to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
