"""Find recent Neo4j plus partner content without changing the tracker database."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from .discovery_common import (
    PARTNERS,
    EnvSettings,
    freshness_value,
    request_json,
    review_window,
    utc_now,
    write_report,
)
from .partner_tracker import canonicalize_url


BRAVE_LLM_CONTEXT_URL = "https://api.search.brave.com/res/v1/llm/context"
BRAVE_WEB_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"

QUERY_TEMPLATES = {
    "AWS": (
        'site:neo4j.com (AWS OR "Amazon Bedrock" OR AgentCore OR Strands) Neo4j',
        'site:aws.amazon.com Neo4j (Bedrock OR AgentCore OR GraphRAG OR Glue)',
        'site:github.com/neo4j-labs Neo4j (AWS OR Bedrock OR AgentCore OR Strands)',
    ),
    "Databricks": (
        'site:neo4j.com Databricks (Spark OR "Unity Catalog" OR Genie OR "Mosaic AI")',
        'site:docs.databricks.com Neo4j',
        'site:github.com/neo4j-partners Neo4j Databricks',
    ),
    "IBM": (
        'site:neo4j.com (IBM OR watsonx OR "Red Hat" OR OpenShift) Neo4j',
        'site:ibm.com Neo4j (watsonx OR Instana OR "Cloud Pak")',
        'site:github.com Neo4j (IBM OR watsonx OR "Red Hat" OR OpenShift)',
    ),
}

PARTNER_TERMS = {
    "AWS": ("aws", "amazon", "bedrock", "agentcore", "strands"),
    "Databricks": ("databricks", "unity catalog", "delta lake", "mosaic ai", "genie"),
    "IBM": ("ibm", "watson", "watsonx", "red hat", "openshift", "instana"),
}


def demonstrates_partner_integration(partner: str, title: str, excerpt: str) -> bool:
    text = f"{title} {excerpt}".lower()
    return "neo4j" in text and any(term in text for term in PARTNER_TERMS[partner])


def candidate(
    partner: str,
    query: str,
    source: str,
    url: str,
    title: str,
    excerpt: str,
    source_date: str | None,
) -> dict[str, str | None]:
    return {
        "partner": partner,
        "query": query,
        "source": source,
        "url": canonicalize_url(url),
        "title": title,
        "evidence_excerpt": excerpt,
        "source_date": source_date,
        "neo4j_role": None,
        "partner_role": None,
        "joint_result": None,
        "suggested_status": "review",
    }


def llm_context_candidates(
    partner: str, query: str, payload: dict[str, Any]
) -> list[dict[str, str | None]]:
    sources = payload.get("sources", {})
    candidates: list[dict[str, str | None]] = []
    for item in payload.get("grounding", {}).get("generic", []):
        url = item.get("url")
        if not url:
            continue
        title = item.get("title", "Untitled source")
        excerpt = " ".join(item.get("snippets", [])[:2])
        if not demonstrates_partner_integration(partner, title, excerpt):
            continue
        age = sources.get(url, {}).get("age", [])
        source_date = age[1] if len(age) > 1 else None
        candidates.append(
            candidate(
                partner,
                query,
                "brave_llm_context",
                url,
                title,
                excerpt,
                source_date,
            )
        )
    return candidates


def web_search_candidates(
    partner: str, query: str, payload: dict[str, Any]
) -> list[dict[str, str | None]]:
    candidates: list[dict[str, str | None]] = []
    for item in payload.get("web", {}).get("results", []):
        url = item.get("url")
        if not url:
            continue
        excerpts = [item.get("description", ""), *item.get("extra_snippets", [])]
        title = item.get("title", "Untitled source")
        excerpt = " ".join(text for text in excerpts[:2] if text)
        if not demonstrates_partner_integration(partner, title, excerpt):
            continue
        candidates.append(
            candidate(
                partner,
                query,
                "brave_web_search",
                url,
                title,
                excerpt,
                item.get("page_age"),
            )
        )
    return candidates


def deduplicate(candidates: list[dict[str, str | None]]) -> list[dict[str, str | None]]:
    unique: dict[str, dict[str, str | None]] = {}
    for item in candidates:
        url = item["url"]
        if url and url not in unique:
            unique[url] = item
    return list(unique.values())


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--partner", required=True, choices=PARTNERS)
    root.add_argument("--db", default="partner-tracking.db", type=Path)
    root.add_argument("--start", help="review start date in YYYY-MM-DD")
    root.add_argument("--end", help="review end date in YYYY-MM-DD")
    root.add_argument("--env-file", default=".env", type=Path)
    root.add_argument("--output", type=Path)
    root.add_argument("--max-results", type=int, default=10)
    return root


def main() -> int:
    command_parser = parser()
    args = command_parser.parse_args()
    if args.max_results < 1 or args.max_results > 20:
        command_parser.error("--max-results must be between 1 and 20")
    try:
        settings = EnvSettings.load(args.env_file)
        api_key = settings.require_brave_api_key()
        start, end = review_window(args.db, args.partner, args.start, args.end)
    except ValueError as error:
        command_parser.error(str(error))
    freshness = freshness_value(start, end)
    headers = {"Accept": "application/json", "X-Subscription-Token": api_key}
    candidates: list[dict[str, str | None]] = []
    for query in QUERY_TEMPLATES[args.partner]:
        llm_payload = request_json(
            BRAVE_LLM_CONTEXT_URL,
            {
                "q": query,
                "count": args.max_results,
                "freshness": freshness,
                "context_threshold_mode": "strict",
                "enable_source_metadata": "true",
            },
            headers,
            settings.timeout,
        )
        candidates.extend(llm_context_candidates(args.partner, query, llm_payload))
        web_payload = request_json(
            BRAVE_WEB_SEARCH_URL,
            {
                "q": query,
                "count": args.max_results,
                "freshness": freshness,
                "extra_snippets": "true",
            },
            headers,
            settings.timeout,
        )
        candidates.extend(web_search_candidates(args.partner, query, web_payload))
    report = {
        "partner": args.partner,
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "queries": list(QUERY_TEMPLATES[args.partner]),
        "generated_at": utc_now(),
        "database_write": False,
        "candidates": deduplicate(candidates),
    }
    output = (
        args.output
        or settings.output_dir / f"{args.partner.lower()}-discovery-{end}.json"
    )
    write_report(output, report)
    print(f"wrote {len(report['candidates'])} candidates to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
