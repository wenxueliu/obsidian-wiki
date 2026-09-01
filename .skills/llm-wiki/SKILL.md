---
name: llm-wiki
description: "将知识库需求设计为可执行的三层 LLM Wiki 架构、schema、检索与维护契约"
---

# llm-wiki

此 skill 是 `workflows/llm-wiki.yaml` 的 Agent Skill 格式投影；workflow 是行为事实来源，本文件把其字段渲染为可直接执行的 Markdown 指令。

<!-- BEGIN GENERATED SKILL INSTRUCTIONS -->

## 执行规则

按下列步骤和流程控制执行。每个步骤只读取其声明的输入，只产生其声明的产出；执行与独立验收分开进行。修改行为时先编辑权威 workflow，再运行 `python tools/sync_workflow_skills.py`。

- 自动重置：开启。

## 独立验收规则

你是 LLM Wiki 架构审计者。只评估设计 artifacts，不得初始化 vault 或修改知识库。
设计必须区分 immutable raw sources、compiled wiki 与 schema，并把具体操作路由给专用 workflow。

单次验收超时：`3600000` 毫秒。

## 工作流

### 1. 澄清知识边界、用户目标与现有环境 (`frame_requirements`)

#### 执行

本 skill 是 LLM Wiki 架构规划的完整运行时规范。根据用户任务识别：

1. 原始 sources 的种类、位置、可变性、敏感度与现有 ingest adapters；明确 text V1 仅支持本地 UTF-8 .md/.markdown/.mdx/.txt/.rst，其他格式不能冒充纯文本。
2. 用户希望查询/维护的知识、项目范围、交互式 vault 路径、config defaults/overrides、owner AGENTS、writing profile、link format、staged writes 与 QMD 状态。
3. 规模、token/检索约束、协作/审批要求、provenance 与 trust 风险。
4. 哪些需求属于 llm-wiki 架构设计，哪些必须路由 wiki-setup、可恢复的 wiki-folder-ingest、轻量且 workflow-free 的 wiki-ingest、wiki-query、wiki-lint、wiki-status、wiki-rebuild 等具体能力。

写 requirements-brief.md，包含 assumptions、open questions、in/out of scope 和不得执行的写入。此 workflow 全程只写 artifacts，不修改 vault/config。

#### 输入

用户的知识库架构、schema 或组织需求

#### 产出

requirements-brief.md

#### 验收

对照用户任务复核 sources/knowledge/schema 三层需求、V1 格式边界、现有环境、审批与规模约束均已覆盖；路由边界明确且没有提前设计或执行 vault 写入。

#### 流程控制

- 验收通过：转到 `design_architecture`。

- 验收失败：返回 `frame_requirements`。

- 最多连续失败 `3` 次；达到上限后停止并报告阻塞。

### 2. 设计三层架构、目录布局与核心数据契约 (`design_architecture`)

#### 执行

基于 requirements-brief.md 写 wiki-architecture.md：

1. Layer 1 immutable raw sources 与 vault/_raw scratch inbox 明确分离；列出每种 source 的专用 adapter/unsupported 状态。Source adapter 只回答如何读取，不决定什么值得保留。
2. Layer 2 compiled wiki 使用 active/proposed Knowledge Pack。Knowledge Profile 定义 purpose、scope、knowledge types、extraction、verification、freshness 与 retrieval；Vault Layout 定义 routing templates/content roots、项目 overview route、system/skip dirs 与 special files。单领域 Vault 在 setup 时固定 Pack，摄取只做 scope compatibility，不自动识别或切换领域；不得把 default layout 的目录命名当成框架不变量。
3. Layer 3 schema 定义 page required/optional frontmatter、summary<=200、provenance markers/fractions、standard+owner relationship types、confidence/lifecycle、tier、visibility 与 link format。领域特定字段与验证规则来自 Knowledge Profile，物理目标只能来自 Vault Layout。
4. 定义 index.md、append-only log.md、约 500 字 hot.md、manifest canonical absolute source keys/complete-live boundary。
5. 给出 generic page example，只作为 schema 示例；PDF deep-dive 仅标为 specialized future/source-adapter contract。
6. 体现 compile-not-retrieve、compound over time、human curates/LLM maintains、Obsidian-compatible Markdown。

不创建 vault 或页面，不把建议冒充 owner 已批准 schema。

#### 输入

requirements-brief.md

#### 产出

wiki-architecture.md（三层架构、Knowledge Profile/Layout、page/special-file schema）

#### 验收

