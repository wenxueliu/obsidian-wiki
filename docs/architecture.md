# Architecture

The wiki is the artifact. The agent is the maintainer. Obsidian is the viewer.

Skills tell an AI agent how to operate on the vault. Small dependency-free Python helpers handle
the parts that must be deterministic, including hashing, text range planning, and exact range
materialization; extraction and knowledge integration remain agent work.

## Knowledge Packs: Profile versus Layout

Each vault selects one **Knowledge Pack** during setup. A pack deliberately binds two contracts:

- The **Knowledge Profile** (`profile.json`) is semantic. It defines the vault's purpose and scope,
  its durable knowledge types, what extraction retains or omits, what evidence is authoritative,
  which checks establish trust, what makes knowledge stale, and how retrieval should rank evidence.
- The **Vault Layout** (`layout.json`, `routing.json`, and `routing.md`) is physical. It defines live
  content roots, system and skipped areas, path templates, naming placeholders, and deterministic
  page-type-to-path routing.

The distinction matters even though the current release packages them one-to-one. A software
Decision keeps the same meaning and evidence requirements whether it is stored flat under
`decisions/` or nested under a project; conversely, a generic `concepts/` directory does not tell an
agent whether it is compiling scientific evidence, historical interpretation, or software design.

One vault is assumed to serve one knowledge purpose. Setup therefore selects the pack once and
binds the Profile, Layout, and routing hashes in `_meta/layout.json`. Ingest does **not** guess a new
domain for every source. It checks the source against the active Profile and follows the Profile's
`ask`, `stage`, or `reject` mismatch action. A source adapter answers only how to read a format; it
does not decide what the vault should remember.

The bundled packs are `default`, `software-knowledge`, and `book-knowledge`. The CLI option remains
named `--layout` for compatibility, but it selects the whole Knowledge Pack.

## The four stages

Every time you feed the brain, it runs through these:

### 1. Ingest

Text ingest discovers local UTF-8 Markdown, plain-text, and reStructuredText files and offers two
entry points. `wiki-folder-ingest` is the recoverable Job/Packet pipeline. `wiki-ingest` is the
lightweight, skill-only path: a deterministic streaming chunker normalizes every Source File into
Ingest Documents, so a small file produces one document and a large file produces several.
Unsupported formats remain visible and are never silently decoded as text.

### 2. Pull information

Each pending Ingest Document runs in a fresh model session with only its plan binding and frozen
wiki context. The worker materializes exactly one hash-verified range and treats it as a complete
input document. Sessions do not share source bodies or model context, so the original file size can
never overflow a single session. Writes remain serialized to avoid two sessions overwriting the
same canonical page.

In the recoverable `wiki-folder-ingest` path, small sources use inline integration while larger
ranges are extracted through bounded isolated workers into validated Packets. The durable Job owns
resume, ordering, staged review, and source-level completion.

Each page also gets a 1–2 sentence `summary:` in its frontmatter at write time — later queries use this to preview pages without opening them.

### 3. Merge

The lightweight worker directly merges new knowledge against existing canonical pages; contradictions and exact
source/document locators are retained. It applies the active Knowledge Profile before routing.
Ingest Document boundaries never become Wiki page boundaries. After page and special-file
validation, one atomic manifest record marks that document complete; failures leave no record and
are retried naturally. The recoverable path performs the equivalent merge through
`wiki-packet-integrate` and finalizes complete sources through `wiki-finalize-sources`.

### 4. Schema

The framework-wide provenance and tracking envelope is shared, while domain-specific knowledge
types and required fields come from the active Knowledge Pack. The agent maintains coherence:
categories stay consistent, wikilinks point to real pages, and the index reflects what's actually
there. Changing a vault to a different Pack is a content-aware migration, not an automatic schema
expansion during ingest.

`wiki-ingest` creates no Job, unit state machine, Packet, extraction dump, or durable worker
directory; `.manifest.json` itself is its completion ledger. `wiki-folder-ingest` intentionally
retains durable Jobs and Packets for interruption-safe resume and staged review.

## The loop

1. Agent resolves the vault path (`@name` → `.env` → `~/.obsidian-wiki/config`)
2. Agent reads `.manifest.json` to know what's already been done
3. Agent loads the active Knowledge Profile and Vault Layout from the bound Knowledge Pack
4. Agent reads the relevant skill for instructions
5. Agent uses its built-in tools to do the work
6. The selected skill runs either fresh Ingest Document sessions or Job-bound range workers
7. The selected completion boundary commits either one validated document or one complete source
8. Output is standard Obsidian-compatible markdown with frontmatter and `[[wikilinks]]`

