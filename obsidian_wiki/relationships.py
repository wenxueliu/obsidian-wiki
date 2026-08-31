"""Typed relationship vocabulary and representation normalization.

The wiki accepts three persisted projections of the same directional edge:

* ``relationships: [{target, type}]`` — the framework's legacy nested form;
* top-level ``supports: ["[[Target]]"]`` keys — Wikilink Types compatibility;
* body ``[[Target|Label @supports]]`` aliases — human authoring syntax.

Consumers normalize all three to one ``(target, relation)`` identity and keep
the representations that supplied it. Writers are expected to keep the
projections consistent; readers remain tolerant of legacy single-form pages.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from collections.abc import Collection
from typing import Any


STANDARD_RELATIONSHIP_TYPES = frozenset(
    {
        "supersedes", "updates", "evolution_of",
        "supports", "contradicts", "disputes",
        "parent_of", "child_of", "sibling_of", "composed_of", "part_of",
        "causes", "influenced_by", "prerequisite_for",
        "implements", "documents", "tests", "example_of",
        "responds_to", "references", "inspired_by",
        "follows", "precedes",
        "depends_on",
    }
)

LEGACY_RELATIONSHIP_TYPES = frozenset(
    {"extends", "derived_from", "uses", "replaces", "related_to"}
)

ALLOWED_RELATIONSHIP_TYPES = STANDARD_RELATIONSHIP_TYPES | LEGACY_RELATIONSHIP_TYPES

_FRONT_RE = re.compile(r"^---\r?\n(.*?)\r?\n---(?:\r?\n|$)", re.DOTALL)
_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+?)(?:[|#][^\]]*?)?\]\]")
_WIKILINK_WITH_ALIAS_RE = re.compile(r"\[\[([^\]|]+)\|([^\]]+)\]\]")
_AT_TYPE_RE = re.compile(r"(?:^|\s)@([\w-]+)")
_FENCE_RE = re.compile(r"^\s*(?:>\s*)?(`{3,}|~{3,})")
_INLINE_CODE_RE = re.compile(r"(`+)(.*?)\1")


def normalise_target_slug(raw: str) -> str:
    """Normalize a wikilink target to the basename slug used by graph indexes."""
    target = raw.strip().removeprefix("[[").removesuffix("]]")
    target = target.split("|", 1)[0].split("#", 1)[0].strip()
    if target.lower().endswith(".md"):
        target = target[:-3]
    target = target.strip("/").split("/")[-1]
    return target.strip().lower().replace(" ", "-")


def split_frontmatter(text: str) -> tuple[str, str]:
    """Return ``(frontmatter_without_markers, body)``."""
    match = _FRONT_RE.match(text)
    if not match:
        return "", text
    return match.group(1), text[match.end():]


def strip_code_content(body: str) -> str:
    """Mask fenced, indented, and inline code before parsing authored links."""
    output: list[str] = []
    fence_char = ""
    fence_len = 0
    for line in body.splitlines(keepends=True):
        fence = _FENCE_RE.match(line)
        if fence_char:
            token = fence.group(1) if fence else ""
            if token and token[0] == fence_char and len(token) >= fence_len:
                fence_char = ""
                fence_len = 0
            output.append("\n" if line.endswith("\n") else "")
            continue
        if fence:
            token = fence.group(1)
            fence_char = token[0]
            fence_len = len(token)
            output.append("\n" if line.endswith("\n") else "")
            continue
        if line.startswith("    ") or line.startswith("\t"):
            output.append("\n" if line.endswith("\n") else "")
            continue
        output.append(_INLINE_CODE_RE.sub("", line))
    return "".join(output)


def parse_nested_relationships(frontmatter: str) -> list[tuple[str, str]]:
    """Parse the framework ``relationships:`` list."""
    edges: list[tuple[str, str]] = []
    in_relationships = False
    current_target = ""
    current_type = "related_to"

    def finish() -> None:
        nonlocal current_target, current_type
        if current_target:
            edges.append((current_target, current_type))
        current_target = ""
        current_type = "related_to"

    for raw_line in frontmatter.splitlines():
        if raw_line.startswith("relationships:") and not raw_line.startswith((" ", "\t")):
            in_relationships = True
            continue
        if in_relationships and raw_line and not raw_line.startswith((" ", "\t")):
            finish()
            break
        if not in_relationships or not raw_line.strip():
            continue
        line = raw_line.strip()
        if line.startswith("-"):
            finish()
            line = line[1:].strip()
        target_match = re.search(r'target:\s*"?\[\[([^\]]+)\]\]"?', line)
        if target_match:
            current_target = normalise_target_slug(target_match.group(1))
        type_match = re.search(r"type:\s*([^\s,}]+)", line)
        if type_match:
            current_type = type_match.group(1).strip("'\"")
    else:
        if in_relationships:
            finish()
    return edges


def parse_flat_relationships(
    frontmatter: str,
    allowed_types: Collection[str] = ALLOWED_RELATIONSHIP_TYPES,
) -> list[tuple[str, str]]:
    """Parse Wikilink Types top-level relationship keys."""
    allowed = set(allowed_types)
    edges: list[tuple[str, str]] = []
    lines = frontmatter.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line or line.startswith((" ", "\t")) or ":" not in line:
            index += 1
            continue
        key, inline = line.split(":", 1)
        relation = key.strip()
        if relation not in allowed:
            index += 1
            continue
        values = [inline]
        index += 1
        while index < len(lines):
            continuation = lines[index]
            if continuation and not continuation.startswith((" ", "\t")):
                break
            values.append(continuation)
            index += 1
        for target in _WIKILINK_RE.findall("\n".join(values)):
            slug = normalise_target_slug(target)
            if slug:
                edges.append((slug, relation))
    return edges


def parse_inline_relationships(
    body: str,
    allowed_types: Collection[str] = ALLOWED_RELATIONSHIP_TYPES,
) -> list[tuple[str, str]]:
    """Parse valid ``@type`` tokens from wikilink aliases outside code."""
    allowed = set(allowed_types)
    edges: list[tuple[str, str]] = []
    clean_body = strip_code_content(body)
    for match in _WIKILINK_WITH_ALIAS_RE.finditer(clean_body):
        target = normalise_target_slug(match.group(1))
        for type_match in _AT_TYPE_RE.finditer(match.group(2)):
            relation = type_match.group(1)
            if target and relation in allowed:
                edges.append((target, relation))
    return edges


def collect_typed_relationships(
    text: str,
    allowed_types: Collection[str] = ALLOWED_RELATIONSHIP_TYPES,
) -> list[dict[str, Any]]:
    """Normalize all supported projections and deduplicate edge identities."""
    frontmatter, body = split_frontmatter(text)
    occurrences = (
        ("relationships", parse_nested_relationships(frontmatter)),
        ("flat", parse_flat_relationships(frontmatter, allowed_types)),
        ("inline", parse_inline_relationships(body, allowed_types)),
    )
    merged: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()
    for representation, edges in occurrences:
        for target, relation in edges:
            record = merged.setdefault(
                (target, relation),
                {
                    "target": target,
                    "relation": relation,
                    "kind": "relationship",
                    "typed": True,
                    "weight": 1,
                    "representations": [],
                },
            )
            if representation not in record["representations"]:
                record["representations"].append(representation)
    return list(merged.values())


def body_wikilink_targets(body: str) -> list[str]:
    """Return ordinary body wikilink targets outside code."""
    return [
        slug
        for target in _WIKILINK_RE.findall(strip_code_content(body))
        if (slug := normalise_target_slug(target))
    ]
