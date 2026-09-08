"""Generate the public partner tracker site from SQLite."""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import partner_tracker as tracker


PUBLIC_WHERE = "ci.status = 'active' AND ci.relationship = 'direct'"
NAMED_PUBLISHER_GROUPS = ("neo4j", "partner", "community")
PUBLISHER_GROUP_LABELS = {
    "neo4j": "Neo4j",
    "partner": "Partner",
    "community": "Community",
    "not_applicable": "Not applicable",
    "unclassified": "Needs classification",
}
PUBLIC_QUERY_KEYS = frozenset({"topic"})
PRIVATE_DATA_MARKERS = (
    "/users/",
    "/home/",
    "brave_api_key",
    "github_token",
    "begin private key",
)
PUBLIC_ITEM_FIELDS = frozenset(
    {
        "id",
        "partner",
        "content_type",
        "title",
        "summary",
        "canonical_url",
        "partner_products",
        "publisher_name",
        "publisher_group",
        "published_date",
        "published_sort_date",
        "published_sort_value",
        "last_checked_date",
        "publisher_group_label",
        "content_type_label",
    }
)
PUBLIC_DATA_FIELDS = frozenset(
    {
        "integration_assets",
        "articles",
        "publisher_metrics",
        "partner_metrics",
        "reviews",
        "data_through",
        "partners",
        "research_gaps",
    }
)
PUBLIC_GAP_FIELDS = frozenset(
    {
        "partner",
        "product_area",
        "gap_statement",
        "status",
        "last_checked_date",
        "next_check_date",
        "next_action",
    }
)


def validated_url(value: str | None) -> str | None:
    if not value:
        return None
    parts = urlsplit(value)
    if parts.scheme != "https" or not parts.netloc:
        raise ValueError(f"unsafe public URL: {value}")
    if parts.username or parts.password:
        raise ValueError(f"unsafe public URL: {value}")
    query_keys = {
        key.lower() for key, _ in parse_qsl(parts.query, keep_blank_values=True)
    }
    if not query_keys <= PUBLIC_QUERY_KEYS:
        raise ValueError(f"unsafe public URL query: {value}")
    return value


def public_rows(
    connection: sqlite3.Connection, content_types: tuple[str, ...]
) -> list[dict[str, object]]:
    placeholders = ", ".join("?" for _ in content_types)
    rows = connection.execute(
        f"""
        SELECT
            ci.id,
            p.name AS partner,
            ci.content_type,
            ci.title,
            ci.summary,
            ci.canonical_url,
            ci.partner_products,
            ci.publisher_name,
            ci.publisher_group,
            ci.published_date,
            ci.published_sort_date,
            ci.last_checked_date
        FROM content_items AS ci
        JOIN partners AS p ON p.id = ci.partner_id
        WHERE {PUBLIC_WHERE}
          AND ci.content_type IN ({placeholders})
        ORDER BY
            p.name COLLATE NOCASE,
            ci.title COLLATE NOCASE,
            ci.id
        """,
        content_types,
    ).fetchall()
    result: list[dict[str, object]] = []
    for row in rows:
        item = dict(row)
        item["canonical_url"] = validated_url(row["canonical_url"])
        item["publisher_group_label"] = PUBLISHER_GROUP_LABELS[
            row["publisher_group"]
        ]
        item["content_type_label"] = {
            "local_sample": "Sample",
            "repository": "Repository",
            "public_reference": "Article",
        }[row["content_type"]]
        item["published_sort_value"] = row["published_sort_date"] or "9999-12-31"
        result.append(item)
    return result


def publisher_metrics(connection: sqlite3.Connection) -> dict[str, dict[str, object]]:
    """Count public repositories and articles for each publisher group."""
    counts = {
        group: {"label": PUBLISHER_GROUP_LABELS[group], "repository": 0, "public_reference": 0}
        for group in NAMED_PUBLISHER_GROUPS
    }
    rows = connection.execute(
        f"""
        SELECT ci.publisher_group, ci.content_type, COUNT(*) AS total
        FROM content_items AS ci
        WHERE {PUBLIC_WHERE}
          AND ci.publisher_group IN ('neo4j', 'partner', 'community')
          AND ci.content_type IN ('repository', 'public_reference')
        GROUP BY ci.publisher_group, ci.content_type
        """
    ).fetchall()
    for row in rows:
        counts[row["publisher_group"]][row["content_type"]] = row["total"]
    return {
        group: {
            "label": entry["label"],
            "integration_count": entry["repository"],
            "article_count": entry["public_reference"],
            "total": entry["repository"] + entry["public_reference"],
        }
        for group, entry in counts.items()
    }


