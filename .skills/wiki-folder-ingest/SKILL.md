---
name: wiki-folder-ingest
description: >
  可恢复地发现和规划本地文本来源；小文档 inline 提取，大文档隔离生成 Packet，并按
  source/unit 顺序串行归并到 Obsidian wiki。用于 ingest 或处理本地 .md、.markdown、
  .mdx、.txt、.rst 文件及包含这些文件的目录。
---

# Wiki Folder Ingest

协调本地文本来源的 V1 ingest。此 skill 与 `workflows/wiki-folder-ingest.yaml` 保持行为一致，
但以适合 agent 直接执行的形式表达，不复制 workflow 的重试、跳转、超时和审计器配置。

Coordinator 只持有 metadata 和 artifacts，永远不读取或接收完整 source body。正文读取与
提取属于 `wiki-source-text` 或 `wiki-packet-integrate`；所有 shared wiki writes 由集成与
finalization 阶段串行完成。

## 1. 解析上下文

执行 `wiki-context`，复用其 Config Resolution Protocol、write mode、owner rules、active
Knowledge Profile/Layout 和 writing profile。请求以下配置：

- `OBSIDIAN_VAULT_PATH`
- `WIKI_STAGED_WRITES`
- `OBSIDIAN_LINK_FORMAT`
- `WIKI_FOLDER_INGEST_MAX_EXTRACTION_WORKERS`
- `WIKI_TEXT_DIRECT_EXTRACT_MAX_BYTES`
- `WIKI_TEXT_CHUNK_TARGET_BYTES`
- `WIKI_TEXT_CHUNK_HARD_MAX_BYTES`
- `WIKI_TEXT_CHUNK_MIN_BYTES`
- `WIKI_TEXT_CHUNK_STRATEGY`
- `WIKI_TEXT_CHUNK_OPTIONS`
- `QMD_TRANSPORT`
- `QMD_WIKI_COLLECTION`
- `QMD_CLI_SEARCH_MODE`

输入：用户 invocation、source CWD 与上述配置字段。

输出：`wiki-context.json`、`wiki-context.md`、`text-chunk-options.json`。

## 2. 创建或恢复 Job

输入：`wiki-context.json` 和用户给定的本地文本文件或文件夹。

读取已确认的 vault、write mode 和 text-ingest 配置，然后只运行 package CLI：

```bash
obsidian-wiki text-ingest-plan "<source-root>" \
  --vault "<wiki-context.json vault_path>" \
  --write-mode "<direct-or-staged>" \
  --target-budget "<text_chunking.target_bytes>" \
  --min-budget "<text_chunking.min_bytes>" \
  --hard-budget "<text_chunking.hard_max_bytes>" \
  --direct-extract-max-bytes "<text_ingest.direct_extract_max_bytes>" \
  --chunk-strategy "<text_chunking.strategy>" \
  --strategy-options-file "<artifacts-dir>/text-chunk-options.json" \
  --output "<artifacts-dir>/job-plan.json" \
  --pretty
```

若 console script 不在 `PATH`，使用 `python3 -m obsidian_wiki text-ingest-plan ...`。

CLI 独占 discovery、hash、UTF-8 validation、chunk planning、resume/replan、transport 选择和
Job 原子写入；不要手工复现。Coordinator 只读取 `job-plan.json` 与 Job metadata，不读取
source body。active Knowledge Profile/Layout 必须 matched 且 hashes 完整；URL、缺失或未授权
source 直接失败，unsupported 文件保留在 Job 中。

输出：原子 `job.json` 和 `job-plan.json`。

验收：核对 CLI exit status；确认 `job-plan.json` 指向 vault 内
`_meta/ingest-jobs/<job-id>/job.json`，且 Job 不含 source body。不要重复 hash 或重跑 chunk
plan。

## 3. 冻结页面契约

为整个 Job 执行一次 `wiki-page-contract`，冻结 Knowledge Profile、页面 schema、路由和写入
契约。使用 `transaction_kind: text_ingest_job`，source scope 是当前 Job 的全部 planned
sources/units，且契约不得包含 source body。

输入：`wiki-context.json` 和 `job-plan.json`。

输出：`page-contract.json` 和 `page-contract.md`。

## 4. 处理 units

输入：`wiki-context.json`、`page-contract.json`、已验证的 `job.json`，并按需执行
`wiki-source-text` 与 `wiki-packet-integrate`。

从 `wiki-context.json` 读取 `text_ingest.max_extraction_workers`，默认 4；它是当前 Job 的
Packet extraction 并发硬上限，宿主资源更少时取较小值。运行：

```bash
obsidian-wiki text-ingest-extract "<job-dir>" \
  --max-workers "<text_ingest.max_extraction_workers>" \
  --worker-timeout-seconds 3600 \
  --output "<artifacts-dir>/packet-extraction-report.json" \
  --pretty
```

