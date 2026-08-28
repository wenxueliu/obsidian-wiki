from pathlib import Path

import obsidian_wiki.cli as cli


def _template_root(tmp_path: Path) -> tuple[Path, str]:
    skills = tmp_path / "skills"
    reference = skills / "llm-wiki" / "references" / "WRITING.md"
    reference.parent.mkdir(parents=True)
    content = "# Wiki Writing Profile\n\n## Language\n"
    reference.write_text(content, encoding="utf-8")
    return skills, content


def test_ensure_global_writing_profile_copies_packaged_template(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    skills, content = _template_root(tmp_path)
    monkeypatch.setattr(cli, "GLOBAL_CONFIG_DIR", config_dir)
    monkeypatch.setattr(cli, "skills_dir", lambda: skills)

    target = cli.ensure_global_writing_profile()

    assert target == config_dir / "WRITING.md"
    assert target.read_text(encoding="utf-8") == content


def test_ensure_global_writing_profile_never_overwrites_user_preferences(
    tmp_path, monkeypatch
):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    target = config_dir / "WRITING.md"
    target.write_text("custom profile\n", encoding="utf-8")
    skills, _ = _template_root(tmp_path)
    monkeypatch.setattr(cli, "GLOBAL_CONFIG_DIR", config_dir)
    monkeypatch.setattr(cli, "skills_dir", lambda: skills)

    assert cli.ensure_global_writing_profile() == target
    assert target.read_text(encoding="utf-8") == "custom profile\n"


def test_source_and_cli_setup_have_writing_profile_parity():
    root = Path(__file__).resolve().parents[1]
    source_setup = (root / "setup.py").read_text(encoding="utf-8")
    cli_setup = (root / "obsidian_wiki" / "cli.py").read_text(encoding="utf-8")

    for implementation in (source_setup, cli_setup):
        assert "ensure_global_writing_profile" in implementation
        assert '"WRITING.md"' in implementation
        assert "if target.exists()" in implementation or "if not target.exists()" in implementation
