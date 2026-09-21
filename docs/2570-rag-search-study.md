# Budget search and document retrieval patterns

This document records reusable design patterns for turning government-budget PDFs into a verifiable search application. It intentionally omits deployment hostnames, private filesystem layout, credentials, and operational details.

## Two complementary retrieval layers

```text
Immutable source documents
├─ Text extraction and structured-item index
│  └─ amount, agency, geography, category, page, source reference
└─ Page extraction and document retrieval index
   └─ excerpt, source reference, page, chunk identifier
```

| Layer | Best for | Return value |
| --- | --- | --- |
| Structured search | filters, totals, exports, comparisons | typed budget records and aggregates |
| Document retrieval | evidence, context, explanations | excerpt with source and page citation |

Numbers and aggregates must come from the structured index. Document retrieval provides the evidence needed to inspect and explain a result.

## Text extraction for structured search

A practical extraction pipeline is:

```text
PDF → pdftotext -layout → text corpus → Thai-font repair → item parser → SQLite index
```

`-layout` preserves columns that matter to tables. A parser can buffer lines until it reaches an amount, then attach the closest preceding headings such as organisation, place, category, page, quantity, and unit.

Thai PDF extraction needs defensive search forms because combining marks and embedded fonts can be damaged. Keep:

- normalised text for regular matching;
- a consonant-oriented form for tolerant matching;
- provenance fields: source path, page, line, extractor version, and index version.

Some embedded fonts require a known byte-to-Unicode repair. Such a repair must only run when a recognisable signature is present, must be versioned, and must leave unaffected text unchanged.

## Document retrieval and OCR

A citation-first document index should:

1. Extract both `pdftotext -layout` and `pdftotext -raw`.
2. Compare the output per page and select the version with fewer broken Thai combining marks.
3. Normalise Unicode and index a folded Thai form in addition to readable text.
4. Chunk by page while retaining source path and page number.
5. Put pages with too little selectable text into an OCR review queue rather than indexing empty content.

OCR needs a review boundary:

```text
pending → approved → OCR or submitted text → done
```

Source PDFs stay read-only. OCR text belongs in an indexed sidecar so it can be corrected, audited, and rebuilt without changing the original document.

## External-source monitoring

Monitoring is a separate intake capability, not a side effect of search:

```text
source URL → fetch/API/RSS → canonicalise → hash/deduplicate → watch event → optional budget match
```

Use official APIs, RSS, or sitemaps before HTML scraping. A useful initial matcher can be keyword based, but a higher-confidence budget match should compare category, organisation, geography, quantity, and amount. Every match needs confidence, explanation, reviewer state, and source URL.

## Reproducibility requirements

- Store source URL, checksum, ingest time, parser/extractor version, and index version.
- Build a new index and validate it before an atomic switch; do not destroy a live index in place.
- Monitor file/chunk counts, index freshness, failed fetches, OCR backlog, and database checkpoint/backup health.
- Keep source documents, generated indexes, and application state in separate storage boundaries.
