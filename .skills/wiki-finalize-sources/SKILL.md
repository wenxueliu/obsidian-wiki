---
name: wiki-finalize-sources
description: "在 exact-hash source 完成门成立时统一更新 special files，并以 manifest-last 原子提交一个或多个来源"
---

# wiki-finalize-sources

此 skill 直接执行下方从 `workflows/wiki-finalize-sources.yaml` 同步的完整契约。内嵌 YAML 是实际指令，不是摘要或外部参考；按 `steps`、输入输出、检查、跳转、失败上限和人工审批要求逐项执行。

发生任何冲突时，以内嵌 workflow 契约为准。不要用历史 skill 文案补写、弱化或覆盖它。修改行为时先编辑 workflow，再运行 `python tools/sync_workflow_skills.py`。

<!-- BEGIN GENERATED WORKFLOW CONTRACT -->
````yaml
description: 在 exact-hash source 完成门成立时统一更新 special files，并以 manifest-last 原子提交一个或多个来源

auto_reset: true

adversarial_check:
  timeout_ms: 3600000
  system_prompt: |
    你是 Wiki Source Finalization 的事务审计者。只有 live-complete source 才能推进永久 manifest；manifest 必须是最后写入，partial/staged/rejected source 必须安全 no-op。

steps:
  - id: verify_completion_gate
    desc: 重算每个候选 source 的 exact-hash live completion
    do: |
      1. 对每个 candidate 重读最新 Job/source/units、Packets、staging decisions、live page reports 和 permanent manifest；不得信任父报告中的缓存计数。
      2. eligible 必须同时满足：canonical source 仍对应 exact content hash；全部 planned units 按 source order integrated；所有相关页面 live 且通过页面校验；无 pending/failed/extracting/packet_ready/staged/rejected artifact。
      3. 不满足条件的 candidate 标 deferred，保留 Job/Packet/历史 manifest，写 exact reason 与 next action；绝不把 awaiting_review 当 complete。
      4. 对 eligible source 计算去重 created/updated/live pages、source metadata、兼容 manifest fields 与预期 stats，写 `source-finalization-plan.json/md`。此步骤零写入 vault。
    input: 父 workflow 提供的 candidate Jobs/sources/page reports/event type + 最新 vault state
    output: source-finalization-plan.json + source-finalization-plan.md
    check_voting:
      - check: 从磁盘重算 hash、unit order/status、staging 与 live pages，确认 eligible/deferred 和 next action 准确
      - check: 核对 manifest candidate 保留 unrelated entries/shape/fields，pages 去重且 stats 可复算
      - check: 确认此步骤没有修改 Job、pages、index/log/hot/manifest/QMD
    on_pass: update_special_files
    on_fail: verify_completion_gate
    max_fail_count: 4

  - id: update_special_files
    desc: 为 eligible sources 幂等更新并验证 index、log 与 hot
    do: |
      1. 若 eligible_count=0，写明确 no-op 的 `special-files-report.md` 并保持所有 vault 文件字节不变。
      2. 从实际 live diff 更新 index.md，每页恰好一次，移除本事务制造的重复但保留 unrelated entries 和 owner 格式。
      3. 以父 workflow event_type/run_id 幂等追加一条 parseable log event；重试只校验已有同 id 事件，不重复追加。
      4. 刷新约 500 字 hot.md，保留 `# Hot Cache`、updated、Recent Activity、Active Threads、Key Takeaways、Flagged Contradictions 与最近 3 次 operations；不得把 staged/deferred 内容写成 live。
      5. 所有文件通过 candidate + validation + temporary sibling + atomic replacement 更新。验证 changed pages 与三个 special files；失败时不得继续 manifest commit。
      6. 写 `special-files-report.md/json`，记录 before/after、eligible/deferred sources、events、validation 和写入顺序。
    input: source-finalization-plan + 最新 index/log/hot + 父 workflow event type/run id
    output: 已验证的 index/log/hot（eligible 时）+ special-files-report
    check_voting:
      - check: 从 live pages 重算 index 与 counts，确认每页一次、deferred/staged 不进入 live tracking、unrelated 内容保留
      - check: 核对 log run_id 恰好一次、hot 章节/最近三次/约500字及事实一致性
      - check: 验证 candidate/atomic 顺序；任何 special-file failure 都未推进 manifest
    on_pass: commit_manifest
    on_fail: update_special_files
    max_fail_count: 4

  - id: commit_manifest
    desc: 最后原子提交 manifest 并验证 completeness
    do: |
      1. 若 eligible_count=0，保持 manifest/Job 状态不变并生成 no-op report。
      2. 重读最新 manifest，保留其 list/dict 兼容形态、unrelated entries 和未知字段；合并 eligible source entries，重算 stats。先验证 candidate JSON、pages、index/log/hot 和 source/page counts。
      3. 使用同目录 temporary sibling + fsync/atomic replacement 写 `.manifest.json`；它必须是本事务最后一个永久 vault write。
      4. 对每个 eligible source 运行 `obsidian-wiki verify <source>` 或 package `verify_completeness`；修复 missing_entry/empty_pages/phantom_pages 后才把 source/Job 标 complete。验证失败保留可重试状态，不虚报完成。
      5. 只有 live Markdown 实际变化且 QMD wiki collection 已配置时，在 manifest commit 后运行 update/必要 embed，并用 ls/get 验证；QMD 失败记录 warning，不回滚 source of truth。
      6. 写 `source-finalization-report.md/json`，逐 source 报告 committed/deferred、pages、special files、manifest locator、verify、QMD、warnings 与 next action。事实一致后输出 `<promise>done</promise>`。
    input: finalization plan + special-files report + 最新 manifest/Jobs + QMD config
    output: manifest-last commit（eligible 时）+ source-finalization-report
    check_voting:
      - check: 复核 manifest shape/entries/stats/pages/hash、atomic replacement 和 last-write 顺序；deferred source 无永久推进
      - check: 重跑 verify/completeness，确认 eligible source/Job 仅在全部校验后 complete，失败状态可安全重试
      - check: 核对 QMD guard/update/embed/verification、最终报告和磁盘事实，重试不会重复 index/log/hot/manifest 内容
    on_pass: done
    on_fail: commit_manifest
    max_fail_count: 5
````
<!-- END GENERATED WORKFLOW CONTRACT -->
