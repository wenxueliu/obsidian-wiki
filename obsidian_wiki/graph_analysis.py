"""Vault graph analysis: community detection, god nodes, surprising connections.

Reads the vault's wikilink graph (from page frontmatter and [[wikilinks]]),
then runs:
  1. Degree-based god-node ranking (most-linked pages)
  2. Greedy modularity community detection (pure Python, no binary deps)
     — equivalent to Leiden for small-to-medium graphs (<10k nodes)
  3. Surprising connections — edges that cross community boundaries,
     ranked by how unexpected they are (inter-community edges where both
     endpoints have low cross-community degree)

Optional: install `obsidian-wiki[graph]` for the real Leiden algorithm via
`leidenalg` + `igraph`. Falls back to the greedy method automatically.

Output JSON:
{
  "god_nodes": [{"page": "...", "degree": N, "in_degree": N, "out_degree": N}, ...],
  "communities": [{"id": N, "pages": [...], "label": "..."}, ...],
  "surprising_connections": [{"source": "...", "target": "...", "score": 0.N}, ...],
  "dead_ends": ["page with 0 outgoing links", ...],
  "isolated": ["page with 0 links at all", ...],
  "stats": {"pages": N, "edges": N, "communities": N}
}
"""

from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from obsidian_wiki.index import load_index


def parse_vault_graph(vault: Path) -> tuple[dict[str, list[str]], dict[str, list[str]], dict[tuple[str, str], str]]:
    """Parse all .md pages and return (outgoing_edges, page_tags, edge_types).

    outgoing_edges: {source_slug: [target_slug, ...]}
    page_tags:      {slug: [tag, ...]}
    edge_types:     {(source_slug, target_slug): relation_type}  — from frontmatter relationships:
    """
    outgoing: dict[str, list[str]] = defaultdict(list)
    tags_map: dict[str, list[str]] = {}
    edge_types: dict[tuple[str, str], str] = {}

    for entry in load_index(vault).values():
        src = entry["slug"]
        tags_map[src] = list(entry["tags"])
        # Plain links + typed relationships (both are edges).
        outgoing[src] = list(entry["out_links"]) + list(entry["out_edges"].keys())
        for target, rtype in entry["out_edges"].items():
            edge_types[(src, target)] = rtype

    return dict(outgoing), tags_map, edge_types


# ---------------------------------------------------------------------------
# Graph metrics
# ---------------------------------------------------------------------------

def _build_degree_tables(
    outgoing: dict[str, list[str]]
) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    out_deg: dict[str, int] = {n: len(v) for n, v in outgoing.items()}
    in_deg: dict[str, int] = defaultdict(int)
    for targets in outgoing.values():
        for t in targets:
            in_deg[t] += 1
    degree = {n: out_deg.get(n, 0) + in_deg.get(n, 0) for n in outgoing}
    for n in in_deg:
        degree.setdefault(n, in_deg[n])
    return degree, dict(in_deg), out_deg


def god_nodes(outgoing: dict[str, list[str]], top_n: int = 20) -> list[dict]:
    degree, in_deg, out_deg = _build_degree_tables(outgoing)
    ranked = sorted(degree, key=lambda n: -degree[n])[:top_n]
    return [
        {"page": n, "degree": degree[n],
         "in_degree": in_deg.get(n, 0), "out_degree": out_deg.get(n, 0)}
        for n in ranked
    ]


def dead_ends(outgoing: dict[str, list[str]]) -> list[str]:
    """Pages with no outgoing links."""
    return [n for n, targets in outgoing.items() if not targets]


def isolated(outgoing: dict[str, list[str]]) -> list[str]:
    """Pages with zero links in either direction."""
    _, in_deg, out_deg = _build_degree_tables(outgoing)
    return [n for n in outgoing if in_deg.get(n, 0) == 0 and out_deg.get(n, 0) == 0]


# ---------------------------------------------------------------------------
# Community detection — greedy modularity (Newman-Girvan, pure Python)
# ---------------------------------------------------------------------------

def _modularity(communities: list[set[str]], outgoing: dict[str, list[str]]) -> float:
    """Approximate modularity Q for an undirected projection of outgoing edges."""
    all_edges = [(s, t) for s, targets in outgoing.items() for t in targets]
    m = len(all_edges)
    if m == 0:
        return 0.0
    degree = defaultdict(int)
    for s, t in all_edges:
        degree[s] += 1
        degree[t] += 1
    node_comm: dict[str, int] = {}
    for i, comm in enumerate(communities):
        for n in comm:
            node_comm[n] = i
    Q = 0.0
    for s, t in all_edges:
        if node_comm.get(s) == node_comm.get(t):
            Q += 1 - (degree[s] * degree[t]) / (2 * m)
    return Q / m


