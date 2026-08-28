# Text Range Knowledge Extraction Frame

Use this frame only after materializing the one range assigned by the Job. The range is a transport
window, not necessarily a complete document or section. Extract what the range supports without
guessing what precedes or follows it.

## Identify durable knowledge

Ask these questions in order:

1. **What are the most important ideas in this range?**
   Capture concepts or definitions that remain useful outside the source's immediate wording. Do
   not force a quota; a range may contain no durable concept or several.
2. **Who or what is materially discussed?**
   Capture people, tools, libraries, organizations, products, standards, and projects as entities
   only when the range says something useful about them. A passing mention is not enough.
3. **What does the range teach someone to do?**
   Capture procedures, workflows, techniques, constraints, and failure-recovery steps as skill
   candidates. Preserve ordering and prerequisites when explicitly stated.
4. **What claims does the range make?**
   Capture factual statements, decisions, trade-offs, requirements, measurements, and conclusions.
   Keep qualifications, scope, and uncertainty; a shorter claim must not become stronger than its
   source sentence.
5. **What relationships are explicit?**
   When direction and meaning are clear, use the standard relationship vocabulary and effective
   owner extensions from `llm-wiki/SKILL.md`. Prefer current standard types over legacy aliases.
   Omit a typed relationship when the range only implies a vague association.
6. **What questions remain open?**
   Capture questions the range raises but does not resolve, including missing evidence or a
   forced-split statement whose conclusion lies outside the range.

Drop navigation, boilerplate, repeated framing, raw code listings, and details that are useful only
for reconstructing the source. Consolidate repetitions within the range, but do not reconcile with
other ranges or the wiki; the integration stage owns cross-Packet synthesis.

## Classify provenance per item

Assign one provenance state to every extracted item:

- `extracted` — explicitly stated by this range;
- `inferred` — a local implication or generalization that is useful but not stated verbatim;
- `ambiguous` — wording is vague, internally inconsistent, or cut by the range boundary.

Prefer `extracted`. Never use outside knowledge to fill a missing premise. Preserve competing
statements as separate `ambiguous` items rather than selecting a winner.

## Attach exact locators

Every concept, claim, entity, relationship, and question needs the narrowest supporting locator:

```json
{
  "start_line": 12,
  "end_line": 18,
  "start_byte": 341,
  "end_byte": 812
}
```

Line numbers and byte offsets are absolute source coordinates and must stay within the assigned
unit. When multiple disjoint spans support one item, emit separate locators. Use the whole unit only
when the support genuinely spans the whole unit.

## Suggested item shapes

Keep Packet items compact and declarative:

```json
{
  "concepts": [
    {"name": "...", "description": "...", "provenance": "extracted", "locator": {}}
  ],
  "claims": [
    {"text": "...", "provenance": "extracted", "locator": {}}
  ],
  "entities": [
    {"name": "...", "kind": "tool", "description": "...", "provenance": "extracted", "locator": {}}
  ],
  "relationships": [
    {"source": "...", "target": "...", "type": "uses", "provenance": "extracted", "locator": {}}
  ],
  "questions": [
    {"text": "...", "provenance": "ambiguous", "locator": {}}
  ]
}
```

These are item shapes inside the minimal Packet contract, not instructions to create wiki pages.
Do not select categories, filenames, tags, page tiers, or wikilinks here.

## Forced-split discipline

For a forced split:

- use the inherited heading path only for orientation;
- do not complete truncated sentences, code, list items, or table rows;
- mark boundary-dependent items `ambiguous` and add a warning;
- do not extract a context hint as evidence;
- allow an empty extraction when the range contains no complete, supportable knowledge.
