# Packet Integration Page-Write Policy

Read this policy before changing any knowledge page. Packet integration has two write modes, but
both produce the same final page content and apply the same schema, provenance, validation, and
cross-reference rules.

## Select the write mode

Use the `WIKI_STAGED_WRITES` value from the same resolved vault config used for
`OBSIDIAN_VAULT_PATH`:

- unset or `false`: write directly to live category paths;
- `true`: write review artifacts under `_staging/` and leave live knowledge pages unchanged.

Do not infer the mode from whether `_staging/` happens to contain files. Record the selected mode in
the Job so every Packet for that Job follows the same path.

## Plan page changes

For every extracted item, decide whether to update an existing canonical page, create a genuinely
new page, or omit non-durable noise. Apply tier-aware filtering to existing pages:

| Existing tier | Update rule |
|---|---|
| `core` | Update when the Packet is even marginally relevant |
| `supporting` or missing | Update only for clear new claims or useful provenance |
| `peripheral` | Update only when the source is primarily about that page |

Project-specific knowledge uses the active vault layout under `projects/<project>/`; general
knowledge uses the global category directories. Packet boundaries never determine page boundaries.

## Build complete final page content

For a new page, use the generic page template from `llm-wiki/SKILL.md`. Text ingest V1 has no
academic-PDF special case. Include the effective owner schema and at least:

```yaml
title: Page Title
category: concept
tags: []
sources: []
summary: A one- or two-sentence preview no longer than 200 characters.
relationships: []
provenance:
  extracted: 1.0
  inferred: 0.0
  ambiguous: 0.0
base_confidence: 0.65
lifecycle: draft
lifecycle_changed: 2026-08-26
tier: supporting
created: 2026-08-26
updated: 2026-08-26
```

Owner conventions may extend lifecycle/relationship values or make trust fields optional. Apply
that effective schema rather than blindly overwriting it with framework defaults.

- Set new pages to `lifecycle: draft`, `tier: supporting`, and today's `lifecycle_changed` date.
- Compute `base_confidence = min(distinct_source_count / 3, 1.0) * 0.5 +
  average_source_quality * 0.5` when the effective schema requires it.
- Recompute confidence on update only when sources or material content changed; preserve lifecycle
  because only a human promotes it.
- Recompute the `provenance` fractions after merging. They should total approximately `1.0`.
- Keep `^[inferred]` and `^[ambiguous]` markers inline; extracted claims need no marker.
- Add `visibility/internal` or `visibility/pii` only when clearly warranted. Visibility tags do not
  count toward the normal five-tag limit.
- Preserve exact Packet locators in claim provenance. Add the source to `sources:` once, without
  duplicating existing entries.

For an existing page, read the current page first and merge into its narrative. Do not append a
Packet dump. Preserve owner fields, update `updated`, refresh a meaningfully changed `summary`, and
record unresolved contradictions rather than erasing either position.

For `_raw/` sources, inherit `sources:` and `capture_source` from the raw file's frontmatter. The
staging path is not the real source and must not become page provenance.

## Direct-write mode

- New pages go to `<category>/<page>.md`.
- Existing pages are merged in place.
- Write reciprocal links or typed relationships in the same integration transaction when they are
  useful and supported.
- Validate all changed pages before advancing the Job unit.

## Staged-write mode

Staging is a review boundary, not successful integration. Do not modify live knowledge pages,
`index.md`, or the permanent source manifest while review is pending.

### New pages

Write the complete final page to `_staging/<category>/<page>.md`. Add this staging metadata to its
frontmatter while retaining normal page frontmatter:

```yaml
staged_write:
  final_path: concepts/page.md
  job_id: 20260826-143012-a81f
  packet_ids: [pkt_a, pkt_b]
  source_ids: [src_a13f9c]
  unit_ids: [unit-a, unit-b]
  ingested_at: 2026-08-26T15:30:00+08:00
```

If a later Packet updates the same not-yet-live page, merge into this staged page and append its
Packet/unit IDs instead of creating another artifact.

### Updates to live pages

Write `_staging/<category>/<page>.patch.md` with enough metadata to bind approval back to the Job:

```markdown
---
title: Page Title
patch_target: concepts/page.md
job_id: 20260826-143012-a81f
packet_ids: [pkt_a]
source_ids: [src_a13f9c]
unit_ids: [unit-a]
ingested_at: 2026-08-26T15:30:00+08:00
target_updated_at_plan: 2026-08-25
---
# Proposed Update: Page Title

## Additions
<new or replacement content, including provenance and links>

## Deletions
<exact current lines to remove>

## Updated Fields
<summary, updated, sources, provenance, confidence, relationships, and other changed fields>
```

Merge later Packets targeting the same page into the existing patch and append their IDs. Never
overwrite an earlier Packet's proposed changes. Stage reciprocal-link edits as page patches too;
staged mode must not smuggle cross-reference changes into live pages.

Validate complete staged pages with the normal page validator. Validate patches for required
binding metadata, an existing in-vault `patch_target`, and the three structured sections above.
After validation, record every artifact path on the Job unit and set the unit to `staged`, not
`integrated`. Track `units_staged` separately; leave `units_integrated` unchanged. When all units are
staged, set the source/Job to `awaiting_review`. Do not write its permanent manifest entry.

`log.md` may record a `STAGE_PENDING` event and `hot.md` may mention pending review, but neither may
claim the pages or source are live. `index.md` changes only when artifacts are accepted.

## Validate before state advancement

Run the repository page validator on every live or complete staged page. Confirm required
frontmatter, effective trust fields, controlled tags, `summary` length, provenance fractions,
source locators, relationship types, and valid links. A failed validation leaves the unit pending
or failed; it never advances Job or manifest state.

## Cross-reference pass

After drafting page content, inspect every new wikilink:

1. Confirm its target exists live or is created by the same staged transaction.
2. Consider whether the target should link back; add a reciprocal link when it improves navigation,
   not mechanically for every mention.
3. Add a typed `relationships:` entry only when evidence supports its direction and allowed type.
4. In staged mode, represent any backlink change as another staged page/patch bound to the same
   units.

The coordinator still runs `cross-linker` once after the complete Job becomes live. This local pass
ensures links introduced by the current Packet are coherent before integration is considered done.
