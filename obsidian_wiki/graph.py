"""Vault graph built with networkx — frontmatter-aware graph queries.

Builds a directed graph from all .md files in the vault, with:
  - Nodes: page slugs with attributes (title, tags, category, tier, summary)
  - Edges: wikilinks + typed relationships from frontmatter

Query operations:
  - paths: shortest path between two pages (with optional type filter)
  - neighbors: ego-network around a page
  - centrality: degree, betweenness, pagerank
  - tag-subgraph: extract the subgraph of pages with a given tag
  - community: Louvain/Leiden community detection
  - stats: node/edge counts, density, components

Usage:
  python -m obsidian_wiki.graph <vault> paths --from A --to B
  python -m obsidian_wiki.graph <vault> neighbors <slug> --radius 2
  python -m obsidian_wiki.graph <vault> centrality --method pagerank --top 10
  python -m obsidian_wiki.graph <vault> tag-subgraph --tag ml --output graph.json

Requires: networkx (pip install networkx). Falls back to a warning if missing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from obsidian_wiki.index import entry_edges, load_index

GRAPH_CACHE_VERSION = 2


def _source_fingerprint(index: dict[str, dict[str, Any]]) -> list[list[Any]]:
    """Return the index metadata that determines whether graph cache is fresh."""
    return [
        [path, entry.get("mtime_ns"), entry.get("size")]
        for path, entry in sorted(index.items())
    ]

# ── Graph building ────────────────────────────────────────────────────

def build_graph(vault: str | Path) -> "nx.DiGraph":
    """Build a networkx DiGraph from all .md files in the vault.

    Nodes are page slugs. Edges are wikilinks (type=link) and typed
    relationships from frontmatter (type=relationship).

    Raises ImportError if networkx is not installed.
    """
    try:
        import networkx as nx
    except ImportError:
        raise ImportError(
            "networkx is required for graph queries. "
            "Install with: pip install obsidian-wiki[graph]"
        ) from None

    vault = Path(vault)
    raw = load_index(vault)

    G = nx.DiGraph()

    # Nodes
    for entry in raw.values():
        G.add_node(
            entry["slug"],
            title=entry["title"],
            tags=entry["tags"],
            category=entry["category"],
            tier=entry["tier"],
            summary=entry["summary"],
            path=entry["path"],
        )

    # Edges
    known = set(G.nodes())
    for entry in raw.values():
        slug = entry["slug"]

        for edge in entry_edges(entry):
            target = edge["target"]
            if not target or target == slug or target not in known:
                continue
            relation = edge["relation"]
            weight = edge.get("weight", 1)
            if G.has_edge(slug, target):
                G[slug][target]["weight"] = G[slug][target].get("weight", 1) + weight
                types = G[slug][target].setdefault("types", [])
                if relation not in types:
                    types.append(relation)
                representations = G[slug][target].setdefault("representations", [])
                for representation in edge.get("representations", []):
                    if representation not in representations:
                        representations.append(representation)
                if edge.get("typed"):
                    G[slug][target]["relation"] = relation
            else:
                G.add_edge(
                    slug,
                    target,
                    weight=weight,
                    types=[relation],
                    relation=relation,
                    representations=list(edge.get("representations", [])),
                )

    return G


def load_graph(vault: str | Path) -> "nx.DiGraph":
    """Load cached graph from vault's .obsidian/ directory, or build fresh."""
    vault = Path(vault)
    cache_path = vault / ".obsidian" / "graph.json"
    current_index = load_index(vault)
    fingerprint = _source_fingerprint(current_index)
    if cache_path.exists():
        try:
            import networkx as nx
            data = json.loads(cache_path.read_text())
            if (
                data.get("version") == GRAPH_CACHE_VERSION
                and data.get("source_fingerprint") == fingerprint
            ):
                return nx.node_link_graph(data["graph"])
        except (json.JSONDecodeError, KeyError):
            pass
    G = build_graph(vault)
    save_graph(G, vault)
    return G


def save_graph(G: "nx.DiGraph", vault: str | Path) -> None:
    """Cache the graph to vault's .obsidian/ directory."""
    import networkx as nx
    vault = Path(vault)
    cache_path = vault / ".obsidian"
    cache_path.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": GRAPH_CACHE_VERSION,
        "source_fingerprint": _source_fingerprint(load_index(vault)),
        "graph": nx.node_link_data(G),
    }
    (cache_path / "graph.json").write_text(json.dumps(payload, ensure_ascii=False))


# ── Query operations ──────────────────────────────────────────────────

