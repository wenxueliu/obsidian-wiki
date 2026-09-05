from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "example" / "design"
SKILLS = {
    "requirement-spec",
    "design-spec",
    "implementation-plan",
    "test-design",
    "issue-diagnosis",
}


def test_design_example_contains_project_rules_and_five_valid_skills() -> None:
    rules = (EXAMPLE / "AGENTS.md").read_text(encoding="utf-8")
    assert "Knowledge Pack: `software-knowledge`" in rules
    assert "Do not query or update the Wiki while writing code" in rules
    assert "Use CodeGraph for current code structure" in rules

    skill_root = EXAMPLE / ".skills"
    assert {path.name for path in skill_root.iterdir() if path.is_dir()} == SKILLS
    for name in SKILLS:
        text = (skill_root / name / "SKILL.md").read_text(encoding="utf-8")
        assert text.startswith(f"---\nname: {name}\ndescription: ")
        assert "\n---\n" in text[4:]


def test_design_example_keeps_deliverables_out_of_the_wiki_by_default() -> None:
    readme = (EXAMPLE / "README.md").read_text(encoding="utf-8")
    assert "not automatically canonical Wiki pages" in readme
    assert "Do not query the Wiki again" in readme

    for name in SKILLS:
        text = (EXAMPLE / ".skills" / name / "SKILL.md").read_text(encoding="utf-8")
        assert "docs/product-deliverables/" in text
