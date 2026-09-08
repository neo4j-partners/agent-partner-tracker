#!/usr/bin/env python3
"""Validate that every generated site link stays inside the published site."""

from __future__ import annotations

import argparse
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


class ReferenceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.references: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        attributes = dict(attrs)
        if tag == "a" and attributes.get("href"):
            self.references.append(str(attributes["href"]))
        elif tag == "script" and attributes.get("src"):
            self.references.append(str(attributes["src"]))
        elif tag == "link" and attributes.get("href"):
            self.references.append(str(attributes["href"]))


def page_references(path: Path) -> list[str]:
    parser = ReferenceParser()
    parser.feed(path.read_text(encoding="utf-8"))
    return parser.references


def validate_structure(site: Path) -> set[str]:
    """Check every internal reference and return the external URLs found."""
    root = site.resolve()
    errors: list[str] = []
    external: set[str] = set()
    pages = sorted(site.glob("*.html"))
    if not pages:
        raise ValueError(f"no HTML pages found in {site}")

    for page in pages:
        for reference in page_references(page):
            parts = urlsplit(reference)
            if parts.scheme in {"http", "https"}:
                external.add(reference)
                continue
            if parts.scheme:
                errors.append(f"{page.name}: unsafe scheme in {reference}")
                continue
            if reference.startswith("/"):
                errors.append(f"{page.name}: root-relative reference {reference}")
                continue
            if not parts.path:
                continue
            target = (page.parent / unquote(parts.path)).resolve()
            if not target.is_relative_to(root):
                errors.append(f"{page.name}: reference escapes site root: {reference}")
            elif not target.is_file():
                errors.append(f"{page.name}: missing internal target: {reference}")

    if errors:
        raise ValueError("\n".join(errors))
    return external


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("site", type=Path, nargs="?", default=Path("_site"))
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        external = validate_structure(args.site)
    except (OSError, ValueError) as error:
        raise SystemExit(f"error: {error}") from error
    print(
        f"structural links: ok; pages: {len(list(args.site.glob('*.html')))}; "
        f"external links: {len(external)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
