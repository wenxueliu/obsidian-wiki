# Software Knowledge Rules

## Knowledge boundary

- Classify by durable meaning, not by source filename, source directory, meeting type, or document format.
- One page has one primary knowledge type. Split mixed changes, behaviors, rules, architecture responsibilities, contracts, decisions, and reusable patterns when they can evolve independently.
- Compile definitions, constraints, behavior, decisions, relationships, boundaries, evidence, and open questions. Do not archive or copy whole source passages.
- Search first. Prefer canonical merge over a new page; skip transient or mechanically derivable information.
- Do not create pages for ordinary code symbols or copy full CodeGraph paths, OpenAPI, Proto, GraphQL, DDL, DTO, or ORM structures.

## Evidence and state

- Every formal page must identify a source ID, URI, revision, and locator. Missing values are `missing_context`, never guessed values.
- Mark claims as extracted, inferred, or ambiguous. Conflicting claims remain side by side with their sources and must not silently replace one another.
- `lifecycle` records knowledge maturity: draft, reviewed, verified, disputed, or archived.
- `operational_status.state` records the described object's runtime state: active, deprecated, or sunset. Never infer one axis from the other.
- Stable code references include project, revision, symbol, relation, verification time, and replayable CodeGraph query intent. Revalidate references after repository drift.

## Page threshold and relationships

A formal page requires one clear type, durable reuse value, no equivalent canonical page, at least one locatable source, a globally unique ID, a meaningful relationship or explicit reason for independence, and successful Schema validation.

Use typed Wikilinks such as `belongs_to`, `defines`, `realizes`, `constrained_by`, `implemented_by`, `hosted_by`, `exposed_through`, `decided_by`, `verified_by`, `depends_on`, `supersedes`, `replaces`, and `related_to`. Put relationships whose targets do not yet exist in `pending_relations` rather than creating dead links.

## Write boundary

- Plan mode performs no writes.
- Staged mode writes new pages or patches below `_staging/<category>/`.
- Direct mode is allowed only for confirmed, traceable, conflict-free, Schema-valid input; otherwise stage it.
- When `WIKI_STAGED_WRITES=true`, staged mode overrides any requested direct mode.
- Never write business knowledge directly to `index.md`, `log.md`, `hot.md`, `.manifest.json`, `_meta/`, `_state/`, `_archives/`, `_readouts/`, or `.codegraph/`.
- Framework workflows alone advance manifest, index, log, and hot cache after the complete source transaction succeeds.
