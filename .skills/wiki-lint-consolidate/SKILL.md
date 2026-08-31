---
name: wiki-lint-consolidate
description: "对 Obsidian wiki 执行完整 lint dry-run，经人工批准后安全应用可自动化的结构维护"
---

# wiki-lint-consolidate

此 skill 直接执行下方从 `workflows/wiki-lint-consolidate.yaml` 同步的完整契约。内嵌 YAML 是实际指令，不是摘要或外部参考；按 `steps`、输入输出、检查、跳转、失败上限和人工审批要求逐项执行。

发生任何冲突时，以内嵌 workflow 契约为准。不要用历史 skill 文案补写、弱化或覆盖它。修改行为时先编辑 workflow，再运行 `python tools/sync_workflow_skills.py`。

<!-- BEGIN GENERATED WORKFLOW CONTRACT -->
````yaml
description: 对 Obsidian wiki 执行完整 lint dry-run，经人工批准后安全应用可自动化的结构维护

auto_reset: true

manual_step:
  - approve_actions

adversarial_check:
  timeout_ms: 3600000
  system_prompt: |
    你是 Wiki Lint Consolidate 的安全审计者。批准前 vault 必须零写入；批准后也只能应用批准清单。
    禁止自动改 base_confidence、合并页面、伪造 provenance，或把 stale 当作 lifecycle 值。

