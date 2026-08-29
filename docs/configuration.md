# Configuration

## How config is resolved

Skills resolve the vault path in this order:

0. **Inline vault override (`@name`)** — an `@<name>` token anywhere in a request resolves `~/.obsidian-wiki/config.<name>` directly, overriding everything below, **for that request only**.
1. **Walk up from CWD** — look for a `.env` in the current directory, then each parent, up to `$HOME`. Stop at the first one containing `OBSIDIAN_VAULT_PATH`.
2. **Global config** — `~/.obsidian-wiki/config`.
3. **Prompt setup** — if neither exists, you'll be told to run setup.

After resolving, skills also read `$OBSIDIAN_VAULT_PATH/AGENTS.md` if it exists. That's where you put owner-specific conventions — domain vocabulary, ingest preferences, writing style, project scoping — which override framework defaults for every skill.

Both `~/.obsidian-wiki/config` and `.env` use the same `KEY=value` format. Start from [`.env.example`](../.env.example).

## Vault layout

Vault layout is not an environment setting. Setup selects a bundled contract from
`workflows/layouts/<name>/` and records its identity and integrity hashes in
`$OBSIDIAN_VAULT_PATH/_meta/layout.json`. That marker travels with the vault and is the source of
truth for its content roots, system directories, and page routes. Subsequent workflows reload the
named bundled contract and fail closed when the recorded hashes are stale.

Use `obsidian-wiki setup --list-layouts` to inspect available layouts and select one during setup.
Changing an existing vault to another layout requires a content-aware migration; editing `.env`,
renaming directories, or changing the marker by hand is not a supported switch mechanism.

## Global wiki writing profile

Setup creates `~/.obsidian-wiki/WRITING.md` on POSIX systems, or
`%LOCALAPPDATA%/.obsidian-wiki/WRITING.md` on Windows. It never overwrites an existing profile.
Use it for writing preferences shared across projects, for example:

```markdown
## Language

Write in Chinese. Keep technical identifiers in their original form.

## Tone and Voice

Be concise, direct, and practical.

## Avoid

Avoid filler, repetition, and unsupported claims.
```

Precedence is framework invariants and task requirements, then project `AGENTS.md`, vault
`AGENTS.md`, and finally global `WRITING.md`. The profile affects only newly drafted or rewritten
natural-language wiki content. It cannot change schema, provenance, JSON, structured logs, patches,
or pass-through source text. Missing, empty, or unreadable profiles do not block an operation.

The deterministic `lint`, `trust-record`, and `trust-check` commands use the same vault-scoped resolution: an explicit path uses no unrelated config, `@name` reads only `~/.obsidian-wiki/config.<name>`, otherwise the nearest CWD `.env` wins before global config. Schema settings are read from that same resolved config only, so one vault's lifecycle extensions cannot leak into another vault.

## Core

| Variable | What it does | Default |
|---|---|---|
| `OBSIDIAN_VAULT_PATH` | **Required.** Absolute path to your vault | — |
| `OBSIDIAN_WIKI_REPO` | Where this repo is cloned (set by setup; used for skill/asset lookups) | *auto* |
| `OBSIDIAN_SOURCES_DIR` | Comma-separated source directories to ingest documents from | *(empty)* |
| `OBSIDIAN_MAX_PAGES_PER_INGEST` | Max pages created or updated per ingest | `15` |
| `OBSIDIAN_LINK_FORMAT` | `wikilink` → `[[concepts/foo]]`, or `markdown` → `` [text](path.md) ``. Affects future writes only — existing content is never migrated | `wikilink` |
| `LINT_SCHEDULE` | Health-check frequency: `daily` \| `weekly` \| `manual` | `weekly` |

Local git repo clones work in `OBSIDIAN_SOURCES_DIR` (public or private, any host). Clone locally, then add the path. Repo directories are auto-detected via a `.git` folder and enumerated with `git ls-files`, so whatever the repo's own `.gitignore` excludes — `node_modules`, build output, venvs, secrets — is skipped automatically rather than relying on a hardcoded skip-list.

## History ingest