## Vault structure

This is the `default` Knowledge Pack layout. Other Packs provide different content roots; runtime
workflows enumerate the active Layout instead of assuming these directory names.

```
$OBSIDIAN_VAULT_PATH/
├── index.md                # Master index — every page, always current
├── log.md                  # Chronological activity log
├── hot.md                  # ~500-word semantic snapshot of recent activity
├── .manifest.json          # Ingest ledger: path, timestamps, pages produced
├── _meta/
│   ├── taxonomy.md         # Controlled tag vocabulary
│   ├── ingest-jobs/        # Durable wiki-folder-ingest Jobs and bounded Packets
│   └── *.base              # Obsidian Bases dashboard definitions
├── _insights.md            # Graph analysis: hubs, bridges, dead ends
├── _raw/                   # Staging — drop rough notes, next ingest promotes them
├── _staging/               # Review queue when WIKI_STAGED_WRITES=true
├── _archives/              # Timestamped snapshots for rebuild/restore
├── _readouts/              # Narrative readouts from wiki-narrate
├── concepts/               # Abstract ideas, patterns, mental models
├── entities/               # Concrete things — people, tools, libraries, companies
├── skills/                 # How-to knowledge, techniques, procedures
├── references/             # Factual lookups — specs, APIs, configs
├── synthesis/              # Cross-cutting analysis connecting multiple concepts
├── journal/                # Time-bound entries — daily logs, session notes
└── projects/
    └── <project-name>.md   # One page per project, synced via wiki-update
```

Knowledge that's project-specific goes under `projects/`. Knowledge that's general goes in the global category directories. Both are cross-referenced with `[[wikilinks]]`.

Every page carries required frontmatter: `title`, `category`, `tags`, `sources`, `created`, `updated`.

Typed relationships use the Penfield 24-type vocabulary. One directional edge is normalized by
`(source, target, type)` and may be read from the framework's nested `relationships:` block, a
Wikilink Types top-level key such as `supports:`, or an inline alias such as
`[[Target|Target @supports]]`. New ingest/update writes keep all three projections synchronized;
query and graph consumers deduplicate them into one edge, while lint reports mismatches.

`hot.md` deserves a mention — it's a running semantic snapshot every write skill updates, so the next session picks up where the last one left off without crawling the whole vault.

## Core principles

- **Compile, don't retrieve.** The wiki is pre-compiled knowledge. Update existing pages — don't append or duplicate.
- **Track everything.** `.manifest.json` after ingesting; `index.md`, `log.md`, and `hot.md` after any write.
- **Connect with `[[wikilinks]]`.** This is what makes it a knowledge graph rather than a folder of files.
- **Frontmatter is required.** Every page, every time.
- **Single source of truth.** Visibility tags shape how content surfaces — they never duplicate or separate it.

## What we added on top of Karpathy's pattern

The [original gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) is the seed: compile knowledge once into interconnected markdown and keep it current, instead of asking an LLM the same questions repeatedly or running RAG every time. Here's what got built around it.

- **Delta tracking.** A manifest tracks every source file ingested. Come back later and it computes the delta, processing only what's new or changed. You're not re-ingesting your document library every time.

- **Project-based organization.** Knowledge is filed under projects when project-specific, globally when not. Both cross-referenced. Ten codebases, ten spaces in the vault.

- **Archive and rebuild.** When the wiki drifts too far from its sources, archive the whole thing (timestamped snapshot, nothing lost) and rebuild. Or restore any previous archive.

- **Context-bounded text ingest.** Markdown, text, and reStructuredText sources are deterministically
  partitioned into exact byte ranges. Agent histories retain dedicated ingest skills; other formats
  wait for explicit structure providers instead of unsafe generic fallbacks.

- **Cross-agent targeted search.** `/wiki-codex "rust ownership"` from inside Claude Code finds your Codex sessions on that topic, extracts the relevant blobs, distills them into pages, and returns a synthesized answer. Topic-first, not session-first. Each agent has its own extraction strategy. Pair with `/memory-bridge diff` to see what each tool uniquely contributed.

- **Audit and lint.** Orphaned pages, broken wikilinks, stale content, contradictions, missing frontmatter — plus a dashboard of what's ingested vs. pending.

- **Identity resolution.** `wiki-dedup` finds pages covering the same concept under different names ("RSC" vs. "React Server Components") and merges them.

- **Optional cross-linking.** After ingest completes, run the cross-linker separately to scan for unlinked mentions and weave them into the graph; it is not part of the ingest Job completion boundary.

