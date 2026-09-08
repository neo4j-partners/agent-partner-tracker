"""Shared helpers for read-only partner content discovery."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .partner_tracker import PARTNERS, read_only_connection


__all__ = [
    "PARTNERS",
    "EnvSettings",
    "freshness_value",
    "read_partner_review_date",
    "request_json",
    "review_window",
    "utc_now",
    "write_report",
]

DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_OUTPUT_DIR = "private/reports"


def load_env_file(path: Path) -> dict[str, str]:
    """Load simple KEY=VALUE settings without replacing process environment values."""
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not key.strip():
            raise ValueError(f"invalid environment setting in {path}: {raw_line}")
        values[key.strip()] = value.strip()
    return values


@dataclass(frozen=True)
class EnvSettings:
    """Settings read once from the process environment and the .env file."""

    brave_api_key: str | None
    github_token: str | None
    timeout: int
    output_dir: Path

    @classmethod
    def load(cls, env_file: Path) -> EnvSettings:
        values = load_env_file(env_file)

        def setting(name: str) -> str | None:
            return os.environ.get(name) or values.get(name)

        raw_timeout = setting("REQUEST_TIMEOUT_SECONDS")
        timeout = int(raw_timeout) if raw_timeout else DEFAULT_TIMEOUT_SECONDS
        if timeout <= 0:
            raise ValueError("REQUEST_TIMEOUT_SECONDS must be greater than zero")
        return cls(
            brave_api_key=setting("BRAVE_API_KEY"),
            github_token=setting("GITHUB_TOKEN"),
            timeout=timeout,
            output_dir=Path(setting("DISCOVERY_OUTPUT_DIR") or DEFAULT_OUTPUT_DIR),
        )

    def require_brave_api_key(self) -> str:
        if not self.brave_api_key:
            raise ValueError(
                "BRAVE_API_KEY is required. Copy .env.sample to .env and set it."
            )
        return self.brave_api_key


def read_partner_review_date(db_path: Path, partner: str) -> date | None:
    connection = read_only_connection(db_path)
    try:
        row = connection.execute(
            "SELECT last_completed_review_date FROM partners WHERE name = ?", (partner,)
        ).fetchone()
    finally:
        connection.close()
    if not row or not row[0]:
        return None
    return date.fromisoformat(str(row[0]))


def review_window(
    db_path: Path, partner: str, start: str | None, end: str | None
) -> tuple[date, date]:
    end_date = date.fromisoformat(end) if end else date.today()
    if start:
        start_date = date.fromisoformat(start)
    else:
        last_review = read_partner_review_date(db_path, partner)
        start_date = (
            last_review - timedelta(days=7) if last_review else end_date - timedelta(days=30)
        )
    if start_date > end_date:
        raise ValueError("the review start date must be on or before the end date")
    return start_date, end_date


def freshness_value(start: date, end: date) -> str:
    return f"{start.isoformat()}to{end.isoformat()}"


def request_json(
    url: str,
    params: dict[str, str | int | bool],
    headers: dict[str, str],
    timeout: int,
) -> dict[str, Any]:
    query = urlencode(params)
    request = Request(f"{url}?{query}", headers=headers)
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
