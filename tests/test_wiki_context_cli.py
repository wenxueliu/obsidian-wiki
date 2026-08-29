from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_context_resolver(
    tmp_path: Path,
    vault: Path | None,
    *,
    setup_mode: str,
    requested_keys: str = "",
    mode: str = "interactive",
    profile: str | None = None,
    home: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    supplied = tmp_path / f"vault-input-{setup_mode}.json"
    input_value: dict[str, object] = {"mode": mode, "overrides": {}}
    if vault is not None:
        input_value["vault_path"] = str(vault)
    if profile is not None:
        input_value["profile"] = profile
    supplied.write_text(
        json.dumps(input_value),
        encoding="utf-8",
    )
    output = tmp_path / f"artifacts-{setup_mode}"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    if home is not None:
        env["HOME"] = str(home)
    return subprocess.run(
        [
            sys.executable, "-m", "obsidian_wiki", "wiki-context-resolve",
            "--input", str(supplied), "--source-cwd", str(tmp_path),
            "--requested-keys", requested_keys,
            "--optional-reads", "active layout",
            "--setup-mode", setup_mode, "--output-dir", str(output),
        ],
        cwd=tmp_path, env=env, text=True, capture_output=True, check=False,
    )


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
    assert '"mode":"config"' in workflow
    assert "manual_step:" not in workflow


def test_setup_mode_true_allows_an_uninitialized_vault(tmp_path: Path) -> None:
    vault = tmp_path / "new-vault"

    result = run_context_resolver(tmp_path, vault, setup_mode="true")

    assert result.returncode == 0, result.stderr
    context = json.loads(
        (tmp_path / "artifacts-true" / "wiki-context.json").read_text(encoding="utf-8")
    )
    assert context["setup_mode"] is True
    assert context["optional_metadata"]["active_layout"]["status"] == "uninitialized"
    assert context["warnings"] == []


def test_setup_mode_false_rejects_a_missing_vault(tmp_path: Path) -> None:
    vault = tmp_path / "missing-vault"

    result = run_context_resolver(tmp_path, vault, setup_mode="false")

    assert result.returncode == 1
    assert "vault does not exist or is not a directory" in result.stderr


def test_context_resolver_types_text_chunk_budget_config(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (tmp_path / ".env").write_text(
        f"OBSIDIAN_VAULT_PATH={vault}\n"
        "WIKI_TEXT_CHUNK_TARGET_BYTES=12000\n"
        "WIKI_TEXT_CHUNK_HARD_MAX_BYTES=16000\n",
        encoding="utf-8",
    )

    result = run_context_resolver(
        tmp_path,
        vault,
        setup_mode="false",
        requested_keys="WIKI_TEXT_CHUNK_TARGET_BYTES,WIKI_TEXT_CHUNK_HARD_MAX_BYTES",
    )

    assert result.returncode == 0, result.stderr
    context = json.loads(
        (tmp_path / "artifacts-false" / "wiki-context.json").read_text(encoding="utf-8")
    )
    assert context["requested_values"]["WIKI_TEXT_CHUNK_TARGET_BYTES"] == 12000
    assert context["requested_values"]["WIKI_TEXT_CHUNK_HARD_MAX_BYTES"] == 16000


def test_context_resolver_reads_vault_from_nearest_env(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = home / "project"
    nested = project / "nested"
    vault = tmp_path / "vault"
    nested.mkdir(parents=True)
    vault.mkdir()
    (project / ".env").write_text(
        f"OBSIDIAN_VAULT_PATH={vault}\nWIKI_TEXT_CHUNK_TARGET_BYTES=9000\n",
        encoding="utf-8",
    )

    result = run_context_resolver(
        nested, None, setup_mode="false", mode="config",
        requested_keys="OBSIDIAN_VAULT_PATH,WIKI_TEXT_CHUNK_TARGET_BYTES", home=home,
    )

    assert result.returncode == 0, result.stderr
    context = json.loads((nested / "artifacts-false" / "wiki-context.json").read_text())
    assert context["vault_path"] == str(vault)
    assert context["config_source"] == str(project / ".env")
    assert context["requested_values"]["WIKI_TEXT_CHUNK_TARGET_BYTES"] == 9000


def test_context_resolver_reads_vault_from_global_setup_config(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = home / "project"
    vault = tmp_path / "vault"
    project.mkdir(parents=True)
    vault.mkdir()
    config = home / ".obsidian-wiki" / "config"
    config.parent.mkdir()
    config.write_text(f"OBSIDIAN_VAULT_PATH={vault}\n", encoding="utf-8")

    result = run_context_resolver(
        project, None, setup_mode="false", mode="config",
        requested_keys="OBSIDIAN_VAULT_PATH", home=home,
    )

    assert result.returncode == 0, result.stderr
    context = json.loads((project / "artifacts-false" / "wiki-context.json").read_text())
    assert context["vault_path"] == str(vault)
    assert context["config_source"] == str(config)


def test_context_resolver_honors_named_vault_profile(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = home / "project"
    vault = tmp_path / "work-vault"
    project.mkdir(parents=True)
    vault.mkdir()
    config = home / ".obsidian-wiki" / "config.work"
    config.parent.mkdir()
    config.write_text(f"OBSIDIAN_VAULT_PATH={vault}\n", encoding="utf-8")

    result = run_context_resolver(
        project, None, setup_mode="false", mode="config", profile="work",
        requested_keys="OBSIDIAN_VAULT_PATH", home=home,
    )

    assert result.returncode == 0, result.stderr
    context = json.loads((project / "artifacts-false" / "wiki-context.json").read_text())
    assert context["vault_path"] == str(vault)
    assert context["config_source"] == str(config)


def test_context_resolver_does_not_bypass_empty_nearest_vault_config(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = home / "project"
    global_vault = tmp_path / "global-vault"
    project.mkdir(parents=True)
    global_vault.mkdir()
    (project / ".env").write_text("OBSIDIAN_VAULT_PATH=\n", encoding="utf-8")
    config = home / ".obsidian-wiki" / "config"
    config.parent.mkdir()
    config.write_text(f"OBSIDIAN_VAULT_PATH={global_vault}\n", encoding="utf-8")

    result = run_context_resolver(
        project, None, setup_mode="false", mode="config",
        requested_keys="OBSIDIAN_VAULT_PATH", home=home,
    )

    assert result.returncode == 1
    assert f"OBSIDIAN_VAULT_PATH is empty in config: {project / '.env'}" in result.stderr


def test_missing_named_profile_never_falls_back_to_default(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = home / "project"
    default_vault = tmp_path / "default-vault"
    project.mkdir(parents=True)
    default_vault.mkdir()
    config_dir = home / ".obsidian-wiki"
    config_dir.mkdir()
    (config_dir / "config").write_text(
        f"OBSIDIAN_VAULT_PATH={default_vault}\n", encoding="utf-8"
    )
    (config_dir / "config.personal").write_text(
        f"OBSIDIAN_VAULT_PATH={default_vault}\n", encoding="utf-8"
    )

    result = run_context_resolver(
        project, None, setup_mode="false", mode="config", profile="missing",
        requested_keys="OBSIDIAN_VAULT_PATH", home=home,
    )

    assert result.returncode == 1
    assert "named vault config does not exist" in result.stderr
    assert "available profiles: personal" in result.stderr


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
