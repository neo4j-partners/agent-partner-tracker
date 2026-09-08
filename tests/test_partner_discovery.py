import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from agent_tracker import check_partner_repositories as repositories
from agent_tracker import discover_partner_content as discovery


FIXTURES = Path(__file__).parent / "fixtures"


class PartnerDiscoveryTests(unittest.TestCase):
    def fixture(self, name):
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    def test_llm_context_candidate_keeps_evidence_and_normalizes_url(self):
        candidates = discovery.llm_context_candidates(
            "AWS", "Neo4j AWS", self.fixture("brave_llm_context.json")
        )
        self.assertEqual(candidates[0]["url"], "https://neo4j.com/example")
        self.assertEqual(candidates[0]["source_date"], "2026-09-08")
        self.assertIn("Amazon Bedrock", candidates[0]["evidence_excerpt"])

    def test_web_candidate_keeps_partner_story_fields_for_review(self):
        candidates = discovery.web_search_candidates(
            "AWS", "Neo4j AWS", self.fixture("brave_web_search.json")
        )
        self.assertEqual(candidates[0]["url"], "https://aws.amazon.com/example")
        self.assertIsNone(candidates[0]["neo4j_role"])
        self.assertEqual(candidates[0]["suggested_status"], "review")

    def test_candidate_requires_neo4j_and_the_selected_partner(self):
        self.assertFalse(
            discovery.demonstrates_partner_integration(
                "AWS", "Amazon Bedrock AgentCore", "AWS documentation for agents."
            )
        )
        self.assertFalse(
            discovery.demonstrates_partner_integration(
                "AWS", "Neo4j GraphRAG", "Neo4j graph-based retrieval."
            )
        )

    def test_repository_change_report_detects_dates_after_cutoff(self):
        cutoff = datetime(2026, 9, 8, tzinfo=timezone.utc)
        fields = repositories.changed_fields(
            self.fixture("github_repository.json"),
            self.fixture("github_commit.json"),
            self.fixture("github_release.json"),
            cutoff,
        )
        self.assertEqual(
            fields,
            ["repository_updated", "repository_pushed", "latest_commit", "latest_release"],
        )

    def test_repository_coordinates_accepts_only_top_level_github_repositories(self):
        self.assertEqual(
            repositories.repository_coordinates("https://github.com/neo4j/mcp"),
            ("neo4j", "mcp"),
        )
        self.assertIsNone(
            repositories.repository_coordinates("https://github.com/neo4j/mcp/issues")
        )


if __name__ == "__main__":
    unittest.main()
