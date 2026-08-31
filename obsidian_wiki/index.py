"""Unified vault page index.

Single source of frontmatter/wikilink parsing for the graph modules
(``graph.py``, ``graphrag.py``, ``graph_analysis.py``). Replaces three
near-identical parsers that each scanned and regex'd the whole vault per call.

The markdown files remain the source of truth; this module derives a cached
index (``.obsidian/frontmatter-index.json``) and updates it incrementally:

- File *set* changed (page added/removed/renamed) → full rebuild, because the
  known-slug set (which resolves wikilinks) changed too.
- File set unchanged → re-parse only files whose mtime/size changed; reuse the
  rest. Invalidation uses mtime_ns + size (a stat, no file read) so unchanged
  files cost nothing.

Each page entry is keyed by vault-relative path and carries:
  slug, title, category, tags, summary, tier, path, edges,
  plus compatibility fields out_links/out_edges and mtime_ns/size for
  invalidation.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Iterator

from obsidian_wiki.relationships import (
    body_wikilink_targets,
    collect_typed_relationships,
    parse_nested_relationships as parse_relationships,
    split_frontmatter,
    strip_code_content,
)
from obsidian_wiki.workflow_layout import iter_content_pages

# ── Shared parsing (consolidated from graph.py / graphrag.py / graph_analysis.py) ──

_MD_LINK_RE = re.compile(r"\[.*?\]\(([^)]+\.md[^)]*)\)")
_TAGS_RE = re.compile(r"^tags:\s*\[([^\]]+)\]", re.MULTILINE)
_TAGS_LIST_RE = re.compile(r"^tags:\s*\n((?:\s+-\s+\S+\n)+)", re.MULTILINE)
_CATEGORY_RE = re.compile(r"^category:\s*(\w+)", re.MULTILINE)
_TIER_RE = re.compile(r"^tier:\s*(\w+)", re.MULTILINE)
_BLOCK_SCALAR_RE = re.compile(r"^[>|][+-]?\d*$")

INDEX_VERSION = 3
INDEX_FILENAME = "frontmatter-index.json"

def _slug(s: str) -> str:
    return s.strip().lower().replace(" ", "-")


def _index_path(vault: Path) -> Path:
    return vault / ".obsidian" / INDEX_FILENAME


def iter_pages(vault: Path) -> Iterator[Path]:
    """Yield pages declared live by the vault's workflow layout."""
    yield from iter_content_pages(vault)


def _extract_scalar(front: str, key: str) -> str:
    """Extract a YAML scalar value, folding block scalars (``>`` / ``|``)."""
    lines = front.splitlines()
    pattern = re.compile(rf"^{re.escape(key)}:\s*(.*)$")
    for i, line in enumerate(lines):
        m = pattern.match(line)
        if not m:
            continue
        rest = m.group(1).strip()
        if not rest or _BLOCK_SCALAR_RE.match(rest):
            block_lines = []
            for cont in lines[i + 1 :]:
                if cont.strip() == "":
                    continue
                if re.match(r"^\s+\S", cont):
                    block_lines.append(cont.strip())
                else:
                    break
            return " ".join(block_lines).strip()
        return rest.strip("\"'")
    return ""


def _parse_tags(front: str) -> list[str]:
    m = _TAGS_RE.search(front)
    if m:
        return [t.strip().strip("'\"") for t in m.group(1).split(",")]
    m2 = _TAGS_LIST_RE.search(front)
    if m2:
        return [ln.strip().lstrip("- ") for ln in m2.group(1).splitlines() if ln.strip()]
    return []


