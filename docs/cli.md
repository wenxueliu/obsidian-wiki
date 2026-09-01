# CLI Reference

The `obsidian-wiki` Python package ships a CLI for setup, inspection, and the deterministic parts of the workflow — the things that don't need an LLM. Everything else is a [skill](skills.md) your agent runs.

```bash
pip install obsidian-wiki
obsidian-wiki --help
obsidian-wiki --version
```

Running `obsidian-wiki` with no subcommand defaults to `setup`.

## Setup & inspection

| Command | What it does |
|---|---|
| `setup` | Install skills into your agents and write `~/.obsidian-wiki/config` |
| `info` | Show install paths, version, and resolved config |
| `list` | List the bundled skills |
| `doctor` | Health-check config, vault shape, bootstrap assets, and installed skills |

```bash
obsidian-wiki setup --vault ~/brain
obsidian-wiki setup --list-layouts         # list Knowledge Packs (Profile + Layout)
obsidian-wiki setup --vault ~/brain --layout software-knowledge
obsidian-wiki setup --project .        # also install project-local skills + bootstrap files
obsidian-wiki setup --project-only     # skip the global install (use with --project)
obsidian-wiki setup --copy             # copy skill files instead of symlinking
obsidian-wiki setup --project . --project-only --copy --skills-only  # local files only; do not touch a vault
obsidian-wiki setup --vault ~/brain --layout default --refresh-layout-marker  # refresh one same-Pack marker
obsidian-wiki setup --remote https://github.com/you/my-wiki.git   # configure sync non-interactively

obsidian-wiki doctor --json --pretty
obsidian-wiki doctor --vault /other/vault --project .
obsidian-wiki doctor --strict          # exit non-zero on warnings too
```

