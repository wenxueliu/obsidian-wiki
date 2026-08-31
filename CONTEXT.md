# Obsidian Wiki

The project compiles source material into a persistent, interconnected knowledge graph represented as Obsidian-compatible Markdown.

## Language

**Typed Relationship**:
A directional semantic assertion from one source page to one target page using a declared relationship type.
_Avoid_: Typed link, semantic link

**Edge Identity**:
The unique `(source page, target page, relationship type)` identity of a Typed Relationship, independent of how it is represented in Markdown or YAML.
_Avoid_: Link identity

**Relationship Projection**:
A persisted expression of an Edge Identity in one of the vault's supported authoring or metadata forms.
_Avoid_: Relationship format, duplicate edge

**Relationship Vocabulary**:
The effective allowlist of relationship types for a vault, consisting of the framework vocabulary plus owner-declared extensions.
_Avoid_: Link types