def _build_edges(
    out_links: list[str], relationships: list[dict[str, Any]] | list[tuple[str, str]]
) -> list[dict[str, Any]]:
    """Build the shared edge representation used by every graph consumer.

    Repeated links are collapsed into a weight. Distinct typed relationships
    between the same pages remain distinct instead of being overwritten by the
    legacy ``out_edges`` mapping.
    """
    counts: dict[str, int] = defaultdict(int)
    for target in out_links:
        counts[target] += 1
    edges = [
        {
            "target": target,
            "relation": "link",
            "kind": "link",
            "typed": False,
            "weight": weight,
            "representations": ["body"],
        }
        for target, weight in counts.items()
    ]
    for relationship in relationships:
        if isinstance(relationship, tuple):
            target, relation = relationship
            edges.append({
                "target": target,
                "relation": relation,
                "kind": "relationship",
                "typed": True,
                "weight": 1,
                "representations": ["relationships"],
            })
        else:
            edges.append(dict(relationship))
    return edges


def entry_edges(entry: dict[str, Any]) -> list[dict[str, Any]]:
    """Return normalized edges for an index entry, including v1-shaped data."""
    edges = entry.get("edges")
    if isinstance(edges, list):
        return [dict(edge) for edge in edges if isinstance(edge, dict)]
    return _build_edges(
        list(entry.get("out_links", [])),
        list(entry.get("out_edges", {}).items()),
    )


def find_index_path(
    pages: dict[str, dict[str, Any]],
    source_slug: str,
    target_slug: str,
    *,
    max_depth: int = 4,
    bidirectional: bool = True,
) -> dict[str, Any] | None:
    """Find a shortest path while preserving relation type and direction.

    ``pages`` is keyed by slug. Reverse traversal is enabled for natural
    language "connected to" questions, but each returned edge records whether
    the underlying assertion was followed forward or in reverse.
    """
    if source_slug not in pages or target_slug not in pages:
        return None
    if source_slug == target_slug:
        return {"path": [source_slug], "length": 0, "edges": []}

    adjacency: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for asserted_source, entry in pages.items():
        # Prefer typed assertions when equally short paths are available.
        edges = sorted(entry_edges(entry), key=lambda edge: not edge.get("typed", False))
        for edge in edges:
            asserted_target = str(edge.get("target", ""))
            if asserted_target not in pages or asserted_target == asserted_source:
                continue
            common = {
                "relation": str(edge.get("relation", "link")),
                "kind": str(edge.get("kind", "link")),
                "typed": bool(edge.get("typed", False)),
                "weight": int(edge.get("weight", 1)),
                "representations": list(edge.get("representations", [])),
                "asserted_source": asserted_source,
                "asserted_target": asserted_target,
            }
            adjacency[asserted_source].append({
                **common,
                "source": asserted_source,
                "target": asserted_target,
                "direction": "forward",
            })
            if bidirectional:
                adjacency[asserted_target].append({
                    **common,
                    "source": asserted_target,
                    "target": asserted_source,
                    "direction": "reverse",
                })

    # Traversal is node-based, but one page pair may assert several semantic
    # types. Collapse that parallel bundle for BFS while retaining every edge
    # identity for the answer layer.
    for node, outgoing in list(adjacency.items()):
        bundles: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for edge in outgoing:
            bundles[edge["target"]].append(edge)
        adjacency[node] = []
        for parallel in bundles.values():
            selected = dict(parallel[0])
            selected["types"] = list(dict.fromkeys(edge["relation"] for edge in parallel))
            selected["edge_details"] = [
                {
                    "relation": edge["relation"],
                    "kind": edge["kind"],
                    "typed": edge["typed"],
                    "representations": edge["representations"],
                }
                for edge in parallel
            ]
            adjacency[node].append(selected)

    queue: deque[tuple[str, list[str], list[dict[str, Any]]]] = deque(
        [(source_slug, [source_slug], [])]
    )
    visited = {source_slug}
    while queue:
        node, path, traversed = queue.popleft()
        if len(traversed) >= max_depth:
            continue
        for edge in adjacency.get(node, []):
            neighbour = edge["target"]
            if neighbour in visited:
                continue
            next_path = path + [neighbour]
            next_edges = traversed + [edge]
            if neighbour == target_slug:
                return {
                    "path": next_path,
                    "length": len(next_edges),
                    "edges": next_edges,
                }
            visited.add(neighbour)
            queue.append((neighbour, next_path, next_edges))
    return None