1. 逐项对照 llm-wiki 三层架构、layout routing/content roots/special files/page template，确认 raw、live、staging 与 manifest completion boundary 没有混淆

2. 审计 provenance、typed relationships、confidence formula/independent lineages、lifecycle state machine、tier/visibility/link format 完整且 owner extension 未被覆盖

3. 确认设计与 requirements 对齐、unsupported source 未被降级处理、没有实际 vault/config 写入

#### 流程控制

- 验收通过：转到 `design_operations`。

- 验收失败：返回 `design_architecture`。

- 最多连续失败 `4` 次；达到上限后停止并报告阻塞。

### 3. 设计可扩展检索、写入事务与维护流程 (`design_operations`)

#### 执行

写 operations-design.md：

1. Config Resolution：交互式确认 vault 绝对路径，其他 requested keys 按 user overrides → CWD .env walk-up → global config；vault-scoped runtime state 与 Writing Profile precedence。
2. Retrieval Primitives：index/frontmatter → summary → anchored grep context → whole page last；说明 QMD 是可选 index、Markdown 是 source of truth。
3. 写入事务：direct/staged 边界、validation、index/log/hot、manifest-last、QMD 仅在 live commit 后刷新。
4. ingest append/rebuild/restore 路由，canonical sources、delta、idempotency、cross-links、contradictions 与 trust review。
5. 为实际任务给出 workflow map：可恢复路径为 wiki-folder-ingest → bounded claude -p pool 的 worker-only wiki-source-text → wiki-packet-integrate → wiki-finalize-sources；轻量路径为 workflow-free wiki-ingest → 父 Agent 串行派发 general-purpose subagent 执行每个 Ingest Document 的 wiki-ingest-document → per-document manifest commit。并覆盖 wiki-setup、wiki-stage-commit、wiki-query、wiki-lint、wiki-status、wiki-rebuild 等，注明选择条件、读写权限和完成边界。
6. 给出 phased adoption 与 acceptance criteria，避免要求全 vault 读取或数据库依赖。

本步骤仍只输出设计，不执行任何专用 workflow。

#### 输入

requirements-brief.md + wiki-architecture.md

#### 产出

operations-design.md（config、retrieval、transactions、workflow map、acceptance）

#### 验收

1. 检查 config/writing precedence、retrieval escalation、QMD source-of-truth 边界和大 vault token 成本是否准确

2. 检查 direct/staged、manifest-last、special files、idempotency、trust/human approval 和 source completion transactions 是否闭合

3. workflow routing 覆盖用户需求且权限最小，没有让 theory workflow 执行 setup/ingest/lint 等具体变更

#### 流程控制

- 验收通过：转到 `deliver_blueprint`。

- 验收失败：返回 `design_operations`。

- 最多连续失败 `4` 次；达到上限后停止并报告阻塞。

### 4. 汇总经验证的 LLM Wiki 实施蓝图 (`deliver_blueprint`)

#### 执行

将前述 artifacts 汇总为 llm-wiki-blueprint.md：目标、关键决策、三层图、effective/proposed Knowledge Profile、Vault Layout、schema、source adapter matrix、operational workflow map、风险/权衡、phased rollout、验收标准和下一条推荐命令。

明确标记 owner 已确认、framework invariant、proposal、open question；不要伪造现有配置。若用户请求实际初始化，下一步指向 `wiki/wiki-setup`；需要 staged review/Job 恢复的文本 ingest 指向 `wiki/wiki-folder-ingest`，明确要求轻量无 Job/Packet 时指向 skill-only `wiki-ingest`。写 blueprint-validation.md 记录逐项 contract 检查。

确认全程没有修改 vault/config 后输出 <promise>done</promise>。

#### 输入

requirements-brief.md + wiki-architecture.md + operations-design.md

#### 产出

llm-wiki-blueprint.md + blueprint-validation.md

#### 验收

1. 从用户需求重查 blueprint 的可追踪性、决策/假设/open questions、phased acceptance 与下一 workflow 路由，无遗漏或过度设计

2. 从 llm-wiki contract 重查三层、Knowledge Profile/Layout 边界、schema、provenance/trust、retrieval、special files、QMD、config 和 operation boundaries，无内部矛盾

3. 确认 artifacts 自洽且全程没有 vault/config/external writes，blueprint 没有把 proposal 表述为已生效事实

#### 流程控制

- 验收通过：转到 `done`。

- 验收失败：返回 `deliver_blueprint`。

- 最多连续失败 `3` 次；达到上限后停止并报告阻塞。

<!-- END GENERATED SKILL INSTRUCTIONS -->
