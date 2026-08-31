---
name: cross-linker
description: "发现并写入高置信 Obsidian 页面链接、typed relationships 与 misc affinity，收紧知识图谱"
---

# cross-linker

此 skill 直接执行下方从 `workflows/cross-linker.yaml` 同步的完整契约。内嵌 YAML 是实际指令，不是摘要或外部参考；按 `steps`、输入输出、检查、跳转、失败上限和人工审批要求逐项执行。

发生任何冲突时，以内嵌 workflow 契约为准。不要用历史 skill 文案补写、弱化或覆盖它。修改行为时先编辑 workflow，再运行 `python tools/sync_workflow_skills.py`。

<!-- BEGIN GENERATED WORKFLOW CONTRACT -->
````yaml
description: 发现并写入高置信 Obsidian 页面链接、typed relationships 与 misc affinity，收紧知识图谱

auto_reset: true

adversarial_check:
  timeout_ms: 3600000
  system_prompt: |
    你是 Cross-Linker 的保守审计者。只允许 EXTRACTED/INFERRED 候选落盘，禁止代码块/frontmatter 内正文链接、自链接、重复链接与强行 relationship type。
    写前必须遵守 standalone Git vault snapshot 规则；archive/readout/staging 不属于 live linking scope。

steps:
  - id: resolve_context
    desc: 复用共享子 workflow 解析 linking 上下文
    workflow: wiki-context
    input: linking invocation、run_condition 与当前 CWD
    output: wiki-context.json + wiki-context.md
    inputs:
      requested_keys: OBSIDIAN_VAULT_PATH,OBSIDIAN_LINK_FORMAT,QMD_TRANSPORT,QMD_WIKI_COLLECTION,QMD_CLI_SEARCH_MODE
      optional_reads: owner AGENTS,index,manifest,active layout
      setup_mode: "false"
      run_condition: 若父调用提供 completion/reconciliation gate，则先验证该报告；false 时 context 自身也不得扫描 config/vault
    on_pass: build_registry
    on_fail: resolve_context
    max_fail_count: 3

  - id: build_registry
    desc: 解析 vault 并建立低成本页面词汇表
    do: |
      使用 wiki-context.json 的配置、retrieval order、link format 与 typed relationships。

      1. 若父 workflow 传入 `run_condition`，先只读取其中指定的 completion/reconciliation report，验证条件是否成立。条件不成立时写 `linking-context.md`（mode=skipped、reason、evidence）和空 `page-registry.json`，后续步骤全部 no-op；不得扫描或修改 vault。没有 run_condition 的直接调用默认执行。
      2. 执行模式下使用 context 的 canonical vault、OBSIDIAN_LINK_FORMAT、index.md，并按需只读近期 log.md；不得重新选择 profile。
      3. 只扫描 active layout routing.content_roots 下的 live `.md`，排除 routing.skip_dirs/system_dirs/system_paths；只 grep frontmatter/title/aliases/tags/category/summary，不盲读全 vault。
      4. 建立 page-name/title/alias 到 canonical target 的 registry，标记同名冲突、shortest unambiguous wikilink path、项目归属与当前 incoming/outgoing degree。
      5. 写 page-registry.json 和 linking-context.md；不得修改 vault。
    input: cross-link、连接 orphan 或补齐 wikilink 请求（vault 由 wiki-context 交互式确认）
    output: page-registry.json + linking-context.md
    check_voting:
      - check: 对照 index/frontmatter 抽查 registry 的 path/title/alias/tags/category/summary 和重名消歧准确
      - check: 确认 conditional skip 有明确 evidence 且没有扫描 vault；执行模式的 config/link format、live scope 与 exclusions 正确，未全量读取不相关正文且 vault 无变化
    on_pass: discover_links
    on_fail: build_registry
    max_fail_count: 3

  - id: discover_links
    desc: 按需读取候选页面并评分缺失链接
    do: |
      若 linking-context.md 为 mode=skipped，写空 link-plan.json 与标记同一 reason 的 cross-link-plan.md，不读取页面并直接完成本步骤。

      使用 registry 与近期新增页面优先级发现候选：

      1. 只对 title/summary/tags 表明可能有关的页面读取正文；提取已有 links，并在排除 YAML/code block 后查找未链接 filename/title/alias/entity/concept mentions。
      2. 匹配 case-insensitive、Unicode NFKD diacritic-insensitive；跳过 self/common word/double-link，distinctive name 才可匹配。
      3. 评分：exact +4、shared tags>=2 +2、same project +2、entity/concept +2、cross-category +2、peripheral→hub +2、partial +1。
      4. >=6 标 EXTRACTED，3-5 标 INFERRED，1-2 标 AMBIGUOUS；只规划前两类。为每项选择 first natural inline mention，无法自然内联才 Related。
      5. 从允许的 24 个标准 relationship types 中依据句子语义选最具体方向；不能精确判断则不写 typed relation，不发明 `uses`/`related_to`。
      6. 写 link-plan.json 和 cross-link-plan.md，含 source/target、score/signals/confidence、locator、placement、body link format、typed relationship 或 null。保持 vault 只读。
    input: page-registry.json + 相关页面正文
    output: link-plan.json + cross-link-plan.md
    check_voting:
      - check: skip 模式的计划为空且未读取页面；执行模式重算候选分数和 confidence，确认只含 >=3，exact/semantic/cross-category/hub signals 有正文或 registry 证据
      - check: 检查 self/common/duplicate/code/frontmatter/ambiguous 均排除，inline locator 自然且每个 target 只链接首次合理 mention
      - check: 对 typed relationships 逐项复核标准 type、方向、语境与 target；不能精确分类的确为 null，vault 尚未写入
    on_pass: snapshot_and_apply
    on_fail: discover_links
    max_fail_count: 4

  - id: snapshot_and_apply
    desc: 建立可回退快照并原子应用链接计划
    do: |
      若 linking-context.md 为 mode=skipped，写 cross-link-apply-report.md 标记 no-op，不创建 Git snapshot、不修改 vault。

      执行 cross-linker 的 Pre-write snapshot 与 Apply Links：

      1. canonical 比较 vault 与 `git rev-parse --show-toplevel`；只有 vault 自身是 Git root 才 snapshot。clean repo 记录当前 HEAD；dirty repo 必须 `git add -A` 后成功提交 `pre-cross-linker snapshot`。add/commit 失败则在任何 vault 写入前停止。非 standalone Git vault 静默跳过 snapshot。
      2. 应用 link-plan.json 前重读并校验 source hash/locator，漂移则停止重规划，不能覆盖并发修改。
      3. 普通 body link 按 OBSIDIAN_LINK_FORMAT 写 inline 或现有/新 `## Related`；markdown link 从编辑文件计算相对 `.md` path。typed edge 则始终写 `[[target|label @type]]`，并同步追加 nested `relationships:` 与顶层 type-key quoted-wikilink list，三处均不得重复。
      4. 保留 archive/readout/staging/special files；每页验证 YAML、links、targets、placement、无重复和无意正文改动，并比较三种 typed projection 的 canonical `(target,type)` 集合完全一致。
      5. 写 cross-link-apply-report.md，记录 snapshot SHA/skipped reason、changed pages、links、relations 与 diff。此时不更新 tracking/QMD。
    input: link-plan.json + 最新 live pages + Git 状态
    output: 已验证的 links/relationships + cross-link-apply-report.md
    check_voting:
      - check: skip 模式没有 snapshot/vault diff；执行模式复核 standalone Git root 判定与 snapshot 行为，dirty standalone vault 在写前有有效 commit，clean/non-standalone 分支处理正确
      - check: 将实际 diff 与 plan 逐项对账，检查 link format/relative path、inline/Related placement、首次 mention、并发 hash 与无额外改动
      - check: 验证所有 targets 存在、relationship type/direction 合法、nested/flat-key/inline @type 三种 projection 一致，且无 duplicate/self/code/frontmatter links，tracking/QMD 尚未改变
    on_pass: update_affinity
    on_fail: snapshot_and_apply
    max_fail_count: 4

  - id: update_affinity
    desc: 重算 misc 页面项目亲和度与晋升候选
    do: |
      若 linking-context.md 为 mode=skipped，写空 affinity-report.md 与 cross-link-report.md，保留 skip reason，不读取或修改 misc 页面。

      只处理 misc/ 或 frontmatter `promotion_status: misc` 页面：

      1. 读取 misc 正文收集 outgoing；用 vault grep 收集 incoming；从 linked page path/project frontmatter 确定项目归属。
      2. affinity[project]=incoming+outgoing，去重并确定 score>=3 的 promotion candidates。
      3. 仅在数值变化时更新 misc frontmatter affinity，保留其他字段与正文；验证 YAML 和所有 counts。
      4. 写 affinity-report.md 与 cross-link-report.md，后者列 links/pages/confidence/placement/types、orphans、promotion candidates、skipped scope。
    input: cross-link-apply-report.md + misc pages + page-registry.json
    output: 更新的 misc affinity + affinity-report.md + cross-link-report.md
    check_voting:
      - check: skip 模式保持空报告且 vault 无变化；执行模式对每个 changed misc page 重算 incoming/outgoing 项目计数，确认 affinity 与 score>=3 候选准确
      - check: 检查只改 misc affinity 且报告 link/relation/page/orphan counts 可由实际 vault 重算
    on_pass: record_and_refresh
    on_fail: update_affinity
    max_fail_count: 3

  - id: record_and_refresh
    desc: 幂等记录 Cross-Link 并刷新可选 QMD
    do: |
      1. linking-context.md 为 mode=skipped 时，不写 log/hot、不刷新 QMD，写 cross-link-completion.md 记录 `skipped`、run_condition 与 evidence。
      2. 执行模式从实际 diff 重算 pages_scanned、links_added、typed_relations_written、pages_modified、orphans_remaining、misc_affinity_updated、promotion_candidates。
      3. 执行模式向 log.md 幂等追加带 stable run_id 的 CROSS_LINK；更新 hot.md Recent Activity，保留最近 3 次并更新 timestamp。
      4. 有 live Markdown 修改且 QMD_WIKI_COLLECTION 配置时运行 `${QMD_CLI:-qmd} update`，需要时 embed，并用 ls/get 验证；unset/unavailable/error 单独报告，不回滚 vault。
      5. 写 cross-link-completion.md，若有 snapshot SHA 列出其值与安全回退说明；所有事实与磁盘一致后输出 <promise>done</promise>。
    input: cross-link/affinity reports + log/hot/QMD config
    output: 幂等 CROSS_LINK tracking + cross-link-completion.md + 可选 QMD refresh
    check_voting:
      - check: skip 模式确认 log/hot/QMD/vault 零变化且 reason 可证；执行模式从最终 vault 重算 counts，确认 CROSS_LINK run_id 恰好一次、hot last-3/timestamp 与报告一致
      - check: 验证 QMD guard/update/embed/verify 状态准确，失败未回滚 Markdown；snapshot SHA 如报告则真实存在
      - check: 最终抽查 links、typed relationships、orphans 与 misc candidates 可发现且无 archive/readout/staging 越界写入
    on_pass: done
    on_fail: record_and_refresh
    max_fail_count: 3
````
<!-- END GENERATED WORKFLOW CONTRACT -->