| Variable | What it does | Default |
|---|---|---|
| `CLAUDE_HISTORY_PATH` | Where to find Claude data | *auto-discovers from `~/.claude`* |
| `CODEX_HISTORY_PATH` | Where to find Codex data | `~/.codex` |
| `HERMES_HISTORY_PATH` | Where to find Hermes data | `~/.hermes` |
| `OPENCLAW_HISTORY_PATH` | Where to find OpenClaw data | `~/.openclaw` |
| `COPILOT_HISTORY_PATH` | Where to find Copilot CLI data | `~/.copilot/session-state` |
| `PI_HISTORY_PATH` | Where to find Pi sessions | `~/.pi/agent/sessions` |
| `WIKI_SKIP_PROJECTS` | Comma-separated substrings; project dirs matching any are skipped during scan, delta, and manifest steps. e.g. `archived,scratch,sandbox` | *(empty)* |
| `WIKI_SESSION_BRAIN_DIR` | Where the session-brain sidecar is written | `~/.claude/session-brain` |

## Staged writes & trust

| Variable | What it does | Default |
|---|---|---|
| `WIKI_STAGED_WRITES` | When `true`, LLM-written pages land in `_staging/` for human review instead of the live vault. Promote them with `/wiki-stage-commit` | *(unset — direct writes)* |
| `OBSIDIAN_TRUST_STRICT` | When `1`, `obsidian-wiki lint` treats missing trust fields, ledger errors, stale reviews, and score mismatches as failures rather than warnings. Same as `lint --strict-trust` | *(unset)* |
| `OBSIDIAN_ALLOWED_LIFECYCLES` | Comma-separated lifecycle extensions for this resolved vault | *(framework defaults only)* |
| `OBSIDIAN_ALLOWED_RELATIONSHIP_TYPES` | Comma-separated relationship-type extensions for this resolved vault | *(framework defaults only)* |
| `OBSIDIAN_REQUIRED_TRUST_FIELDS` | Comma-separated effective required trust fields. Allowed values: `base_confidence`, `lifecycle`, `lifecycle_changed`, `updated`; unknown values fail closed | `base_confidence,lifecycle` for lint; also `updated` for standalone trust commands |
| `OBSIDIAN_SCHEMA_SOURCE` | Owner authority locator emitted in machine reports | `config:<resolved-config-path>` when overrides exist |

Schema resolution precedence is CLI flags > resolved environment/config values > framework defaults. Lifecycle and relationship-type extension lists are additive to framework defaults; CLI required-field values replace environment requiredness. CLI-only schema overrides use a `cli:<context>` source label rather than claiming a config-file provenance. If CLI and resolved config both contribute overrides, reports use `cli+config:<resolved-config-path>` unless `--schema-source` or `OBSIDIAN_SCHEMA_SOURCE` supplies the owner authority explicitly.

The four schema variables are `OBSIDIAN_ALLOWED_LIFECYCLES`, `OBSIDIAN_ALLOWED_RELATIONSHIP_TYPES`, `OBSIDIAN_REQUIRED_TRUST_FIELDS`, and `OBSIDIAN_SCHEMA_SOURCE`. When any is present, its value and every comma-separated entry must be non-empty after trimming whitespace. Empty values, repeated commas, and trailing commas fail closed with exit 1; remove the variable entirely to use framework defaults. The distributable `.env.example` documents safe commented examples for all four.

Staged pages aren't visible in Obsidian's graph until promoted. `wiki-status` lists pending staged
writes first when this mode is on. For text-ingest Jobs, staged units remain `awaiting_review` and
do not increase `units_integrated` or advance the permanent source manifest until every required
artifact is accepted and live. The `_staging/` directory is created at setup even when the mode is
off.

## Vault Skill Factory

`vault-skill-factory` turns mature curated pages into portable Agent Skills. Generated skills land in a **review directory** — never auto-installed, never written into `.skills/`.

| Variable | What it does | Default |
|---|---|---|
| `SKILL_FACTORY_OUTPUT_DIR` | Where generated skills are written | `<vault>/_generated-skills` |
| `SKILL_FACTORY_MATURITY` | Which lifecycle states count as mature enough to harvest (pages with `tier: core` also qualify) | `reviewed,verified` |

## Text ingest extraction and chunking

Text ingest V1 uses dependency-free UTF-8 byte budgets rather than a model-specific tokenizer.
`wiki-folder-ingest` resolves these values from the target vault's config and records the effective
values in each durable Job. A changed budget creates a new plan instead of resuming an incompatible
incomplete Job.

