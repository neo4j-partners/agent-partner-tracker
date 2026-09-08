import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

from agent_tracker import partner_tracker as tracker
from agent_tracker.build_site import export_public_data


PROJECT_ROOT = Path(__file__).parents[1]


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "a" and "href" in attributes:
            self.links.append(attributes["href"])
        if tag == "script" and "src" in attributes:
            self.links.append(attributes["src"])
        if tag == "link" and "href" in attributes:
            self.links.append(attributes["href"])


@unittest.skipUnless(importlib.util.find_spec("jinja2"), "Jinja2 is not installed")
class StaticSiteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = self.root / "tracker.db"
        connection = tracker.connect(str(self.database))
        tracker.initialize(connection)
        owner = str(tracker.partner_id(connection, "AWS"))
        common = {
            "partner_id": owner,
            "partner_products": "Bedrock",
            "relationship": "direct",
            "status": "active",
            "decision_reason": "Public fixture.",
            "evidence_url": None,
            "first_seen_date": "2026-09-08",
            "last_checked_date": "2026-09-08",
        }
        tracker.add_item(
            connection,
            {
                **common,
                "content_type": "local_sample",
                "title": "Internal sample",
                "summary": "Local only.",
                "canonical_url": None,
                "local_path": "private/sample-path",
                "published_date": None,
            },
        )
        tracker.add_research_gap(
            connection,
            {
                "partner_id": owner,
                "product_area": "Amazon OpenSearch",
                "gap_statement": "No direct technical example found.",
                "status": "open",
                "search_scope": "Official sources.",
                "last_checked_date": "2026-09-08",
                "next_check_date": "2026-12-08",
                "next_action": "Recheck official examples.",
                "resolution_item_id": None,
            },
        )
        tracker.add_item(
            connection,
            {
                **common,
                "content_type": "repository",
                "title": "Public repository",
                "summary": "Repository fixture.",
                "canonical_url": "https://github.com/neo4j/example",
                "local_path": None,
                "publisher_name": "Neo4j",
                "publisher_group": "neo4j",
                "published_date": None,
            },
        )
        tracker.add_item(
            connection,
            {
                **common,
                "content_type": "public_reference",
                "title": "<script>alert('escaped')</script>",
                "summary": "Public article.",
                "canonical_url": "https://aws.amazon.com/example",
                "local_path": None,
                "publisher_name": "AWS",
                "publisher_group": "partner",
                "published_date": "Sep 2026",
                "published_sort_date": "2026-09-01",
            },
        )
        connection.execute(
            """UPDATE partners
               SET last_completed_review_date = '2026-09-08'
               WHERE name = 'AWS'"""
        )
        connection.commit()
        connection.close()

    def tearDown(self):
        self.temp.cleanup()

    def generate(self, public_data=None):
        output = self.root / "_site"
        source = ["--data", str(public_data)] if public_data else ["--db", str(self.database)]
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "agent_tracker.build_site",
                *source,
                "--output",
                str(output),
                "--templates",
                str(PROJECT_ROOT / "site/templates"),
                "--assets",
                str(PROJECT_ROOT / "site/assets"),
            ],
            check=False,
            capture_output=True,
            text=True,
        )

    def artifact_digest(self):
        output = self.root / "_site"
        digest = hashlib.sha256()
        for path in sorted(item for item in output.rglob("*") if item.is_file()):
            digest.update(str(path.relative_to(output)).encode())
            digest.update(path.read_bytes())
        return digest.hexdigest()

    def test_build_is_private_safe_and_deterministic(self):
        database_before = hashlib.sha256(self.database.read_bytes()).hexdigest()
        first = self.generate()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn(
            f"status: building static site from {self.database}", first.stdout
        )
        self.assertIn(
            "statistics: 2 integration assets, 1 article, 1 partner, "
            "data through 2026-09-08",
            first.stdout,
        )
        self.assertIn("status: generated", first.stdout)
        first_digest = self.artifact_digest()

        output = self.root / "_site"
        files = {
            str(path.relative_to(output))
            for path in output.rglob("*")
            if path.is_file()
        }
        self.assertEqual(
            files,
            {
                ".nojekyll",
                "articles.html",
                "assets/site.css",
                "assets/tables.js",
                "index.html",
                "integration-assets.html",
                "research-gaps.html",
            },
        )
        index = (output / "index.html").read_text(encoding="utf-8")
        integrations = (output / "integration-assets.html").read_text(
            encoding="utf-8"
        )
        articles = (output / "articles.html").read_text(encoding="utf-8")
        gaps = (output / "research-gaps.html").read_text(encoding="utf-8")
        self.assertIn('<p class="metric-label">AWS Integration Assets</p>', index)
        self.assertIn('<p class="metric-label">AWS Articles</p>', index)
        self.assertIn('<p class="metric-value">2</p>', index)
        self.assertIn('<p class="metric-value">1</p>', index)
        self.assertNotIn("private/sample-path", integrations)
        self.assertNotIn("<script>alert('escaped')</script>", articles)
        self.assertIn("&lt;script&gt;alert", articles)
        self.assertIn("Amazon OpenSearch", gaps)

        parser = LinkParser()
        for page in (index, integrations, articles, gaps):
            parser.feed(page)
        self.assertFalse(any(link.startswith("/") for link in parser.links))
        self.assertFalse(any(link.startswith(("file:", "javascript:")) for link in parser.links))

        second = self.generate()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(first_digest, self.artifact_digest())
        self.assertEqual(
            database_before, hashlib.sha256(self.database.read_bytes()).hexdigest()
        )

    def test_build_rejects_unclassified_public_record(self):
        connection = tracker.connect(str(self.database))
        connection.execute(
            """UPDATE content_items
               SET publisher_name = NULL, publisher_group = 'unclassified'
               WHERE content_type = 'repository'"""
        )
        connection.commit()
        connection.close()

        result = self.generate()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("need publisher classification", result.stderr)
        self.assertIn("status: failed:", result.stderr)

    def test_public_data_export_excludes_private_fields_and_builds(self):
        public_data = self.root / "public-data.json"
        export_public_data(self.database, public_data)
        exported = public_data.read_text(encoding="utf-8")
        self.assertNotIn("private/sample-path", exported)
        self.assertNotIn("Public fixture.", exported)
        self.assertNotIn("evidence_url", exported)
        self.assertNotIn("/Users/", exported)

        result = self.generate(public_data)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"status: building static site from {public_data}", result.stdout)

    def test_public_data_rejects_sensitive_url_query(self):
        public_data = self.root / "public-data.json"
        export_public_data(self.database, public_data)
        data = json.loads(public_data.read_text(encoding="utf-8"))
        data["articles"][0]["canonical_url"] += "?token=not-public"
        public_data.write_text(json.dumps(data), encoding="utf-8")

        result = self.generate(public_data)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsafe public URL query", result.stderr)

    def test_public_data_rejects_private_data_marker(self):
        public_data = self.root / "public-data.json"
        export_public_data(self.database, public_data)
        data = json.loads(public_data.read_text(encoding="utf-8"))
        data["articles"][0]["summary"] = "Stored under /Users/private"
        public_data.write_text(json.dumps(data), encoding="utf-8")

        result = self.generate(public_data)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("private-data marker", result.stderr)


if __name__ == "__main__":
    unittest.main()
