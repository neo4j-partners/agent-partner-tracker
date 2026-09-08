# Agent instructions

## Review one partner at a time

Start with the partner's saved review state. Check known technical sources before you search the web. Add or update each useful item. Save one short review summary when the work is complete.

1. Run `status` for AWS, Databricks, or IBM. Read the last review date and the next action.
2. Run `list` for active items. Run it again for watched, excluded, or archived items when they affect the review.
3. Run three discovery passes for every partner review: (a) a known-source pass over saved high-value sources and tracked repositories, (b) an expansion pass for technical examples, and (c) an external-web pass for third-party articles. The external-web pass must cover system integrators, consultancies, marketplace vendors, conference sites, developer blogs, technical publishers, and community publications, rather than being limited to Neo4j, partner, or GitHub domains. Do not limit expansion or external-web searches to recent content unless the review is explicitly change-only. Record excluded candidates so they are not repeatedly evaluated.
4. Add direct technical integrations as active items. Explain the Neo4j role, partner role, and joint result in the summary. Apply the repository deep-walk rule before adding a repository: enumerate its partner-relevant subdirectories, read each nested README and implementation entry point, and inspect deployment, authentication, dependencies, and documented limitations. Log every distinct nested sample as its own content item, using its canonical GitHub `tree/main/<subpath>` URL as both the source and evidence. Record the concrete Neo4j capability, partner services, outcome, and any prerequisite or dependency in the item's summary or decision reason. Do not collapse a multi-example repository into one umbrella item; use the umbrella only as a discovery index. Treat the remote GitHub branch or checked commit as authoritative: if a local checkout is stale or lacks paths shown remotely, fetch or inspect the remote source before classifying maturity. `neo4j-labs/neo4j-agent-integrations` and `neo4j-partners/graph-enrichment` are required deep-walk examples. Add useful future candidates as watch items. Keep thin pages, duplicates, and index pages as excluded items when that decision prevents repeat work.
5. Update an existing item when the URL, source, or decision already exists. The tracker normalizes URLs, so a tracking link and its canonical URL identify the same item.
6. Start a review with status `in_progress`. Finalize the same review ID with status `complete` or `no_change` after every planned check has a result.
7. Export the active inventory before you finish. The export confirms that the catalog works without the retired source documents.

## Write each summary in one order

State the Neo4j role, then the partner role, then the joint result. This format makes the value of the integration easy to understand.

- **Neo4j role:** Name the graph, GraphRAG, vector search, analytics, knowledge graph, or graph access capability that Neo4j provides.
- **Partner role:** Name the AWS, Databricks, IBM, or Red Hat product that provides the model, data platform, runtime, deployment platform, security, or operations capability.
- **Joint result:** Name the practical outcome, such as grounded AI, governed data, faster graph data movement, secure deployment, or better observability.
- **Evidence:** Link to a technical sample, repository, guide, architecture, or case study that proves the relationship.

## Supply the publisher when you add an item

`add` does not guess the publisher from the URL. Pass `--publisher-name` and `--publisher-group` for any item with a canonical URL. The valid groups are `neo4j`, `partner`, `community`, and `unclassified`. Leave both flags off for a local-only sample, and the item records `not_applicable`.

The site build refuses to publish an active direct record that has a URL and no publisher classification. Classify the item when you add it.

## Use the public GitHub source for every local project

A local directory is discovery evidence, not the source of record. For every local integration project, resolve its `origin` remote and store the canonical HTTPS GitHub URL in `canonical_url`; use that same public URL as `evidence_url` unless a more specific public technical page is stronger. Keep `local_path` only as a supplemental checkout reference.

Do not create or retain an active direct item that has only a local path when its GitHub source is available. Classify the public repository by its actual owner: repositories published by Neo4j or Neo4j Partners use the `neo4j` group, while repositories or articles published by AWS, Databricks, IBM, or Red Hat use the `partner` group. Never infer `partner` merely from a project name or a local directory.

## Use parallel agents safely

Use parallel agents for independent discovery and verification work. Keep database writes with one coordinator. This rule prevents conflicting updates.

1. Split work by partner or source group. For example, assign one agent to AWS technical sources and another agent to tracked GitHub repositories.
2. Give each agent a clear date window, partner, source list, and output format.
3. Ask each agent to return candidate URLs, titles, evidence, the Neo4j role, the partner role, the joint result, and a proposed status.
4. Let the coordinator deduplicate URLs, verify the strongest candidates, and write all database updates.
5. Use one final review summary for the partner. Record what changed and what to check next.