def partner_metrics(connection: sqlite3.Connection) -> dict[str, dict[str, object]]:
    """Count integration assets and articles for each partner."""
    rows = connection.execute(
        f"""
        SELECT p.name AS partner, ci.content_type, COUNT(*) AS total
        FROM content_items AS ci
        JOIN partners AS p ON p.id = ci.partner_id
        WHERE {PUBLIC_WHERE}
          AND ci.content_type IN ('local_sample', 'repository', 'public_reference')
        GROUP BY p.name, ci.content_type
        """
    ).fetchall()
    counts: dict[str, dict[str, int]] = {}
    for row in rows:
        entry = counts.setdefault(
            row["partner"], {"integration_count": 0, "article_count": 0}
        )
        if row["content_type"] == "public_reference":
            entry["article_count"] += row["total"]
        else:
            entry["integration_count"] += row["total"]
    return {
        partner: {
            "integration_count": entry["integration_count"],
            "article_count": entry["article_count"],
        }
        for partner, entry in counts.items()
    }


def public_research_gaps(connection: sqlite3.Connection) -> list[dict[str, object]]:
    rows = connection.execute(
        """SELECT p.name AS partner, rg.product_area, rg.gap_statement, rg.status,
                  rg.last_checked_date, rg.next_check_date, rg.next_action
           FROM research_gaps AS rg JOIN partners AS p ON p.id = rg.partner_id
           WHERE rg.status = 'open'
           ORDER BY p.name COLLATE NOCASE, rg.product_area COLLATE NOCASE"""
    ).fetchall()
    return [dict(row) for row in rows]


def site_data(connection: sqlite3.Connection) -> dict[str, object]:
    invalid_publishers = connection.execute(
        f"""
        SELECT COUNT(*)
        FROM content_items AS ci
        WHERE {PUBLIC_WHERE}
          AND ci.canonical_url IS NOT NULL
          AND (
              ci.publisher_name IS NULL
              OR ci.publisher_group IN ('unclassified', 'not_applicable')
          )
        """
    ).fetchone()[0]
    if invalid_publishers:
        raise ValueError(
            f"{invalid_publishers} public records need publisher classification"
        )

    integration_assets = public_rows(connection, ("local_sample", "repository"))
    articles = public_rows(connection, ("public_reference",))
    research_gaps = public_research_gaps(connection)
    missing_article_urls = sum(1 for article in articles if not article["canonical_url"])
    if missing_article_urls:
        raise ValueError(
            f"{missing_article_urls} public articles are missing a canonical URL"
        )
    reviews = [
        dict(row)
        for row in connection.execute(
            """SELECT name, last_completed_review_date
               FROM partners ORDER BY name COLLATE NOCASE"""
        ).fetchall()
    ]
    data_through = connection.execute(
        f"""SELECT MAX(ci.last_checked_date)
            FROM content_items AS ci WHERE {PUBLIC_WHERE}"""
    ).fetchone()[0]
    return {
        "integration_assets": integration_assets,
        "articles": articles,
        "publisher_metrics": publisher_metrics(connection),
        "partner_metrics": partner_metrics(connection),
        "reviews": reviews,
        "data_through": data_through,
        "partners": sorted({row["partner"] for row in integration_assets + articles}),
        "research_gaps": research_gaps,
    }


def export_public_data(database: Path, output: Path) -> dict[str, object]:
    """Write the strictly public site projection from a private SQLite catalog."""
    with closing(tracker.read_only_connection(database)) as connection:
        data = site_data(connection)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return data