def find_paths(
    G: "nx.DiGraph",
    source: str,
    target: str,
    max_len: int = 4,
    relation_filter: str | None = None,
) -> list[dict]:
    """Find shortest paths between two pages, with optional relation type filter."""
    if source not in G or target not in G:
        return []

    def _edge_filter(u, v):
        if relation_filter is None:
            return True
        edge = G[u][v]
        types = edge.get("types", [])
        return relation_filter in types

    try:
        import networkx as nx
        paths = list(
            nx.shortest_simple_paths(G, source, target)
        )
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return []

    result = []
    for path in paths[:10]:
        if len(path) > max_len + 1:
            break
        if all(
            _edge_filter(path[i], path[i + 1])
            for i in range(len(path) - 1)
        ):
            path_info = {
                "path": path,
                "length": len(path) - 1,
                "nodes": [
                    {
                        "slug": node,
                        "title": G.nodes[node].get("title", node),
                        "category": G.nodes[node].get("category", ""),
                        "tags": G.nodes[node].get("tags", []),
                    }
                    for node in path
                ],
                "edges": [
                    {
                        "source": path[i],
                        "target": path[i + 1],
                        "relation": G[path[i]][path[i + 1]].get("relation", "link"),
                        "kind": (
                            "link"
                            if G[path[i]][path[i + 1]].get("relation", "link") == "link"
                            else "relationship"
                        ),
                        "typed": G[path[i]][path[i + 1]].get("relation", "link") != "link",
                        "weight": G[path[i]][path[i + 1]].get("weight", 1),
                        "types": G[path[i]][path[i + 1]].get("types", ["link"]),
                        "representations": G[path[i]][path[i + 1]].get(
                            "representations", []
                        ),
                        "direction": "forward",
                        "asserted_source": path[i],
                        "asserted_target": path[i + 1],
                    }
                    for i in range(len(path) - 1)
                ],
            }
            result.append(path_info)

    return result


def neighbors(
    G: "nx.DiGraph", slug: str, radius: int = 1
) -> dict[str, Any] | None:
    """Return the ego-network around a page."""
    if slug not in G:
        return None

    import networkx as nx
    ego = nx.ego_graph(G, slug, radius=radius)

    incoming = [
        {
            "slug": n,
            "title": G.nodes[n].get("title", n),
            "category": G.nodes[n].get("category", ""),
            "relation": G[n][slug].get("relation", "link") if G.has_edge(n, slug) else None,
        }
        for n in ego.predecessors(slug)
    ]
    outgoing = [
        {
            "slug": n,
            "title": G.nodes[n].get("title", n),
            "category": G.nodes[n].get("category", ""),
            "relation": G[slug][n].get("relation", "link") if G.has_edge(slug, n) else None,
        }
        for n in ego.successors(slug)
    ]

    return {
        "node": {
            "slug": slug,
            "title": G.nodes[slug].get("title", slug),
            "category": G.nodes[slug].get("category", ""),
            "tags": G.nodes[slug].get("tags", []),
            "degree": G.degree(slug),
            "in_degree": G.in_degree(slug),
            "out_degree": G.out_degree(slug),
        },
        "incoming": incoming,
        "outgoing": outgoing,
        "subgraph_size": ego.number_of_nodes(),
        "subgraph_edges": ego.number_of_edges(),
    }


def centrality(
    G: "nx.DiGraph",
    method: str = "pagerank",
    top: int = 10,
    tag_filter: str | None = None,
) -> list[dict]:
    """Compute centrality scores and return top-ranked pages."""
    import networkx as nx

    sub = G
    if tag_filter:
        tagged = [n for n, d in G.nodes(data=True) if tag_filter in d.get("tags", [])]
        sub = G.subgraph(tagged) if tagged else G

    if method == "pagerank":
        try:
            scores = nx.pagerank(sub, weight="weight")
        except ImportError:
            # scipy not available — fall back to degree centrality
            scores = {n: sub.degree(n) for n in sub.nodes()}
    elif method == "betweenness":
        scores = nx.betweenness_centrality(sub, weight="weight")
    elif method == "degree":
        scores = {n: sub.degree(n) for n in sub.nodes()}
    elif method == "in_degree":
        scores = {n: sub.in_degree(n) for n in sub.nodes()}
    elif method == "out_degree":
        scores = {n: sub.out_degree(n) for n in sub.nodes()}
    else:
        raise ValueError(f"Unknown centrality method: {method}")

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top]
    return [
        {
            "slug": n,
            "score": round(s, 4),
            "title": G.nodes[n].get("title", n),
            "category": G.nodes[n].get("category", ""),
            "tags": G.nodes[n].get("tags", []),
            "degree": G.degree(n),
        }
        for n, s in ranked
    ]


def tag_subgraph(
    G: "nx.DiGraph", tag: str, min_degree: int = 1
) -> "nx.DiGraph":
    """Extract the subgraph of pages with a given tag, with degree >= min_degree."""
    tagged = [
        n for n, d in G.nodes(data=True)
        if tag in d.get("tags", []) and G.degree(n) >= min_degree
    ]
    return G.subgraph(tagged)


