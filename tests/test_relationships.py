"""Compatibility tests for framework and Wikilink Types relationship forms."""

from pathlib import Path

from obsidian_wiki.graphrag import build_index, query
from obsidian_wiki.lint import lint_vault
from obsidian_wiki.relationships import (
    collect_typed_relationships,
    parse_flat_relationships,
    parse_inline_relationships,
)


def _document(frontmatter: str, body: str = "") -> str:
    return f"---\n{frontmatter.strip()}\n---\n{body}"


def _write(vault: Path, name: str, text: str) -> None:
    (vault / f"{name}.md").write_text(text, encoding="utf-8")


def test_parses_wikilink_types_flat_frontmatter() -> None:
    frontmatter = '''
supports:
  - "[[Evidence A]]"
contradicts: ["[[Claim B]]"]
'''
    assert parse_flat_relationships(frontmatter) == [
        ("evidence-a", "supports"),
        ("claim-b", "contradicts"),
    ]


def test_parses_multiple_inline_types_and_ignores_email_style_tokens() -> None:
    body = (
        "[[Analysis|This @supersedes and @contradicts the old work]] "
        "[[Contact|john@causes but @supports the claim]]"
    )
    assert parse_inline_relationships(body) == [
        ("analysis", "supersedes"),
        ("analysis", "contradicts"),
        ("contact", "supports"),
    ]


def test_inline_parser_ignores_code_and_unknown_types() -> None:
    body = '''
`[[Inline Code|@supports]]`
```
[[Fence|@contradicts]]
```
[[Real|Real @supports]]
[[Unknown|Unknown @not_declared]]
'''
    assert parse_inline_relationships(body) == [("real", "supports")]


def test_three_representations_normalize_to_one_edge() -> None:
    text = _document(
        '''
title: Source
supports:
  - "[[Target]]"
relationships:
  - target: "[[Target]]"
    type: supports
''',
        "[[Target|Target @supports]]\n",
    )
    assert collect_typed_relationships(text) == [{
        "target": "target",
        "relation": "supports",
        "kind": "relationship",
        "typed": True,
        "weight": 1,
        "representations": ["relationships", "flat", "inline"],
    }]


def test_graph_index_reads_flat_and_inline_relationships(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write(
        vault,
        "source",
        _document(
            'title: Source\nsupports:\n  - "[[Target]]"',
            "[[Other|Other @depends_on]]\n",
        ),
    )
    _write(vault, "target", _document("title: Target"))
    _write(vault, "other", _document("title: Other"))

    index = build_index(vault)
    typed = {
        (edge["target"], edge["relation"]): tuple(edge["representations"])
        for edge in index["source"]["edges"]
        if edge["typed"]
    }
    assert typed == {
        ("target", "supports"): ("flat",),
        ("other", "depends_on"): ("inline",),
    }


def test_unknown_inline_type_degrades_to_plain_link(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write(
        vault,
        "source",
        _document("title: Source", "[[Target|Target @not_declared]]\n"),
    )
    _write(vault, "target", _document("title: Target"))

    edges = build_index(vault)["source"]["edges"]
    assert [(edge["target"], edge["relation"], edge["typed"]) for edge in edges] == [
        ("target", "link", False)
    ]


def test_graphrag_path_uses_reference_flat_relationship(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write(
        vault,
        "source",
        _document('title: Source\nsupports:\n  - "[[Target]]"'),
    )
    _write(vault, "target", _document("title: Target"))

    result = query(vault, "How is source connected to target?")
    assert result["path_length"] == 1
    assert result["path_edges"][0]["relation"] == "supports"
    assert result["path_edges"][0]["representations"] == ["flat"]


def test_graphrag_path_preserves_parallel_relationship_types(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _write(
        vault,
        "source",
        _document(
            "title: Source",
            "[[Target|Target @supports and @contradicts]]\n",
        ),
    )
    _write(vault, "target", _document("title: Target"))

    edge = query(vault, "How is source connected to target?")["path_edges"][0]
    assert edge["types"] == ["supports", "contradicts"]
    assert [detail["relation"] for detail in edge["edge_details"]] == [
        "supports", "contradicts"
    ]


def test_lint_accepts_consistent_dual_write(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    common = "category: concepts\ntags: [test]\nsources: [manual]\ncreated: 2026-08-31\nupdated: 2026-08-31"
    _write(
        vault,
        "source",
        _document(
            f'''title: Source
{common}
supports:
  - "[[Target]]"
relationships:
  - target: "[[Target]]"
    type: supports''',
            "[[Target|Target @supports]]\n",
        ),
    )
    _write(vault, "target", _document(f"title: Target\n{common}"))

    report = lint_vault(vault, require_trust_ledger=False)
    assert report["findings"]["typed_relationship_issues"] == []


def test_lint_reports_projection_mismatch(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    common = "category: concepts\ntags: [test]\nsources: [manual]\ncreated: 2026-08-31\nupdated: 2026-08-31"
    _write(
        vault,
        "source",
        _document(
            f'''title: Source
{common}
supports:
  - "[[Target]]"
relationships:
  - target: "[[Other]]"
    type: supports''',
            "[[Target|Target @supports]]\n",
        ),
    )
    _write(vault, "target", _document(f"title: Target\n{common}"))
    _write(vault, "other", _document(f"title: Other\n{common}"))

    report = lint_vault(vault, require_trust_ledger=False)
    issues = report["findings"]["typed_relationship_issues"]
    assert any(issue["issue"] == "representation_mismatch" for issue in issues)


def test_ingest_and_query_contracts_require_synchronized_projections() -> None:
    repo = Path(__file__).resolve().parents[1]
    contracts = [
        repo / ".skills/wiki-packet-integrate/references/page-write-policy.md",
        repo / ".skills/wiki-capture/SKILL.md",
        repo / ".skills/wiki-update/SKILL.md",
        repo / "workflows/wiki-packet-integrate.yaml",
        repo / "workflows/wiki-query.yaml",
    ]
    for contract in contracts:
        text = contract.read_text(encoding="utf-8")
        assert "relationships:" in text, contract
        assert "@type" in text, contract
        assert "top-level" in text or "顶层" in text, contract