steps:
  - id: audit
    desc: 复用 wiki-lint 完成全量零写入审计
    workflow: wiki-lint
    input: 用户的 wiki-lint --consolidate 请求
    output: lint-context.md/json + structural/semantic findings + wiki-health-report.md + lint-summary.json + lint-completion.md；vault 零写入
    inputs:
      mode: consolidate-dry-run
      record_log: false
      constraint: 完成全部检查与 artifacts 报告，但不得修改包括 log.md 在内的任何 vault 文件
    on_pass: plan_actions
    on_fail: audit
    max_fail_count: 4

  - id: plan_actions
    desc: 从已验证 lint findings 生成零写入 consolidation 计划
    do: |
      读取子 workflow 产出的 lint-context.md/json、structural-findings.json、semantic-findings.json、wiki-health-report.md 与 lint-summary.json；不得重新执行或弱化 lint。

      1. 确认 lint-completion.md 标记 `LINT log skipped: parent dry-run`，并验证 vault 包括 log.md 仍零写入。
      2. 只为以下允许动作形成候选：修复 broken wikilinks、orphan rescue（每个最多 3 处）、符合规则的 lifecycle/callout 更新、tier demotion、taxonomy alias normalization、contradiction callout。不得 merge 页面，不得自动写 base_confidence/trust ledger，不得自动解决矛盾。
      3. 对每项生成稳定 action id、目标、精确 before/after、理由、evidence、风险与受影响文件。无法唯一匹配的 broken link 规划为 plain text + `<!-- unresolved-link: original-target -->` comment；不创建页面。
      4. 写 consolidation-plan.json 和 consolidation-dry-run.md，按编号显示全部 N 个动作以及 `Apply these N changes? [yes / no / select by number]`。若 N=0 也生成明确空计划。
    input: 已验证的 wiki-lint artifacts + vault 零写入证明
    output: consolidation-plan.json + consolidation-dry-run.md；vault 零写入
    check_voting:
      - check: 对照子 workflow 的 lint-summary/findings/report 核对 plan 输入完整，record_log=false 生效且 vault/log.md 零写入
      - check: 逐项验证 consolidation plan 只包含本 workflow 明列的 6 类自动动作，before/after 可复现；没有 confidence 重算、trust-record、page merge/new page、矛盾解决或 human-only transition
      - check: action ids 稳定，N 与计划一致，选择提示清楚且可按编号批准；没有重复执行 lint 或丢失 finding
    on_pass: approve_actions
    on_fail: plan_actions
    max_fail_count: 4

  - id: approve_actions
    desc: 人工确认全部或选定 consolidation 动作
    do: |
      展示 consolidation-dry-run.md 的完整编号清单，生成 approval-request.md。

      此步骤只准备审批，不得写 vault。用户运行 /ralphflow-continue 即表示批准清单中的全部动作；若用户只批准部分编号，先把明确选择写入 approved-actions.json 并重新展示选中项，再等待 /ralphflow-continue；若拒绝，应取消 workflow。

      approved-actions.json 必须绑定 audit_id、plan hash、canonical vault、批准的 action ids、明确排除项和审批时间。不得自行扩大用户选择。准备好后输出 <promise>done</promise>，等待人工门。
    input: consolidation-plan.json + consolidation-dry-run.md + 用户的 yes/no/select 决定
    output: approval-request.md + approved-actions.json（默认等待批准全部；可按用户选择缩小）
    check: |
      确认 approval 与当前 plan hash/audit_id/vault 精确绑定，批准 id 是计划的子集且没有新增动作；用户已通过人工门明确批准。确认截至批准时 vault 仍零写入，且没有把 /continue 解释为 confidence/lifecycle 人工语义审查授权。
    on_pass: apply_actions
    on_fail: approve_actions
    max_fail_count: 3

  - id: apply_actions
    desc: 建立可恢复快照并只应用获批动作
    do: |
      仅执行 approved-actions.json 中的动作。

      1. 写入前按 wiki-lint Safety protocol 判断 vault 是否自身就是 Git root。若是且 dirty，先 `git add -A` + `git commit -m "pre-wiki-lint snapshot"`；若 clean，只记录 HEAD。snapshot 失败则在首次 vault 编辑前停止。若 vault 只是更大 repo 的子目录，静默跳过。
      2. 按固定顺序执行：broken links、orphan cross-references、lifecycle/callout、tier demotion、tag alias、contradiction callouts。每个 orphan 最多 3 个新 incoming links。
      3. 只应用批准清单的 exact before/after；磁盘内容与 plan 前置条件不同时停止该动作并报告 stale plan，不得模糊套用。
      4. 不 merge/create knowledge pages，不更改 base_confidence 或 trust ledger，不把 stale 写成 lifecycle，不执行未批准 action。
      5. 使用 lint-context.json 中 frozen active layout 声明的 `lint_consolidation_report` page type，并以 `--routing lint-context.json` 调用 `resolve_wiki_route.py` 生成报告 target，写入 audit_id/date/scope/actions/results/validation/remaining_findings/rollback 字段和逐类结果；同日已有报告时幂等合并本 audit_id，不能覆盖其他运行。
      6. 追加一条带 audit_id 的 parseable LINT_CONSOLIDATE log；重试不得重复。写 consolidation-apply-report.md，列出 applied/skipped/failed、文件、snapshot SHA 与 diff 摘要。
    input: approved-actions.json + consolidation-plan.json + 最新 vault 状态
    output: 获批 vault 修改 + consolidation report + LINT_CONSOLIDATE log + consolidation-apply-report.md
    check_voting:
      - check: 将实际 diff 与 approved action ids 逐项对账，确认没有越权文件/动作，所有 exact before/after 成立，stale plan 被跳过而非强行应用
      - check: 审计 snapshot protocol、恢复 SHA、report schema、同日幂等合并和唯一 LINT_CONSOLIDATE entry；独立确认未写 base_confidence/trust ledger、未 merge/create knowledge pages、未产生 lifecycle=stale
      - check: 复跑受影响链接、orphan、frontmatter、tag、contradiction 与页面格式检查，确认获批修复有效且未制造新 broken links/schema errors
    on_pass: verify_and_refresh
    on_fail: apply_actions
    max_fail_count: 4

  - id: verify_and_refresh
    desc: 复核最终健康状态并按需刷新 QMD
    do: |
      1. 复跑与所有 applied actions 相关的 lint checks，并执行 vault 正常验证命令；将剩余 findings 与原计划对比，未批准项应继续保留而非伪装解决。
      2. 若 QMD_WIKI_COLLECTION 未设置，记录 skipped；若已设置且 CLI 可用，因为本流程写过 Markdown，运行 `${QMD_CLI:-qmd} update`，仅在提示 vectors stale/missing 时 embed，再用 qmd ls 或针对已改页面的 qmd get 验证。
      3. QMD 失败不回滚 vault，单独报告短错误。
      4. 写 consolidation-completion.md，包含 audit_id、批准/应用/跳过/失败计数、剩余 issues、验证结果、snapshot SHA、consolidation report、log locator 和规定格式的 QMD 状态。完成后输出 <promise>done</promise>。
    input: consolidation-apply-report.md + 最终 vault + QMD 配置
    output: consolidation-completion.md + 可选 QMD refresh
    check_voting:
      - check: 独立复跑 changed-file 与相关 lint/vault validation，确认 completion 的 applied/skipped/remaining 计数及路径与磁盘事实一致
      - check: 核对 snapshot、consolidation report、唯一 log entry 和未批准 findings 保留情况；确认任务可按报告回滚且重试幂等
      - check: QMD 未配置时确实跳过；已配置时 update/embed 条件和验证命令正确，失败被隔离且未回滚 vault
    on_pass: done
    on_fail: verify_and_refresh
    max_fail_count: 4
````
<!-- END GENERATED WORKFLOW CONTRACT -->
