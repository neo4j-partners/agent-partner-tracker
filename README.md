# Partner Content Tracker

[View the public partner catalogue](https://neo4j-partners.github.io/agent-partner-tracker/).

- Tracks how Neo4j and AWS, Databricks, or IBM work better together.
- Explains the role of Neo4j, the role of the partner product, and the result of the integration.
- Stores private content, partner review state, and review summaries in local SQLite.
- Prevents duplicate public URLs and local paths for each partner.
- Lists and exports the current active inventory.
- Keeps watched, excluded, and archived items for future reference.

The private database and discovery reports live under `private/`, which is
ignored by Git. The only data committed for publication is the reviewed,
sanitized `site/public-data.json` export.

Agent workflow guidance lives in `CLAUDE.md`.

## Better together focus

This tracker records useful proof that Neo4j and a partner product solve a problem together.

- **Neo4j role:** Describe the graph, GraphRAG, vector search, analytics, knowledge graph, or graph access capability that Neo4j provides.
- **Partner role:** Describe the AWS, Databricks, IBM, or Red Hat product that provides the model, data platform, runtime, deployment platform, security, or operations capability.
- **Joint result:** Describe the practical outcome, such as grounded AI, governed data, faster graph data movement, secure deployment, or better observability.
- **Evidence:** Link to a technical sample, repository, guide, architecture, or case study that proves the relationship.

Write each item summary in this order: Neo4j role, partner role, then joint result. This format makes the value of the integration easy to understand.

## Quick start

Install [uv](https://docs.astral.sh/uv/) and run these commands from the project
root. `uv sync` creates the virtual environment and installs the locked project
dependencies.

```bash
uv sync
```

Publish a reviewed release. This exports public data from the ignored private
catalog, runs the tests and static-site checks, stages tracked public changes and
`site/public-data.json`, then commits and pushes. It refuses private file
additions. Pass a descriptive commit message:

```bash
uv run publish --message "Publish reviewed partner data"
```

Generate the reviewed public-data export, then build the static site from it:

```bash
uv run export-public-data --db private/partner-tracking.db --output site/public-data.json
uv run build-site --data site/public-data.json --output _site
uv run validate-site _site
```

`export-public-data` selects only fields used by the public site. `build-site`
does not read SQLite in the publication workflow.

Check the database and run the tests:

```bash
uv run python -m unittest discover -s tests -v
sqlite3 private/partner-tracking.db 'PRAGMA integrity_check;'
```

Check one partner's review state:

```bash
uv run partner-tracker --db private/partner-tracking.db status --partner AWS
```

List the active inventory for one partner:

```bash
uv run partner-tracker --db private/partner-tracking.db list --partner Databricks --status active
```

Export an active inventory as Markdown or JSON:

```bash
uv run partner-tracker --db private/partner-tracking.db export --partner IBM --format markdown
uv run partner-tracker --db private/partner-tracking.db export --partner IBM --format json
```

View the available commands:

```bash
uv run partner-tracker --help
```

## Project layout

- `src/agent_tracker/` contains the Python package and its command modules.
- `tests/` contains the unit tests and their fixtures.
- `site/` contains the static-site templates and browser assets.
- `pyproject.toml` defines the project metadata, dependencies, and CLI commands.
- `uv.lock` locks the complete Python environment for reproducible runs.
- `CLAUDE.md` holds the review workflow that agents follow.

## Schema changes

The schema lives in one place: the `initialize` function in
`src/agent_tracker/partner_tracker.py`. There is no migration runner. Change a
column by editing that function and applying a matching `ALTER TABLE` to the
private database by hand. Copy the database first.

## Static website

Generate the partner-neutral GitHub Pages artifact from the committed public
data export:

```bash
uv run build-site --data site/public-data.json --output _site
uv run validate-site _site
```

Open `_site/index.html` directly or serve `_site` with a local static-file server. The generated site contains a dashboard plus filterable Integration assets and Articles catalogues. It publishes only active direct records, never exposes local paths or internal review actions, and does not need SQLite after generation. Public links must use HTTPS, and only an explicit allowlist of harmless query parameters is accepted.

`validate-site` checks that every internal reference resolves inside the site root. It reports how many external links the pages contain, and it does not request them.

The Pages workflow validates the public data, runs the complete test suite,
rebuilds `_site`, and publishes only that generated directory.

## Discovery setup

Copy the sample environment file. Add a Brave API key to the local `.env` file. The `.gitignore` file keeps the local file out of version control.

```bash
cp .env.sample .env
```

Run a read-only partner discovery report after you set `BRAVE_API_KEY`:

```bash
uv run discover-partner-content --partner AWS --db private/partner-tracking.db
```

Run a read-only GitHub repository change report. `GITHUB_TOKEN` is optional for small public checks and recommended for larger repository batches.

```bash
uv run check-partner-repositories --partner AWS --db private/partner-tracking.db
```

Both scripts write their report to `DISCOVERY_OUTPUT_DIR`, which defaults to
`private/reports`. Neither script writes to the database.

### Public-source requirement for local projects

When an agent accepts a local directory into the catalog, it must record the
canonical HTTPS GitHub URL in `canonical_url` and use it as the primary source
reference. `local_path` is optional supplemental checkout information, never a
replacement for the public source. Classify the publisher from the remote
owner: Neo4j and Neo4j Partners repositories are `neo4j`-published; AWS,
Databricks, IBM, and Red Hat sources are `partner`-published. Do not infer a
partner publisher from a directory name.

For a repository that contains multiple integrations, the repository root is a
discovery index, not a single catalog entry. Walk its partner-relevant
subdirectories, read each example's README and implementation, and add a
separate record for every distinct sample using its GitHub tree URL. Capture
the Neo4j capability, partner services, authentication/deployment model,
dependencies, and documented limitations so the catalog remains actionable.
The remote canonical GitHub branch or checked commit is authoritative: refresh
or inspect it when a local clone is stale or missing expected paths before
deciding that an example is documentation-only.

## Terms

- **Partner:** AWS, Databricks, or IBM. Each partner has its own inventory and review state.
- **Content item:** A local sample, repository, or public reference stored in the catalog. A single repository can hold more than one distinct sample; track each nested sample as its own content item rather than logging the whole repository as one item. `neo4j-partners/graph-enrichment` is a known example of a repository with multiple samples inside it.
- **Direct:** Content that demonstrates a real Neo4j integration with the selected partner.
- **Supporting:** Content that helps build or understand an integration.
- **Active:** Current content that appears in the default inventory and export.
- **Watch:** A useful candidate that needs another check before promotion.
- **Excluded:** A remembered result that does not meet the inclusion rules.
- **Archived:** Historical content that remains searchable but is not current guidance.
- **Review:** A short record of a partner check, its sources, result, and next action.
- **Canonical URL:** The normalized public URL used to prevent duplicates.
- **Local checkout:** A supplemental developer reference only. Every published local project must also record its canonical public GitHub URL as the source of record.
- **Publisher name:** The reviewed public name of the site, account, or repository organization that published an item.
- **Publisher group:** Neo4j, partner, community, not applicable, or temporarily unclassified.
- **Markdown archive:** A private retired project document stored in local SQLite
  with its checksum and original text. Do not include archives in the public-data
  export.