| Variable | What it does | Default |
|---|---|---|
| `WIKI_FOLDER_INGEST_MAX_EXTRACTION_WORKERS` | Maximum concurrent isolated unit-to-Packet extraction workers per Job; the host may impose a lower limit | `4` |
| `WIKI_TEXT_DIRECT_EXTRACT_MAX_BYTES` | Complete sources at or below this size use serial inline extraction/integration without a Packet file; `0` disables | smaller of `16000` and the hard maximum |
| `WIKI_TEXT_CHUNK_TARGET_BYTES` | Preferred UTF-8 byte size for each planned text unit | `48000` |
| `WIKI_TEXT_CHUNK_MIN_BYTES` | Minimum accumulated size before a heading becomes a preferred split point | half the target (`24000` by default) |
| `WIKI_TEXT_CHUNK_HARD_MAX_BYTES` | Absolute UTF-8 byte cap for each planned text unit | `64000` |
| `WIKI_TEXT_CHUNK_STRATEGY` | `adaptive_sections`, `strict_sections`, or an installed custom strategy name | `adaptive_sections` |
| `WIKI_TEXT_CHUNK_OPTIONS` | JSON object passed to the selected strategy | `{}` |

The three budgets must be positive integers, minimum ≤ target ≤ hard maximum, and the workflow hard
maximum cannot exceed 64,000 bytes. The direct-extraction threshold must be a non-negative integer
no larger than the hard maximum. Inline sources retain one logical unit for provenance, staged
review, resumability, and finalization, but do not create a Packet file. `adaptive_sections` merges adjacent short sections until the
minimum is reached and may merge a small tail above target when it remains within the hard maximum.
`strict_sections` preserves the legacy behavior where every heading-path change ends a unit. For
direct CLI use, the corresponding flags override command defaults per invocation.

Custom strategy names come from trusted installed Python packages using the
`obsidian_wiki.text_chunk_strategies` entry-point group. Selecting one executes that package's code;
do not configure an untrusted extension.

Extraction concurrency applies across packet units in the whole Job, including multiple units from
the same source document. Workers write distinct Packet files and never mutate shared wiki state. Completed Packets
are buffered and integrated serially in stable source/unit order, so increasing this value speeds up
extraction without making page writes concurrent.

PageIndex is not a V1 dependency. A future PDF pipeline may use it only as a structure provider
behind the local hard-budget splitter; PDFs remain explicitly unsupported until that pipeline exists.

## QMD semantic search (optional)

