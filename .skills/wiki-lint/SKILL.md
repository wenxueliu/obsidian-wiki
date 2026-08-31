---
name: wiki-lint
description: "只读审计 Obsidian wiki 的结构、schema、链接、来源与知识图谱健康度，并记录可复核报告"
---

# wiki-lint

此 skill 直接执行下方从 `workflows/wiki-lint.yaml` 同步的完整契约。内嵌 YAML 是实际指令，不是摘要或外部参考；按 `steps`、输入输出、检查、跳转、失败上限和人工审批要求逐项执行。

发生任何冲突时，以内嵌 workflow 契约为准。不要用历史 skill 文案补写、弱化或覆盖它。修改行为时先编辑 workflow，再运行 `python tools/sync_workflow_skills.py`。

<!-- BEGIN GENERATED WORKFLOW CONTRACT -->
````yaml
description: 只读审计 Obsidian wiki 的结构、schema、链接、来源与知识图谱健康度，并记录可复核报告

auto_reset: true

adversarial_check:
  timeout_ms: 3600000
  system_prompt: |
    你是 Wiki Lint 的只读审计者。除最终步骤可幂等追加一条 LINT 日志外，不得修改 vault。
    严格依据解析后的 owner schema、实际文件与命令输出复核，不能为减少 findings 而放宽规则。

