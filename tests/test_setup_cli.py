from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import obsidian_wiki.cli as cli


def setup_args(**overrides) -> Namespace:
    values = {
        "list_layouts": False,
        "project_only": True,
        "project": None,
        "copy": True,
        "skills_only": False,
        "vault": None,
        "layout": None,
        "refresh_layout_marker": False,
        "remote": None,
    }
    values.update(overrides)
    return Namespace(**values)


def isolate_setup_side_effects(monkeypatch, vault: Path, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "resolve_vault_path", lambda _vault: str(vault))
    monkeypatch.setattr(cli, "write_config", lambda _vault: None)
    monkeypatch.setattr(cli, "ensure_global_writing_profile", lambda: tmp_path / "WRITING.md")
    monkeypatch.setattr(cli, "_maybe_configure_sync", lambda _vault, _remote: False)


def test_setup_skills_only_project_install_does_not_resolve_vault(
    tmp_path: Path,
    monkeypatch,
) -> None:
    installed: list[tuple[Path, str]] = []

    def fail_resolve(_vault: str | None) -> str:
        raise AssertionError("skills-only setup must not resolve a vault")

    monkeypatch.setattr(cli, "resolve_vault_path", fail_resolve)
    monkeypatch.setattr(
        cli,
        "install_project",
        lambda path, mode: installed.append((path, mode)),
    )
    monkeypatch.setattr(cli, "list_skills", lambda: ["wiki-setup"])

    result = cli.cmd_setup(setup_args(project=str(tmp_path), skills_only=True))

    assert result == 0
    assert installed == [(tmp_path.resolve(), "copy")]


def test_setup_parser_accepts_skills_only_and_marker_refresh() -> None:
    args = cli.build_parser().parse_args(
        [
            "setup",
            "--project",
            ".",
            "--project-only",
            "--skills-only",
            "--copy",
        ]
    )

    assert args.skills_only is True
    assert args.project_only is True
    assert args.copy is True

    refresh_args = cli.build_parser().parse_args(
        ["setup", "--vault", "/tmp/vault", "--refresh-layout-marker"]
    )
    assert refresh_args.refresh_layout_marker is True


def test_vault_argument_is_resolved_to_an_absolute_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    resolved = cli.resolve_vault_path("~/wiki-vault")

    assert resolved == str((Path.home() / "wiki-vault").resolve())
    assert Path(resolved).is_absolute()


def test_project_setup_copies_packaged_env_template_only_when_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    template = tmp_path / "packaged.env.example"
    template.write_text("OBSIDIAN_VAULT_PATH=\n", encoding="utf-8")
    project = tmp_path / "project"
    monkeypatch.setattr(cli, "_env_example_path", lambda: template)

    assert cli.ensure_project_env(project) is True
    assert (project / ".env").read_text(encoding="utf-8") == template.read_text(encoding="utf-8")

    (project / ".env").write_text("OBSIDIAN_VAULT_PATH=/custom\n", encoding="utf-8")
    assert cli.ensure_project_env(project) is False
    assert (project / ".env").read_text(encoding="utf-8") == "OBSIDIAN_VAULT_PATH=/custom\n"


def test_project_setup_applies_vault_override_to_new_env(tmp_path: Path, monkeypatch) -> None:
    template = tmp_path / "packaged.env.example"
    template.write_text("# config\nOBSIDIAN_VAULT_PATH=\n", encoding="utf-8")
    project = tmp_path / "project"
    monkeypatch.setattr(cli, "_env_example_path", lambda: template)

    cli.ensure_project_env(project, {"OBSIDIAN_VAULT_PATH": "/tmp/my-vault"})

    assert (project / ".env").read_text(encoding="utf-8") == (
        '# config\nOBSIDIAN_VAULT_PATH="/tmp/my-vault"\n'
    )


def test_setup_without_layout_preserves_existing_custom_pack(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    cli.scaffold_vault(vault, cli.load_layout("software-knowledge"))
    isolate_setup_side_effects(monkeypatch, vault, tmp_path)

    result = cli.cmd_setup(setup_args())

    assert result == 0
    marker = json.loads((vault / "_meta" / "layout.json").read_text())
    assert marker["name"] == "software-knowledge"


def test_setup_upgrades_pre_profile_marker_for_same_pack(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    cli.scaffold_vault(vault, cli.load_layout("software-knowledge"))
    marker_path = vault / "_meta" / "layout.json"
    marker = json.loads(marker_path.read_text())
    marker.pop("profile_sha256")
    marker_path.write_text(json.dumps(marker))
    isolate_setup_side_effects(monkeypatch, vault, tmp_path)

    result = cli.cmd_setup(setup_args())

    assert result == 0
    upgraded = json.loads(marker_path.read_text())
    assert upgraded["name"] == "software-knowledge"
    assert upgraded["profile_sha256"].startswith("sha256:")
