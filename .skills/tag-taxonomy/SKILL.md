---
name: tag-taxonomy
description: "审计、规范化或扩展 Obsidian wiki 的受控标签词表，并安全维护 tracking 与可选 QMD 索引"
---

# tag-taxonomy

此 skill 是 `workflows/tag-taxonomy.yaml` 的 Agent Skill 格式投影；workflow 是行为事实来源，本文件把其字段渲染为可直接执行的 Markdown 指令。

<!-- BEGIN GENERATED SKILL INSTRUCTIONS -->

## 执行规则

按下列步骤和流程控制执行。每个步骤只读取其声明的输入，只产生其声明的产出；执行与独立验收分开进行。修改行为时先编辑权威 workflow，再运行 `python tools/sync_workflow_skills.py`。

- 自动重置：开启。

- 人工审批步骤：`approve_changes`。

## 独立验收规则

你是 Tag Taxonomy 的审计者。_meta/taxonomy.md 是 canonical vocabulary，visibility/* 是独立系统标签。
未经人工门批准不得改标签或 taxonomy；未知标签不能自动猜映射，知识页最多 5 个普通标签。

单次验收超时：`3600000` 毫秒。

## 工作流

### 1. 复用共享子 workflow 解析 taxonomy 上下文 (`resolve_context`)

#### 执行

调用 `wiki-context` skill，并把下列输入传给它。以被调用 skill 的验收结果作为本步骤结果。

#### 输入

taxonomy invocation 与当前 CWD

调用参数：

- `requested_keys`: OBSIDIAN_VAULT_PATH,QMD_TRANSPORT,QMD_WIKI_COLLECTION,QMD_CLI_SEARCH_MODE

- `optional_reads`: owner AGENTS,taxonomy,index,manifest,active layout

- `setup_mode`: false

#### 产出

wiki-context.json + wiki-context.md

#### 验收

采用被调用 skill 的验收结论，不在本步骤重复验收。

#### 流程控制

- 验收通过：转到 `audit_tags`。

- 验收失败：返回 `resolve_context`。

- 最多连续失败 `3` 次；达到上限后停止并报告阻塞。

### 2. 解析词表并生成全 vault 标签审计 (`audit_tags`)

#### 执行

使用 wiki-context.json 解析后的 vault 与 canonical taxonomy。

1. 使用 context 的 canonical vault、_meta/taxonomy.md 和 index.md；不得重新选择 profile。
2. 只扫描 active layout routing.content_roots 下的 live `.md`，排除 routing.skip_dirs/system_dirs/system_paths；从 YAML frontmatter 提取 tags，不把正文 hashtag 当标签。
3. 建立频率表并识别 canonical、alias、unknown、>5 普通标签、untagged；visibility/public|internal|pii 单独统计，不计 5-tag 限额，不受 alias mapping，且每页最多一个。
4. 识别用户模式：audit、normalize、tag-new-page、add-tag；所有模式先完成审计。
5. 写 tag-audit-report.md 和 tag-inventory.json，包含逐页 locator、counts 与配置来源。不得修改 vault。

#### 输入

标签审计、规范化、新页面选标签或新增 canonical tag 请求

#### 产出

tag-audit-report.md + tag-inventory.json

#### 验收

1. 对照 taxonomy 重算 canonical/alias/unknown/over-tagged/untagged，确认 frontmatter-only 与排除目录准确

2. 独立核对 visibility 统计和规则：不计普通标签上限、不当 unknown、不被 normalization 改写且每页至多一个

3. 确认审计只写 artifacts，vault/taxonomy/index/log/hot/QMD 无变化

#### 流程控制

- 验收通过：转到 `plan_changes`。

- 验收失败：返回 `audit_tags`。

- 最多连续失败 `3` 次；达到上限后停止并报告阻塞。

### 3. 形成确定性标签变更或只读报告计划 (`plan_changes`)

#### 执行

基于用户模式和 tag-inventory.json 先在内存中形成唯一 canonical tag change plan result；`tag-change-plan.json` 完整承载该 result，Markdown 只从同一 result 渲染、不得独立推导或补充事实，并在同一批 artifact 写入中提交二者。

1. audit 模式生成 empty write plan，仅保留报告。
2. normalize 模式只自动规划 taxonomy 明示的 alias→canonical；去重并保证普通标签<=5，超限时列出保留/删除理由。
3. unknown 用于 2+ pages 时仅建议新增，单页仅建议最接近 canonical；在用户明确同意前不得纳入写计划。
4. tag-new-page 选择最多 5 个 canonical 普通标签：1-2 domain、1 type、可选 project/descriptor；保留合法 visibility。
5. add-tag 先证明现有词表不能覆盖，再给 section、definition、aliases 和受影响页面。
6. 每项记录 before/after、路径、taxonomy evidence、是否需人工选择和 stable plan_id。保持 vault 只读。

#### 输入

tag-audit-report.md + tag-inventory.json + 用户意图

#### 产出

tag-change-plan.md + tag-change-plan.json

#### 验收

1. 逐项对照 taxonomy 确认 alias mapping 精确、canonical tags 合法、普通标签去重且不超过 5

2. unknown/new tag 没有被自动决定，tag selection 的 domain/type/project 配额合理，visibility 完整保留

3. 解析 tag change plan JSON，逐项核对 Markdown 的 plan_id、mode、before/after、paths、evidence、decisions 与 warnings 是同一 canonical result 的准确投影；audit 模式 write plan 严格为空，所有模式尚未修改 vault

#### 流程控制

- 验收通过：转到 `approve_changes`。

- 验收失败：返回 `plan_changes`。

- 最多连续失败 `3` 次；达到上限后停止并报告阻塞。

### 4. 人工确认标签页面与 taxonomy 的精确变更集 (`approve_changes`)

#### 执行

展示 tag-change-plan.md 的所有 before/after、unknown 决策与 taxonomy additions。

把用户选择写入 approved-tag-plan.json，绑定 plan_id、plan hash、canonical vault、mode、page edits 和 taxonomy edits。audit 模式绑定明确 no-op；拒绝则取消。输出 <promise>done</promise> 后等待人工门，批准前不得修改 vault 或刷新 QMD。

#### 输入

tag-change-plan.md + 用户 accept/reject/select 决策

#### 产出

approved-tag-plan.json（绑定 plan hash 的批准或 no-op）

#### 验收

确认 approved plan 是原计划子集，所有 unknown/new taxonomy 决定均有明确用户选择，vault 与 hash 匹配；人工门之前没有 vault 写入。

#### 流程控制

- 验收通过：转到 `apply_tags`。

- 验收失败：返回 `approve_changes`。

- 最多连续失败 `3` 次；达到上限后停止并报告阻塞。

### 5. 应用获批标签并验证 frontmatter 与词表 (`apply_tags`)

#### 执行

只执行 approved-tag-plan.json；audit/no-op 模式不写 vault。

1. 修改前读取最新页面与 taxonomy；若 before/hash 已漂移，停止并回到重规划，不覆盖并发修改。
2. 只改 YAML tags 字段与明确批准的 _meta/taxonomy.md 条目，保留 frontmatter 顺序、正文和无关字段。
3. 对每页验证普通标签均 canonical、去重且<=5，visibility 合法且至多一个；taxonomy additions 位于正确 section，alias 无冲突。
4. 写 tag-apply-report.md 和实际 diff/counts；此时不得更新 log/hot 或 QMD。

#### 输入

approved-tag-plan.json + 最新 pages/taxonomy

#### 产出

获批的标签/taxonomy edits + tag-apply-report.md，或 audit no-op

#### 验收

1. 将实际 diff 与 approved plan 逐项对账，确认无越权、无并发覆盖，正文及其他 frontmatter 字段未改变

2. 重扫所有 changed pages，确认 canonical、<=5、visibility 与新增 taxonomy/alias 约束全部满足

3. audit/no-op 时 vault 字节不变；写模式下 log/hot/QMD 尚未改变

#### 流程控制

- 验收通过：转到 `record_and_refresh`。

- 验收失败：返回 `apply_tags`。

- 最多连续失败 `4` 次；达到上限后停止并报告阻塞。

### 6. 幂等记录标签操作并按需刷新 QMD (`record_and_refresh`)

#### 执行

1. 根据 mode 向 log.md 幂等写 TAG_AUDIT 或 TAG_NORMALIZE，带 plan_id、tags_normalized/unknown/pages_modified/new_tags_added；重试不得重复。
2. 有 live page/taxonomy 修改时更新 hot.md Recent Activity，保留最近 3 次并更新 frontmatter timestamp；纯 audit 只记录 audit log，不虚报 normalization。
3. 仅有 live Markdown 写入且 QMD_WIKI_COLLECTION 已配置时运行 `${QMD_CLI:-qmd} update`，需要时 embed，并以 ls/get 验证；unset/unavailable/error 分别记录且不回滚 Markdown。
4. 写 tag-taxonomy-completion.md，事实匹配实际 diff、tracking 和 QMD。完成后输出 <promise>done</promise>。

#### 输入

approved-tag-plan.json + tag-apply-report.md + log/hot/QMD config

#### 产出

幂等 tracking + tag-taxonomy-completion.md + 可选 QMD refresh

#### 验收

1. 核对 TAG event 恰好一次、字段与实际 counts 一致，hot last-3/timestamp 只在适用时更新

2. 核对 QMD guard/update/embed/verify 顺序和状态；失败未回滚 vault，no-op 未刷新

3. 从最终页面和 taxonomy 抽样验证报告准确，没有未批准 unknown mapping 或隐藏写入

#### 流程控制

- 验收通过：转到 `done`。

- 验收失败：返回 `record_and_refresh`。

- 最多连续失败 `3` 次；达到上限后停止并报告阻塞。

<!-- END GENERATED SKILL INSTRUCTIONS -->
