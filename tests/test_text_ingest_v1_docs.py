from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_v1_skills_are_packaged_and_have_clear_write_ownership():
    folder = (ROOT / ".skills" / "wiki-folder-ingest" / "SKILL.md").read_text()
    worker = (ROOT / ".skills" / "wiki-source-text" / "SKILL.md").read_text()
    integrator = (ROOT / ".skills" / "wiki-ingest" / "SKILL.md").read_text()

    assert "never read or receive full source bodies" in folder
    assert "Never update\n`job.json`, `.manifest.json`" in worker
    assert "permanent manifest **last**" in integrator
    assert "serial incremental reducer" in integrator


def test_v1_routing_and_cli_are_documented():
    agents = (ROOT / "AGENTS.md").read_text()
    cli = (ROOT / "docs" / "cli.md").read_text()
    skills = (ROOT / "docs" / "skills.md").read_text()

    assert "`wiki-folder-ingest`" in agents
    assert "`wiki-source-text`" in agents
    assert "text-chunk-plan <source>" in cli
    assert "text-chunk-read <source>" in cli
    assert "Text ingest V1 accepts UTF-8" in skills


def test_pageindex_runtime_configuration_was_removed():
    config = (ROOT / ".env.example").read_text()
    assert "PAGEINDEX_REPO=" not in config
    assert "PAGEINDEX_MODEL=" not in config
