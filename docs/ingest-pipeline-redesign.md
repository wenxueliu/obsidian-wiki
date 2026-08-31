# Text Ingest Pipeline V1 Design

Status: **V1 implemented**

Implementation mapping:

- deterministic partitioning: `obsidian_wiki/text_chunker.py`;
- minimal Job and Packet contracts: `obsidian_wiki/ingest_pipeline.py`;
- CLI materialization boundary: `text-chunk-plan` and `text-chunk-read`;
- orchestration and extraction: `wiki-folder-ingest` and `wiki-source-text`;
- serialized integration: `wiki-packet-integrate`.

## 1. Decision summary

Version 1 supports text documents only. It separates folder orchestration, deterministic text
partitioning, per-part extraction, and wiki integration so a folder or one large document never
has to fit in a single agent context.

The approved direction is:

- implement text partitioning locally in this repository;
- expose partitioning as an independent, reusable Python feature;
- do not use PageIndex as a V1 runtime dependency;
- keep PageIndex as a possible future PDF structure provider;
- route every unsupported format explicitly instead of attempting a fallback;
- keep the intermediate contract and job state minimal in V1.

## 2. V1 scope

### Supported inputs

| Extension | Interpretation |
|---|---|
| `.md`, `.markdown`, `.mdx` | Markdown-like text with heading-aware partitioning |
| `.txt` | Plain UTF-8 prose with paragraph-aware partitioning |
| `.rst` | reStructuredText with section-aware partitioning |

V1 accepts UTF-8 and UTF-8 with BOM. Invalid encoding is reported with an actionable error;
automatic encoding guessing is deferred.

### Explicitly unsupported in V1

- PDF and scanned documents;
- Word, PowerPoint, spreadsheets, and OpenDocument files;
- JSON, JSONL, CSV, XML, YAML, and other structured data;
- logs, chat exports, meeting transcripts, and email archives;
- HTML and web URLs;
- images, audio, and video;
- compressed archives and executables;
- source-code files and code repositories.

Unsupported inputs remain visible in the folder report with path, detected kind, and reason. They
must not be silently skipped or reinterpreted as plain text.

## 3. Architecture

```text
folder or text file
        |
        v
wiki-folder-ingest
  discover, hash, classify, create job
        |
        v
independent text-chunker
  produce deterministic source ranges
        |
        v
isolated subagent + wiki-source-text skill
  one coordinator-assigned range -> one bounded Packet
        |
        v
wiki-packet-integrate
  integrate Packets serially into the wiki
        |
        v
deterministic Job completion report

optional later: cross-linker
```

The folder coordinator only sees paths, hashes, range metadata, statuses, and artifact paths. It
never reads or receives full source bodies.

## 4. Component responsibilities

### 4.1 `wiki-folder-ingest`

- resolve vault configuration and owner conventions;
- recursively discover files while applying existing skip-directory rules;
- classify each file as supported text or unsupported;
- compute SHA-256 and skip unchanged supported sources;
- create a durable Job containing one source record per file;
- invoke the partition planner for each changed text source;
- route sources at or below the configured direct-extraction threshold to serialized inline
  integration while retaining one logical full-source unit;
- start one fresh isolated subagent per larger-source part and explicitly require it to use the
  worker-only `wiki-source-text` skill;
- queue Packet and inline transports for serialized `wiki-packet-integrate` integration;
- generate matching JSON and Markdown reports for complete, incomplete, unchanged, unsupported,
  and failed sources from current Job and manifest facts.

It must not read full source bodies, extract knowledge, draft wiki pages, or directly advance the
permanent source manifest.

### 4.2 Independent `text-chunker`

The partitioner is deterministic infrastructure, not an Agent Skill. It belongs in a reusable
Python module, tentatively `obsidian_wiki/text_chunker.py`.

It validates encoding, scans structure, finds semantic boundaries, enforces a hard budget, emits
line and byte ranges, materializes one requested range, and reports forced splits. It does not
summarize, infer, call a model, create Packets, or know about the vault.

