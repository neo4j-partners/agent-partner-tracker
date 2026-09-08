#!/usr/bin/env python3
"""Small local SQLite catalog for Neo4j partner content."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


PARTNERS = ("AWS", "Databricks", "IBM")
CONTENT_TYPES = ("local_sample", "repository", "public_reference")
RELATIONSHIPS = ("direct", "supporting")
ITEM_STATUSES = ("active", "watch", "excluded", "archived")
GAP_STATUSES = ("open", "resolved", "no_evidence")
REVIEW_STATUSES = ("in_progress", "complete", "no_change", "partial", "blocked")
PUBLISHER_GROUPS = (
    "neo4j",
    "partner",
    "community",
    "not_applicable",
    "unclassified",
)
NAMED_PUBLISHER_GROUPS = frozenset({"neo4j", "partner", "community"})
TRACKING_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "source"}


def today() -> str:
    return date.today().isoformat()


def normalize_date(value: str | None, label: str) -> str | None:
    """Return an ISO date string, or None when no value is given."""
    if not value:
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as error:
        raise ValueError(f"{label} must use YYYY-MM-DD") from error


def valid_date(value: str) -> str:
    """Adapt normalize_date to the error type argparse expects."""
    try:
        parsed = normalize_date(value, "dates")
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error
    if parsed is None:
        raise argparse.ArgumentTypeError("dates must use YYYY-MM-DD")
    return parsed


def published_sort_date(value: str | None) -> str | None:
    """Return a sortable date only when the display date has a reliable month."""
    if not value:
        return None
    for pattern in ("%b %Y", "%B %Y"):
        try:
            return datetime.strptime(value, pattern).date().isoformat()
        except ValueError:
            continue
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def canonicalize_url(value: str | None) -> str | None:
    """Normalize enough URL variation to make catalog identity predictable."""
    if not value:
        return None
    parts = urlsplit(value.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("canonical URLs must be absolute http(s) URLs")
    query = [
        (key, item)
        for key, item in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_KEYS
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def connect(db_path: str) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def read_only_connection(path: Path) -> sqlite3.Connection:
    """Open the catalog for reading so no caller can change it by accident."""
    if not path.is_file():
        raise ValueError(f"database does not exist: {path}")
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def initialize(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS partners (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE CHECK (name IN ('AWS', 'Databricks', 'IBM')),
            last_completed_review_date TEXT,
            next_action TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS content_items (
            id INTEGER PRIMARY KEY,
            partner_id INTEGER NOT NULL REFERENCES partners(id),
            content_type TEXT NOT NULL CHECK (content_type IN ('local_sample', 'repository', 'public_reference')),
            title TEXT NOT NULL,
            summary TEXT NOT NULL,
            canonical_url TEXT,
            local_path TEXT,
            partner_products TEXT NOT NULL DEFAULT '',
            relationship TEXT NOT NULL CHECK (relationship IN ('direct', 'supporting')),
            status TEXT NOT NULL CHECK (status IN ('active', 'watch', 'excluded', 'archived')),
            decision_reason TEXT NOT NULL,
            evidence_url TEXT,
            published_date TEXT,
            published_sort_date TEXT,
            publisher_name TEXT,
            publisher_group TEXT NOT NULL DEFAULT 'unclassified'
                CHECK (
                    publisher_group IN (
                        'neo4j', 'partner', 'community',
                        'not_applicable', 'unclassified'
                    )
                ),
            first_seen_date TEXT NOT NULL,
            last_checked_date TEXT NOT NULL,
            CHECK (canonical_url IS NOT NULL OR local_path IS NOT NULL),
            CHECK (publisher_group != 'not_applicable' OR canonical_url IS NULL),
            CHECK (publisher_group != 'not_applicable' OR publisher_name IS NULL),
            CHECK (
                publisher_group NOT IN ('neo4j', 'partner', 'community')
                OR publisher_name IS NOT NULL
            )
        );
        CREATE UNIQUE INDEX IF NOT EXISTS one_url_per_partner
            ON content_items(partner_id, canonical_url) WHERE canonical_url IS NOT NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS one_path_per_partner
            ON content_items(partner_id, local_path) WHERE local_path IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_content_items_publisher_group
            ON content_items(publisher_group);

        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY,
            partner_id INTEGER NOT NULL REFERENCES partners(id),
            review_identifier TEXT NOT NULL,
            started_date TEXT NOT NULL,
            completed_date TEXT,
            review_window TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('in_progress', 'complete', 'no_change', 'partial', 'blocked')),
            sources_checked TEXT NOT NULL DEFAULT '',
            useful_queries TEXT NOT NULL DEFAULT '',
            result_summary TEXT NOT NULL,
            next_action TEXT NOT NULL,
            UNIQUE(partner_id, review_identifier)
        );

        CREATE TABLE IF NOT EXISTS research_gaps (
            id INTEGER PRIMARY KEY,
            partner_id INTEGER NOT NULL REFERENCES partners(id),
            product_area TEXT NOT NULL,
            gap_statement TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('open', 'resolved', 'no_evidence')),
            search_scope TEXT NOT NULL DEFAULT '',
            last_checked_date TEXT NOT NULL,
            next_check_date TEXT,
            next_action TEXT NOT NULL DEFAULT '',
            resolution_item_id INTEGER REFERENCES content_items(id),
            UNIQUE(partner_id, product_area)
        );

        CREATE TABLE IF NOT EXISTS markdown_archives (
            filename TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            byte_length INTEGER NOT NULL CHECK (byte_length >= 0),
            source_modified_at TEXT NOT NULL,
            archived_at TEXT NOT NULL
        );
        """
    )
    connection.executemany(
        "INSERT OR IGNORE INTO partners(name) VALUES (?)", ((name,) for name in PARTNERS)
    )
    connection.commit()


