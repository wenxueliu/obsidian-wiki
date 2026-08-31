"""GraphRAG query index for wiki-query.

Builds a compact in-memory index from vault page frontmatter and wikilinks,
then answers structural and factual queries against it without opening any
page bodies. Equivalent to graphify's "query the compiled graph instead of
raw files" — saves reading 10–50 pages for questions answerable from the
graph structure.

The agent calls:
  obsidian-wiki graph-query <vault> "<question>" [options]

And gets back a JSON response:
{
  "answer_type": "direct" | "path" | "list" | "gap",
  "candidates": [{"page": "...", "score": 0.N, "summary": "..."}, ...],
  "path": ["page-a", "page-b", "page-c"],   # multi-hop, if applicable
  "path_length": 2,
  "path_edges": [{"source": "page-a", "target": "page-b",
                    "relation": "uses", "direction": "forward", ...}],
  "god_nodes_relevant": ["page", ...],        # hub pages related to query terms
  "should_read": ["page-a.md", "page-b.md"], # pages worth opening for full detail
  "index_only": true/false                    # true = answer is complete without page reads
}

The `should_read` list is the key output: it tells the agent exactly which pages
to open, replacing the current approach of opening 10+ pages speculatively.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Index building
# ---------------------------------------------------------------------------

from obsidian_wiki.index import _slug, entry_edges, find_index_path, load_index


def build_index(vault: Path) -> dict[str, dict]:
    """Build a lightweight index dict from vault frontmatter and wikilinks.

    Returns:
        {slug: {title, tags, summary, category, tier, edges, out_links, in_links, path}}
    """
    raw = load_index(vault)
    pages: dict[str, dict] = {}
    for entry in raw.values():
        edges = entry_edges(entry)
        pages[entry["slug"]] = {
            "title": entry["title"],
            "tags": list(entry["tags"]),
            "summary": entry["summary"],
            "category": entry["category"],
            "tier": entry["tier"],
            "path": entry["path"],
            "edges": edges,
            # Compatibility projection used for degree ranking.
            "out_links": [edge["target"] for edge in edges],
            "in_links": [],
        }

    # Reverse pass: compute in_links.
    for slug, e in pages.items():
        for target in e["out_links"]:
            if target in pages:
                pages[target]["in_links"].append(slug)
    return pages


# ---------------------------------------------------------------------------
# Scoring / ranking
# ---------------------------------------------------------------------------

_TIER_WEIGHT = {"core": 1.3, "supporting": 1.0, "peripheral": 0.7}


def _score(slug: str, entry: dict, terms: list[str]) -> float:
    score = 0.0
    title_lower = entry["title"].lower()
    summary_lower = entry["summary"].lower()
    tags_lower = [t.lower() for t in entry["tags"]]
    for term in terms:
        t = term.lower()
        if t == slug or t == title_lower:
            score += 10.0
        elif t in title_lower:
            score += 6.0
        elif any(t in tag for tag in tags_lower):
            score += 4.0
        elif t in summary_lower:
            score += 2.0

    if score > 0:
        # Degree bonus only when at least one term matched — prevents degree
        # noise from surfacing irrelevant pages
        degree = len(entry["in_links"]) + len(entry["out_links"])
        score += min(degree * 0.1, 2.0)
        score *= _TIER_WEIGHT.get(entry.get("tier", "supporting"), 1.0)
    return score


def rank_candidates(
    index: dict[str, dict],
    terms: list[str],
    top_n: int = 8,
) -> list[dict]:
    scored = [
        {
            "slug": slug,
            "page": entry["path"],
            "title": entry["title"],
            "score": _score(slug, entry, terms),
            "summary": entry["summary"],
            "tier": entry["tier"],
            "in_degree": len(entry["in_links"]),
        }
        for slug, entry in index.items()
    ]
    scored.sort(key=lambda x: (-x["score"], -x["in_degree"]))
    return [c for c in scored[:top_n] if c["score"] > 0]


# ---------------------------------------------------------------------------
# Multi-hop path finding (BFS)
# ---------------------------------------------------------------------------

def find_path(
    index: dict[str, dict],
    source_slug: str,
    target_slug: str,
    max_depth: int = 4,
) -> list[str] | None:
    """Compatibility wrapper around the shared typed-edge path traversal."""
    result = find_index_path(
        index, source_slug, target_slug, max_depth=max_depth, bidirectional=True
    )
    return result["path"] if result else None


# ---------------------------------------------------------------------------
# Query classification
# ---------------------------------------------------------------------------

_PATH_PATTERNS = re.compile(
    r"how (?:is|are|does) (.+?) (?:connected|related|linked) to (.+?)[\?]?$"
    r"|trace (?:the )?(?:chain|path) from (.+?) to (.+?)[\?]?$"
    r"|what connects (.+?) (?:to|and) (.+?)[\?]?$",
    re.IGNORECASE,
)

_GAP_PATTERNS = re.compile(
    r"what (?:do|don'?t) I (?:not )?know about|what.?s missing|what gaps|open questions",
    re.IGNORECASE,
)

_LIST_PATTERNS = re.compile(
    r"(?:list|show|find|give me) (?:all|every|pages about)",
    re.IGNORECASE,
)


def classify_query(question: str) -> tuple[str, list[str]]:
    """Return (answer_type, extracted_terms).

    answer_type: "path" | "gap" | "list" | "direct"
    """
    m = _PATH_PATTERNS.search(question)
    if m:
        groups = [g for g in m.groups() if g]
        terms = groups[:2] if len(groups) >= 2 else [question]
        return "path", terms

    if _GAP_PATTERNS.search(question):
        # Extract what the gap is about
        terms = re.sub(r"what (?:do|don't) I (?:not )?know about|what.?s missing", "", question, flags=re.IGNORECASE).strip().split()
        return "gap", terms

    if _LIST_PATTERNS.search(question):
        terms = re.sub(r"(?:list|show|find|give me) (?:all|every|pages about)", "", question, flags=re.IGNORECASE).strip().split()
        return "list", terms

    # Default: extract meaningful terms (drop stop words)
    stop = {"what", "the", "a", "an", "is", "are", "how", "does", "do", "in", "of", "to", "for", "and", "or"}
    terms = [w.strip("?,.'\"") for w in question.split() if w.lower().strip("?,.'\"") not in stop and len(w) > 2]
    return "direct", terms


# ---------------------------------------------------------------------------
# Main query entry point
# ---------------------------------------------------------------------------

def query(
    vault: Path,
    question: str,
    *,
    top_n: int = 8,
    max_should_read: int = 3,
) -> dict[str, Any]:
    index = build_index(vault)
    if not index:
        return {
            "answer_type": "direct",
            "candidates": [],
            "path": [],
            "path_length": None,
            "path_edges": [],
            "god_nodes_relevant": [],
            "should_read": [],
            "index_only": True,
            "note": "Vault appears empty.",
        }

    answer_type, terms = classify_query(question)

    # God nodes relevant to the query
    degree = {s: len(e["in_links"]) + len(e["out_links"]) for s, e in index.items()}
    god_slugs = sorted(degree, key=lambda s: -degree[s])[:10]
    term_set = {t.lower() for t in terms}
    god_relevant = [
        index[s]["path"] for s in god_slugs
        if any(t in index[s]["title"].lower() or t in " ".join(index[s]["tags"]).lower() for t in term_set)
    ][:5]

    path_result: list[str] = []
    path_edges: list[dict[str, Any]] = []
    path_length: int | None = None
    if answer_type == "path" and len(terms) >= 2:
        src_slug = _slug(terms[0])
        tgt_slug = _slug(terms[1])
        # Try to find slugs by scoring if exact match fails
        if src_slug not in index:
            cands = rank_candidates(index, [terms[0]], top_n=1)
            src_slug = cands[0]["slug"] if cands else src_slug
        if tgt_slug not in index:
            cands = rank_candidates(index, [terms[1]], top_n=1)
            tgt_slug = cands[0]["slug"] if cands else tgt_slug
        path_detail = find_index_path(
            index, src_slug, tgt_slug, max_depth=4, bidirectional=True
        )
        if path_detail:
            raw_path = path_detail["path"]
            path_result = [index[s]["path"] for s in raw_path if s in index]
            path_length = path_detail["length"]
            for edge in path_detail["edges"]:
                enriched = dict(edge)
                enriched["source_page"] = index[edge["source"]]["path"]
                enriched["target_page"] = index[edge["target"]]["path"]
                enriched["asserted_source_page"] = index[edge["asserted_source"]]["path"]
                enriched["asserted_target_page"] = index[edge["asserted_target"]]["path"]
                path_edges.append(enriched)

    candidates = rank_candidates(index, terms, top_n=top_n)

    # Decide whether page reads are needed
    top_candidate = candidates[0] if candidates else None
    index_only = False
    if top_candidate and top_candidate["score"] >= 10.0 and top_candidate["summary"]:
        index_only = True  # Exact title match with a summary — likely answerable from index

    should_read = [c["page"] for c in candidates[:max_should_read] if not index_only]
    if path_result and not index_only:
        # Add path pages to should_read, deduplicated
        for p in path_result:
            if p not in should_read:
                should_read.append(p)
        should_read = should_read[:max_should_read + 2]

    return {
        "answer_type": answer_type,
        "candidates": [
            {
                "page": c["page"],
                "title": c["title"],
                "score": round(c["score"], 2),
                "summary": c["summary"],
                "tier": c["tier"],
            }
            for c in candidates
        ],
        "path": path_result,
        "path_length": path_length,
        "path_edges": path_edges,
        "god_nodes_relevant": god_relevant,
        "should_read": should_read,
        "index_only": index_only,
        "stats": {
            "indexed_pages": len(index),
            "query_terms": terms,
        },
    }