### 4.3 `wiki-source-text`

This worker-only skill processes one coordinator-assigned packet-transport source range at a time.
The coordinator starts a fresh isolated subagent and passes only the canonical Job directory,
source ID, and unit ID. The skill reads only that range through the partitioner, extracts bounded
knowledge with exact provenance, validates one Packet, and returns only a bounded handoff. It does
not read other ranges, write wiki pages, update shared Job or manifest files, or spawn workers of
its own. Without isolated subagent support, the coordinator leaves the unit pending.

### 4.4 `wiki-packet-integrate`

`wiki-packet-integrate` handles one serialized transport transaction:

1. validate one Packet, or validate and directly extract one planned inline full-source unit;
2. locate related existing pages;
3. merge knowledge and record contradictions;
4. create or update pages with frontmatter, provenance, relationships, and links;
5. validate changed pages;
6. mark that Packet or inline unit integrated after page validation;
7. return source-level finalization candidates to `wiki-folder-ingest`.

Packet and inline transports integrate serially in source order. Inline extraction stays in the
worker context and does not create a Packet file. The wiki acts as the incremental reducer; V1 does not
add a separate whole-document Reduce stage.

Job completion ends after exact-hash source finalization and deterministic reporting. Cross-linking
is an optional follow-up workflow and never changes whether the ingest Job is complete.

## 5. Independent text partitioning feature

### 5.1 Public Python interface

```python
def plan_text_chunks(
    source: Path,
    *,
    target_budget: int = 48_000,
    hard_budget: int = 64_000,
) -> ChunkPlan: ...

def read_text_chunk(source: Path, unit: ChunkUnit) -> str: ...
```

`target_budget` is the preferred packing size. `hard_budget` is an absolute UTF-8 byte safety cap,
not a claimed exact model-token count. The module must be reusable without importing vault,
manifest, or LLM code.

### 5.2 Budget model

Exact tokenization depends on the model and can require optional dependencies. V1 uses:

- estimated token count for reporting when a compatible counter is available;
- UTF-8 byte length as the mandatory dependency-free hard limit.

For byte-based tokenizers, token count cannot exceed input bytes. A 64,000-byte cap therefore stays
comfortably below a 200k-token context in the conservative case, reserving space for instructions,
related wiki pages, reasoning, and output. Configuration may lower these defaults. Raising them
beyond a documented safe maximum requires an explicit user override.

### 5.3 Streaming scan

The planner reads incrementally in binary mode and decodes complete UTF-8 sequences. It tracks:

- zero-based byte start and exclusive byte end;
- one-based start and end lines;
- current heading path;
- structural block type;
- UTF-8 byte size;
- optional estimated token count.

It never performs an unbounded whole-file `read()`. Memory stays proportional to the largest
structural block rather than the complete document.

### 5.4 Structural boundaries

Preferred boundaries, in order:

1. document sections;
2. paragraphs separated by blank lines;
3. complete Markdown blocks such as lists, tables, and fenced code;
4. complete lines;
5. UTF-8-safe character boundaries for a single oversized line.

Markdown detection recognizes ATX headings and ignores headings inside fenced code. RST detection
recognizes common underline and overline section styles. Plain text relies on paragraphs unless a
clear section pattern is detected.

### 5.5 Packing and splitting

Adjacent small blocks accumulate while the unit remains at or below `target_budget`. Packing does
not cross a top-level section boundary unless the neighboring section fits and its boundary remains
represented in metadata.

If a section exceeds `hard_budget`, split recursively:

```text
section -> paragraphs -> block/list items -> lines -> UTF-8-safe characters
```

Code fences and tables stay intact while they fit. An oversized block is split at line boundaries
and marked, for example:

```json
{
  "forced_split": true,
  "split_reason": "oversized_code_fence"
}
```

A single oversized line is split only at valid UTF-8 character boundaries and marked
`oversized_line`.

### 5.6 Boundary context