若 console script 不在 `PATH`，使用 `python3 -m obsidian_wiki text-ingest-extract ...`。

1. Scheduler 恢复时对账所有 packet transport 的 `extracting` unit：已有合法 planned Packet
   的标为 `packet_ready`，否则标为 failed 供本次恢复重试。
2. Scheduler 按稳定 source/unit 顺序动态补满 worker pool；同一文档的多个 packet unit 也可并行提取，
   inline unit 不进入 extraction pool。每个 eligible unit 在一次 invocation 中最多执行一次。
3. Scheduler 原子 claim/completion Job 状态，并给每个 attempt 独立 worker directory，在其中
   映射 package 自带的当前 `wiki-source-text` skill。它用固定
   argv（不用 shell）启动 `claude -p --dangerously-skip-permissions --no-session-persistence
   --disallowed-tools Agent,Task --output-format json`，直接调用 `/wiki-source-text`；危险权限
   只用于已验证 Job 边界内的 worker，Agent/Task tools 被禁用，worker 不得再派生 subagent。
4. 每个 process 只接收 Job directory、一个 `source_id` 和当前 `unit_id`。Scheduler 只依据
   磁盘 planned Packet 的 contract validation 更新 `packet_ready`/failed；stdout、完整 source
   body 和 extracted items 不回流 coordinator。缺少 Claude/skill、timeout 或验证失败均留下
   可恢复 failed unit，不得由 coordinator 降级提取。
5. 可按完成顺序接收 validated Packet 并标为 `packet_ready`；后序 Packet 留在有界缓冲区。
6. 严格按 Job 的 source/unit 全局顺序逐个执行 worker-only `wiki-packet-integrate`。packet
   transport 传入冻结 context/contract、Job 和 Packet；inline transport 传入冻结
   context/contract、Job directory、`source_id` 和 `unit_id`。所有 integration 均不并发。
   较早 unit 未就绪或失败时，暂停后序 integration 并保留已有 Packet。
7. 以 integrator 的 completion report 和最新 Job 为唯一状态转换结果；不要在 coordinator
   中复述或重算 write mode、unit 状态和计数规则。

单 unit 失败时只记录该失败，并安全停在可恢复边界。写 `unit-processing-report.md`，只记录
调度 metadata、skill/integrator handoff、错误和恢复点。

输出：持续原子更新的 Job、Packets、page 或 staged artifacts，以及
`unit-processing-report.md`。

验收：对账 `packet-extraction-report.json`、skill handoff 与最新 Job，确认 argv 包含
`claude -p`、`--dangerously-skip-permissions`、`--no-session-persistence` 和直接
`/wiki-source-text` 调用；task 只含三个允许输入，并发有硬上限、worker directory 单 unit
隔离、无重复派发、无 nested subagent、handoff 不回传 source body/extracted items、integration
全局有序串行且 coordinator 未读取 source body。不要重复验收下游 skill 已负责的内部状态转换。

## 5. Finalize eligible sources

transport integration sweep 完成后执行一次 `wiki-finalize-sources`，提交当前 Job 中所有
eligible sources；partial、staged、failed sources 必须 deferred。使用 `event_type: INGEST`。
读取并遵守 [finalization-policy.md](references/finalization-policy.md)，尤其是 manifest-last
提交边界。

输入：`wiki-context.json`、`page-contract.json`、最新 `job.json` 和全部 transport
integration reports。

输出：`source-finalization-report.md` 和 `source-finalization-report.json`。

## 6. 生成完成报告

输入：最新 `job.json`、permanent manifest 和 `source-finalization-report.json`。

用只读的确定性 CLI 同时生成 JSON 和 Markdown，不手工统计或改写事实：

```bash
obsidian-wiki text-ingest-report "<job-dir>" \
  --output "<artifacts-dir>/job-completion.json" \
  --markdown-output "<artifacts-dir>/folder-ingest-completion.md" \
  --pretty
```

若 console script 不在 `PATH`，使用 `python3 -m obsidian_wiki text-ingest-report ...`。报告应
包含 source/unit 状态、精确恢复点、exact-hash manifest entries、失败信息和
`live_complete`。

输出：`job-completion.json` 和 `folder-ingest-completion.md`。

验收：解析两份报告并对照 Job、manifest 与 finalization report，确认 counts、paths、
failures 和 next action 一致。只有 sources 均为 complete、unchanged 或 unsupported，且所需
exact-hash manifest entries 完整时，`live_complete=true`。

`cross-linker` 只是在 live-complete 后可由用户单独调用的可选后处理；本 skill 不调用它，
也不把它纳入 Job 完成定义。事实一致后输出 `<promise>done</promise>`。