def partner_id(connection: sqlite3.Connection, partner: str) -> int:
    record = connection.execute("SELECT id FROM partners WHERE name = ?", (partner,)).fetchone()
    if not record:
        raise ValueError(f"unknown partner: {partner}")
    return int(record["id"])


def ensure_choice(value: str, allowed: tuple[str, ...], label: str) -> str:
    if value not in allowed:
        raise ValueError(f"{label} must be one of: {', '.join(allowed)}")
    return value


def normalize_publisher_fields(values: dict[str, str | None]) -> None:
    canonical_url = values.get("canonical_url")
    group = values.get("publisher_group")
    if not group:
        group = "not_applicable" if canonical_url is None else "unclassified"
    ensure_choice(group, PUBLISHER_GROUPS, "publisher group")

    name = (values.get("publisher_name") or "").strip() or None
    if group == "not_applicable" and canonical_url is not None:
        raise ValueError("not_applicable publisher group requires no canonical URL")
    if group == "not_applicable" and name is not None:
        raise ValueError("not_applicable publisher group cannot have a publisher name")
    if group in NAMED_PUBLISHER_GROUPS and name is None:
        raise ValueError(f"{group} publisher group requires a publisher name")

    values["publisher_name"] = name
    values["publisher_group"] = group


def clean_item_fields(
    values: dict[str, str | None], fill_missing: bool
) -> dict[str, str | None]:
    """Canonicalize URLs, trim the local path, and validate the sort date.

    `add_item` fills every cleaned field, because it writes a whole row.
    `update_item` cleans only the fields the caller supplied, so a field the
    caller left out stays untouched.
    """
    cleaned = values.copy()
    for key in ("canonical_url", "evidence_url"):
        if fill_missing or key in cleaned:
            cleaned[key] = canonicalize_url(cleaned.get(key))
    if fill_missing or "local_path" in cleaned:
        cleaned["local_path"] = (cleaned.get("local_path") or "").strip() or None
    if fill_missing or "published_sort_date" in cleaned:
        cleaned["published_sort_date"] = normalize_date(
            cleaned.get("published_sort_date"), "published sort date"
        )
    return cleaned


