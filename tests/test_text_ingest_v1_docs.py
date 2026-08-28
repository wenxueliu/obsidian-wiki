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


def test_extraction_and_synthesis_guidance_remain_in_the_correct_stage():
    worker = (ROOT / ".skills" / "wiki-source-text" / "SKILL.md").read_text()
    extraction = (
        ROOT / ".skills" / "wiki-source-text" / "references" / "extraction-frame.md"
    ).read_text()
    integrator = (ROOT / ".skills" / "wiki-ingest" / "SKILL.md").read_text()
    prompts = (
        ROOT / ".skills" / "wiki-ingest" / "references" / "ingest-prompts.md"
    ).read_text()

    assert "Read `references/extraction-frame.md` completely" in worker
    for category in ("concepts", "claims", "entities", "relationships", "questions"):
        assert f'"{category}"' in extraction
    for provenance in ("extracted", "inferred", "ambiguous"):
        assert f"`{provenance}`" in extraction
    assert "Every concept, claim, entity, relationship, and question" in extraction
    assert "Paper Extraction" not in extraction
    assert "`references/ingest-prompts.md` completely" in integrator
    assert "## Knowledge routing frame" in prompts
    assert "## Synthesis frame" in prompts
    assert "## Cross-reference discovery frame" in prompts
    for relationship in ("Is-a", "Uses", "Contrasts-with", "Part-of", "Created-by", "Applied-in"):
        assert f"**{relationship}**" in prompts
    assert "Paper Extraction Frame is intentionally absent" in prompts
    assert "do not reconcile with\nother ranges or the wiki" in extraction


def test_page_writes_staging_and_cross_references_remain_integrated():
    integrator = (ROOT / ".skills" / "wiki-ingest" / "SKILL.md").read_text()
    policy = (
        ROOT / ".skills" / "wiki-ingest" / "references" / "page-write-policy.md"
    ).read_text()
    stage_commit = (ROOT / ".skills" / "wiki-stage-commit" / "SKILL.md").read_text()
    coordinator = (ROOT / ".skills" / "wiki-folder-ingest" / "SKILL.md").read_text()

    assert "`references/page-write-policy.md` completely" in integrator
    assert "WIKI_STAGED_WRITES" in integrator
    for field in (
        "summary", "relationships", "provenance", "base_confidence", "lifecycle",
        "lifecycle_changed", "tier", "created", "updated",
    ):
        assert f"{field}:" in policy
    assert "New pages go to `<category>/<page>.md`" in policy
    assert "_staging/<category>/<page>.patch.md" in policy
    assert "set the unit to `staged`, not\n`integrated`" in policy
    assert "leave `units_integrated` unchanged" in policy
    assert "Consider whether the target should link back" in policy
    assert "staged -> integrated" in integrator
    assert "approved_waiting_order" in stage_commit
    assert "Remove the staging-only `staged_write` metadata" in stage_commit
    assert "permanent source manifest" in stage_commit
    assert "not advance until" in stage_commit
    assert "pages are live" in stage_commit
    assert "mark it staged without increasing `units_integrated`" in coordinator
    assert "Job in `awaiting_review` is not complete" in coordinator


def test_manifest_and_special_file_finalization_is_a_shared_complete_source_policy():
    integrator = (ROOT / ".skills" / "wiki-ingest" / "SKILL.md").read_text()
    stage_commit = (ROOT / ".skills" / "wiki-stage-commit" / "SKILL.md").read_text()
    policy = (
        ROOT / ".skills" / "wiki-ingest" / "references" / "finalization-policy.md"
    ).read_text()

    assert "`references/finalization-policy.md` completely" in integrator
    assert "../wiki-ingest/references/finalization-policy.md" in stage_commit
    for field in (
        '"content_hash"', '"last_ingested"', '"pages_produced"',
        '"pages_created"', '"pages_updated"', '"source_type"',
        '"chunker_version"', '"units_total"', '"units_integrated"',
    ):
        assert field in policy
    assert "version: 1" in policy
    assert "stats.total_sources_ingested" in policy
    assert "stats.total_pages" in policy
    assert "pages_updated=N pages_created=M mode=append|full" in policy
    for heading in ("Recent Activity", "Active Threads", "Key Takeaways", "Flagged Contradictions"):
        assert heading in policy
    for finding in ("missing_entry", "empty_pages", "phantom_pages"):
        assert f"`{finding}`" in policy
    assert "`.manifest.json` **last**" in policy
    assert "PageIndex section-coverage checks and QMD index refresh are not part" in policy


