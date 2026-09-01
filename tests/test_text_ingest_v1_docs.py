from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_lightweight_and_legacy_skills_have_clear_write_ownership():
    folder = (ROOT / "workflows" / "wiki-folder-ingest.yaml").read_text()
    lightweight = (ROOT / ".skills" / "wiki-ingest" / "SKILL.md").read_text()
    document_worker = (ROOT / ".skills" / "wiki-ingest-document" / "SKILL.md").read_text()
    worker = (ROOT / ".skills" / "wiki-source-text" / "SKILL.md").read_text()
    adapter = (ROOT / "workflows" / "wiki-source-text.yaml").read_text()
    integrator = (ROOT / "workflows" / "wiki-packet-integrate.yaml").read_text()

    assert "Coordinator 永远不读取 source body" in folder
    assert "不创建 Job、unit 状态机、Packet" in lightweight
    assert "text-document-commit" in document_worker
    assert "Never edit the ingest-document manifest" in document_worker
    assert "Do not modify `job.json` or any shared file" in worker
    assert "claude -p --dangerously-skip-permissions" in adapter
    assert "直接调用 `/wiki-source-text`" in adapter
    assert "不得更新 index/log/hot/manifest" in integrator
    assert "串行增量 reducer" in integrator


def test_extraction_and_synthesis_guidance_remain_in_the_correct_stage():
    worker = (ROOT / ".skills" / "wiki-source-text" / "SKILL.md").read_text()
    extraction = (
        ROOT / ".skills" / "wiki-source-text" / "references" / "extraction-frame.md"
    ).read_text()
    integrator = (ROOT / "workflows" / "wiki-packet-integrate.yaml").read_text()
    prompts = (
        ROOT / ".skills" / "wiki-packet-integrate" / "references" / "ingest-prompts.md"
    ).read_text()

    for category in ("concepts", "claims", "entities", "relationships", "questions"):
        assert category in worker
    for category in ("concepts", "claims", "entities", "relationships", "questions"):
        assert f'"{category}"' in extraction
    for provenance in ("extracted", "inferred", "ambiguous"):
        assert f"`{provenance}`" in extraction
    assert "Every concept, claim, entity, relationship, and question" in extraction
    assert "Paper Extraction" not in extraction
    assert "canonical topic routing" in integrator
    assert "跨 item synthesis" in integrator
    assert "缺失 cross-reference discovery" in integrator
    assert "## Knowledge routing frame" in prompts
    assert "## Synthesis frame" in prompts
    assert "## Cross-reference discovery frame" in prompts
    for relationship in ("Is-a", "Uses", "Contrasts-with", "Part-of", "Created-by", "Applied-in"):
        assert f"**{relationship}**" in prompts
    assert "Paper Extraction Frame is intentionally absent" in prompts
    assert "do not reconcile with\nother ranges or the wiki" in extraction


def test_recoverable_and_lightweight_ingest_dispatch_differ_intentionally():
    coordinator = (ROOT / "workflows" / "wiki-folder-ingest.yaml").read_text()
    lightweight = (ROOT / ".skills" / "wiki-ingest" / "SKILL.md").read_text()

    assert "obsidian-wiki text-ingest-extract" in coordinator
    assert "claude -p --dangerously-skip-permissions" in coordinator
    assert "直接调用 `/wiki-source-text`" in coordinator
    assert "Job directory、一个 source_id 和当前 unit_id" in coordinator
    assert "worker 不得再派生 subagent" in coordinator
    assert "obsidian-wiki text-document-run" in lightweight
    assert "fresh `claude -p` session" in lightweight
    assert "`/wiki-ingest-document` skill" in lightweight
    assert "一个 `document_id`" in lightweight
    assert "Wiki writes 严格串行" in lightweight


def test_page_writes_staging_and_cross_references_remain_integrated():
    integrator = (ROOT / "workflows" / "wiki-packet-integrate.yaml").read_text()
    policy = (
        ROOT / ".skills" / "wiki-packet-integrate" / "references" / "page-write-policy.md"
    ).read_text()
    stage_commit = (ROOT / "workflows" / "wiki-stage-commit.yaml").read_text()
    coordinator = (ROOT / "workflows" / "wiki-folder-ingest.yaml").read_text()

    assert "direct mode" in integrator
    assert "staged mode" in integrator
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
    assert "units_staged" in integrator
    assert "approved_waiting_order" in stage_commit
    assert "移除 staged_write metadata" in stage_commit
    assert "永久 manifest" in stage_commit
    assert "live validation 成功后" in stage_commit
    assert "父 workflow 不复述或重算 write-mode、unit 状态和计数规则" in coordinator
    assert "awaiting_review" in integrator


