---
name: wiki-ingest
description: >
  轻量摄取本地 UTF-8 文本：将每个文件统一规划为独立 ingest documents，并在 fresh sessions
  中直接归并到 Obsidian wiki。用于明确要求轻量、无 Job/Packet 的 ingest；小文档一个 document，
  大文档多个 documents。需要 staged review 或 Job 级恢复时使用 wiki-folder-ingest。
---

# Wiki Ingest

所有支持的源文件通过同一个 chunker 标准化为 ingest documents：文件大小只影响 document 数量，
不改变执行协议。每个 pending document 使用独立模型上下文直接更新 Wiki，验证成功后才在
`.manifest.json` 登记完成。

本 skill 不依赖 workflow，也不创建 Job、unit 状态机、Packet、extraction dump 或 source-body
中间文档。document 是独立执行输入，但不是 Wiki 页面边界；页面仍按 canonical topic
existing-first 归并。

## Resolve context

遵循 Config Resolution Protocol 解析 canonical vault，并读取 vault 的 `AGENTS.md`。取得 write
mode、link format、Knowledge Profile/Layout、Writing Profile、taxonomy 和文本 chunk 配置：

- `WIKI_TEXT_CHUNK_TARGET_BYTES`
- `WIKI_TEXT_CHUNK_HARD_MAX_BYTES`
- `WIKI_TEXT_CHUNK_MIN_BYTES`
- `WIKI_TEXT_CHUNK_STRATEGY`
- `WIKI_TEXT_CHUNK_OPTIONS`

将冻结结果写到临时 artifacts directory 的 `wiki-context.json`，将 chunk options 写为
`text-chunk-options.json`。轻量模式只执行 direct writes；若 resolved write mode 是 staged，停止
并建议改用 `wiki-folder-ingest`，不能把 staged artifact 记录为 complete document。

## Plan ingest documents

运行确定性 Python CLI：

```bash
obsidian-wiki text-document-plan "<source-root>" \
  --vault "<canonical-vault>" \
  --target-budget "<text_chunking.target_bytes>" \
  --min-budget "<text_chunking.min_bytes>" \
  --hard-budget "<text_chunking.hard_max_bytes>" \
  --chunk-strategy "<text_chunking.strategy>" \
  --strategy-options-file "<artifacts-dir>/text-chunk-options.json" \
  --output "<artifacts-dir>/document-plan.json" \
  --pretty
```

若 console script 不在 PATH，使用 `python3 -m obsidian_wiki ...`。CLI 独占 discovery、UTF-8
校验、当前 chunker 分片、stable document identity 和 manifest 去重。小文件必须产生一个
document，大文件产生多个；计划只含 source path/hash、heading 和 line/byte range，不含正文。

核对计划版本、vault、完整范围覆盖、document id 唯一性与 pending/unchanged 计数，并确认没有在
vault 中产生 `_meta/ingest-jobs`、Packet 或 source-body artifact。

## Process documents

运行：

```bash
obsidian-wiki text-document-run "<artifacts-dir>/document-plan.json" \
  --context "<artifacts-dir>/wiki-context.json" \
  --worker-timeout-seconds 3600 \
  --output "<artifacts-dir>/document-session-report.json" \
  --pretty
```

Runner 按稳定计划顺序为每个 pending document 启动一个 fresh `claude -p` session，直接调用内部
`/wiki-ingest-document` skill。每个 session 只收到 plan path、一个 `document_id` 和 frozen
context path；通过 `text-document-read` 读取唯一范围，把它作为完整独立文档处理。Sessions 不共享
source body 或模型上下文；Wiki writes 严格串行，避免相同 canonical page 的并发覆盖。

Worker existing-first 归并并验证页面，更新 `index.md`、`log.md`、`hot.md`，最后调用
`text-document-commit` 原子写 manifest。失败 worker 不写 document record，下次 invocation 自然
重试。不要手工写 manifest，也不要因为 document 独立而机械创建一 document 一页面。

## Report

依据 `document-plan.json`、`document-session-report.json` 和 permanent manifest 报告 source/document
总数、manifest skipped、complete、failed、created/updated pages 与失败 document ids。只有所有
pending documents 均有 exact-binding complete record 才报告完成。事实一致后输出
`<promise>done</promise>`。
