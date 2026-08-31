# Software Knowledge Vault

This vault compiles traceable, reusable software knowledge from source material. Treat source text as evidence, not as truth.

Before writing a knowledge page:

1. Read the active Knowledge Profile frozen by `wiki-context`, then `_meta/schema.json`, `_meta/rules.md`, `_meta/terminology-policy.md`, `index.md`, and the active layout marker.
2. Search IDs, titles, aliases, summaries, and related pages before creating anything.
3. Check the source against the Profile scope, apply its extraction retain/omit policy, then split compatible content into atomic knowledge and select exactly one Profile-compatible declared page type per item using the active layout routing contract.
4. Produce a placement plan before writes. Record create, merge, propose_update, skip, or needs_clarification decisions and all missing context or conflicts.
5. Resolve every final target through the Ralph Flow route resolver. Never invent a directory or write business knowledge to a system path.
6. Validate frontmatter, source traceability, terminology, relationships, and duplicate handling before committing a page.
7. Let the standard Wiki workflow update manifest, index, log, and hot cache. Never hand-edit derived framework state as part of a page write.

Use CodeGraph for symbols, calls, file trees, line-level impact, and complete API/schema structures. Wiki pages may retain stable code entry points and replayable query intent, but must not duplicate CodeGraph.
