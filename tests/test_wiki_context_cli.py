from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_wiki_context_resolve_does_not_depend_on_cwd(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    supplied = tmp_path / "vault-input.json"
    supplied.write_text(
        json.dumps({"mode": "interactive", "vault_path": str(vault), "overrides": {}}),
        encoding="utf-8",
    )
    output = tmp_path / "artifacts"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "obsidian_wiki",
            "wiki-context-resolve",
            "--input",
            str(supplied),
            "--source-cwd",
            str(tmp_path),
            "--output-dir",
            str(output),
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    context = json.loads((output / "wiki-context.json").read_text(encoding="utf-8"))
    assert context["vault_path"] == str(vault)


def test_wiki_context_workflow_uses_cwd_independent_cli() -> None:
    workflow = (ROOT / "workflows" / "wiki-context.yaml").read_text(encoding="utf-8")

    assert "obsidian-wiki wiki-context-resolve" in workflow
    assert "python3 .cac/ralph-flow/workflows/wiki/scripts/resolve_wiki_context.py" not in workflow


def test_wiki_route_resolve_does_not_depend_on_cwd(tmp_path: Path) -> None:
    routing = tmp_path / "routing.json"
    routing.write_text(
        json.dumps({
            "version": 1,
            "allowed_placeholders": ["slug"],
            "content_roots": ["concepts"],
            "system_dirs": ["_meta"],
            "skip_dirs": ["_meta"],
            "system_paths": ["index.md", "_meta/layout.json"],
            "fallback": "concept",
            "routes": {"concept": "concepts/{slug}.md"},
        }),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    result = subprocess.run(
        [
            sys.executable, "-m", "obsidian_wiki", "wiki-route-resolve",
            "--routing", str(routing), "--page-type", "concept", "--slug", "alpha",
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["target"] == "concepts/alpha.md"


def test_page_contract_uses_cwd_independent_route_cli() -> None:
    workflow = (ROOT / "workflows" / "wiki-page-contract.yaml").read_text(encoding="utf-8")
    assert "obsidian-wiki wiki-route-resolve" in workflow
    assert ".cac/" not in workflow
