from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import obsidian_wiki.cli as cli
import pytest


def setup_args(**overrides) -> Namespace:
    values = {
        "list_layouts": False,
        "list_agents": False,
        "project_only": True,
        "project": None,
        "copy": True,
        "skills_only": False,
        "agent": ["claude"],
        "vault": None,
        "layout": "default",
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
        lambda path, mode, agents: installed.append((path, mode, agents)) or set(agents),
    )
    monkeypatch.setattr(cli, "list_skills", lambda: ["wiki-setup"])

    result = cli.cmd_setup(
        setup_args(project=str(tmp_path), skills_only=True, layout=None)
    )

    assert result == 0
    assert installed == [(tmp_path.resolve(), "copy", ("claude",))]


def test_setup_skills_only_requires_agent_selection(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(
        cli,
        "install_project",
        lambda *_args, **_kwargs: pytest.fail("install must not run without a selection"),
    )

    result = cli.cmd_setup(
        setup_args(project=str(tmp_path), skills_only=True, agent=None, layout=None)
    )

    assert result == 2


def test_setup_parser_accepts_skills_only_and_marker_refresh() -> None:
    args = cli.build_parser().parse_args(
        [
            "setup",
            "--project",
            ".",
            "--project-only",
            "--skills-only",
            "--copy",
            "--agent",
            "claude,codex",
        ]
    )

    assert args.skills_only is True
    assert args.project_only is True
    assert args.copy is True
    assert args.agent == ["claude,codex"]

    refresh_args = cli.build_parser().parse_args(
        ["setup", "--vault", "/tmp/vault", "--refresh-layout-marker"]
    )
    assert refresh_args.refresh_layout_marker is True


def test_setup_agent_selection_has_no_noninteractive_default(monkeypatch) -> None:
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)

    assert cli._select_setup_agents(None) == ()
    assert cli._parse_setup_agents(["claude,codex", "pi"]) == ("claude", "codex", "pi")
    assert cli._parse_setup_agents(["all"]) == cli.SETUP_AGENT_NAMES


def test_interactive_agent_selection_supports_multiple_choices(monkeypatch) -> None:
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: "1,4,13")

    assert cli._select_setup_agents(None) == ("claude", "codex", "pi")


def test_noninteractive_setup_requires_explicit_agent_choice(monkeypatch) -> None:
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)

    result = cli.cmd_setup(setup_args(agent=None, skills_only=False))

    assert result == 2


def test_noninteractive_setup_requires_explicit_layout_choice(monkeypatch) -> None:
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)

    result = cli.cmd_setup(setup_args(layout=None, skills_only=False))

    assert result == 2


def test_interactive_layout_selection_is_single_choice(monkeypatch, capsys) -> None:
    answers = iter(("default,book-knowledge", "2"))
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    selected = cli._select_setup_layout(None)

    assert selected == "default"
    assert "single-choice" in capsys.readouterr().out


def test_setup_agent_selection_rejects_unknown_or_mixed_sentinels() -> None:
    with pytest.raises(ValueError, match="unknown agent"):
        cli._parse_setup_agents(["claude,unknown"])
    with pytest.raises(ValueError, match="cannot be combined"):
        cli._parse_setup_agents(["all", "claude"])
    with pytest.raises(ValueError, match="cannot be combined"):
        cli._parse_setup_agents(["none", "claude"])


def test_global_skill_install_only_targets_selected_agents(monkeypatch, tmp_path: Path) -> None:
    installed: list[Path] = []
    monkeypatch.setattr(cli, "HOME", tmp_path)
    monkeypatch.setattr(
        cli,
        "install_skills",
        lambda target, _label, **_kwargs: installed.append(target) or 1,
    )

    result = cli.install_global_skills("copy", ("codex", "pi"))

    assert result == {"codex", "pi"}
    assert installed == [tmp_path / ".codex/skills", tmp_path / ".pi/agent/skills"]


def test_install_skills_preserves_directory_level_link_to_canonical_source(
    monkeypatch, tmp_path: Path,
) -> None:
    source = tmp_path / "canonical-skills"
    skill = source / "example"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# Example\n", encoding="utf-8")
    target = tmp_path / "project" / ".claude" / "skills"
    target.parent.mkdir(parents=True)
    target.symlink_to(source, target_is_directory=True)
    monkeypatch.setattr(cli, "skills_dir", lambda: source)

    installed = cli.install_skills(target, "project Claude", mode="symlink")

    assert installed == 1
    assert skill.is_dir()
    assert not skill.is_symlink()
    assert (target / "example" / "SKILL.md").read_text(encoding="utf-8") == "# Example\n"


def test_install_skills_rejects_target_inside_canonical_source(
    monkeypatch, tmp_path: Path,
) -> None:
    source = tmp_path / "canonical-skills"
    (source / "example").mkdir(parents=True)
    monkeypatch.setattr(cli, "skills_dir", lambda: source)

    with pytest.raises(RuntimeError, match="inside canonical source"):
        cli.install_skills(source / "nested", "unsafe target", mode="symlink")


