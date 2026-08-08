"""Tests for obsidian_wiki.graph — networkx-based vault graph queries."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("networkx", reason="networkx not installed")

from obsidian_wiki.graph import build_graph, load_graph, save_graph
from obsidian_wiki.graph import find_paths, neighbors, centrality, communities, stats
from obsidian_wiki.graph import tag_subgraph


def _make_vault(tmp_path: Path) -> Path:
    """Create a small test vault with 4 interconnected pages."""
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "concepts").mkdir()
    (vault / "entities").mkdir()

    (vault / "concepts/ml.md").write_text("""---
title: Machine Learning
category: concepts
tags: [ml, ai]
summary: The study of algorithms that improve through experience.
---

# ML
- [[entities/nn|Neural Networks @parent_of]]
- [[concepts/dl|Deep Learning @child_of]]
""")

    (vault / "concepts/dl.md").write_text("""---
title: Deep Learning
category: concepts
tags: [ml, ai, deep-learning]
relationships:
  - target: "[[concepts/ml]]"
    type: child_of
---

# DL
[[concepts/ml]] is the broader field.
- [[entities/cnn|CNN @example_of]]
""")

    (vault / "entities/nn.md").write_text("""---
title: Neural Networks
category: entities
tags: [ml, architecture]
relationships:
  - target: "[[concepts/ml]]"
    type: implements
---

# NN
[[concepts/ml]] implemented via NNs.
""")

    (vault / "entities/cnn.md").write_text("""---
title: CNN
category: entities
tags: [ml, deep-learning, architecture]
---

# CNN
[[concepts/dl|Deep Learning @child_of]] uses CNNs.
""")
    return vault


class TestBuildGraph:
    def test_build_and_stats(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        G = build_graph(vault)
        s = stats(G)
        assert s["nodes"] == 4
        assert s["edges"] >= 6  # bidirectional + typed
        assert s["is_weakly_connected"]
        assert s["weakly_connected_components"] == 1

    def test_cache_roundtrip(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        G1 = build_graph(vault)
        save_graph(G1, vault)
        G2 = load_graph(vault)
        assert G2.number_of_nodes() == G1.number_of_nodes()
        assert G2.number_of_edges() == G1.number_of_edges()

    def test_find_paths(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        G = build_graph(vault)
        paths = find_paths(G, "cnn", "ml")
        assert len(paths) >= 1
        p = paths[0]
        assert p["length"] >= 2  # cnn -> dl -> ml or cnn -> dl -> ml

    def test_neighbors(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        G = build_graph(vault)
        n = neighbors(G, "ml")
        assert n is not None
        assert len(n["incoming"]) >= 2
        assert len(n["outgoing"]) >= 2

    def test_centrality(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        G = build_graph(vault)
        c = centrality(G, method="degree", top=2)
        assert len(c) == 2
        assert c[0]["slug"] in ("dl", "ml")

    def test_tag_subgraph(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        G = build_graph(vault)
        sg = tag_subgraph(G, "ml")
        assert sg.number_of_nodes() >= 3

    def test_communities(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        G = build_graph(vault)
        comms = communities(G)
        assert len(comms) >= 1
        all_pages = {p["slug"] for c in comms for p in c["pages"]}
        assert "ml" in all_pages

    def test_unknown_node_returns_empty(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        G = build_graph(vault)
        assert find_paths(G, "nonexistent", "ml") == []
        assert neighbors(G, "nonexistent") is None