def add_item(connection: sqlite3.Connection, values: dict[str, str | None]) -> int:
    for key, allowed, label in (
        ("content_type", CONTENT_TYPES, "content type"),
        ("relationship", RELATIONSHIPS, "relationship"),
        ("status", ITEM_STATUSES, "item status"),
    ):
        ensure_choice(str(values[key]), allowed, label)
    values = clean_item_fields(values, fill_missing=True)
    if not values["canonical_url"] and not values["local_path"]:
        raise ValueError("provide --canonical-url and/or --local-path")
    normalize_publisher_fields(values)
    keys = tuple(values)
    cursor = connection.execute(
        f"INSERT INTO content_items ({', '.join(keys)}) VALUES ({', '.join('?' for _ in keys)})",
        tuple(values[key] for key in keys),
    )
    connection.commit()
    return int(cursor.lastrowid)


def update_item(
    connection: sqlite3.Connection, item_id: int, changes: dict[str, str | None]
) -> None:
    if not changes:
        raise ValueError("provide at least one field to update")
    current = connection.execute(
        """SELECT canonical_url, local_path, publisher_name, publisher_group
           FROM content_items WHERE id = ?""",
        (item_id,),
    ).fetchone()
    if not current:
        raise ValueError(f"content item {item_id} does not exist")
    for key, allowed, label in (
        ("content_type", CONTENT_TYPES, "content type"),
        ("relationship", RELATIONSHIPS, "relationship"),
        ("status", ITEM_STATUSES, "item status"),
        ("publisher_group", PUBLISHER_GROUPS, "publisher group"),
    ):
        if key in changes:
            ensure_choice(str(changes[key]), allowed, label)
    changes = clean_item_fields(changes, fill_missing=False)
    canonical_url = changes.get("canonical_url", current["canonical_url"])
    local_path = changes.get("local_path", current["local_path"])
    if not canonical_url and not local_path:
        raise ValueError("a content item must retain a canonical URL and/or local path")
    publisher_values = {
        "canonical_url": canonical_url,
        "publisher_name": changes.get("publisher_name", current["publisher_name"]),
        "publisher_group": changes.get("publisher_group", current["publisher_group"]),
    }
    normalize_publisher_fields(publisher_values)
    changes["publisher_name"] = publisher_values["publisher_name"]
    changes["publisher_group"] = publisher_values["publisher_group"]
    keys = tuple(changes)
    connection.execute(
        f"UPDATE content_items SET {', '.join(f'{key} = ?' for key in keys)} WHERE id = ?",
        (*[changes[key] for key in keys], item_id),
    )
    connection.commit()


def items_for(
    connection: sqlite3.Connection, partner: str, status: str | None = None
) -> list[sqlite3.Row]:
    query = """
        SELECT ci.*, p.name AS partner FROM content_items ci
        JOIN partners p ON p.id = ci.partner_id
        WHERE p.name = ?
    """
    parameters: list[str] = [partner]
    if status:
        ensure_choice(status, ITEM_STATUSES, "item status")
        query += " AND ci.status = ?"
        parameters.append(status)
    return connection.execute(query + " ORDER BY ci.content_type, ci.title", parameters).fetchall()


def print_items(rows: list[sqlite3.Row], as_json: bool = False) -> None:
    if as_json:
        print(json.dumps([dict(row) for row in rows], indent=2))
        return
    for row in rows:
        identity = row["canonical_url"] or row["local_path"]
        print(f"{row['id']}\t{row['content_type']}\t{row['status']}\t{row['title']}\t{identity}")


