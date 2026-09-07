"""Tests for the doctor CLI command."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from obsidian_wiki.cli import list_skills


def _run(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    return subprocess.run(
        [sys.executable, "-m", "obsidian_wiki.cli", *args],
        capture_output=True,
        text=True,
        env=env,
    )


def _write_config(home: Path, vault: Path, *, version: str | None = None) -> None:
    config_dir = home / ".obsidian-wiki"
    config_dir.mkdir(parents=True, exist_ok=True)
    lines = [f'OBSIDIAN_VAULT_PATH="{vault}"']
    if version is not None:
        lines.append(f'OBSIDIAN_WIKI_VERSION="{version}"')
    (config_dir / "config").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _make_vault(vault: Path, *, manifest: str = '{"sources": {}}') -> None:
    vault.mkdir(parents=True, exist_ok=True)
    for name in ("index.md", "log.md", "hot.md"):
        (vault / name).write_text(f"# {name}\n", encoding="utf-8")
    (vault / ".manifest.json").write_text(manifest, encoding="utf-8")


def _install_all_skills(project: Path) -> None:
    project.mkdir(parents=True, exist_ok=True)
    (project / "AGENTS.md").write_text("# Agent context\n", encoding="utf-8")
    target = project / ".agents" / "skills"
    target.mkdir(parents=True, exist_ok=True)
    for name in list_skills():
        skill_dir = target / name
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")


def test_doctor_json_clean_install(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    project = tmp_path / "project"
    _make_vault(vault)
    _write_config(home, vault)
    _install_all_skills(project)

    proc = _run(home, "doctor", "--project", str(project), "--json")

    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["status"] == "pass"
    assert any(check["name"] == "manifest-json" and check["status"] == "pass" for check in data["checks"])


def test_doctor_warns_without_agent_installs_but_exits_zero(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    project = tmp_path / "project"
    project.mkdir()
    _make_vault(vault)
    _write_config(home, vault)

    proc = _run(home, "doctor", "--project", str(project), "--json")

    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["status"] == "warn"
    assert any(check["name"] == "agent-installs" and check["status"] == "warn" for check in data["checks"])


def test_doctor_fails_on_invalid_manifest(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    project = tmp_path / "project"
    _make_vault(vault, manifest="{not json")
    _write_config(home, vault)
    _install_all_skills(project)

    proc = _run(home, "doctor", "--project", str(project), "--json")

    assert proc.returncode == 1
    data = json.loads(proc.stdout)
    assert data["status"] == "fail"
    assert any(check["name"] == "manifest-json" and check["status"] == "fail" for check in data["checks"])


def test_doctor_strict_turns_warnings_into_nonzero_exit(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    _make_vault(vault)
    _write_config(home, vault, version="0.0.0")

    proc = _run(home, "doctor", "--json", "--strict")

    assert proc.returncode == 1
    data = json.loads(proc.stdout)
    assert any(check["name"] == "setup-version" and check["status"] == "warn" for check in data["checks"])
