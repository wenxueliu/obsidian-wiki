---
name: wiki-folder-ingest
description: "可恢复地发现和规划本地文本来源；小文档 inline 提取，大文档隔离生成 Packet，并按 source/unit 顺序串行归并到 Obsidian wiki"
---

# wiki-folder-ingest

此 skill 直接执行下方从 `workflows/wiki-folder-ingest.yaml` 同步的完整契约。内嵌 YAML 是实际指令，不是摘要或外部参考；按 `steps`、输入输出、检查、跳转、失败上限和人工审批要求逐项执行。

发生任何冲突时，以内嵌 workflow 契约为准。不要用历史 skill 文案补写、弱化或覆盖它。修改行为时先编辑 workflow，再运行 `python tools/sync_workflow_skills.py`。

<!-- BEGIN GENERATED WORKFLOW CONTRACT -->
````yaml
description: 可恢复地发现和规划本地文本来源；小文档 inline 提取，大文档隔离生成 Packet，并按 source/unit 顺序串行归并到 Obsidian wiki

auto_reset: true

adversarial_check:
  timeout_ms: 3600000
  system_prompt: |
    你是 Wiki Folder Ingest coordinator 的审计者。Coordinator 只能持有 metadata 和 artifacts，不能读取或接收完整 source body。
    严格检查路径边界、Job 原子性、单位顺序、direct/staged 状态隔离和 permanent manifest 的完成边界。