def _parse_page(path: Path, vault: Path, known_slugs: set[str], mtime_ns: int, size: int) -> dict[str, Any]:
    """Parse one page into an index entry. *known_slugs* filters link targets."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""

    slug = _slug(path.stem)
    front, body = split_frontmatter(text)

    title = _extract_scalar(front, "title") or path.stem
    category = str(path.relative_to(vault).parent)
    cm = _CATEGORY_RE.search(front)
    if cm:
        category = cm.group(1).strip()
    tier = "supporting"
    tm = _TIER_RE.search(front)
    if tm:
        tier = tm.group(1).strip()

    relationships = [
        relationship
        for relationship in collect_typed_relationships(text)
        if relationship["target"] != slug and relationship["target"] in known_slugs
    ]
    typed_targets = {relationship["target"] for relationship in relationships}

    out_links = [
        target
        for target in body_wikilink_targets(body)
        if target != slug and target in known_slugs and target not in typed_targets
    ]
    for href in _MD_LINK_RE.findall(strip_code_content(body)):
        target = _slug(Path(href).stem)
        if target and target != slug and target in known_slugs and target not in typed_targets:
            out_links.append(target)

    out_edges: dict[str, str] = {}
    for relationship in relationships:
        out_edges[relationship["target"]] = relationship["relation"]

    return {
        "slug": slug,
        "title": title,
        "category": category,
        "tags": _parse_tags(front),
        "summary": _extract_scalar(front, "summary"),
        "tier": tier,
        "path": str(path.relative_to(vault)),
        "edges": _build_edges(out_links, relationships),
        "out_links": out_links,
        "out_edges": out_edges,
        "mtime_ns": mtime_ns,
        "size": size,
    }


def _build_full(vault: Path, files: list[Path]) -> dict[str, dict[str, Any]]:
    """Full rebuild from scratch."""
    known_slugs = {_slug(p.stem) for p in files}
    index: dict[str, dict[str, Any]] = {}
    for p in files:
        st = p.stat()
        rel = str(p.relative_to(vault))
        index[rel] = _parse_page(p, vault, known_slugs, st.st_mtime_ns, st.st_size)
    return index


def _load_cache(vault: Path) -> dict[str, dict[str, Any]]:
    """Load the cached index, or ``{}`` if absent/unreadable."""
    path = _index_path(vault)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") != INDEX_VERSION:
            return {}
        pages = data.get("pages", {})
        return pages if isinstance(pages, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(vault: Path, index: dict[str, dict[str, Any]]) -> None:
    path = _index_path(vault)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": INDEX_VERSION, "pages": index}
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def load_index(vault: Path, *, force: bool = False) -> dict[str, dict[str, Any]]:
    """Return ``{vault_relative_path: entry}``, incrementally rebuilt.

    Rebuilds fully when the file set changed; otherwise re-parses only files
    whose mtime/size changed and reuses the rest from the cache.
    """
    vault = Path(vault)
    files = list(iter_pages(vault))

    if force:
        index = _build_full(vault, files)
        _save_cache(vault, index)
        return index

    cache = _load_cache(vault)
    current_paths = {str(p.relative_to(vault)) for p in files}
    cached_paths = set(cache.keys())

    if current_paths != cached_paths:
        # File set changed → known-slug set changed → full rebuild.
        index = _build_full(vault, files)
        _save_cache(vault, index)
        return index

    # File set unchanged → incremental re-parse of changed files only.
    changed = False
    result: dict[str, dict[str, Any]] = {}
    known_slugs = {_slug(p.stem) for p in files}
    for p in files:
        rel = str(p.relative_to(vault))
        st = p.stat()
        entry = cache.get(rel)
        if (
            entry is not None
            and entry.get("mtime_ns") == st.st_mtime_ns
            and entry.get("size") == st.st_size
        ):
            result[rel] = entry
        else:
            result[rel] = _parse_page(p, vault, known_slugs, st.st_mtime_ns, st.st_size)
            changed = True

    if changed:
        _save_cache(vault, result)
    return result