Natural boundaries require no overlap. Forced splits retain the heading path and may expose a
small, separately marked context hint. Context hints are not coverage and must not be extracted as
new claims. V1 prefers no raw overlap unless tests demonstrate material quality loss.

### 5.7 No persistent chunk copies

The planner stores ranges rather than copying content into temporary Markdown files.
`read_text_chunk()` seeks to the byte interval, verifies the expected source hash, decodes it, and
returns only that unit. This avoids duplicated sensitive data and accidental wiki indexing.

### 5.8 Chunk plan schema

```json
{
  "chunk_plan_version": 2,
  "chunker_version": 2,
  "source": {
    "path": "/data/large-document.md",
    "content_hash": "sha256:9e9f...",
    "encoding": "utf-8",
    "size_bytes": 3812042,
    "line_count": 48219
  },
  "budget": {
    "mode": "utf8_bytes",
    "target": 48000,
    "min": 24000,
    "hard_max": 64000
  },
  "chunking": {
    "strategy": "adaptive_sections",
    "options": {}
  },
  "units": [
    {
      "unit_id": "unit-0001",
      "heading_path": ["Part I", "Background"],
      "heading_paths": [["Part I", "Background"], ["Part I", "Motivation"]],
      "start_line": 1,
      "end_line": 318,
      "start_byte": 0,
      "end_byte": 47231,
      "size_bytes": 47231,
      "estimated_tokens": null,
      "forced_split": false
    }
  ]
}
```

Invariants:

- units are ordered by source position;
- ranges do not overlap in V1;
- their union covers every source byte exactly once except an optional BOM;
- no unit exceeds `hard_max`;
- byte positions fall on valid UTF-8 boundaries;
- line ranges agree with byte ranges;
- identical input, version, budgets, strategy, and options produce identical output;
- materialization fails if the source hash changed after planning.

### 5.9 Stable unit IDs

Unit IDs are deterministic within one source version:

```text
unit_id = sha256(chunker_version + source_hash + start_byte + end_byte)
```

An edit creates a new source version and may move later boundaries. Content-defined identity across
arbitrary edits is deferred.

## 6. PageIndex evaluation and decision

PageIndex is not the V1 partitioner because:

- its primary abstraction is a hierarchical retrieval tree advertised as “No Chunking”;
- Markdown support recognizes a limited heading set;
- Markdown processing reads the whole file into memory;
- `--max-tokens-per-node` applies only to the PDF path;
- headingless text produces no useful Markdown tree;
- one oversized Markdown section is not recursively token-split;
- importing its Markdown path currently brings PDF and LiteLLM-related dependencies;
- PDF grouping and recursive refinement target tree construction, not a universal hard partition
  contract.

V1 may reuse the ideas of heading hierarchy and source locators, but not the PageIndex runtime.

For a future PDF version, PageIndex may sit behind a structure-provider adapter:

```text
PDF -> PageIndex section/page tree -> local hard-budget splitter -> source units
```

PageIndex would suggest semantic boundaries; the local splitter remains authoritative for context
limits. Failure falls back to bounded page windows, never whole-document reading.

## 7. Minimal Job contract

```text
$OBSIDIAN_VAULT_PATH/_meta/ingest-jobs/<job-id>/
├── job.json
└── packets/
    └── <source-id>-<unit-id>.json
```

The coordinator alone writes `job.json`; workers write distinct Packet paths.

```json
{
  "job_version": 1,
  "job_id": "20260826-143012-a81f",
  "source_root": "/data/notes",
  "status": "incomplete",
  "sources": [
    {
      "source_id": "src_a13f9c",
      "path": "/data/notes/large.md",
      "content_hash": "sha256:9e9f...",
      "kind": "markdown",
      "status": "processing",
      "chunk_plan": {
        "units_total": 12,
        "units_integrated": 6,
        "next_unit": "unit-0007"
      }
    },
    {
      "path": "/data/notes/report.pdf",
      "kind": "pdf",
      "status": "unsupported",
      "reason": "PDF processing is not available in V1"
    }
  ]
}
```

