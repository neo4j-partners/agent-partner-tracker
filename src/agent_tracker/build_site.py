"""Generate the public partner tracker site from SQLite."""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit

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


def validated_url(value: str | None) -> str | None:
    if not value:
        return None
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError(f"unsafe public URL: {value}")
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
    }


def render_site(
    database: Path, output: Path, templates: Path, assets: Path
) -> dict[str, object]:
    if not templates.is_dir():
        raise ValueError(f"template directory does not exist: {templates}")
    if not assets.is_dir():
        raise ValueError(f"asset directory does not exist: {assets}")

    with closing(tracker.read_only_connection(database)) as connection:
        data = site_data(connection)

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
    root.add_argument("--db", type=Path, default=Path("partner-tracking.db"))
    root.add_argument("--output", type=Path, default=Path("_site"))
    root.add_argument("--templates", type=Path, default=Path("site/templates"))
    root.add_argument("--assets", type=Path, default=Path("site/assets"))
    return root


def main() -> int:
    args = parser().parse_args()
    print(f"status: building static site from {args.db}")
    try:
        data = render_site(args.db, args.output, args.templates, args.assets)
    except (OSError, sqlite3.Error, ValueError) as error:
        print(f"status: failed: {error}", file=sys.stderr)
        return 1
    print(f"statistics: {build_statistics(data)}")
    print(f"status: generated {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