steps:
  - id: resolve_context
    desc: 复用共享子 workflow 解析 vault、write mode 与 owner 规则
    workflow: wiki-context
    input: 用户 invocation、source CWD 与所需配置字段
    output: wiki-context.json + wiki-context.md + text-chunk-options.json
    inputs:
      requested_keys: OBSIDIAN_VAULT_PATH,WIKI_STAGED_WRITES,OBSIDIAN_LINK_FORMAT,WIKI_FOLDER_INGEST_MAX_EXTRACTION_WORKERS,WIKI_TEXT_DIRECT_EXTRACT_MAX_BYTES,WIKI_TEXT_CHUNK_TARGET_BYTES,WIKI_TEXT_CHUNK_HARD_MAX_BYTES,WIKI_TEXT_CHUNK_MIN_BYTES,WIKI_TEXT_CHUNK_STRATEGY,WIKI_TEXT_CHUNK_OPTIONS,QMD_TRANSPORT,QMD_WIKI_COLLECTION,QMD_CLI_SEARCH_MODE
      optional_reads: owner AGENTS,taxonomy,index,manifest,active layout,writing profile
      setup_mode: "false"
    on_pass: plan_job
    on_fail: resolve_context
    max_fail_count: 3

  - id: plan_job
    desc: 用确定性 CLI 发现文档并原子创建或恢复 Job
    do: |
      读取 `wiki-context.json` 中已确认的 vault、write mode 和 text-ingest 配置，然后只运行 package CLI：

      ```bash
      obsidian-wiki text-ingest-plan "<source-root>" \
        --vault "<wiki-context.json vault_path>" \
        --write-mode "<direct-or-staged>" \
        --target-budget "<text_chunking.target_bytes>" \
        --min-budget "<text_chunking.min_bytes>" \
        --hard-budget "<text_chunking.hard_max_bytes>" \
        --direct-extract-max-bytes "<text_ingest.direct_extract_max_bytes>" \
        --chunk-strategy "<text_chunking.strategy>" \
        --strategy-options-file "{{artifacts_dir}}/text-chunk-options.json" \
        --output "{{artifacts_dir}}/job-plan.json" \
        --pretty
      ```

      CLI 独占 discovery、hash、UTF-8 validation、chunk planning、resume/replan、transport 选择和 Job 原子写入规则；coordinator 不手工复现。Coordinator 只读取 `job-plan.json` 与 Job metadata，不读取 source body。active Knowledge Profile/Layout 必须 matched 且 hashes 完整；URL、缺失或未授权 source 直接失败，unsupported 文件保留在 Job 中。若 console script 不在 PATH，使用 `python3 -m obsidian_wiki text-ingest-plan ...`。
    input: wiki-context.json + 用户给定的本地文本文件或文件夹
    output: 原子 job.json + job-plan.json
    check: 核对 CLI exit status、job-plan.json 指向 vault 内 `_meta/ingest-jobs/<job-id>/job.json`，且 Job 不含 source body；不要重复 hash 或重跑 chunk plan
    on_pass: resolve_job_page_contract
    on_fail: plan_job
    max_fail_count: 4

  - id: resolve_job_page_contract
    desc: 为整个 Job 冻结一次 Knowledge Profile、页面 schema、路由和写入契约
    workflow: wiki-page-contract
    input: wiki-context.json + job-plan.json
    output: page-contract.json + page-contract.md
    inputs:
      transaction_kind: text_ingest_job
      source_scope: 当前 Job 的全部 planned sources/units；契约不包含 source body
    on_pass: process_documents
    on_fail: resolve_job_page_contract
    max_fail_count: 3

  - id: process_documents
    desc: 小文档 inline 集成，大文档有界并行提取 Packet，并按 Job 顺序串行集成
    do: |
      Coordinator 永远不读取 source body。读取 `wiki-context.json` 的 `text_ingest.max_extraction_workers`（默认 4），把它作为当前 Job 的 Packet extraction 并发硬上限；宿主可用槽位更少时使用较小值。恢复 Job 时先对账所有 packet transport 的 `extracting` unit：已有合法 planned Packet 的标为 `packet_ready`，否则标为 failed 供重试，避免陈旧 claim 占用并发额度。按稳定 source discovery order 和 unit order 建立全 Job 队列，同一文档的多个 packet unit 也可并行提取。每轮只领取 packet transport 的 pending/failed unit，最多达到该并发上限，并在一次原子 Job 更新中标为 `extracting`；inline unit 不进入 extraction wave，也不生成 Packet。

      每个 extraction subagent 只获得 Job directory、一个 source_id 和当前 unit_id，并以 bare workflow name 调用 `wiki-source-text`。以该子 workflow 的 validated Packet 或失败报告为唯一 handoff；coordinator 不重复其 range 读取、extraction 或 Packet contract。

      Coordinator 可按完成顺序接收 validated Packet 并标为 `packet_ready`，后序 Packet 留在有界缓冲区。然后严格按 Job 的 source/unit 全局顺序，以 bare workflow name 逐个调用 worker-only `wiki-packet-integrate`；packet transport 传入冻结 context/contract、Job 和 Packet，inline transport 传入冻结 context/contract、Job directory、source_id 和 unit_id。以 integrator 的 completion report 和最新 Job 为唯一状态转换结果；父 workflow 不复述或重算 write-mode、unit 状态和计数规则。所有 integration 均不并发；较早 unit 未就绪或失败时暂停后序 integration并保留已有 Packet。

      单 unit 失败只记录该失败并安全停止在可恢复边界；无 subagent 能力时保留 next unit 为 pending。写 `unit-processing-report.md`，只记录调度 metadata、子 workflow handoff、错误和恢复点。
    input: wiki-context.json + page-contract.json + 已验证 job.json；动态调用 wiki-source-text 与 wiki-packet-integrate
    output: 持续原子更新的 Job/Packets/page-or-staged artifacts + unit-processing-report.md
    check: 对账调度报告、子 workflow handoff 与最新 Job，确认并发上限、单 unit 隔离、无重复派发、integration 全局有序串行且 coordinator 未读取 source body；不重复验收子 workflow 内部状态转换
    on_pass: finalize_completed_sources
    on_fail: process_documents
    max_fail_count: 10

  - id: finalize_completed_sources
    desc: transport integration sweep 后一次性提交所有 live-complete sources
    workflow: wiki-finalize-sources
    input: wiki-context.json + page-contract.json + 最新 job.json + 全部 transport integration reports
    output: source-finalization-report.md + source-finalization-report.json
    inputs:
      event_type: INGEST
      candidate_scope: 当前 Job 中全部 eligible sources；partial/staged/failed sources 必须 deferred
    on_pass: report_completion
    on_fail: finalize_completed_sources
    max_fail_count: 5

  - id: report_completion
    desc: 用确定性 CLI 生成 Job 完成事实与可恢复报告
    do: |
      用只读的确定性 CLI 从最新 Job 与 permanent manifest 同时生成 JSON 和 Markdown 报告，不由 agent 手工统计或改写事实：

      ```bash
      obsidian-wiki text-ingest-report "<job-dir>" \
        --output "{{artifacts_dir}}/job-completion.json" \
        --markdown-output "{{artifacts_dir}}/folder-ingest-completion.md" \
        --pretty
      ```

      报告包含 source/unit 状态、精确恢复点、exact-hash manifest entries、失败信息和 `live_complete`。`cross-linker` 仅作为 live-complete 后可单独调用的可选后处理，当前 workflow 不调用它，也不把它的结果纳入 Job 完成定义。若 console script 不在 PATH，使用 `python3 -m obsidian_wiki text-ingest-report ...`。事实一致后输出 <promise>done</promise>。
    input: 最新 job.json + permanent manifest + source-finalization-report.json
    output: job-completion.json + folder-ingest-completion.md
    check: 解析两份报告并对照 Job、manifest 与 finalization report，确认 counts/paths/failures/next action 一致，只有 complete/unchanged/unsupported 且所需 exact-hash manifest entries 完整时 live_complete=true；确认本步骤和整个 ingest workflow 均未调用 cross-linker
    on_pass: done
    on_fail: report_completion
    max_fail_count: 4
````
<!-- END GENERATED WORKFLOW CONTRACT -->
