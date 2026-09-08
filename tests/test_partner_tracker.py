import sqlite3
import tempfile
import unittest
from pathlib import Path

from agent_tracker import partner_tracker as tracker


class PartnerTrackerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.temp.name) / "tracker.db")
        self.connection = tracker.connect(self.db)
        tracker.initialize(self.connection)

    def tearDown(self):
        self.connection.close()
        self.temp.cleanup()

    def item(self, **extra):
        values = {"partner_id": str(tracker.partner_id(self.connection, "AWS")), "content_type": "public_reference",
                  "title": "Example", "summary": "Useful example.", "canonical_url": "https://Example.com/a/?utm_source=test",
                  "local_path": None, "partner_products": "Bedrock", "relationship": "direct", "status": "active",
                  "decision_reason": "Direct technical relationship.", "evidence_url": None,
                  "published_date": None, "first_seen_date": "2026-09-08", "last_checked_date": "2026-09-08"}
        values.update(extra)
        return values

    def test_initialization_creates_required_partners(self):
        rows = self.connection.execute("SELECT name FROM partners ORDER BY name").fetchall()
        self.assertEqual([row["name"] for row in rows], ["AWS", "Databricks", "IBM"])

    def test_local_item_defaults_to_not_applicable_publisher(self):
        item_id = tracker.add_item(
            self.connection,
            self.item(
                content_type="local_sample",
                canonical_url=None,
                local_path="samples/example",
            ),
        )
        row = self.connection.execute(
            "SELECT publisher_name, publisher_group FROM content_items WHERE id = ?",
            (item_id,),
        ).fetchone()
        self.assertIsNone(row["publisher_name"])
        self.assertEqual(row["publisher_group"], "not_applicable")

    def test_named_publisher_group_requires_a_name(self):
        with self.assertRaisesRegex(ValueError, "requires a publisher name"):
            tracker.add_item(
                self.connection,
                self.item(publisher_group="neo4j", publisher_name=None),
            )

    def test_reliable_display_month_has_sort_date(self):
        self.assertEqual(tracker.published_sort_date("Sep 2026"), "2026-09-01")
        self.assertIsNone(tracker.published_sort_date("c. 2026"))
        self.assertIsNone(tracker.published_sort_date("Living documentation"))

    def test_url_normalization_prevents_partner_duplicate(self):
        tracker.add_item(self.connection, self.item())
        with self.assertRaises(sqlite3.IntegrityError):
            tracker.add_item(self.connection, self.item(canonical_url="https://example.com/a#section"))

    def test_same_url_is_allowed_for_another_partner(self):
        tracker.add_item(self.connection, self.item())
        tracker.add_item(self.connection, self.item(partner_id=str(tracker.partner_id(self.connection, "IBM"))))
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM content_items").fetchone()[0], 2)

    def test_status_change_affects_active_inventory(self):
        item_id = tracker.add_item(self.connection, self.item())
        tracker.update_item(self.connection, item_id, {"status": "archived"})
        self.assertEqual(tracker.items_for(self.connection, "AWS", "active"), [])

    def test_item_cannot_lose_its_only_identity(self):
        item_id = tracker.add_item(self.connection, self.item())
        with self.assertRaisesRegex(ValueError, "must retain"):
            tracker.update_item(self.connection, item_id, {"canonical_url": None})

    def test_complete_review_updates_partner_state(self):
        tracker.save_review(self.connection, {"partner": "AWS", "review_identifier": "review-1", "started_date": "2026-09-08",
                                               "completed_date": "2026-09-09", "review_window": "2026-09-01 to 2026-09-09", "status": "complete",
                                               "sources_checked": "Neo4j", "useful_queries": "site:neo4j.com",
                                               "result_summary": "Baseline complete.", "next_action": "Check official sources."})
        partner = self.connection.execute("SELECT * FROM partners WHERE name='AWS'").fetchone()
        self.assertEqual(partner["last_completed_review_date"], "2026-09-09")
        self.assertEqual(partner["next_action"], "Check official sources.")
        state = tracker.partner_status(self.connection, "AWS")
        self.assertEqual(state["reviews"][0]["review_identifier"], "review-1")

    def test_in_progress_review_can_be_finalized_with_the_same_identifier(self):
        review = {"partner": "AWS", "review_identifier": "review-1", "started_date": "2026-09-08",
                  "completed_date": None, "review_window": "2026-09-01 to 2026-09-09", "status": "in_progress",
                  "sources_checked": "Neo4j", "useful_queries": "",
                  "result_summary": "Checking sources.", "next_action": "Finish the review."}
        tracker.save_review(self.connection, review)
        review.update({"completed_date": "2026-09-09", "status": "complete", "result_summary": "Complete.",
                       "next_action": "Check official sources."})
        tracker.save_review(self.connection, review)
        state = tracker.partner_status(self.connection, "AWS")
        self.assertEqual(len(state["reviews"]), 1)
        self.assertEqual(state["reviews"][0]["status"], "complete")
        self.assertEqual(state["partner"]["last_completed_review_date"], "2026-09-09")

    def test_markdown_archive_preserves_text_and_checksum(self):
        source = Path(self.temp.name) / "documents"
        source.mkdir()
        document = source / "history.md"
        document.write_text("# Historical record\n\nRetain this exactly.\n", encoding="utf-8")
        self.assertEqual(tracker.archive_markdown(self.connection, source), ["history.md"])
        archive = tracker.list_markdown_archives(self.connection)
        self.assertEqual(archive[0]["filename"], "history.md")
        self.assertEqual(archive[0]["byte_length"], len(document.read_bytes()))
        self.assertEqual(tracker.archived_markdown(self.connection, "history.md"), document.read_text())


if __name__ == "__main__":
    unittest.main()