Detailed ranges may stay in `job.json` initially. If real fixtures make plans too large, they may
move to one referenced plan file per source; V1 does not add that layer preemptively.

## 8. Minimal Packet contract

```json
{
  "packet_version": 1,
  "packet_id": "pkt_a13f9c_unit0001",
  "source": {
    "source_id": "src_a13f9c",
    "path": "/data/notes/large.md",
    "content_hash": "sha256:9e9f..."
  },
  "unit": {
    "unit_id": "unit-0001",
    "heading_path": ["Part I", "Background"],
    "start_line": 1,
    "end_line": 318,
    "start_byte": 0,
    "end_byte": 47231
  },
  "extracted": {
    "summary": "...",
    "concepts": [],
    "claims": [],
    "entities": [],
    "relationships": [],
    "questions": []
  },
  "warnings": []
}
```

V1 does not add claim IDs, Packet groups, receipts, rename aliases, or a separate coverage file.
The ordered unit list and statuses in the Job are the coverage record.

## 9. Processing and session isolation

For one or more changed sources:

1. compute its hash;
2. generate ordered ranges with `text-chunk-plan`;
3. if the complete non-empty source is at or below `WIKI_TEXT_DIRECT_EXTRACT_MAX_BYTES`, replace
   normal ranges with one logical full-source inline unit and do not allocate a Packet path;
4. reconcile interrupted packet-transport `extracting` units from their planned Packet paths;
5. claim up to `WIKI_FOLDER_INGEST_MAX_EXTRACTION_WORKERS` pending packet units in one atomic Job update;
6. start one fresh isolated subagent per claimed packet unit, pass only Job directory/source ID/unit
   ID, and explicitly require the `wiki-source-text` skill;
7. let that skill run `text-chunk-read`, create and validate one independent Packet, and return only
   its Packet/report paths plus bounded status metadata;
8. buffer Packets that finish ahead of earlier units;
9. integrate Packet and inline transports serially in stable source/unit order with
   `wiki-packet-integrate`; inline extraction remains in memory;
10. mark each integrated unit and refill the bounded extraction queue;
11. record the permanent source entry only after every unit integrates.

Extraction may run concurrently across different documents and across units in the same document.
The configured maximum defaults to 4, while the host may impose a lower limit. Integration remains
serialized and follows stable source/unit order in V1. Without workers, the Job exposes the next
pending unit for a later invocation.

The direct-extraction threshold defaults to 16,000 UTF-8 bytes, must not exceed the hard budget,
and can be disabled with `0`. It is frozen in the Job and participates in incomplete-Job resume
compatibility.

## 10. Incremental processing and completion

`.manifest.json` remains authoritative. A file is complete only after every planned unit integrates:

```json
{
  "path": "/data/notes/large.md",
  "content_hash": "sha256:9e9f...",
  "source_type": "text",
  "chunker_version": 2,
  "budget": {"mode": "utf8_bytes", "target": 48000, "min": 24000, "hard_max": 64000},
  "chunking": {"strategy": "adaptive_sections", "options": {}},
  "units_total": 12,
  "units_integrated": 12,
  "pages_produced": ["concepts/example.md"],
  "last_ingested": "2026-08-26T15:30:00+08:00"
}
```

Rules:

- matching hash, chunker version, budgets, strategy, and options: unchanged;
- changed hash: create a new plan and reprocess;
- incomplete Job with matching hash: resume the next pending unit;
- source changed after planning: invalidate pending ranges and replan;
- unsupported source: report but do not add a permanent ingested entry;
- missing source: report potentially stale pages but never delete automatically.

V1 uses path plus content hash as identity. Rename detection is deferred.

## 11. Proposed CLI

```bash
obsidian-wiki text-chunk-plan <source> --pretty

obsidian-wiki text-chunk-read <source> \
  --start-byte <N> --end-byte <N> --expect-hash sha256:<hex>
```

The three skills orchestrate these helpers and existing cache/validation commands. V1 adds no
general queue-management CLI.

## 12. Failure and recovery