def test_install_skills_ignores_invalid_source_directory_and_removes_its_link(
    monkeypatch, tmp_path: Path,
) -> None:
    source = tmp_path / "canonical-skills"
    valid = source / "valid"
    valid.mkdir(parents=True)
    (valid / "SKILL.md").write_text("# Valid\n", encoding="utf-8")
    invalid = source / "removed-skill"
    invalid.mkdir()
    target = tmp_path / "agent-skills"
    target.mkdir()
    stale_link = target / invalid.name
    stale_link.symlink_to(invalid, target_is_directory=True)
    monkeypatch.setattr(cli, "skills_dir", lambda: source)

    installed = cli.install_skills(target, "test agent", mode="symlink")

    assert installed == 1
    assert (target / "valid" / "SKILL.md").is_file()
    assert not stale_link.is_symlink()


def test_install_skills_removes_link_to_deleted_canonical_skill(
    monkeypatch, tmp_path: Path,
) -> None:
    source = tmp_path / "canonical-skills"
    valid = source / "valid"
    valid.mkdir(parents=True)
    (valid / "SKILL.md").write_text("# Valid\n", encoding="utf-8")
    target = tmp_path / "agent-skills"
    target.mkdir()
    stale_link = target / "deleted-skill"
    stale_link.symlink_to(source / "deleted-skill", target_is_directory=True)
    monkeypatch.setattr(cli, "skills_dir", lambda: source)

    cli.install_skills(target, "test agent", mode="symlink")

    assert not stale_link.is_symlink()


def test_list_skills_only_returns_directories_with_skill_marker(
    monkeypatch, tmp_path: Path,
) -> None:
    source = tmp_path / "skills"
    (source / "valid").mkdir(parents=True)
    (source / "valid" / "SKILL.md").write_text("# Valid\n", encoding="utf-8")
    (source / "empty").mkdir()
    monkeypatch.setattr(cli, "skills_dir", lambda: source)

    assert cli.list_skills() == ["valid"]


def test_project_skill_install_only_targets_selected_agents(
    monkeypatch, tmp_path: Path,
) -> None:
    installed: list[Path] = []
    monkeypatch.setattr(
        cli,
        "install_skills",
        lambda target, _label, **_kwargs: installed.append(target) or 1,
    )
    monkeypatch.setattr(cli, "bootstrap_dir", lambda: None)

    result = cli.install_project(tmp_path, "copy", ("cursor", "kiro"))

    assert result == {"cursor", "kiro"}
    assert installed == [tmp_path / ".cursor/skills", tmp_path / ".kiro/skills"]


def test_project_bootstrap_only_targets_selected_agents(
    monkeypatch, tmp_path: Path,
) -> None:
    boot = tmp_path / "bootstrap"
    for source, _destination in cli.BOOTSTRAP_FILES:
        path = boot / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"bootstrap: {source}\n", encoding="utf-8")
    project = tmp_path / "project"
    monkeypatch.setattr(cli, "bootstrap_dir", lambda: boot)
    monkeypatch.setattr(cli, "install_skills", lambda *_args, **_kwargs: 1)

    result = cli.install_project(project, "copy", ("claude",))

    assert result == {"claude"}
    assert (project / "AGENTS.md").is_file()
    assert (project / "CLAUDE.md").exists()
    assert not (project / "GEMINI.md").exists()
    assert not (project / ".hermes.md").exists()
    for _source, destination in cli.BOOTSTRAP_FILES[1:]:
        assert not (project / destination).exists()


def test_project_bootstrap_supports_multiple_selected_agents(
    monkeypatch, tmp_path: Path,
) -> None:
    boot = tmp_path / "bootstrap"
    for source, _destination in cli.BOOTSTRAP_FILES:
        path = boot / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"bootstrap: {source}\n", encoding="utf-8")
    project = tmp_path / "project"
    monkeypatch.setattr(cli, "bootstrap_dir", lambda: boot)
    monkeypatch.setattr(cli, "install_skills", lambda *_args, **_kwargs: 1)

    cli.install_project(project, "copy", ("cursor", "gemini"))

    assert (project / ".cursor/rules/obsidian-wiki.mdc").is_file()
    assert (project / "GEMINI.md").exists()
    assert not (project / ".windsurf/rules/obsidian-wiki.md").exists()
    assert not (project / "CLAUDE.md").exists()


def test_vault_argument_is_resolved_to_an_absolute_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    resolved = cli.resolve_vault_path("~/wiki-vault")

    assert resolved == str((Path.home() / "wiki-vault").resolve())
    assert Path(resolved).is_absolute()


def test_interactive_setup_vault_defaults_to_current_directory(
    tmp_path: Path, monkeypatch,
) -> None:
    prompts: list[str] = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(
        "builtins.input",
        lambda prompt: prompts.append(prompt) or "",
    )

    resolved = cli._select_setup_vault(None)

    assert resolved == str(tmp_path.resolve())
    assert str(tmp_path.resolve()) in prompts[0]


def test_interactive_setup_vault_accepts_user_input(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: "my-vault")

    assert cli._select_setup_vault(None) == str((tmp_path / "my-vault").resolve())


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


def test_setup_with_explicit_layout_preserves_existing_custom_pack(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    cli.scaffold_vault(vault, cli.load_layout("software-knowledge"))
    isolate_setup_side_effects(monkeypatch, vault, tmp_path)

    result = cli.cmd_setup(setup_args(layout="software-knowledge"))

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

    result = cli.cmd_setup(setup_args(layout="software-knowledge"))

    assert result == 0
    upgraded = json.loads(marker_path.read_text())
    assert upgraded["name"] == "software-knowledge"
    assert upgraded["profile_sha256"].startswith("sha256:")