def export_markdown(rows: list[sqlite3.Row], partner: str) -> str:
    lines = [
        f"# {partner} current inventory",
        "",
        "| Type | Title | Summary | Products | Publisher | Group | URL or path |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        identity = row["canonical_url"] or row["local_path"]
        cells = [
            row["content_type"],
            row["title"],
            row["summary"],
            row["partner_products"],
            row["publisher_name"] or "",
            row["publisher_group"],
            identity,
        ]
        lines.append("| " + " | ".join(str(cell).replace("|", "\\|") for cell in cells) + " |")
    return "\n".join(lines)


def add_research_gap(connection: sqlite3.Connection, values: dict[str, str | None]) -> int:
    ensure_choice(str(values["status"]), GAP_STATUSES, "gap status")
    values = values.copy()
    values["last_checked_date"] = normalize_date(
        values.get("last_checked_date"), "last checked date"
    )
    values["next_check_date"] = normalize_date(
        values.get("next_check_date"), "next check date"
    )
    cursor = connection.execute(
        f"INSERT INTO research_gaps ({', '.join(values)}) "
        f"VALUES ({', '.join('?' for _ in values)})",
        tuple(values.values()),
    )
    connection.commit()
    return int(cursor.lastrowid)


def update_research_gap(
    connection: sqlite3.Connection, gap_id: int, changes: dict[str, str | None]
) -> None:
    if not changes:
        raise ValueError("provide at least one field to update")
    exists = connection.execute(
        "SELECT 1 FROM research_gaps WHERE id = ?", (gap_id,)
    ).fetchone()
    if not exists:
        raise ValueError(f"research gap {gap_id} does not exist")
    if "status" in changes:
        ensure_choice(str(changes["status"]), GAP_STATUSES, "gap status")
    for key, label in (
        ("last_checked_date", "last checked date"),
        ("next_check_date", "next check date"),
    ):
        if key in changes:
            changes[key] = normalize_date(changes[key], label)
    keys = tuple(changes)
    connection.execute(
        f"UPDATE research_gaps SET {', '.join(f'{key} = ?' for key in keys)} WHERE id = ?",
        (*[changes[key] for key in keys], gap_id),
    )
    connection.commit()


def research_gaps_for(
    connection: sqlite3.Connection, status: str | None = None
) -> list[sqlite3.Row]:
    query = """
        SELECT rg.*, p.name AS partner
        FROM research_gaps AS rg JOIN partners AS p ON p.id = rg.partner_id
    """
    parameters: list[str] = []
    if status:
        ensure_choice(status, GAP_STATUSES, "gap status")
        query += " WHERE rg.status = ?"
        parameters.append(status)
    return connection.execute(
        query + " ORDER BY p.name COLLATE NOCASE, rg.product_area COLLATE NOCASE",
        parameters,
    ).fetchall()


def partner_status(connection: sqlite3.Connection, partner: str) -> dict[str, object]:
    partner_row = connection.execute("SELECT * FROM partners WHERE name = ?", (partner,)).fetchone()
    reviews = connection.execute(
        """SELECT review_identifier, started_date, completed_date, status, result_summary, next_action
           FROM reviews WHERE partner_id = ? ORDER BY started_date DESC, id DESC""",
        (partner_row["id"],),
    ).fetchall()
    return {"partner": dict(partner_row), "reviews": [dict(row) for row in reviews]}


def archive_markdown(connection: sqlite3.Connection, source: Path) -> list[str]:
    """Archive every top-level Markdown document and verify its stored bytes."""
    archived_at = datetime.now(timezone.utc).isoformat()
    filenames: list[str] = []
    for path in sorted(source.glob("*.md")):
        content = path.read_text(encoding="utf-8")
        content_bytes = content.encode("utf-8")
        sha256 = hashlib.sha256(content_bytes).hexdigest()
        source_modified_at = datetime.fromtimestamp(
            path.stat().st_mtime, timezone.utc
        ).isoformat()
        connection.execute(
            """INSERT INTO markdown_archives(
                   filename, content, sha256, byte_length, source_modified_at, archived_at
               ) VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(filename) DO UPDATE SET
                   content=excluded.content,
                   sha256=excluded.sha256,
                   byte_length=excluded.byte_length,
                   source_modified_at=excluded.source_modified_at,
                   archived_at=excluded.archived_at""",
            (
                path.name,
                content,
                sha256,
                len(content_bytes),
                source_modified_at,
                archived_at,
            ),
        )
        stored = connection.execute(
            "SELECT content, sha256, byte_length FROM markdown_archives WHERE filename = ?",
            (path.name,),
        ).fetchone()
        if (
            not stored
            or stored["sha256"] != sha256
            or stored["byte_length"] != len(content_bytes)
            or stored["content"] != content
        ):
            raise ValueError(f"could not verify Markdown archive for {path.name}")
        filenames.append(path.name)
    connection.commit()
    return filenames


def list_markdown_archives(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        """SELECT filename, sha256, byte_length, source_modified_at, archived_at
           FROM markdown_archives ORDER BY filename"""
    ).fetchall()


def archived_markdown(connection: sqlite3.Connection, filename: str) -> str:
    archive = connection.execute(
        "SELECT content FROM markdown_archives WHERE filename = ?", (filename,)
    ).fetchone()
    if not archive:
        raise ValueError(f"no archived Markdown document named {filename}")
    return str(archive["content"])


def save_review(connection: sqlite3.Connection, values: dict[str, str | None]) -> None:
    review_status = str(values["status"])
    ensure_choice(review_status, REVIEW_STATUSES, "review status")
    values = values.copy()
    partner = str(values.pop("partner"))
    owner = partner_id(connection, partner)
    completed_date = values["completed_date"]
    if review_status in {"complete", "no_change"} and not completed_date:
        raise ValueError("complete and no_change reviews require a completed date")
    if review_status == "in_progress" and completed_date:
        raise ValueError("in_progress reviews cannot have a completed date")
    existing = connection.execute(
        "SELECT status FROM reviews WHERE partner_id = ? AND review_identifier = ?",
        (owner, values["review_identifier"]),
    ).fetchone()
    if existing:
        if existing["status"] != "in_progress":
            raise ValueError("only an in_progress review can be updated")
        keys = tuple(values)
        connection.execute(
            f"UPDATE reviews SET {', '.join(f'{key} = ?' for key in keys)} "
            "WHERE partner_id = ? AND review_identifier = ?",
            (*[values[key] for key in keys], owner, values["review_identifier"]),
        )
    else:
        keys = ("partner_id",) + tuple(values)
        connection.execute(
            f"INSERT INTO reviews ({', '.join(keys)}) VALUES ({', '.join('?' for _ in keys)})",
            (owner,) + tuple(values.values()),
        )
    if review_status in {"complete", "no_change"}:
        connection.execute(
            """UPDATE partners
               SET last_completed_review_date = ?, next_action = ?
               WHERE id = ?""",
            (completed_date, values["next_action"], owner),
        )
    connection.commit()


def run_init(connection: sqlite3.Connection, args: argparse.Namespace) -> None:
    print(f"initialized {args.db}")


def run_archive_markdown(
    connection: sqlite3.Connection, args: argparse.Namespace
) -> None:
    filenames = archive_markdown(connection, Path(args.source))
    print(f"archived and verified {len(filenames)} Markdown documents")


def run_archives(connection: sqlite3.Connection, args: argparse.Namespace) -> None:
    for archive in list_markdown_archives(connection):
        print(
            f"{archive['filename']}\t{archive['byte_length']}\t"
            f"{archive['sha256']}\t{archive['archived_at']}"
        )


def run_archive_show(connection: sqlite3.Connection, args: argparse.Namespace) -> None:
    print(archived_markdown(connection, args.filename), end="")


def run_add(connection: sqlite3.Connection, args: argparse.Namespace) -> None:
    values = {
        key: value
        for key, value in vars(args).items()
        if key not in {"db", "command", "func", "partner"}
    }
    values["partner_id"] = str(partner_id(connection, args.partner))
    print(f"added item {add_item(connection, values)}")


def run_update(connection: sqlite3.Connection, args: argparse.Namespace) -> None:
    changes = {
        key: value
        for key, value in vars(args).items()
        if key not in {"db", "command", "func", "id"}
    }
    update_item(connection, args.id, changes)
    print(f"updated item {args.id}")


def run_list(connection: sqlite3.Connection, args: argparse.Namespace) -> None:
    print_items(items_for(connection, args.partner, args.status), args.json)


def run_status(connection: sqlite3.Connection, args: argparse.Namespace) -> None:
    state = partner_status(connection, args.partner)
    if args.json:
        print(json.dumps(state, indent=2))
        return
    partner_row = state["partner"]
    print(
        f"{partner_row['name']}: last review "
        f"{partner_row['last_completed_review_date'] or 'none'}"
    )
    print(f"Next action: {partner_row['next_action'] or 'none'}")
    for review in state["reviews"]:
        print(
            f"{review['review_identifier']}\t{review['status']}\t"
            f"{review['completed_date'] or 'in progress'}\t{review['result_summary']}"
        )


def run_export(connection: sqlite3.Connection, args: argparse.Namespace) -> None:
    rows = items_for(connection, args.partner, "active")
    if args.format == "json":
        print(json.dumps([dict(row) for row in rows], indent=2))
    else:
        print(export_markdown(rows, args.partner))


def run_gap_add(connection: sqlite3.Connection, args: argparse.Namespace) -> None:
    values = {
        key: value
        for key, value in vars(args).items()
        if key not in {"db", "command", "func", "partner"}
    }
    values["partner_id"] = str(partner_id(connection, args.partner))
    print(f"added research gap {add_research_gap(connection, values)}")


def run_gap_update(connection: sqlite3.Connection, args: argparse.Namespace) -> None:
    changes = {
        key: value
        for key, value in vars(args).items()
        if key not in {"db", "command", "func", "id"}
    }
    update_research_gap(connection, args.id, changes)
    print(f"updated research gap {args.id}")


def run_gaps(connection: sqlite3.Connection, args: argparse.Namespace) -> None:
    rows = research_gaps_for(connection, args.status)
    if args.json:
        print(json.dumps([dict(row) for row in rows], indent=2))
        return
    for row in rows:
        print(
            f"{row['id']}\t{row['partner']}\t{row['status']}\t"
            f"{row['product_area']}\t{row['next_check_date'] or ''}"
        )


def run_review(connection: sqlite3.Connection, args: argparse.Namespace) -> None:
    values = {
        key: value
        for key, value in vars(args).items()
        if key not in {"db", "command", "func"}
    }
    save_review(connection, values)
    print(f"saved review {args.review_identifier}")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument(
        "--db",
        default="private/partner-tracking.db",
        help="private SQLite database path (default: private/partner-tracking.db)",
    )
    commands = root.add_subparsers(dest="command", required=True)

    commands.add_parser("init", help="create the catalog and its partner rows").set_defaults(
        func=run_init
    )

    archive = commands.add_parser(
        "archive-markdown", help="archive and verify all top-level Markdown documents"
    )
    archive.add_argument("--source", default=".", help="directory containing Markdown documents")
    archive.set_defaults(func=run_archive_markdown)

    commands.add_parser("archives", help="list archived Markdown documents").set_defaults(
        func=run_archives
    )

    archive_show = commands.add_parser(
        "archive-show", help="print an archived Markdown document"
    )
    archive_show.add_argument("--filename", required=True)
    archive_show.set_defaults(func=run_archive_show)

    add = commands.add_parser("add", help="add a content item")
    add.add_argument("--partner", required=True, choices=PARTNERS)
    add.add_argument("--type", dest="content_type", required=True, choices=CONTENT_TYPES)
    add.add_argument("--title", required=True)
    add.add_argument("--summary", required=True)
    add.add_argument("--relationship", required=True, choices=RELATIONSHIPS)
    add.add_argument("--status", required=True, choices=ITEM_STATUSES)
    add.add_argument("--reason", dest="decision_reason", required=True)
    add.add_argument("--canonical-url")
    add.add_argument("--local-path")
    add.add_argument("--products", dest="partner_products", default="")
    add.add_argument("--evidence-url")
    add.add_argument("--published-date")
    add.add_argument("--published-sort-date", type=valid_date)
    add.add_argument("--publisher-name")
    add.add_argument("--publisher-group", choices=PUBLISHER_GROUPS)
    add.add_argument("--first-seen", dest="first_seen_date", type=valid_date, default=today())
    add.add_argument("--last-checked", dest="last_checked_date", type=valid_date, default=today())
    add.set_defaults(func=run_add)

    update = commands.add_parser("update", help="update an item by ID")
    update.add_argument("id", type=int)
    for flag, destination, kind in (
        ("--type", "content_type", None),
        ("--title", "title", None),
        ("--summary", "summary", None),
        ("--canonical-url", "canonical_url", None),
        ("--local-path", "local_path", None),
        ("--products", "partner_products", None),
        ("--relationship", "relationship", None),
        ("--status", "status", None),
        ("--reason", "decision_reason", None),
        ("--evidence-url", "evidence_url", None),
        ("--published-date", "published_date", None),
        ("--published-sort-date", "published_sort_date", valid_date),
        ("--publisher-name", "publisher_name", None),
        ("--publisher-group", "publisher_group", None),
        ("--last-checked", "last_checked_date", valid_date),
    ):
        update.add_argument(
            flag,
            dest=destination,
            type=kind,
            choices=PUBLISHER_GROUPS if destination == "publisher_group" else None,
            default=argparse.SUPPRESS,
        )
    update.set_defaults(func=run_update)

    listing = commands.add_parser("list", help="list one partner's items")
    listing.add_argument("--partner", required=True, choices=PARTNERS)
    listing.add_argument("--status", choices=ITEM_STATUSES)
    listing.add_argument("--json", action="store_true")
    listing.set_defaults(func=run_list)

    status = commands.add_parser("status", help="show a partner's review state and summaries")
    status.add_argument("--partner", required=True, choices=PARTNERS)
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=run_status)

    export = commands.add_parser("export", help="export active inventory for one partner")
    export.add_argument("--partner", required=True, choices=PARTNERS)
    export.add_argument("--format", choices=("markdown", "json"), default="markdown")
    export.set_defaults(func=run_export)

    gaps = commands.add_parser("gaps", help="list research gaps")
    gaps.add_argument("--status", choices=GAP_STATUSES)
    gaps.add_argument("--json", action="store_true")
    gaps.set_defaults(func=run_gaps)

    gap_add = commands.add_parser("gap-add", help="add a research gap")
    gap_add.add_argument("--partner", required=True, choices=PARTNERS)
    gap_add.add_argument("--product-area", required=True)
    gap_add.add_argument("--statement", dest="gap_statement", required=True)
    gap_add.add_argument("--status", required=True, choices=GAP_STATUSES)
    gap_add.add_argument("--search-scope", default="")
    gap_add.add_argument("--last-checked", dest="last_checked_date", type=valid_date, default=today())
    gap_add.add_argument("--next-check", dest="next_check_date", type=valid_date)
    gap_add.add_argument("--next-action", default="")
    gap_add.add_argument("--resolution-item", dest="resolution_item_id", type=int)
    gap_add.set_defaults(func=run_gap_add)

    gap_update = commands.add_parser("gap-update", help="update a research gap")
    gap_update.add_argument("id", type=int)
    for flag, destination, kind in (
        ("--product-area", "product_area", None),
        ("--statement", "gap_statement", None),
        ("--status", "status", None),
        ("--search-scope", "search_scope", None),
        ("--last-checked", "last_checked_date", valid_date),
        ("--next-check", "next_check_date", valid_date),
        ("--next-action", "next_action", None),
        ("--resolution-item", "resolution_item_id", int),
    ):
        gap_update.add_argument(
            flag,
            dest=destination,
            type=kind,
            choices=GAP_STATUSES if destination == "status" else None,
            default=argparse.SUPPRESS,
        )
    gap_update.set_defaults(func=run_gap_update)

    review = commands.add_parser("review", help="save a partner review summary")
    review.add_argument("--partner", required=True, choices=PARTNERS)
    review.add_argument("--id", dest="review_identifier", required=True)
    review.add_argument("--status", required=True, choices=REVIEW_STATUSES)
    review.add_argument("--summary", dest="result_summary", required=True)
    review.add_argument("--next-action", required=True)
    review.add_argument("--started", dest="started_date", type=valid_date, default=today())
    review.add_argument("--completed", dest="completed_date", type=valid_date)
    review.add_argument("--window", dest="review_window", required=True)
    review.add_argument("--sources", dest="sources_checked", default="")
    review.add_argument("--queries", dest="useful_queries", default="")
    review.set_defaults(func=run_review)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    connection = connect(args.db)
    try:
        initialize(connection)
        args.func(connection, args)
    except (ValueError, sqlite3.IntegrityError) as error:
        connection.rollback()
        print(f"error: {error}", file=sys.stderr)
        return 2
    finally:
        connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
