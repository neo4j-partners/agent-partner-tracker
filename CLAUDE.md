# Agent instructions

## Review one partner at a time

Start with the partner's saved review state. Check known technical sources before you search the web. Add or update each useful item. Save one short review summary when the work is complete.

1. Run `status` for AWS, Databricks, or IBM. Read the last review date and the next action.
2. Run `list` for active items. Run it again for watched, excluded, or archived items when they affect the review.
3. Check the saved high-value sources first. Use a narrow date-bounded search only when those sources leave a clear gap.
4. Add direct technical integrations as active items. Explain the Neo4j role, partner role, and joint result in the summary. When a source is a repository, inspect its structure (subdirectories, README, multiple example or sample folders) for more than one distinct sample. Log each nested sample as its own content item, with its own title, summary, and evidence, instead of collapsing the whole repository into one item; `neo4j-partners/graph-enrichment` is a known repository that contains more than one sample. Add useful future candidates as watch items. Keep thin pages, duplicates, and index pages as excluded items when that decision prevents repeat work.
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

## Content discovery tools

Use these tools to find recent partner content. Verify useful candidates before you add them to the tracker.

- **Brave LLM Context:** Use this first when an agent needs source text. It returns extracted page content and source metadata in one search response.
- **Brave Web Search:** Use this to find a broad set of candidate URLs. Use a custom freshness range and partner-specific `site:` queries.
- **Brave Goggles:** Use this to boost trusted technical domains, such as Neo4j, AWS, Databricks, IBM, Red Hat, and GitHub.
- **Cached page retrieval:** Use this after discovery to verify a small set of candidates. Read the canonical page before adding an item.
- **GitHub API:** Check tracked repositories for new releases, commits, issues, and README changes. This finds product changes that web search can miss. Also check whether a repository contains more than one distinct sample, such as `neo4j-partners/graph-enrichment`, and add each nested sample as its own content item.

The project includes a discovery script and a repository-change script. Both scripts read `.env`, write review reports, and never change the database. A coordinator verifies and classifies every candidate before it becomes an item.

## Never let discovery write to the database

Discovery finds candidates. The tracker stores reviewed decisions.

A direct write can add duplicate links, weak mentions, expired pages, or content that does not show a real integration. A reviewer checks the evidence, applies the inclusion rules, and writes the final decision. This separation keeps the catalog useful and trustworthy.
