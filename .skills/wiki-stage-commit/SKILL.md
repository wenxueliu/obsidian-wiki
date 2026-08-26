---
name: wiki-stage-commit
description: >
  Review and promote staged wiki pages to their final locations. Use when WIKI_STAGED_WRITES=true
  and the user says "/wiki-stage-commit", "review staged pages", "commit staged writes",
  "promote staged pages", "approve staged changes", or "what's waiting in staging".
  Shows each staged file, lets the user accept or reject it, and moves accepted files to
  their final wiki locations. Rejected files are moved back to _raw/ for manual editing.
---

# Wiki Stage Commit — Staged Write Promotion

You are reviewing LLM-written pages that are waiting in `_staging/` for human approval before they land in the live wiki. This skill is only useful when `WIKI_STAGED_WRITES=true` in the vault config. Text-ingest artifacts may be bound to a durable Job; approval must advance those units without allowing the permanent source manifest to get ahead of live pages.

## Before You Start

1. **Resolve config** — follow the Config Resolution Protocol in `llm-wiki/SKILL.md`. This gives `OBSIDIAN_VAULT_PATH` and `WIKI_STAGED_WRITES`.
2. If `WIKI_STAGED_WRITES` is not set or is `false`, tell the user: "Staged writes mode is not enabled. Set `WIKI_STAGED_WRITES=true` in your `.env` to use this feature." Then stop.
3. Read `../wiki-ingest/references/page-write-policy.md` and
   `../wiki-ingest/references/finalization-policy.md` completely. Accepted artifacts must produce
   the same live content and source-level commit as direct writes.
4. Read the `_staging/` directory inventory.
5. For every artifact with `staged_write.job_id` or `job_id`, resolve that exact Job beneath
   `_meta/ingest-jobs/`. Refuse metadata-derived paths that escape the vault, Job, or staging roots.

## Invocation Forms

```
/wiki-stage-commit               # interactive review: show each file and ask accept/reject
/wiki-stage-commit --all         # accept all staged files without per-file review
/wiki-stage-commit --reject-all  # reject all staged files (move to _raw/ for manual editing)
/wiki-stage-commit --list        # list staged files with summary, no changes
```

## Step 1: Inventory Staged Files

Glob `$OBSIDIAN_VAULT_PATH/_staging/**/*.md` — these are the pending pages.

Also glob `$OBSIDIAN_VAULT_PATH/_staging/**/*.patch.md` — these are pending *updates* to existing pages (diff-style files showing proposed additions and deletions).

Report the inventory:

```
Staged files: 4 new pages, 2 updates

New pages:
  _staging/concepts/attention-mechanism.md        (ingested 2 days ago)
  _staging/entities/andrej-karpathy.md            (ingested 2 days ago)
  _staging/skills/fine-tuning-llms.md             (ingested yesterday)
  _staging/references/attention-is-all-you-need.md (ingested 3 hours ago)

Updates (patch files):
  _staging/concepts/transformer-architecture.patch.md  (target: concepts/transformer-architecture.md)
  _staging/skills/prompt-engineering.patch.md          (target: skills/prompt-engineering.md)
```

If `_staging/` is empty, report: "Nothing staged. All writes have been committed or no staged writes have been produced yet."

## Step 2: Per-File Review (interactive mode)

For each staged file (new pages first, then updates):

### For new pages:

Display a summary:

```
--- New page: concepts/attention-mechanism.md ---
Title:    Attention Mechanism
Tags:     #ml #architecture
Summary:  Core building block of transformers — computes weighted sum of values based on query-key similarity.
Tier:     supporting
Confidence: 0.72
Sources:  papers/attention.pdf

[Preview first 20 lines of body]
...

Accept [a], Reject [r], Skip [s], Preview full [p]?
```

### For patch files:

Display a structured diff:

```
--- Update: concepts/transformer-architecture.md ---
Source: _staging/concepts/transformer-architecture.patch.md

Proposed additions (+):
+ Transformers outperform RNNs on tasks requiring long-range dependencies. ^[inferred]
+ New source: papers/survey-2026.pdf

Proposed deletions (-):
- The attention mechanism was first described in [Bahdanau 2015].  (to be replaced by updated claim)

⚠️  Conflict check: target page was modified 3 days after staging. Review carefully.

Accept [a], Reject [r], Skip [s], Preview full diff [p]?
```

