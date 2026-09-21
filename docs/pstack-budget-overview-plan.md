# pstack-budget — overview and roadmap

## Goal

`pstack-budget` is a multi-year budget-information application built on pstack. It provides structured budget search, document evidence retrieval, and monitored external-source intake through one web/API/MCP boundary.

The application consumes immutable corpora arranged by fiscal year. The deployment supplies the corpus root through configuration; source documents are never committed to this repository.

```text
configured data root
├─ <fiscal-year>/ source documents
├─ <fiscal-year>/ manifest and checksums
└─ generated indexes and OCR sidecars in separate writable storage
```

## Target architecture

```text
People, applications, and AI clients
                │
                ▼
           pstack-budget
 ┌──────────────┼──────────────┐
 ▼              ▼              ▼
Search          Document RAG   Web Watch
filters/totals  citations/OCR  sources/events/matches
 └──────────────┴───────┬──────┘
                         ▼
                    pstack MCP
                         ▼
                  authorised MCP gateway
```

### Search

- Fiscal-year aware structured indexes
- Filters by organisation, geography, category, amount, and text
- Facets, aggregation, CSV export, and PDF/page citation
- Atomic validated index replacement

### Document retrieval

- Thai-aware PDF extraction and normalisation
- Page/chunk retrieval with source/page citations
- Curator-governed OCR queue and sidecars
- Search results that supplement, not replace, structured facts

### Web Watch

- A source registry with owner, URL, schedule, parser, policy, and credential reference
- Adapters that prefer RSS/API/sitemap before static HTML or browser rendering
- Hash-based snapshots, deduplicated events, retries, audit, and reviewer workflow
- Budget matching with confidence and explanation

### MCP

pstack-budget owns its tools and RBAC. A gateway connects by using a least-privilege service account, with allow/block policy as a secondary guard.

Initial tool set:

- `search_budget`
- `get_budget_item`
- `search_budget_documents`
- `get_budget_document_chunk`
- `list_watch_events`
- `find_budget_matches`

## Security and quality principles

- Do not commit source PDFs, extracted corpora, database files, `.env`, or credentials.
- Separate read-only source data from generated indexes and application state.
- Separate read tools from reindex, source registration, OCR approval, and OCR submission.
- Keep source provenance, checksums, parser versions, and index versions.
- Respect source policies, rate limits, robots rules, API terms, and credential boundaries.
- Monitor freshness, extraction errors, OCR backlog, watcher failures, matcher confidence, disk, and backups.

## Roadmap

### Phase 0 — foundation

- [ ] Define the fiscal-year corpus and manifest contract.
- [ ] Define roles: reader, analyst, curator, administrator.
- [ ] Write extraction, validation, backup, and rollback runbooks.
- [ ] Validate a reproducible import for an initial corpus.

**Exit:** corpus and index provenance are auditable and no secret is tracked.

### Phase 1 — structured-search parity

- [ ] Support fiscal-year search, facets, sort, export, and citations.
- [ ] Add representative parity tests against the existing baseline.
- [ ] Implement atomic index switch and health/status endpoints.
- [ ] Deploy a candidate separately and verify rollback.

**Exit:** critical queries and totals match the baseline and can be rolled back safely.

### Phase 2 — document retrieval

- [ ] Add a citation-first RAG addon using the same corpus contract.
- [ ] Implement extraction, Thai normalisation, chunk retrieval, and citation model.
- [ ] Add OCR queue, sidecars, curator approval, and metrics.

**Exit:** every document answer points to inspectable source and page evidence.

### Phase 3 — web watch

- [ ] Build the source registry and owner workflow.
- [ ] Add RSS first, then API/sitemap/static-page/browser adapters as required.
- [ ] Add jobs, retry/backoff, events, audit, and budget-match review.

**Exit:** a team can add a governed source without code changes and reviewers can assess each match.

### Phase 4 — MCP and operations hardening

- [ ] Expose only approved tools through a dedicated service account.
- [ ] Add tool-discovery, authorisation, citation, and denied-mutation smoke tests.
- [ ] Add backup/restore tests, index checkpointing, dashboards, and incident runbooks.

**Exit:** authorised AI clients use one audited interface and all answers retain traceable provenance.