def test_llm_wiki_foundation_matches_text_v1_and_live_commit_boundaries():
    foundation = (ROOT / ".skills" / "llm-wiki" / "SKILL.md").read_text()

    for suffix in ("`.md`", "`.markdown`", "`.mdx`", "`.txt`", "`.rst`"):
        assert suffix in foundation
    assert "require a specialized skill or a future source adapter" in foundation
    assert "Paper Deep-Dive Template (specialized/future PDF ingest)" in foundation
    assert "does not make PDF/PageIndex processing part of\ntext V1" in foundation
    assert "PyMuPDF extraction recipe" not in foundation
    assert "wiki-ingest` (URL)" not in foundation
    assert "raw text/chat/log data" not in foundation

    for special_file in ("### `index.md`", "### `log.md`", "### `hot.md`", "### `.manifest.json`"):
        assert special_file in foundation
    assert "Pending `_staging/` artifacts never appear in\nthe index" in foundation
    assert "planned unit, extracted Packet, or staged proposal" in foundation
    assert "atomically replace the\nmanifest last" in foundation
    assert "Never refresh for review-pending staged artifacts" in foundation


def test_text_ingest_uses_the_effective_relationship_schema_without_legacy_hardcoding():
    foundation = (ROOT / ".skills" / "llm-wiki" / "SKILL.md").read_text()
    extraction = (
        ROOT / ".skills" / "wiki-source-text" / "references" / "extraction-frame.md"
    ).read_text()
    prompts = (
        ROOT / ".skills" / "wiki-ingest" / "references" / "ingest-prompts.md"
    ).read_text()
    lint_skill = (ROOT / ".skills" / "wiki-lint" / "SKILL.md").read_text()

    assert "The standard 24-type vocabulary" in foundation
    assert "Existing legacy values" in foundation
    assert "effective\n   owner extensions from `llm-wiki/SKILL.md`" in extraction
    assert "effective allowlist in\n`llm-wiki/SKILL.md`" in prompts
    assert "standard vocabulary in `llm-wiki/SKILL.md`" in lint_skill


def test_writing_profile_is_resolved_for_ingest_without_overriding_structured_contracts():
    foundation = (ROOT / ".skills" / "llm-wiki" / "SKILL.md").read_text()
    integrator = (ROOT / ".skills" / "wiki-ingest" / "SKILL.md").read_text()
    page_policy = (
        ROOT / ".skills" / "wiki-ingest" / "references" / "page-write-policy.md"
    ).read_text()
    setup_skill = (ROOT / ".skills" / "wiki-setup" / "SKILL.md").read_text()
    configuration = (ROOT / "docs" / "configuration.md").read_text()
    template = (
        ROOT / ".skills" / "llm-wiki" / "references" / "WRITING.md"
    ).read_text()

    assert "## Writing Profile Resolution" in foundation
    assert "framework invariants such as schema, provenance, safety" in foundation
    assert "current project `AGENTS.md`" in foundation
    assert "resolved vault `AGENTS.md`" in foundation
    assert "global `WRITING.md`" in foundation
    assert "Packet JSON, structured logs, patches" in foundation
    assert "`Writing Profile Resolution` section" in integrator
    assert "preserve structured records and source content" in integrator
    assert "Apply the resolved Writing Profile" in page_policy
    assert "never overwrite an existing profile" in setup_skill
    assert "## Global wiki writing profile" in configuration
    assert template.startswith("# Wiki Writing Profile")


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
