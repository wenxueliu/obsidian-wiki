# Completed Text Source Finalization Policy

Read and apply this policy for both direct writes and accepted staged writes. Finalization is one
source-level commit boundary, not a per-Packet action.

## Preconditions

Finalize only when all planned units for the exact source hash are `integrated`, every recorded
page is live, no bound staging artifact is pending/rejected, and changed page validation passes.
Re-read the Job immediately before committing so stale counters cannot authorize completion.

If the source disappeared after planning, report it as missing and keep its existing permanent
manifest history; never interpret absence as permission to delete pages or manifest entries.

## Prepare live special files

Before changing the permanent manifest:

1. Compute the deduplicated union of the source's created and updated live pages.
2. Rebuild or update `index.md` so each live knowledge page appears exactly once under its category,
   with its current one-line `summary` and tags. Never list `_staging/` artifacts.
3. Append one parseable ingest event to `log.md`:

   ```text
   - [TIMESTAMP] INGEST source="/absolute/source.md" pages_updated=N pages_created=M mode=append|full
   ```

   A staged review may also append its separate `STAGE_COMMIT` event.
4. Refresh `hot.md` as a roughly 500-word semantic snapshot. Keep `# Hot Cache`, an `updated:`
   timestamp, and the sections `Recent Activity`, `Active Threads`, `Key Takeaways`, and
   `Flagged Contradictions`. Retain the last three operations. Describe conceptual changes and
   pending work, not merely filenames.
5. Validate all changed pages plus `index.md`, `log.md`, and `hot.md`. Repair failures before the
   source can complete.

## Permanent manifest record

Create `.manifest.json` with top-level `version: 1` when absent. Preserve whether `sources` is a
list or dict, preserve unrelated top-level and entry fields, and update only the first matching
source entry so historical duplicate entries survive. Store canonical absolute source paths for
new entries.

The completed text entry includes:

```json
{
  "path": "/absolute/source.md",
  "content_hash": "sha256:<hex>",
  "source_type": "text",
  "project": null,
  "chunker_version": 1,
  "units_total": 12,
  "units_integrated": 12,
  "pages_created": ["concepts/new-page.md"],
  "pages_updated": ["concepts/existing-page.md"],
  "pages_produced": ["concepts/new-page.md", "concepts/existing-page.md"],
  "last_ingested": "<timezone-aware ISO timestamp>"
}
```

`content_hash`, `last_ingested`, and `pages_produced` are compatibility-critical. The created and
updated lists support precise re-ingest and status reporting. Omit `project` only when no project
scope applies. Recompute `stats.total_sources_ingested` from manifest entries and
`stats.total_pages` from live wiki knowledge pages; do not blindly increment either counter, so a
retry remains idempotent.

Atomically replace `.manifest.json` **last**, after every page and special-file candidate has
validated. Then run `obsidian-wiki verify <source>` (or
`obsidian_wiki.verify.verify_completeness`) and require no `missing_entry`, `empty_pages`, or
`phantom_pages` findings. Repair a failed audit before marking the source or Job complete.

If an error occurs before the manifest replacement, leave the permanent entry unchanged. If an
audit fails after replacement, do not report completion; repair the live/special files and retry
idempotently.

## V1 boundary

PageIndex section-coverage checks and QMD index refresh are not part of text V1's completion
contract. They must not block or silently alter text-source finalization.