By default, `wiki-folder-ingest` and `wiki-query` use Grep/Glob — fully functional, no extra setup. If your vault grows large or you want concept-level matches across your sources, plug in [QMD](https://github.com/tobi/qmd), either through MCP or by letting the agent call the local `qmd` CLI.

| Variable | What it does | Default |
|---|---|---|
| `QMD_WIKI_COLLECTION` | Collection indexing your compiled wiki pages — used by `wiki-query` | *(empty — disabled)* |
| `QMD_PAPERS_COLLECTION` | Collection indexing your raw source documents — used by the text-ingest pipeline | *(empty — disabled)* |
| `QMD_TRANSPORT` | `mcp` (agent-configured MCP server) or `cli` (local `qmd` binary) | `mcp` |
| `QMD_CLI_SEARCH_MODE` | `quality` (rerank, best relevance), `balanced` (`--no-rerank`), or `fast` (semantic only) | `quality` |
| `QMD_CLI` | Override the `qmd` binary path if it isn't on `PATH` | `qmd` |

**Setup:**

```bash
qmd collection add /path/to/vault --name my-wiki
qmd collection add /path/to/sources --name papers
```

```env
QMD_WIKI_COLLECTION=my-wiki
QMD_PAPERS_COLLECTION=papers
QMD_TRANSPORT=mcp
QMD_CLI_SEARCH_MODE=quality
```

> **The two collections must stay disjoint.** `wiki-query` treats them as separate layers — compiled knowledge vs. raw staging — and cites them separately. Since `OBSIDIAN_VAULT_PATH` contains `_raw/`, a plain `qmd collection add <vault>` merges the two layers and makes superseded drafts retrievable and citable as though they were compiled pages.
>
> QMD has no `--ignore` flag, so scope the collection by editing `~/.config/qmd/index.yml`:
>
> ```yaml
> collections:
>   my-wiki:
>     path: /path/to/vault
>     pattern: "**/*.md"
>     ignore:
>       - "_raw/**"
>       - "log.md"
> ```
>
> Then run `qmd update`.

**What changes when it's on:**

- `wiki-query` runs a semantic pass (lex+vec) against your wiki collection before falling back to Grep — finds conceptually related pages even when the exact terms don't match.
- `wiki-folder-ingest` coordinates Packet or inline transport integration against your papers collection before writing a new page — surfacing related sources, spotting contradictions, and deciding whether to create a new page or merge into an existing one.

Both degrade gracefully: with the collection names unset, they skip the QMD step silently and use Grep.

## `_raw/` staging directory

`_raw/` is a staging area inside your vault for unprocessed UTF-8 text captures. Drop supported text
files there and the next `wiki-folder-ingest` run processes them; after complete
integration, originals move to `_raw/_archived/` so they are preserved without being processed twice.

The fastest way to feed it during a live coding session:

```text
/wiki-capture --quick
```

It scans the current conversation, extracts bugs and gotchas, and writes structured draft files in under 60 seconds — no subagents, no manifest writes.

To promote everything waiting there:

```text
/wiki-folder-ingest promote my raw pages
```

The directory is created automatically by the selected workflow layout during `wiki-setup`.

### Browser capture extension

This repo includes a zero-build Chrome extension at [`extensions/brain-capture/`](../extensions/brain-capture/) for saving web pages and selected text straight into `_raw/`.

1. Open `chrome://extensions`
2. Enable **Developer mode**
3. Click **Load unpacked**
4. Select `extensions/brain-capture`

To find your configured `_raw` folder from a clone of this repo:

```bash
awk -F= '/^OBSIDIAN_VAULT_PATH=/{print $2 "/_raw"; exit}' "$(git rev-parse --show-toplevel)/.env"
```

## Syncing your vault to GitHub

Your vault is a directory of plain markdown files — push it to a private GitHub repo and you get version history, backup, and cross-device sync for free. `obsidian-wiki setup` and `python3 setup.py` both offer to configure this during install; they share one implementation (`obsidian_wiki/sync.py`), so pip and source installs get an identical flow.

**What setup does:**

1. `git init` your vault if it isn't already a repo
2. Creates a `.gitignore` excluding Obsidian workspace/cache files
3. Sets the remote you supply — the vault's own `git remote`, not a config file, is the source of truth for whether sync is configured, so it can't drift
4. Optionally adds a `wiki-sync` shell alias
5. Optionally installs an hourly cron job

**Run a sync at any time:**

```bash
wiki-sync            # alias added by setup
obsidian-wiki sync   # or call it directly
```

Each run stages all changes, commits as `sync 2026-07-30 14:00`, and pushes.

**Configure it later, or by hand:**

```bash
obsidian-wiki sync-setup https://github.com/you/my-wiki.git
# or:
cd /path/to/your/vault
git init
git remote add origin https://github.com/you/my-wiki.git
```

**Hourly auto-sync via cron:**

```
0 * * * * obsidian-wiki sync --vault /path/to/your/vault >> ~/.obsidian-wiki/sync.log 2>&1
```

> Keep the repo **private** if your vault contains personal notes. Nothing is sent to any third-party service — your vault lives on your machines and in your GitHub account only.

## Visibility tags (optional)

Pages can carry a `visibility/` tag marking their intended reach. This is **entirely optional** — untagged pages behave exactly as they always have. The system stays single-vault, single source of truth.

| Tag | Meaning |
|---|---|
| *(none)* | Same as `visibility/public` — visible in all modes |
| `visibility/public` | Explicitly public |
| `visibility/internal` | Team-only — excluded in filtered mode |
| `visibility/pii` | Sensitive — excluded in filtered mode |

**Filtered mode** is opt-in, triggered by phrases like "public only", "user-facing answer", "no internal content", or "as a user would see it" in a query. Default mode shows everything.

`visibility/` tags are **system tags** — they don't count toward the 5-tag limit and are listed separately from domain/type tags in the taxonomy.