def test_source_and_document_completion_boundaries_coexist():
    integrator = (ROOT / "workflows" / "wiki-packet-integrate.yaml").read_text()
    coordinator = (ROOT / "workflows" / "wiki-folder-ingest.yaml").read_text()
    stage_commit = (ROOT / "workflows" / "wiki-stage-commit.yaml").read_text()
    finalizer = (ROOT / "workflows" / "wiki-finalize-sources.yaml").read_text()

    assert "source finalization 由父 coordinator" in integrator
    assert "workflow: wiki-finalize-sources" in coordinator
    assert "workflow: wiki-finalize-sources" in stage_commit
    lightweight = (ROOT / ".skills" / "wiki-ingest" / "SKILL.md").read_text()
    assert "text-document-commit" in lightweight
    assert "wiki-finalize-sources" not in lightweight
    for field in ("content hash", "created", "updated", "live pages", "stats"):
        assert field in finalizer
    for heading in ("Recent Activity", "Active Threads", "Key Takeaways", "Flagged Contradictions"):
        assert heading in finalizer
    assert "最后一个永久 vault write" in finalizer
    assert "manifest-last" in finalizer


def test_llm_wiki_foundation_matches_text_v1_and_live_commit_boundaries():
    foundation = (ROOT / "workflows" / "llm-wiki.yaml").read_text()

    for suffix in (".md", ".markdown", ".mdx", ".txt", ".rst"):
        assert suffix in foundation
    assert "其他格式不能冒充纯文本" in foundation
    assert "PDF deep-dive 仅标为 specialized future/source-adapter contract" in foundation
    assert "PyMuPDF extraction recipe" not in foundation
    assert "wiki-packet-integrate` (URL)" not in foundation
    assert "raw text/chat/log data" not in foundation

    for special_file in ("index.md", "log.md", "hot.md", "manifest"):
        assert special_file in foundation
    assert "direct/staged 边界" in foundation
    assert "manifest-last" in foundation
    assert "QMD 仅在 live commit 后刷新" in foundation


def test_text_ingest_uses_the_effective_relationship_schema_without_legacy_hardcoding():
    foundation = (ROOT / "workflows" / "llm-wiki.yaml").read_text()
    extraction = (
        ROOT / ".skills" / "wiki-source-text" / "references" / "extraction-frame.md"
    ).read_text()
    prompts = (
        ROOT / ".skills" / "wiki-packet-integrate" / "references" / "ingest-prompts.md"
    ).read_text()
    page_contract = (ROOT / "workflows" / "wiki-page-contract.yaml").read_text()
    lint_workflow = (ROOT / "workflows" / "wiki-lint.yaml").read_text()

    assert "standard+owner relationship types" in foundation
    assert "effective allowlist" in page_contract
    assert "effective\n   owner extensions from `llm-wiki/SKILL.md`" in extraction
    assert "effective allowlist in\n`llm-wiki/SKILL.md`" in prompts
    assert "owner schema" in lint_workflow
    assert "relationship types" in lint_workflow


def test_writing_profile_is_resolved_for_ingest_without_overriding_structured_contracts():
    foundation = (ROOT / "workflows" / "llm-wiki.yaml").read_text()
    integrator = (ROOT / "workflows" / "wiki-packet-integrate.yaml").read_text()
    page_policy = (
        ROOT / ".skills" / "wiki-packet-integrate" / "references" / "page-write-policy.md"
    ).read_text()
    setup_workflow = (ROOT / "workflows" / "wiki-setup.yaml").read_text()
    configuration = (ROOT / "docs" / "configuration.md").read_text()
    template = (
        ROOT / ".skills" / "llm-wiki" / "references" / "WRITING.md"
    ).read_text()

    assert "Writing Profile precedence" in foundation
    assert "Writing Profile" in integrator
    assert "不得重新加载或覆盖这些规则" in integrator
    assert "Apply the resolved Writing Profile" in page_policy
    assert "目标已存在时保持原文" in setup_workflow
    assert "## Global wiki writing profile" in configuration
    assert template.startswith("# Wiki Writing Profile")


def test_v1_routing_and_cli_are_documented():
    agents = (ROOT / "AGENTS.md").read_text()
    cli = (ROOT / "docs" / "cli.md").read_text()
    skills = (ROOT / "docs" / "skills.md").read_text()

    assert "`wiki-ingest`" in agents
    assert "text-chunk-plan <source>" in cli
    assert "text-chunk-read <source>" in cli
    assert "Text ingest V1 accepts UTF-8" in skills


def test_pageindex_runtime_configuration_was_removed():
    config = (ROOT / ".env.example").read_text()
    documentation = (ROOT / "docs" / "configuration.md").read_text()
    assert "WIKI_FOLDER_INGEST_MAX_EXTRACTION_WORKERS=4" in config
    assert "WIKI_FOLDER_INGEST_MAX_EXTRACTION_WORKERS" in documentation
    assert "PAGEINDEX_REPO=" not in config
    assert "PAGEINDEX_MODEL=" not in config