def communities(G: "nx.DiGraph") -> list[dict]:
    """Detect communities using Louvain (if available) or greedy modularity."""
    import networkx as nx
    import networkx.algorithms.community as nx_comm

    undirected = G.to_undirected()

    try:
        # Try Louvain first
        partition = nx_comm.louvain_communities(undirected, weight="weight", seed=42)
    except Exception:
        # Fall back to greedy
        partition = nx_comm.greedy_modularity_communities(
            undirected, weight="weight"
        )

    result = []
    for i, comm in enumerate(partition):
        pages = []
        for n in sorted(comm, key=lambda x: G.degree(x), reverse=True):
            pages.append({
                "slug": n,
                "title": G.nodes[n].get("title", n),
                "category": G.nodes[n].get("category", ""),
                "degree": G.degree(n),
            })
        result.append({"id": i, "size": len(comm), "pages": pages})

    result.sort(key=lambda c: c["size"], reverse=True)
    return result


def stats(G: "nx.DiGraph") -> dict[str, Any]:
    """Return graph statistics."""
    import networkx as nx

    undirected = G.to_undirected()
    return {
        "nodes": G.number_of_nodes(),
        "edges": G.number_of_edges(),
        "density": round(nx.density(G), 6),
        "is_weakly_connected": nx.is_weakly_connected(G),
        "weakly_connected_components": nx.number_weakly_connected_components(G),
        "strongly_connected_components": nx.number_strongly_connected_components(G),
        "isolates": len(list(nx.isolates(G))),
        "avg_clustering": round(nx.average_clustering(undirected), 6) if G.number_of_nodes() > 1 else 0,
        "avg_degree": round(sum(dict(G.degree()).values()) / max(G.number_of_nodes(), 1), 2),
        "density_by_category": {
            cat: {"nodes": n, "edges": m}
            for cat in sorted(
                {G.nodes[n].get("category", "unknown") for n in G.nodes()}
            )
            if (cat_nodes := [n for n, d in G.nodes(data=True) if d.get("category") == cat])
            and (n := len(cat_nodes))
            and (m := G.subgraph(cat_nodes).number_of_edges()) is not None
        },
    }


# ── CLI entry point ───────────────────────────────────────────────────

def _cli() -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Vault graph queries (networkx)",
    )
    parser.add_argument("vault", help="path to the Obsidian vault")
    parser.add_argument("--no-cache", action="store_true", help="force rebuild graph")
    parser.add_argument("--pretty", action="store_true", help="pretty-print JSON")
    parser.add_argument("--cmd", dest="cmd_override", help=argparse.SUPPRESS)

    sub = parser.add_subparsers(dest="cmd")

    # paths
    p = sub.add_parser("paths", help="find shortest paths between two pages")
    p.add_argument("--from", dest="source", required=True, help="source page slug")
    p.add_argument("--to", dest="target", required=True, help="target page slug")
    p.add_argument("--max-len", type=int, default=4, help="max path length")
    p.add_argument("--relation", help="filter by relation type")

    # neighbors
    n = sub.add_parser("neighbors", help="ego-network around a page")
    n.add_argument("slug", help="page slug")
    n.add_argument("--radius", type=int, default=1, help="neighborhood radius")

    # centrality
    c = sub.add_parser("centrality", help="compute centrality scores")
    c.add_argument("--method", default="pagerank",
                   choices=["pagerank", "betweenness", "degree", "in_degree", "out_degree"])
    c.add_argument("--top", type=int, default=10, help="number of top results")
    c.add_argument("--tag", help="filter to pages with this tag")

    # tag-subgraph
    t = sub.add_parser("tag-subgraph", help="extract subgraph by tag")
    t.add_argument("--tag", required=True, help="tag to filter by")
    t.add_argument("--min-degree", type=int, default=1, help="minimum node degree")
    t.add_argument("--output", help="save subgraph as node-link JSON")

    # communities
    cm = sub.add_parser("communities", help="detect communities")

    # stats
    st = sub.add_parser("stats", help="graph statistics")

    args = parser.parse_args()

    vault = args.vault
    try:
        if args.no_cache:
            G = build_graph(vault)
        else:
            G = load_graph(vault)
    except ImportError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    result: Any = None
    if args.cmd == "paths":
        result = find_paths(G, args.source, args.target, args.max_len, args.relation)
    elif args.cmd == "neighbors":
        result = neighbors(G, args.slug, args.radius)
    elif args.cmd == "centrality":
        result = centrality(G, args.method, args.top, args.tag)
    elif args.cmd == "tag-subgraph":
        sg = tag_subgraph(G, args.tag, args.min_degree)
        import networkx as nx
        result = nx.node_link_data(sg)
        if args.output:
            Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2))
            print(f"Saved subgraph to {args.output}")
            return 0
    elif args.cmd == "communities":
        result = communities(G)
    elif args.cmd == "stats":
        result = stats(G)
    else:
        parser.print_help()
        return 1

    indent = 2 if args.pretty else None
    print(json.dumps(result, ensure_ascii=False, indent=indent))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_cli())