def detect_communities_greedy(outgoing: dict[str, list[str]]) -> list[set[str]]:
    """Greedy modularity community detection (label propagation variant).

    Fast O(n·k) approach suitable for vaults up to ~5 000 pages. Each node
    adopts the most frequent label among its neighbours; iterate until stable.
    Falls back gracefully to one community per page if the graph is empty.
    """
    nodes = list(outgoing.keys())
    if not nodes:
        return []

    # Build undirected adjacency
    adj: dict[str, list[str]] = defaultdict(list)
    for src, targets in outgoing.items():
        for t in targets:
            adj[src].append(t)
            adj[t].append(src)

    # Initialise: each node in its own community (label = index)
    labels: dict[str, int] = {n: i for i, n in enumerate(nodes)}

    for _ in range(20):  # max 20 rounds
        changed = False
        for n in nodes:
            neighbours = adj[n]
            if not neighbours:
                continue
            freq: dict[int, int] = defaultdict(int)
            for nb in neighbours:
                freq[labels[nb]] += 1
            best = max(freq, key=lambda lbl: (freq[lbl], -lbl))
            if best != labels[n]:
                labels[n] = best
                changed = True
        if not changed:
            break

    # Group by label
    groups: dict[int, set[str]] = defaultdict(set)
    for n, lbl in labels.items():
        groups[lbl].add(n)
    return list(groups.values())


def detect_communities(outgoing: dict[str, list[str]]) -> list[set[str]]:
    """Try Leiden (leidenalg + igraph) first; fall back to greedy label propagation."""
    try:
        import igraph as ig
        import leidenalg

        nodes = list(outgoing.keys())
        node_idx = {n: i for i, n in enumerate(nodes)}
        edges = [
            (node_idx[s], node_idx[t])
            for s, targets in outgoing.items()
            for t in targets
            if t in node_idx
        ]
        g = ig.Graph(n=len(nodes), edges=edges, directed=False)
        partition = leidenalg.find_partition(g, leidenalg.ModularityVertexPartition)
        return [
            {nodes[i] for i in cluster}
            for cluster in partition
        ]
    except ImportError:
        return detect_communities_greedy(outgoing)


# ---------------------------------------------------------------------------
# Surprising connections
# ---------------------------------------------------------------------------

def surprising_connections(
    outgoing: dict[str, list[str]],
    communities: list[set[str]],
    edge_types: dict[tuple[str, str], str] | None = None,
    top_n: int = 20,
) -> list[dict]:
    """Edges that cross community boundaries, ranked by unexpectedness.

    Score = 1 / (cross_degree(source) * cross_degree(target))
    Low cross-degree nodes connected across communities are the most surprising.
    """
    node_comm: dict[str, int] = {}
    for i, comm in enumerate(communities):
        for n in comm:
            node_comm[n] = i

    # Count how many cross-community edges each node already has
    cross_deg: dict[str, int] = defaultdict(int)
    for src, targets in outgoing.items():
        for t in targets:
            if node_comm.get(src) != node_comm.get(t):
                cross_deg[src] += 1
                cross_deg[t] += 1

    results = []
    seen: set[tuple[str, str]] = set()
    for src, targets in outgoing.items():
        for t in targets:
            pair = tuple(sorted((src, t)))
            if pair in seen:
                continue
            if node_comm.get(src) != node_comm.get(t):
                cd_s = cross_deg.get(src, 1)
                cd_t = cross_deg.get(t, 1)
                score = 1.0 / math.sqrt(cd_s * cd_t)
                rtype = (edge_types or {}).get((src, t)) or (edge_types or {}).get((t, src)) or "link"
                results.append({"source": src, "target": t, "relation": rtype, "score": round(score, 4)})
                seen.add(pair)

    results.sort(key=lambda x: -x["score"])
    return results[:top_n]


# ---------------------------------------------------------------------------
# Community labelling (heuristic: most common tag or longest shared prefix)
# ---------------------------------------------------------------------------

def _label_community(pages: list[str], tags_map: dict[str, list[str]]) -> str:
    freq: dict[str, int] = defaultdict(int)
    for p in pages:
        for tag in tags_map.get(p, []):
            if not tag.startswith("visibility/"):
                freq[tag] += 1
    if freq:
        return max(freq, key=lambda t: freq[t])
    # Fallback: shared prefix of page names
    if len(pages) == 1:
        return pages[0]
    prefix = pages[0]
    for p in pages[1:]:
        while not p.startswith(prefix):
            prefix = prefix[:-1]
        if not prefix:
            break
    return prefix.rstrip("-_") or f"cluster-{pages[0][:20]}"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def analyse_vault(vault: Path, top_n: int = 20) -> dict[str, Any]:
    outgoing, tags_map, edge_types = parse_vault_graph(vault)

    if not outgoing:
        return {
            "god_nodes": [], "communities": [],
            "surprising_connections": [], "dead_ends": [], "isolated": [],
            "stats": {"pages": 0, "edges": 0, "communities": 0},
        }

    communities_raw = detect_communities(outgoing)
    # Sort communities largest-first
    communities_raw.sort(key=lambda c: -len(c))

    total_edges = sum(len(v) for v in outgoing.values())

    return {
        "god_nodes": god_nodes(outgoing, top_n),
        "communities": [
            {
                "id": i,
                "size": len(comm),
                "pages": sorted(comm),
                "label": _label_community(sorted(comm), tags_map),
            }
            for i, comm in enumerate(communities_raw)
        ],
        "surprising_connections": surprising_connections(outgoing, communities_raw, edge_types, top_n),
        "dead_ends": dead_ends(outgoing),
        "isolated": isolated(outgoing),
        "stats": {
            "pages": len(outgoing),
            "edges": total_edges,
            "communities": len(communities_raw),
        },
    }
