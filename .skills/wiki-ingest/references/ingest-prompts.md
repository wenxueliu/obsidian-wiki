# Text Ingest Integration Frames

Use these prompts while locating merge targets and integrating validated Packets. Extraction of a
single source range belongs to `wiki-source-text`; these frames restore the cross-Packet and
wiki-aware judgment that only the serial integrator can perform.

## Knowledge routing frame

For the Packet's extracted items, ask:

1. Which important ideas belong on an existing concept page, and which genuinely need a new one?
2. Which people, tools, organizations, or projects deserve an entity page rather than a mention?
3. Which procedures, workflows, or techniques teach a reusable skill?
4. Which claims require attribution, qualification, or an explicit contradiction note?
5. How does this knowledge connect to what the wiki already knows?

The last question is the most important. Packet boundaries are transport boundaries; they must not
become page boundaries. Omit transient detail and repeated prose, but retain useful provenance.

## Synthesis frame

When a Packet covers ground already represented in the wiki:

- do not duplicate it; synthesize it into the canonical narrative;
- if it agrees, strengthen the claim with additional attribution;
- if it disagrees, preserve both positions in an **Open Questions** or **Debate** section and mark
  unresolved wording `^[ambiguous]`;
- if it adds scope, limits, or nuance, weave that into the existing explanation;
- if the connection itself is an integrator inference, mark it `^[inferred]` rather than presenting
  it as source text.

Never invent continuity across forced unit boundaries. Combine fragments only when their locators
and wording support the connection.

## Cross-reference discovery frame

Look for these useful connection patterns:

- **Is-a** — a concept is a specialization of another concept;
- **Uses** — a process or component depends on another entity;
- **Contrasts-with** — two approaches differ materially or disagree;
- **Part-of** — a component belongs to a larger system;
- **Created-by** — an artifact or concept is attributable to an entity;
- **Applied-in** — a concept is used by a project, system, or technique.

Use typed `relationships:` only when the direction and one of the allowed types (`extends`,
`implements`, `contradicts`, `derived_from`, `uses`, `replaces`, `related_to`) are supported. For
other useful patterns, add ordinary reciprocal wikilinks rather than inventing a type.

## V1 boundary

The former Paper Extraction Frame is intentionally absent: PDF/PageIndex ingestion is outside text
V1. QMD corpus discovery, code AST extraction, URL fetching, and structured-data prompts are also
outside this integration contract.