steps:
  - id: resolve_context
    desc: 复用共享子 workflow 解析 lint 配置与 owner metadata
    workflow: wiki-context
    input: lint invocation 与当前 CWD
    output: wiki-context.json + wiki-context.md
    inputs:
      requested_keys: OBSIDIAN_VAULT_PATH,OBSIDIAN_ALLOWED_LIFECYCLES,OBSIDIAN_ALLOWED_RELATIONSHIP_TYPES,OBSIDIAN_REQUIRED_TRUST_FIELDS,OBSIDIAN_SCHEMA_SOURCE
      optional_reads: owner AGENTS,index,manifest,active layout
      setup_mode: "false"
    on_pass: build_lint_context
    on_fail: resolve_context
    max_fail_count: 3

  - id: build_lint_context
    desc: 解析 vault、owner schema 与审计边界
    do: |
      使用 wiki-context.json 建立本次审计的权威上下文。

      1. 使用 context 的 canonical vault、retrieval order、owner schema、provenance、confidence/lifecycle、typed relationship allowlists 与 status=matched 的 active layout；不得重新解释配置。layout 不 matched 时停止审计并要求 repair/migration。
      2. 形成 effective schema，记录 schema source、required/optional frontmatter、lifecycle、relationship types、trust fields 与 provenance markers；owner 扩展和放宽优先，不能强制改回 framework 默认。
      4. 清理并验证 OBSIDIAN_ALLOWED_LIFECYCLES、OBSIDIAN_ALLOWED_RELATIONSHIP_TYPES、OBSIDIAN_REQUIRED_TRUST_FIELDS、OBSIDIAN_SCHEMA_SOURCE。空白值或空列表项 fail closed。
      5. 读取 index.md 与 log.md，并从 active layout routing.content_roots 建立页面 inventory。所有检查排除 routing.skip_dirs/system_dirs/system_paths；staging role 不算 live knowledge page。
      6. 在产出目录写 lint-context.md 和 lint-context.json，包含 canonical vault path、配置来源、effective schema、active layout name/version/hashes/完整 routing、排除项、页面数量、index/log 状态、审计时间与稳定 audit_id。此步骤不得修改 vault。
    input: 用户任务（vault 由 wiki-context 交互式确认；默认等价于 wiki-lint --check）
    output: lint-context.md + lint-context.json（vault、effective schema、active routing、scope、inventory、audit_id）
    check: |
      独立复核 lint-context.md 与配置、vault/AGENTS.md、index.md、log.md。确认 config precedence、schema precedence、空值 fail-closed 和排除目录准确；schema source 与传给后续 deterministic checks 的参数一致；没有修改任何 vault 文件。任一不符即失败。
    on_pass: structural_audit
    on_fail: build_lint_context
    max_fail_count: 3

  - id: structural_audit
    desc: 执行确定性的结构、链接、schema 与 trust 检查
    do: |
      基于 lint-context.md，按共享 context 的 retrieval order 从 index/frontmatter/rg 开始执行以下确定性检查：

      - 1 Orphaned Pages；2 Broken Wikilinks；3 Missing Frontmatter；3a Missing Summary（仅 soft warning）
      - 4 Stale Content；6 Index Consistency；8 Fragmented Tag Clusters；9 Visibility Tag Consistency
      - 10 Misc Promotion Candidates；12 Confidence and Lifecycle Schema；13 Typed Relationships Validity

      明确执行要求：
      1. 解析 wikilink 的 path、heading、alias，并以 live vault inventory 校验；index.md/log.md 不算 orphan。
      2. frontmatter 检查必须锚定文件头；summary 缺失/超过 200 字符是 soft finding。
      3. tag cohesion 仅检查 n>=5 且阈值 <0.15；visibility/ 为 system tags，不应出现在 taxonomy。
      4. 用 effective schema 的显式 CLI flags/env 运行 deterministic validator；执行 `obsidian-wiki trust-check "$OBSIDIAN_VAULT_PATH" --strict --json --pretty`。保存真实退出码和 JSON。不得运行 trust-record，不得从 source 字符串自动重算 base_confidence。
      5. 校验 lifecycle、base_confidence、computed stale overlay、supersession cycle/target/state、trust ledger reviewed/stale/unreviewed/mismatch/errors，以及 typed relationship type/target/self-reference。
      6. 每条 finding 记录稳定 id、类别、severity、vault-relative path、locator、evidence、effective rule；不得修复 vault。
      7. 在产出目录写 structural-findings.json 和 structural-audit.md，包含逐类计数、命令、退出码、schema block 与 warnings。
    input: lint-context.md + vault 的 index/frontmatter/link/source metadata
    output: structural-findings.json + structural-audit.md
    check_voting:
      - check: 复跑 inventory、orphan、broken link、frontmatter、summary、index、tag cluster、visibility、misc promotion 与 relationship checks，核对 findings 和计数，没有漏扫或误扫排除目录
      - check: 复跑 strict trust-check 并核对 JSON schema block、退出码、ledger errors/mismatches/stale/unreviewed、lifecycle/base_confidence/supersession；确认没有自动重算 confidence 或运行 trust-record
      - check: 审计只读性、locator 与 severity：除 artifacts 外 vault 无变化，soft summary/stale warnings未错误升级，所有 finding 都有可复现 evidence
    on_pass: semantic_audit
    on_fail: structural_audit
    max_fail_count: 4

  - id: semantic_audit
    desc: 聚焦相关页面执行矛盾、provenance 与 synthesis gap 审计
    do: |
      执行 Contradictions、Provenance Drift 与 Synthesis Gaps 三类语义审计。

      1. 只从 shared tags、高 incoming-link、relationships 或共现候选中选相关页；先 grep section/claim context，只有不足时才读整页。
      2. 区分已通过 ^[ambiguous]、Open Questions、Debate 或 contradiction callout 明示的分歧与未标注冲突。逐条保存双方 claim、locator 与 source/provenance。
      3. 对存在 provenance block 或 markers 的页面按句子/项目符号粗算 extracted/inferred/ambiguous；应用 ambiguous>15%、无 sources 且 inferred>40%、top-10 hub inferred>20%、任一声明比例 drift>0.20。无 block 且无 marker 的页面按 fully extracted 跳过。
      4. 从 active layout routing 声明的 concept/entity 内容根中选择 10-15 个高频链接，两两计算共同出现页面；仅报告 co-occurrence>=3 且对应 synthesis route 下不存在页面的 gap，不假定 default layout 目录名。
      5. 在产出目录写 semantic-findings.json 和 semantic-audit.md。每条 finding 使用与 structural findings 相同的稳定 schema，并标明事实、推断和不确定性。不得修改 vault。
    input: lint-context.md + structural findings + 相关页面的局部正文
    output: semantic-findings.json + semantic-audit.md
    check_voting:
      - check: 独立抽样复核 contradictions，确认双方原文/locator 存在，已承认矛盾与未承认矛盾区分准确，没有把措辞差异伪装为事实冲突
      - check: 重算 provenance 分母、marker 数、hub 排名和四个阈值，核对 drift 与 severity；未带 provenance/marker 的页面确实跳过
      - check: 重算 synthesis pair 共现和已有 synthesis coverage，确认候选集 10-15 个且每个报告 gap 达到 >=3；确认仅按需读取相关正文且 vault 未修改
    on_pass: render_report
    on_fail: semantic_audit
    max_fail_count: 4

  - id: render_report
    desc: 汇总完整 Wiki Health Report
    do: |
      将 structural-findings.json 与 semantic-findings.json 去重合并，在产出目录写 wiki-health-report.md 和 lint-summary.json。

      报告采用固定结构，逐节给出：orphans、broken links、missing frontmatter、stale、contradictions、index issues、missing summary（soft）、provenance、fragmented clusters、visibility、promotion candidates、confidence/lifecycle、typed relationships、synthesis gaps。每节即使为 0 也保留计数。

      lint-summary.json 必须包含 audit_id、canonical vault、schema source、mode=check、每类 counts、issues_found 总数、hard_errors、warnings、soft_warnings、trust-check 状态、扫描页数、排除项、命令与生成时间。issues_found 的计数口径必须明确且可由 findings 重算。

      只给修复建议并说明 `wiki/wiki-lint-consolidate` 可处理允许自动修复的子集；不要在此步骤修改 vault 或刷新 QMD。
    input: lint-context.md + structural/semantic findings
    output: wiki-health-report.md + lint-summary.json
    check_voting:
      - check: 从两个 findings JSON 重算每节和总计，确认报告无遗漏、无重复、severity 与 soft warning 口径一致，所有路径和 locator 可定位
      - check: 对照 wiki-lint Output Format、effective schema 与 trust-check 结果，确认 13 类检查均有呈现，修复建议没有越过 human-only lifecycle/confidence 边界
      - check: 确认 report/summary 只写 artifacts，未修改 vault，未运行 QMD；报告清楚区分事实 findings、语义判断与建议
    on_pass: record_lint
    on_fail: render_report
    max_fail_count: 3

  - id: record_lint
    desc: 幂等记录 LINT 操作并完成审计
    do: |
      只有 render_report 已通过独立验证后，才处理 LINT tracking。

      1. 默认 `record_log=true`：使用 lint-summary.json 的 audit_id 和计数，写入 wiki-lint 规定的字段，并补充 lifecycle_issues、relationship_issues。
      2. 当父 workflow 通过 inputs 明确传入 `record_log=false`（例如 wiki/wiki-lint-consolidate 的 dry-run）时，保持 vault/log.md 字节不变，并在 completion 记录 `LINT log skipped: parent dry-run`。该输入只抑制日志，不能跳过任何审计或报告。
      3. record_log=true 时保持 log.md append-only；重试时若同一 audit_id 已存在则校验或原位修正该条，不得重复追加。
      4. 不修改任何知识页、index.md、hot.md、manifest、trust ledger 或 taxonomy。check 模式不刷新 QMD。
      5. 在产出目录写 lint-completion.md，记录报告路径、日志 locator/skipped、计数、schema source、trust 状态、warnings 与 `QMD skipped: read-only lint`。完成后输出 <promise>done</promise>。
    input: 已验证的 wiki-health-report.md + lint-summary.json + vault/log.md
    output: 一条幂等 LINT log 记录 + lint-completion.md
    check: |
      record_log=true 时复核 log.md 中该 audit_id 恰好一次，字段可解析且计数与 lint-summary.json 完全一致；record_log=false 时确认 log.md 字节不变且 completion 明确记录 parent dry-run。除允许的 log.md 和 artifacts 外 vault 无变化；没有刷新 QMD 或改写 trust ledger。确认 completion 指向真实报告和日志状态。任一不符即失败。
    on_pass: done
    on_fail: record_lint
    max_fail_count: 3
````
<!-- END GENERATED WORKFLOW CONTRACT -->