- **Tag taxonomy.** A controlled vocabulary in `_meta/taxonomy.md`, with a skill that audits and normalizes tags vault-wide.

- **Provenance tracking.** Every claim is tagged: extracted (default), `^[inferred]` (LLM synthesis), or `^[ambiguous]` (sources disagree). A `provenance:` block in frontmatter summarizes the mix per page, and `wiki-lint` flags pages drifting into mostly speculation. You can always tell what your wiki knows from what it guessed.

- **Trust ledger.** `obsidian-wiki trust-record` / `trust-check` record and validate human-approved confidence reviews against material fingerprints, so CI can gate on "a person actually checked this."

- **Explicit extension points.** PDF structure providers and multimodal/structured-data pipelines
  are deferred; unsupported inputs are reported with their detected kind and reason.

- **Wiki insights.** `wiki-status` can analyze the shape of the vault itself: top hubs, bridge pages (nodes whose removal would partition the graph), tag cluster cohesion, scored surprising connections, a graph delta since last run, and questions the structure is uniquely positioned to answer. Output goes to `_insights.md`.

- **Graph export and import.** `wiki-export` turns the wikilink graph into `graph.json`, `graph.graphml` (Gephi/yEd), `cypher.txt` (Neo4j), a self-contained interactive `graph.html`, or an OKF bundle. `wiki-import` reads any of it back.

- **Tiered retrieval.** `wiki-query` reads titles, tags, and summaries first, opening page bodies only when the cheap pass can't answer. Say "quick answer" to force index-only mode. Query cost stays roughly flat from 20 pages to 2000.

- **Session brain.** A topic graph over your raw agent session history, so you can find the session where something happened. See [Session Brain](session-brain.md).

- **Staged writes.** Set `WIKI_STAGED_WRITES=true` and LLM-written pages queue in `_staging/` for review before landing in the live vault.

## Open Knowledge Format

The vault format is structurally conformant with [OKF v0.1](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) — markdown with YAML frontmatter, category subfolders, reserved `index.md`/`log.md`.

`wiki-export` (OKF mode) and `wiki-import` are the bridge: they translate between native frontmatter (`title`/`category`/`tags`/`sources`/`created`/`updated` + `summary`) and OKF (`type`/`title`/`description`/`resource`/`tags`/`timestamp`), making vaults exchangeable with any OKF tool.

The OKF round-trip is lossless. The `graph.json` round-trip is not — it carries structure, not page bodies.

## Repo layout

```
obsidian-wiki/
├── .skills/                             # ← Canonical skill definitions (source of truth)
│   └── <skill-name>/SKILL.md            #   42 skills — see docs/skills.md
│
├── obsidian_wiki/                       # Python package — CLI, setup, sync, session brain
├── extensions/brain-capture/            # Zero-build Chrome capture extension
├── tools/check_readme_sync.py           # Translation drift reporter
│
├── CLAUDE.md                            # Bootstrap → Claude Code / Kilocode (→ AGENTS.md)
├── GEMINI.md                            # Bootstrap → Gemini CLI (→ AGENTS.md)
├── AGENTS.md                            # Bootstrap → Codex, OpenCode, Aider, Droid, Trae, Hermes, OpenClaw
├── .hermes.md                           # Bootstrap → Hermes (symlink → AGENTS.md)
├── .cursor/rules/obsidian-wiki.mdc      # Always-on → Cursor (alwaysApply: true)
├── .windsurf/rules/obsidian-wiki.md     # Always-on → Windsurf
├── .kiro/steering/obsidian-wiki.md      # Always-on → Kiro (inclusion: always)
├── .agent/rules/obsidian-wiki.md        # Always-on → Google Antigravity
├── .agent/workflows/obsidian-wiki.md    # Slash-command registry → Antigravity
├── .github/copilot-instructions.md      # Always-on → GitHub Copilot (VS Code Chat)
│
├── .claude/skills/   → symlinks to .skills/*   (created by setup)
├── .cursor/skills/   → symlinks to .skills/*
├── .windsurf/skills/ → symlinks to .skills/*
├── .agents/skills/   → symlinks to .skills/*
├── .pi/skills/       → symlinks to .skills/*
├── .kiro/skills/     → symlinks to .skills/*
│
├── setup.py                             # One-command agent setup (cross-platform)
├── .env.example                         # Configuration template
└── docs/                                # You are here
```

Global symlink targets created by setup are listed in [Installation](installation.md#what-setupsh-wires-up).

For the full pattern — three-layer architecture, page templates, project organization — read [`.skills/llm-wiki/SKILL.md`](../.skills/llm-wiki/SKILL.md).