## Check these known-source groups during routine reviews

- **AWS:** Check Neo4j Labs, Neo4j Contrib, Neo4j Partners, AWS APN, the AWS Database Blog, and the tracked AWS repositories.
- **Databricks:** Check the Neo4j Spark documentation, connector releases, the Databricks quickstart, and the tracked partner workshops.
- **IBM:** Check IBM watsonx.data intelligence, IBM Instana, the Neo4j APOC Watson documentation, and the Neo4j Red Hat deployment guidance.

## Required third-party integration discovery

A third-party integration example can be a sample, reference architecture, notebook, workshop, connector implementation, deployment guide, documented solution, or external technical article that uses Neo4j with a partner product. An external article does not need runnable source code. It must name a concrete Neo4j capability, a concrete partner product, and a joint architecture, workflow, or outcome.

For each partner, search official partner GitHub organizations and documentation; Neo4j GitHub organizations, Labs, Contrib, and partner repositories; partner blogs, architecture centers, workshops, and solution libraries; community GitHub repositories with source code and setup instructions; and conference sessions, solution accelerators, or marketplace examples that link to implementation evidence.

Use query families, not one broad query: combine `Neo4j`, a specific partner product, and an artifact type such as `GitHub`, `sample`, `notebook`, `workshop`, `architecture`, `deployment`, `case study`, `blog`, or `conference`. For example: `Neo4j Bedrock GitHub`, `Neo4j Glue notebook`, `Neo4j Databricks Mosaic AI`, `Neo4j Unity Catalog`, `Neo4j watsonx sample`, and `Neo4j OpenShift deployment`.

For the external-web pass, use at least 20 domain-diverse queries per partner, inspect at least 50 relevant results from at least 10 non-Neo4j and non-partner domains, and deliberately vary product terms and artifact terms. For Databricks, include searches for `Spark Connector`, `Unity Catalog`, `Mosaic AI`, `Model Serving`, `Vector Search`, `Lakehouse`, `Delta`, `Apps`, `workflows`, `GraphRAG`, `architecture`, `case study`, and `blog`. Classify a concrete, current external technical article as `active`; use `watch` when verification, recency, or technical detail is insufficient; and use `excluded` for thin mentions, broad announcements, and duplicates.

Minimum coverage targets per full review are 10 verified AWS technical examples plus 15 external technical articles from at least 10 third-party domains, spanning Bedrock, SageMaker, Lambda, ECS or EKS, Glue, Neptune migration or coexistence, OpenSearch, and IAM or security; 10 verified Databricks technical examples plus 15 external technical articles from at least 10 third-party domains, spanning the Spark Connector, Unity Catalog, Mosaic AI, Model Serving, Vector Search, Lakehouse or Delta, Apps, and workflows; and 8 verified IBM technical examples plus 12 external technical articles from at least 8 third-party domains, spanning watsonx, watsonx.data, watsonx.ai, OpenShift or Red Hat, Cloud Pak for Data, Instana, and data governance. A review is incomplete until every listed product area is searched or explicitly recorded as `no technical example found`.

## Content discovery tools

Use these tools to find recent partner content. Verify useful candidates before you add them to the tracker.

- **Brave LLM Context:** Use this first when an agent needs source text. It returns extracted page content and source metadata in one search response.
- **Brave Web Search:** Use this to find a broad set of candidate URLs. Use a custom freshness range and partner-specific `site:` queries.
- **Brave Goggles:** Use this to boost trusted technical domains, such as Neo4j, AWS, Databricks, IBM, Red Hat, and GitHub.
- **Cached page retrieval:** Use this after discovery to verify a small set of candidates. Read the canonical page before adding an item.
- **GitHub API:** Check tracked repositories for new releases, commits, issues, and README changes. This finds product changes that web search can miss. For a multi-example repository, also list nested README files and implementation directories, capture the source commit or release checked, and add each verified partner-specific example as its own content item rather than treating the repository root as sufficient evidence.

The project includes a discovery script and a repository-change script. Both scripts read `.env`, write review reports, and never change the database. A coordinator verifies and classifies every candidate before it becomes an item.

## Never let discovery write to the database

Discovery finds candidates. The tracker stores reviewed decisions.

A direct write can add duplicate links, weak mentions, expired pages, or content that does not show a real integration. A reviewer checks the evidence, applies the inclusion rules, and writes the final decision. This separation keeps the catalog useful and trustworthy.
