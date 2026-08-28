from pathlib import Path

from obsidian_wiki.cli import _remove_obsolete_managed_skills


LEGACY_SKILL = """---
name: wiki-ingest
description: legacy
---

# Wiki Ingest — Packet Integration
"""


def test_obsolete_managed_copy_is_removed(tmp_path: Path) -> None:
    legacy = tmp_path / "wiki-ingest"
    legacy.mkdir()
    (legacy / "SKILL.md").write_text(LEGACY_SKILL, encoding="utf-8")

    _remove_obsolete_managed_skills(tmp_path)

    assert not legacy.exists()


def test_unrecognized_same_name_directory_is_preserved(tmp_path: Path) -> None:
    custom = tmp_path / "wiki-ingest"
    custom.mkdir()
    (custom / "SKILL.md").write_text(
        "---\nname: wiki-ingest\n---\n\n# My Custom Skill\n", encoding="utf-8"
    )

    _remove_obsolete_managed_skills(tmp_path)

    assert custom.is_dir()


def test_source_and_package_installers_both_clean_legacy_skill() -> None:
    root = Path(__file__).resolve().parents[1]
    source_setup = (root / "setup.py").read_text(encoding="utf-8")
    package_cli = (root / "obsidian_wiki" / "cli.py").read_text(encoding="utf-8")

    assert 'OBSOLETE_MANAGED_SKILLS = ("wiki-ingest",)' in source_setup
    assert 'OBSOLETE_MANAGED_SKILLS = ("wiki-ingest",)' in package_cli
    assert "name: wiki-ingest" in source_setup
    assert "name: wiki-ingest" in package_cli