def load_public_data(path: Path) -> dict[str, object]:
    """Load a reviewed public-data export without accepting internal fields."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid public data JSON: {path}") from error
    if not isinstance(data, dict) or set(data) != PUBLIC_DATA_FIELDS:
        raise ValueError("public data has an unexpected schema")
    for key in ("integration_assets", "articles", "reviews", "partners", "research_gaps"):
        if not isinstance(data[key], list):
            raise ValueError(f"public data field {key} must be a list")
    for key in ("publisher_metrics", "partner_metrics"):
        if not isinstance(data[key], dict):
            raise ValueError(f"public data field {key} must be an object")
    for item in [*data["integration_assets"], *data["articles"]]:
        if not isinstance(item, dict) or set(item) != PUBLIC_ITEM_FIELDS:
            raise ValueError("public data item has an unexpected schema")
        validated_url(item["canonical_url"])
    for review in data["reviews"]:
        if not isinstance(review, dict) or set(review) != {
            "name",
            "last_completed_review_date",
        }:
            raise ValueError("public review has an unexpected schema")
    for gap in data["research_gaps"]:
        if not isinstance(gap, dict) or set(gap) != PUBLIC_GAP_FIELDS:
            raise ValueError("public research gap has an unexpected schema")
    serialized = json.dumps(data, sort_keys=True).lower()
    if any(marker in serialized for marker in PRIVATE_DATA_MARKERS):
        raise ValueError("public data contains a private-data marker")
    return data


def render_site(
    database: Path, output: Path, templates: Path, assets: Path
) -> dict[str, object]:
    with closing(tracker.read_only_connection(database)) as connection:
        data = site_data(connection)
    return render_data(data, output, templates, assets)


def render_public_data(
    public_data: Path, output: Path, templates: Path, assets: Path
) -> dict[str, object]:
    """Generate the site from a checked-in, sanitized public-data export."""
    return render_data(load_public_data(public_data), output, templates, assets)


def render_data(
    data: dict[str, object], output: Path, templates: Path, assets: Path
) -> dict[str, object]:
    """Render a validated public data projection into the static site."""
    if not templates.is_dir():
        raise ValueError(f"template directory does not exist: {templates}")
    if not assets.is_dir():
        raise ValueError(f"asset directory does not exist: {assets}")

    environment = Environment(
        loader=FileSystemLoader(templates),
        autoescape=select_autoescape(enabled_extensions=("html",), default=True),
        keep_trailing_newline=True,
    )
    environment.globals["publisher_group_labels"] = PUBLISHER_GROUP_LABELS

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="partner-site-", dir=output.parent
    ) as temporary:
        staging = Path(temporary)
        pages = {
            "index.html": ("dashboard.html", {}),
            "integration-assets.html": (
                "integration-assets.html",
                {"items": data["integration_assets"]},
            ),
            "articles.html": ("articles.html", {"items": data["articles"]}),
            "research-gaps.html": (
                "research-gaps.html",
                {"items": data["research_gaps"]},
            ),
        }
        for filename, (template_name, context) in pages.items():
            rendered = environment.get_template(template_name).render(
                **data,
                **context,
                current_page=filename,
            )
            (staging / filename).write_text(rendered, encoding="utf-8")
        shutil.copytree(assets, staging / "assets")
        (staging / ".nojekyll").write_text("", encoding="utf-8")

        if output.exists():
            shutil.rmtree(output)
        staging.rename(output)
    return data


def build_statistics(data: dict[str, object]) -> str:
    """Format the public content totals included in a generated site."""
    integration_count = len(data["integration_assets"])
    article_count = len(data["articles"])
    partner_count = len(data["partners"])
    data_through = data["data_through"] or "not available"

    def count(value: int, label: str) -> str:
        suffix = "" if value == 1 else "s"
        return f"{value} {label}{suffix}"

    return ", ".join(
        (
            count(integration_count, "integration asset"),
            count(article_count, "article"),
            count(partner_count, "partner"),
            f"data through {data_through}",
        )
    )


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    source = root.add_mutually_exclusive_group(required=True)
    source.add_argument("--db", type=Path, help="private SQLite catalog")
    source.add_argument("--data", type=Path, help="sanitized public-data JSON")
    root.add_argument("--output", type=Path, default=Path("_site"))
    root.add_argument("--templates", type=Path, default=Path("site/templates"))
    root.add_argument("--assets", type=Path, default=Path("site/assets"))
    return root


def main() -> int:
    args = parser().parse_args()
    source = args.db or args.data
    print(f"status: building static site from {source}")
    try:
        if args.db:
            data = render_site(args.db, args.output, args.templates, args.assets)
        else:
            data = render_public_data(args.data, args.output, args.templates, args.assets)
    except (OSError, sqlite3.Error, ValueError) as error:
        print(f"status: failed: {error}", file=sys.stderr)
        return 1
    print(f"statistics: {build_statistics(data)}")
    print(f"status: generated {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