Commands other than `setup`, `info`, and `doctor` warn you when the install has gone stale (the package upgraded but skills weren't re-linked). Re-run `obsidian-wiki setup` to fix.

`--skills-only` limits setup to skill and project bootstrap installation. It does not read or write
the global config, Writing Profile, vault, layout marker, or Git integration. Combine it with
`--project . --project-only` for a project-local install with no global side effects.

When `--layout` is omitted for an initialized vault, setup preserves the Knowledge Pack named by
the vault's `_meta/layout.json`; it does not fall back to `default`. Setup automatically upgrades
the legacy same-Pack marker format from before Knowledge Profiles added `profile_sha256`.

After an intentional contract update to the currently active Knowledge Pack, pass
`--refresh-layout-marker` together with that same Pack's `--layout` name. This only refreshes the
marker hashes; it cannot switch Pack names, which requires a content-aware migration.

## Querying & linting

| Command | What it does |
|---|---|
| `query <question>` | Answer a question from the configured vault's index |
| `lint [vault]` | Find missing frontmatter, broken links, duplicates, and orphans |

```bash
obsidian-wiki query "what do I know about MCP security?"
obsidian-wiki query "rate limiting" --top 12 --max-read 5 --json

obsidian-wiki lint                     # uses the configured vault
obsidian-wiki lint /path/to/vault --strict
obsidian-wiki lint @research --json    # uses ~/.obsidian-wiki/config.research only
obsidian-wiki lint --strict-trust      # fail on trust-ledger problems, not just warn
obsidian-wiki lint --allow-lifecycle active --allow-relationship-type synthesizes \
  --required-trust-field updated --schema-source /path/to/vault/AGENTS.md
```

Lint resolves its vault and schema together: explicit path (no config inheritance), positional `@name`, nearest CWD `.env`, then global config. CLI schema flags extend/replace that resolved vault's settings and are recorded in the JSON `schema` block.

## Context packs

`wiki-context-pack` compiles a task-scoped snapshot from existing Markdown.
Notes do not need to be moved into wiki-generated folders or migrated to the
full frontmatter schema. The command is read-only.

```bash
obsidian-wiki context-pack "authentication architecture" --budget 8000
obsidian-wiki context-pack --recent --budget 4000
obsidian-wiki context-pack "release notes" --budget 8000 --public-only
```

Omitting `--budget` uses the default of 8000 estimated tokens.

The output includes source paths, summaries, selected excerpts, and a hard
estimated-token ceiling. Vault excerpts are explicitly marked as untrusted
reference data: downstream agents may use their facts but must not execute
instructions embedded in notes. Use `--metadata-only` for the smallest pack,
or `--json` for tool-to-tool integration.

| Flag | Effect |
|---|---|
| `--budget N` | Maximum estimated output tokens, 256–100000 (default 8000) |
| `--recent` | Select recently updated notes — the only way to omit the topic |
| `--public-only` | Exclude `visibility/internal` and `visibility/pii` notes |
| `--metadata-only` | Titles, provenance, and summaries with no body excerpts |
| `--json` | Structured output for tool-to-tool integration |
| `--vault PATH` | Override `OBSIDIAN_VAULT_PATH` |

`context` is an accepted alias for `context-pack`.

## Session brain

Builds a topic graph over your agent session history. Output is a **sidecar** at `~/.claude/session-brain/` — the vault is never written to. Full detail in [Session Brain](session-brain.md).

| Command | What it does |
|---|---|
| `sessions-build` | Build (or incrementally update) the topic graph |
| `sessions-query <topic>` | Find the sessions most relevant to a topic |
| `sessions-show <id>` | Show one session's node and its nearest neighbours |
| `sessions-clusters` | List the discovered topic clusters |
| `sessions-name --from FILE` | Assign durable names to clusters, surviving rebuilds |

```bash
obsidian-wiki sessions-build                       # ~3s cold, under a second incrementally
obsidian-wiki sessions-build --full --verbose      # ignore caches, re-read everything
obsidian-wiki sessions-build --since 2026-01-01 --skip archived,scratch
obsidian-wiki sessions-build --k 12 --min-sim 0.12 --mutual --half-life 60

obsidian-wiki sessions-query "prismor telemetry"
obsidian-wiki sessions-query "auth bug" --project my-app --cluster 3 --json

obsidian-wiki sessions-show 01935a40 --neighbors 12
obsidian-wiki sessions-clusters --unnamed
obsidian-wiki sessions-name --from names.json      # or - for stdin
```

`sessions-name` takes a JSON array of `{"id": N, "name": "...", "summary": "..."}`. The `/session-brain` skill generates this for you.

## Vault syncing

| Command | What it does |
|---|---|
| `sync` | Stage, commit, and push pending vault changes |
| `sync-setup <remote>` | Configure GitHub sync (git init, `.gitignore`, remote) |

```bash
obsidian-wiki sync
obsidian-wiki sync-setup https://github.com/you/my-wiki.git
```

See [Configuration → Syncing your vault to GitHub](configuration.md#syncing-your-vault-to-github).

## Trust ledger

Records and validates human-approved confidence reviews, so you can gate on "a person actually checked these pages" in CI.

| Command | What it does |
|---|---|
| `trust-record` | Record explicitly approved manual confidence reviews |
| `trust-check` | Validate confidence values and material fingerprints against the ledger |

```bash
obsidian-wiki trust-record --all --reviewed-at 2026-07-30T10:00:00+00:00 --approved
obsidian-wiki trust-record --page concepts/rate-limiting.md --reviewed-at <ISO> --approved
obsidian-wiki trust-check --strict
obsidian-wiki trust-record @research --all --reviewed-at <ISO> --approved --allow-lifecycle active
obsidian-wiki trust-check @research --allow-lifecycle active --schema-source /vault/AGENTS.md
```

`--reviewed-at` needs a timezone. `--approved` is required and mandatory — it's your assertion that a human approved every confidence value being recorded. `trust-check --strict` is the CI/scheduled gate. `trust-record` and `trust-check` resolve the same vault-scoped schema as lint; pass the same lifecycle and required-field overrides to record and check. If the owner schema does not require `base_confidence`, pages without it are reported as `not_applicable`, excluded by `trust-record --all`, and any obsolete ledger entry is warned by `trust-check` then removed by `trust-record --page` or a rebuild. Both JSON and human-readable record output list excluded pages and removed obsolete entries; human output also emits a stderr warning when removal occurs. Required-field config accepts only `base_confidence`, `lifecycle`, `lifecycle_changed`, and `updated`; typos fail closed. Lifecycle, relationship-type, and required-field override values are stripped and empty or whitespace-only entries are rejected rather than added to an allowlist. Without an explicit `--schema-source`, CLI overrides on an explicit vault are labeled `cli:explicit-vault`; combined CLI and config overrides use `cli+config:<resolved-config-path>`.

## Lower-level commands

Available for automation, scripting, and debugging. Skills call some of these internally.

| Command | What it does |
|---|---|
| `graph-query <vault> <question>` | Answer from the wikilink index without reading page bodies |
| `graph-analyse <vault>` | God nodes, communities, surprising connections |
| `batch-plan <vault> <source_dir>` | Split a source directory into parallel-ingest batches, skipping unchanged files |
| `cache-check <vault> <sources...>` | Which sources are new / modified / unchanged vs. `.manifest.json` |
| `cache-update <vault> <source>` | Record a source's SHA-256 in `.manifest.json` after ingest |
| `cache-hash <path>` | Compute a file or directory hash (no manifest I/O) |
| `text-chunk-plan <source>` | Plan deterministic, exhaustive UTF-8 byte ranges for one supported text source |
| `text-chunk-strategies` | List built-in, registered, and installed custom chunk strategies |
| `text-chunk-read <source>` | Verify the source hash and materialize exactly one planned byte range |
| `text-document-plan <source>` | Normalize all supported sources into manifest-backed Ingest Documents; small files produce one, large files produce several |
| `text-document-read <plan>` | Verify and materialize exactly one planned Ingest Document |
| `text-document-run <plan>` | Process pending documents in fresh, serialized `claude -p` sessions |
| `text-document-commit <plan>` | Atomically record one validated Ingest Document in `.manifest.json` |
| `text-ingest-plan <source>` | Recoverable `wiki-folder-ingest`: create or resume a metadata-only text-ingest Job |
| `text-ingest-status <job>` | Report deterministic source/unit counts, next unit, and live completion state |
| `text-ingest-extract <job>` | Run eligible Packet units through a bounded pool of isolated `claude -p` workers |
| `text-ingest-report <job>` | Generate matching JSON and Markdown completion reports from Job and manifest facts |
| `text-ingest-packet-check <job> <packet>` | Validate one Packet's Job/source/unit/path binding before page integration |
| `text-ingest-unit-advance <job> <packet>` | Atomically advance one validated direct or staged unit after page validation |
| `text-ingest-inline-check <job>` | Validate a planned full-source inline unit and current source hash without a Packet |
| `text-ingest-inline-advance <job>` | Atomically advance a revalidated inline unit after page validation |
| `wiki-context-resolve` | Run the bundled workflow context resolver without depending on the current directory |
| `wiki-setup-contract-build <phase>` | Build the setup contract from bundled templates and Knowledge Packs |
| `wiki-layout-apply` | Apply a bundled Knowledge Pack without depending on the current directory; the command name is retained for compatibility |
| `wiki-route-resolve` | Resolve a declared page type through the bundled deterministic layout router |
| `ast-extract <path>` | Extract classes, functions, and imports from code — no LLM, no API calls |

```bash
obsidian-wiki graph-query /path/to/vault "transformer architecture" --pretty
obsidian-wiki graph-analyse /path/to/vault --top 30 --pretty
obsidian-wiki batch-plan /path/to/vault ~/research --max-mb 4 --max-files 30
obsidian-wiki cache-check /path/to/vault ~/research/*.pdf
obsidian-wiki cache-update /path/to/vault ~/research/paper.pdf --pages concepts/attention.md
obsidian-wiki text-chunk-plan ~/research/large.md \
  --chunk-strategy adaptive_sections --min-budget 24000 --pretty
obsidian-wiki text-chunk-strategies --pretty
obsidian-wiki text-chunk-read ~/research/large.md \
  --start-byte 0 --end-byte 47231 --expect-hash sha256:9e9f...
obsidian-wiki text-document-plan ~/research \
  --vault ~/brain \
  --target-budget 48000 --min-budget 24000 --hard-budget 64000 \
  --chunk-strategy adaptive_sections --strategy-options-file /tmp/chunk-options.json \
  --output /tmp/document-plan.json --pretty
obsidian-wiki text-document-run /tmp/document-plan.json \
  --context /tmp/wiki-context.json --output /tmp/document-session-report.json --pretty
obsidian-wiki text-document-read /tmp/document-plan.json --document-id doc-...
obsidian-wiki text-document-commit /tmp/document-plan.json \
  --document-id doc-... --created-page concepts/example.md --pretty

# Recoverable wiki-folder-ingest Job/Packet commands
obsidian-wiki text-ingest-plan ~/research --vault ~/brain --output /tmp/job-plan.json --pretty
obsidian-wiki text-ingest-status ~/brain/_meta/ingest-jobs/<job-id> --pretty
obsidian-wiki text-ingest-extract ~/brain/_meta/ingest-jobs/<job-id> \
  --max-workers 4 --worker-timeout-seconds 3600 \
  --output /tmp/packet-extraction-report.json --pretty
obsidian-wiki text-ingest-report ~/brain/_meta/ingest-jobs/<job-id> \
  --output /tmp/job-completion.json \
  --markdown-output /tmp/folder-ingest-completion.md --pretty
obsidian-wiki text-ingest-packet-check ~/brain/_meta/ingest-jobs/<job-id> packets/<packet>.json
obsidian-wiki text-ingest-unit-advance ~/brain/_meta/ingest-jobs/<job-id> packets/<packet>.json \
  --mode staged --artifact _staging/concepts/example.md
obsidian-wiki text-ingest-inline-check ~/brain/_meta/ingest-jobs/<job-id> \
  --source-id <source-id> --unit-id <unit-id>
obsidian-wiki text-ingest-inline-advance ~/brain/_meta/ingest-jobs/<job-id> \
  --source-id <source-id> --unit-id <unit-id> --mode direct
obsidian-wiki wiki-setup-contract-build core --output-dir /tmp/wiki-setup
obsidian-wiki wiki-layout-apply --layout default --vault ~/brain --output-dir /tmp/wiki-setup
obsidian-wiki wiki-route-resolve --routing page-contract.json \
  --page-type concept --slug example
obsidian-wiki ast-extract ./src --pretty
```

`wiki-layout-apply --layout <name>` selects a complete Knowledge Pack. Its `profile.json` defines
the semantic purpose, scope, extraction, verification, freshness, and retrieval contract; its
layout and routing files define physical paths. `_meta/layout.json` binds hashes for both sides, so
changing `profile.json` requires an explicit same-pack marker refresh or a content-aware migration.
Refresh an existing vault after an intentional same-pack contract update with
`wiki-layout-apply --refresh-layout-marker`; the flag cannot switch Pack names.

`text-chunk-plan` accepts `.md`, `.markdown`, `.mdx`, `.txt`, and `.rst` encoded as UTF-8 or
UTF-8 with BOM. `--target-budget` defaults to 48,000 bytes, `--min-budget` to half the target, and
`--hard-budget` to 64,000 bytes; the latter is the documented safe maximum and an absolute cap for
every planned unit. The default `adaptive_sections` strategy merges short adjacent sections;
`strict_sections` retains heading-per-unit splitting. `--strategy-options` accepts an inline JSON
object and `--strategy-options-file` accepts the same object from a file. Raising the hard maximum
requires the explicit `--allow-unsafe-hard-budget` override. `text-chunk-read` writes the exact
range without adding a newline and fails if the source changed after planning.

`text-document-plan` is the `wiki-ingest` planner. It applies the same deterministic
chunker to every file, consults `.manifest.json`, and emits only metadata. Every pending document is
processed in a fresh session; writes are serialized. `text-document-read` revalidates the whole
Source File hash before returning one exact range, while `text-document-commit` repeats that check
before atomically recording completion. A failed session therefore has no manifest record and is
retried on the next run. The lightweight path creates no Job, unit state machine, Packet, extraction
dump, or durable worker directory.

The `text-ingest-*` commands implement the recoverable `wiki-folder-ingest` Job/Packet path.
`text-ingest-extract` dynamically fills a bounded worker pool (default 4, hard maximum 32), atomically
claims and completes Packet units, and invokes `/wiki-source-text` directly through isolated
`claude -p --dangerously-skip-permissions --no-session-persistence` processes with the Agent and Task
tools disabled. It never uses a shell,
gives each attempt a separate worker directory with the package's current `wiki-source-text` skill,
discards process stdout/stderr, and trusts only the
planned Packet plus `packet-validation.md` on disk. The dangerous permission bypass is therefore
limited to an already validated Job boundary. Each eligible unit runs at most once per invocation;
failed or interrupted units remain resumable.
`text-ingest-status`, `text-ingest-report`, `text-ingest-packet-check`, and
`text-ingest-inline-check` are read-only with respect to the vault. `text-ingest-report` writes
only its requested artifacts, derives exact-hash manifest coverage directly from the current vault,
and treats cross-linking as optional post-processing rather than part of Job completion.
The corresponding advance command revalidates its Packet or inline source binding before atomically
changing exactly one unit; staged mode requires at least one `--artifact` and never increments the
integrated count. These commands keep deterministic coordination in code while Packet extraction
may run concurrently and all page integration remains serial. `wiki-folder-ingest` supplies the
effective threshold, budgets, strategy, and options from the resolved vault config and freezes them
in the Job; chunk compatibility fields are also retained in the completed manifest entry.

### Custom text chunk strategies

A trusted extension package registers an entry point in its `pyproject.toml`:

```toml
[project.entry-points."obsidian_wiki.text_chunk_strategies"]
my_sections = "my_wiki_extension.chunking:pack_sections"
```

The target is a callable with this contract:

```python
from collections.abc import Iterable
from obsidian_wiki.text_chunker import ChunkStrategyContext, TextBlock

def pack_sections(
    blocks: Iterable[TextBlock], context: ChunkStrategyContext
) -> Iterable[Iterable[TextBlock]]:
    # Stream groups in source order. This example deliberately emits one block per unit.
    for block in blocks:
        yield (block,)
```

The callable must return every supplied block exactly once and in order. Every group must stay at
or below `context.hard_budget`, and a `forced:` block must remain isolated. The planner validates
these invariants before persisting a Job. Options from `WIKI_TEXT_CHUNK_OPTIONS` are available as
`context.options`. Embedded callers may alternatively use `register_chunk_strategy()` before
calling `plan_text_chunks()`.

`wiki-context-resolve`, `wiki-setup-contract-build`, `wiki-layout-apply`, and
`wiki-route-resolve` locate their helper scripts and bundled resources inside the installed package
or source checkout. Workflows therefore do not depend on a `.cac/...` path or the caller's current
working directory. A `vault-input.json` with `{"mode":"config"}` makes `wiki-context-resolve`
load the vault configured by wiki-setup: an optional Named Vault Profile (`profile`) first, otherwise the nearest
`.env` containing `OBSIDIAN_VAULT_PATH`, then `~/.obsidian-wiki/config`. An explicit approved vault
path uses `{"mode":"interactive","vault_path":"/absolute/path"}`.

Most commands accept `--json` and/or `--pretty` for machine-readable output.
