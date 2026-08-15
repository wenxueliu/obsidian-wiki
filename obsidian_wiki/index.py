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
  slug, title, category, tags, summary, tier, path, out_links, out_edges,
  plus mtime_ns/size for invalidation.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterator

from obsidian_wiki.layout import load_layout

# ── Shared parsing (consolidated from graph.py / graphrag.py / graph_analysis.py) ──

_FRONT_RE = re.compile(r"^---\r?\n(.*?)\r?\n---(?:\r?\n|$)", re.DOTALL)
_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+?)(?:[|#][^\]]*?)?\]\]")
_MD_LINK_RE = re.compile(r"\[.*?\]\(([^)]+\.md[^)]*)\)")
_TAGS_RE = re.compile(r"^tags:\s*\[([^\]]+)\]", re.MULTILINE)
_TAGS_LIST_RE = re.compile(r"^tags:\s*\n((?:\s+-\s+\S+\n)+)", re.MULTILINE)
_CATEGORY_RE = re.compile(r"^category:\s*(\w+)", re.MULTILINE)
_TIER_RE = re.compile(r"^tier:\s*(\w+)", re.MULTILINE)
_RELATIONSHIPS_RE = re.compile(r"^relationships:\s*\n((?:\s+-\s+\S.*\n)+)", re.MULTILINE)
_BLOCK_SCALAR_RE = re.compile(r"^[>|][+-]?\d*$")

INDEX_VERSION = 1
INDEX_FILENAME = "frontmatter-index.json"

SKIP_DIRS = load_layout().skip_dirs


def _slug(s: str) -> str:
    return s.strip().lower().replace(" ", "-")


def _index_path(vault: Path) -> Path:
    return vault / ".obsidian" / INDEX_FILENAME


def iter_pages(vault: Path) -> Iterator[Path]:
    """Yield vault ``.md`` page paths, skipping layout-configured dirs."""
    for p in vault.rglob("*.md"):
        if any(part in SKIP_DIRS for part in p.relative_to(vault).parts):
            continue
        yield p


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


def parse_relationships(front: str) -> list[tuple[str, str]]:
    """Parse the frontmatter ``relationships:`` block into (target_slug, type) pairs."""
    edges: list[tuple[str, str]] = []
    m = _RELATIONSHIPS_RE.search(front)
    if not m:
        return edges
    for line in m.group(1).splitlines():
        line = line.strip().lstrip("- ")
        target_m = re.search(r'target:\s*"?\[\[([^\]]+)\]\]"?', line)
        type_m = re.search(r'type:\s*(\S+)', line)
        if target_m:
            target = _slug(target_m.group(1).split("/")[-1])
            rtype = type_m.group(1).strip() if type_m else "related_to"
            edges.append((target, rtype))
    return edges


def _parse_page(path: Path, vault: Path, known_slugs: set[str], mtime_ns: int, size: int) -> dict[str, Any]:
    """Parse one page into an index entry. *known_slugs* filters link targets."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""

    slug = _slug(path.stem)
    front_m = _FRONT_RE.match(text)
    front = front_m.group(1) if front_m else ""

    title = _extract_scalar(front, "title") or path.stem
    category = str(path.relative_to(vault).parent)
    cm = _CATEGORY_RE.search(front)
    if cm:
        category = cm.group(1).strip()
    tier = "supporting"
    tm = _TIER_RE.search(front)
    if tm:
        tier = tm.group(1).strip()

    out_links: list[str] = []
    for link in _WIKILINK_RE.findall(text):
        target = _slug(link.split("/")[-1])
        if target and target != slug and target in known_slugs:
            out_links.append(target)
    for href in _MD_LINK_RE.findall(text):
        target = _slug(Path(href).stem)
        if target and target != slug and target in known_slugs:
            out_links.append(target)

    out_edges: dict[str, str] = {}
    for target, rtype in parse_relationships(front):
        if target and target != slug and target in known_slugs:
            out_edges[target] = rtype

    return {
        "slug": slug,
        "title": title,
        "category": category,
        "tags": _parse_tags(front),
        "summary": _extract_scalar(front, "summary"),
        "tier": tier,
        "path": str(path.relative_to(vault)),
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