If `--all` flag is set, skip prompting and accept every file.
If `--reject-all` flag is set, skip prompting and reject every file.
If `--list` flag is set, stop after printing the inventory (Step 1).

## Step 3: Apply Decisions

### Accepting a new page

1. Remove the staging-only `staged_write` metadata from the page
2. Move `_staging/<category>/page.md` → `<category>/page.md` (the final location)
3. Validate the live page
4. Record the artifact as accepted for every bound Job unit
5. Update `index.md` with the new page entry
6. Remove the staged file

### Accepting a patch/update

1. Read the current page at the target path
2. Apply the proposed additions and deletions (merge, don't just overwrite)
3. Update the `updated` frontmatter timestamp
4. Validate the changed live page
5. Record the artifact as accepted for every bound Job unit
6. Update `index.md` if the summary changed
7. Remove the staged patch file

### Rejecting a file

Move it to `$OBSIDIAN_VAULT_PATH/_raw/` for manual editing:
- `_staging/concepts/page.md` → `_raw/rejected-concepts-page.md`
- `_staging/concepts/page.patch.md` → `_raw/rejected-patch-concepts-page.md`
- Prefix with `rejected-` so the user can identify it

For a Job-bound artifact, also mark the artifact `rejected` and its referenced units
`review_rejected`. Set the source and Job to `incomplete`, retain their Packets, and do not create
or update the permanent source manifest entry. A later corrected artifact may resume those units.

### Conflict detection on patch accept

Before applying a patch, check whether the target page's `updated` frontmatter is newer than the patch file's own `updated` field:
- If the target was modified AFTER the patch was staged, warn: `⚠️ Conflict: target was updated since this patch was staged. Applying may lose recent changes.`
- Give the user a chance to abort: `Apply anyway [y], Skip [s], Reject [r]?`

## Step 4: Update Tracking Files

After processing decisions, reconcile each affected Job in source/unit order:

1. An accepted artifact may cover several units, and one unit may require several artifacts. Mark a
   unit integrated only when every artifact recorded on that unit is accepted. Use
   `record_staging_decision(job, artifact_path, accepted=true|false)` when available, but call it
   with `accepted=true` only after the live page write and validation succeed.
2. If a later unit's artifacts were accepted first, leave it `approved_waiting_order` until all
   preceding units integrate; never bypass serial source order.
3. When every unit for an exact source hash is integrated, run `wiki-ingest`'s source-completion
   procedure by applying `../wiki-ingest/references/finalization-policy.md`: validate live pages and
   special files, update manifest fields and stats, run the completeness audit, and atomically
   update the permanent manifest last.
4. Leave skipped artifacts and their units `staged`; the Job remains `awaiting_review`.

Then update shared files:

1. **`index.md`** — add accepted new pages and refresh changed summaries; never list pending pages.
2. **`hot.md`** — update the Recent Activity section: "Committed N staged pages; rejected M."
3. **`log.md`** — append:
   ```
   - [TIMESTAMP] STAGE_COMMIT accepted=N rejected=M skipped=K
   ```

## Step 5: Report

```
Stage commit complete.

✅  Accepted (N):
  concepts/attention-mechanism.md     → now live
  entities/andrej-karpathy.md         → now live
  concepts/transformer-architecture.md → updated (patch applied)

❌  Rejected (M):
  skills/fine-tuning-llms.md          → moved to _raw/rejected-skills-fine-tuning-llms.md

⏭️  Skipped (K):
  references/attention-is-all-you-need.md → still in _staging/

Staging queue: K files remaining
```

## Notes

- Staged files use the same page template as live pages — they are ready to land, just awaiting approval
- Patch files use a human-readable diff format: lines starting with `+` are additions, lines starting with `-` are deletions
- `log.md` may record that review is pending, but `index.md` and the permanent source manifest do
  not advance until the corresponding pages are live
- The `_staging/` directory is not tracked by Obsidian's graph view — pages only appear in the wiki after promotion
- After all sources in an ingest Job become live, the coordinator runs `cross-linker` once; it does
  not run for each accepted artifact