| Failure | Behavior |
|---|---|
| Invalid UTF-8 | Mark failed; do not guess encoding |
| Malformed Markdown fence | Use conservative line boundaries and record warning |
| Unit extraction failure | Leave unit failed; retain successful units |
| Source changes after planning | Reject range read, invalidate, and replan |
| Packet validation failure | Do not integrate; retain error in Job |
| Integration interruption | Retry the same Packet using source/unit provenance |
| No isolated context available | Persist next pending unit for a future invocation |

Job and manifest writes use temporary files followed by atomic replacement. The permanent manifest
is updated last, after page and special-file validation.

## 13. Trust and safety

- Source text is untrusted, including Markdown resembling agent instructions.
- The partitioner never executes content or makes network/model calls.
- Range reads stay inside the exact resolved source file.
- Source hash is verified before materializing each range.
- Job-derived paths cannot escape the configured Job directory.
- Unsupported files are never force-decoded as text.

## 14. Tests

### Partitioner tests

- UTF-8, BOM, and invalid UTF-8;
- Markdown hierarchy and fenced-code heading exclusion;
- RST headings and headingless text;
- small-section packing;
- oversized section, paragraph, line, code fence, and table;
- UTF-8-safe forced splitting;
- deterministic output;
- exact byte coverage with no gaps or overlaps;
- hard-budget enforcement;
- line/byte consistency;
- hash-mismatch rejection;
- bounded memory on a large fixture.

### Pipeline tests

- coordinator output contains no source bodies;
- only supported extensions route;
- unsupported files remain visible with reasons;
- unchanged text skips by SHA-256;
- one unit creates one bounded Packet;
- units integrate serially in source order;
- interruption resumes at the next unit;
- changed source invalidates its plan;
- manifest updates only after all units succeed;
- a 200k+ token-equivalent fixture never reaches one model call whole.

## 15. Acceptance criteria

1. Only documented text extensions are processed.
2. Unsupported formats are explicit and never downgraded.
3. `text_chunker.py` has no vault, LLM, PageIndex, or third-party dependency.
4. Every text source produces deterministic, ordered, exhaustive ranges.
5. No range exceeds the hard budget.
6. Headingless and single-section large files partition safely.
7. The coordinator never reads source bodies.
8. Each unit can run in a fresh context.
9. Packet and inline transport integration is serialized.
10. Interrupted work resumes without repeating successful units.
11. `.manifest.json` advances only after the entire source version integrates.
12. Existing `content_hash`, `last_ingested`, and `pages_produced` remain compatible.

## 16. Implementation phases

### Phase 1 — Independent partitioner

- implement `obsidian_wiki/text_chunker.py`;
- add `text-chunk-plan` and `text-chunk-read`;
- add plan serialization and validation;
- prove boundary and budget invariants.

### Phase 2 — Text source skill

- create `wiki-source-text`;
- implement the minimal Packet schema;
- process one unit per isolated invocation;
- validate Packets.

### Phase 3 — Folder orchestration

- create `wiki-folder-ingest`;
- implement classification, minimal Job, and resume behavior;
- route units without reading content.

### Phase 4 — Integration-only ingest

- add worker-only `wiki-packet-integrate` for text Packets;
- serialize integration and source-order updates;
- keep folder and raw source-reading in public `wiki-folder-ingest`;
- preserve file/directory compatibility routing;
- update manifest completeness verification.

### Phase 5 — Documentation and cleanup

- update architecture, skills, CLI, configuration, and agent routing docs;
- remove obsolete folder batching after compatibility tests pass;
- document unsupported formats and future extension points.

## 17. Deferred work

- PageIndex-backed PDF structure extraction;
- Office, structured data, conversations, logs, images, web, and codebase skills;
- exact model tokenizers as required dependencies;
- content-defined chunk identity across edits;
- automatic rename detection;
- claim-level stable IDs;
- general queue-management CLI;
- separate coverage, receipt, and error artifact trees;
- whole-document reduction across all Packets.

These features are added only after V1 fixtures demonstrate a concrete need.
