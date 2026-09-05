# 软件知识编译与落位

本 layout 面向软件知识编译。Agent 的职责不是归档原文，而是从输入材料中提取可复用、可验证的软件知识，将其合并到正确的 Vault 页面。

输入材料始终是“来源”，不会自动成为“事实”。只有完成来源标注、冲突检查和结构校验的内容，才能成为正式 Wiki 知识。

本文件定义完整的语义分类和知识编译契约；它不能自行授权文件路径。模型只能选择 `routing.json` 已声明的 page type，最终目标必须由 Ralph Flow 的 `resolve_wiki_route.py` 展开并校验。

## 一、运行参数

执行前收集以下上下文：

```text
Vault 路径：{{vault_path}}
写入模式：{{write_mode}}                    # plan | staged | direct
是否启用 Deployable 分类：{{enable_deployables}} # true | false

来源类型：{{source_type}}                   # requirement | architecture | meeting | code | test | incident | api | other
来源标识：{{source_id}}
来源位置：{{source_uri}}
来源版本：{{source_revision}}
来源 Owner：{{source_owner}}
来源确认状态：{{source_status}}              # unconfirmed | confirmed | disputed

关联项目：{{project_id}}
代码仓库：{{repository_path}}
当前 Git HEAD：{{git_head}}

待编译内容：
{{source_content}}
```

未提供的参数不得自行编造，必须逐项列入 `missing_context`。

## 二、核心原则

1. 按知识语义分类，不按来源文件名、原目录或文档类型分类。PRD 可以同时产生 Change、Behavior、Rule、Term；架构文档可以同时产生 System、Component、Interface、Decision；事故报告可以产生 Operation、Rule、Behavior、Decision。
2. 一页只表达一种主要知识类型。输入同时包含多个知识类型时，拆成多个页面，并通过 Wikilink 建立关系。
3. 先搜索、后新建。写入前检查相同 ID、同义标题、alias 和等价主题：已存在则 `merge` 或 `propose_update`；不存在且达到建页门槛才 `create`；只是现有页面的例子或补充则 `merge`；无长期复用价值则 `skip`。
4. 编译知识，不复制原文。只保留定义、约束、行为、决策、关系、边界、证据和未决问题，不把整段 PRD、会议纪要或源码复制成页面。
5. Wiki 不复制 CodeGraph。类、方法、调用边、文件树、行号和完整调用链由 CodeGraph 管理；Wiki 只保存稳定业务语义、稳定架构职责、设计意图和约束、必要代码入口以及可重放的 CodeGraph 查询意图。
6. 不确定内容不得静默升级为事实：来源直接支持的内容为 `extracted`，跨来源推导为 `inferred`，来源冲突或语义不明为 `ambiguous`。
7. 正式业务术语由 `terms/` 管理。Agent 可以创建候选术语，但不得自动合并、重命名、废弃或改变已确认术语的核心定义。
8. 保持两个状态轴独立：`lifecycle` 表示知识成熟度；`operational_status.state` 表示所描述对象是否仍在运行。
9. 所有正式页面必须可追溯到来源。缺少 `source_id`、`source_uri` 或 `source_revision` 时，只能生成落位计划或 staged 候选，不能直接写入 verified 页面。
10. 输入与现有知识冲突时不得覆盖旧结论。创建 staged patch，保留双方来源，并将页面标为 `disputed` 或把冲突列入 `unresolved_conflicts`。

## 三、禁止直接写入的位置

不得把业务知识直接写入：

- `index.md`
- `log.md`
- `hot.md`
- `.manifest.json`
- `_meta/`
- `_state/`
- `_archives/`
- `_readouts/`
- `.codegraph/`

这些位置由框架、配置、健康检查、CodeGraph 或派生任务维护。

- `_raw/`：未编译的临时输入，不是正式知识。
- `_staging/`：候选页面或候选 patch，等待审核。
- `_archives/`：Vault 快照与恢复数据，不存放单个废弃知识页面。
- `_readouts/`：临时报告和一次性分析，不作为正式知识事实。

当 `WIKI_STAGED_WRITES=true` 时，无论请求的 `write_mode` 是什么，所有新页面和更新都必须进入 `_staging/<category>/`。

## 四、知识类型与目录

模型必须为每个原子知识选择唯一主要 page type：

1. `project` / `project_overview` → `projects/`：回答哪个 Git 仓库或开发项目承载知识。保存仓库地址、Owner、技术栈、同步状态和系统关联；不保存详细业务行为、普通类或方法。
2. `term` → `terms/`：回答业务词语准确是什么意思。保存正式名称、别名、定义、边界、易混淆术语和领域归属。识别信号包括“称为”“定义为”“指的是”“不要与……混淆”。
3. `domain` → `domains/`：回答业务领域边界、职责和上下游。保存领域边界、核心职责、Owner 和上下文关系；不保存单个 Feature 或代码组件。
4. `capability` → `capabilities/`：回答系统长期具备什么业务能力。保存稳定能力、业务价值、范围和相关行为；识别信号是“支持……能力”“能够……”且不依赖一次性项目时间。
5. `behavior` → `behaviors/`：回答特定条件和触发下系统应产生什么可观察结果。必须能表达 Given + When + Then；不保存具体类、方法、数据库表和内部算法。
6. `rule` → `rules/`：回答什么约束或不变量始终不能违反。保存业务不变量、计算规则、状态约束和资格条件；识别信号包括“必须”“禁止”“只能”“不得”“始终”。
7. `model` → `models/`：回答核心业务对象、状态和数据语义。保存业务实体、值对象、状态机和字段业务含义；不机械复制完整 DDL、DTO 或 ORM 类。
8. `process` → `processes/`：回答多个能力或系统如何完成端到端业务流程。保存跨 Behavior、跨 System 的流程和状态转换；不保存单个方法调用链。
9. `system` → `systems/`：回答哪个稳定的软件系统或运行责任边界承担职责。`enable_deployables=false` 时，System 表示可独立构建、发布、运行和回滚的单元；`enable_deployables=true` 时，System 表示由一个或多个 Deployable 组成的更高层逻辑系统。
10. `deployable` → `deployables/`：仅当 `enable_deployables=true` 时使用，回答什么单元可以独立构建、发布、启动和回滚，例如 API 服务、Worker、定时 Job 或 Serverless Function；不要求独立数据库或配置中心。
11. `component` → `components/`：回答哪个不可独立运行但具有稳定架构职责的组件实现能力。建页门槛是职责稳定、被多个 Behavior/Interface/Decision 引用，并且仅查看代码不足以理解设计意图。必须具有 `hosted_by`，指向 System 或 Deployable。普通 Controller、DAO、DTO、Util、Package 不建页。
12. `interface` → `interfaces/`：回答系统边界通过什么契约交互。保存 API、事件、消息、批处理、文件和数据契约的语义；不复制完整 OpenAPI、Proto 或 GraphQL Schema，只保留权威来源引用。
13. `decision` → `decisions/`：回答为什么选择当前方案而不是其他方案。至少包含背景、决策驱动因素、备选方案、结论、代价和失效条件。只有“现在怎么实现”而没有选择与权衡的内容不是 Decision。
14. `change` → `changes/`：回答为什么现在改变、改变什么、范围和验收目标。保存已确认并归一化的变更意图；不复制原始 PRD，原始 PRD 仅作为 source 引用。
15. `operation` → `operations/`：回答系统如何部署、运行、观测、恢复和处理故障。保存运行机制、配置语义、故障模式、补偿、Runbook 和事故沉淀的长期知识；不保存原始日志或完整事故时间线。
16. `quality` → `quality/`：回答如何验证知识或系统行为正确。保存测试策略、质量门槛、覆盖目标和验证方法；不保存每次执行的完整测试输出。
17. `concept` → `concepts/`：回答需要长期理解的抽象技术概念。保存技术原理、通用概念和心智模型。
18. `pattern` → `patterns/`：回答什么解决方案可以跨项目重复使用。保存可复用架构模式、编码模式、反模式及适用边界；项目私有实现放入对应 System、Component 或 Decision。
19. `skill` → `skills/`：回答如何完成开发、排障或操作任务。保存可执行 How-to、排障步骤和操作指南。
20. `reference` → `references/`：回答需要反复查阅的稳定事实或外部规范。保存规范索引、配置含义、版本兼容表和外部文档引用。
21. `synthesis` → `synthesis/`：回答多个知识节点组合后产生什么新结论。保存跨领域分析、能力到系统的综合映射和有证据的影响分析；单一来源摘要不是 Synthesis。

`project_*` page type 是现有项目同步 workflow 的兼容别名，仍然路由到对应语义目录。项目归属通过 frontmatter 关系表达，不通过目录嵌套表达；项目入口使用 `project_overview`。

## 五、分类判定顺序

对每个原子知识依次判断，命中后停止：

1. 只是未处理材料 → `_raw/`，不创建正式知识。
2. 定义业务词语 → `term`。
3. 描述一次有时间边界的变更目标 → `change`。
4. 能写成 Given/When/Then → `behavior`。
5. 表达必须始终成立的约束 → `rule`。
6. 描述长期业务能力 → `capability`。
7. 描述业务对象、状态或数据语义 → `model`。
8. 描述跨能力、跨系统端到端流程 → `process`。
9. 记录选择、备选方案和权衡 → `decision`。
10. 定义跨系统交互契约 → `interface`。
11. 是独立运行或责任边界 → `system` 或在启用时选择 `deployable`。
12. 是不可独立运行但具有稳定架构职责的单元 → `component`。
13. 描述运行、故障、观测或恢复 → `operation`。
14. 描述验证方法和质量门槛 → `quality`。
15. 可跨项目复用 → `pattern`、`concept` 或 `skill`。
16. 仅为稳定查阅材料 → `reference`。
17. 是多个已存在节点形成的新结论 → `synthesis`。
18. 只是代码符号、调用关系或文件结构 → 不创建 Wiki 页面，交给 CodeGraph。
19. 仍无法确定 → 不写入，返回 `needs_clarification`。

框架要求 `routing.json` 声明 fallback，但语义不明确时不得为了“把内容放进去”而使用 fallback。无法确定比错误归类更安全。

## 六、拆分规则

满足任一条件时必须拆成多个知识页面：

- 同时包含“为什么改变”和“系统如何表现”。
- 同时包含业务不变量与实现方案。
- 同时包含架构职责与具体接口契约。
- 同时包含决策结论与通用技术模式。
- 不同知识部分具有不同 Owner、生命周期或来源可信度。
- 不同部分可以独立验证、废弃或替换。

以下情况不得拆分：

- 同一 Behavior 的不同数据示例。
- 同一 Rule 的正反例。
- 同一 Decision 的不同备选方案。
- 同一 Component 的多个代码入口。

## 七、新建页面门槛

只有同时满足以下条件才能新建正式页面：

- 有单一、明确的主要知识类型。
- 具有长期或跨任务复用价值。
- 无现有等价页面可以合并。
- 至少有一个可定位来源。
- 标题和 ID 全局唯一。
- 能建立至少一个有意义的关系，或明确说明其独立性。
- 通过 `_meta/schema.json` 中对应类型的 Frontmatter 校验。

以下内容禁止新建正式页面：

- 普通代码类、方法、DTO、DAO、Util、Package。
- 单次聊天中的临时想法。
- 没有结论的会议流水账。
- 可直接从 CodeGraph 获取的调用关系。
- 可直接从 OpenAPI、Proto、DDL 机械读取的完整结构。
- 无法定位来源的断言。
- 已有页面的轻微重复表达。
- 仅对当前任务有效的一次性分析。

## 八、文件命名与关系

优先沿用 Vault 现有命名规范；没有现有规范时：

- 普通页面 slug：`<ID>-<short-slug>`。
- 术语页面 slug：`<domain>--<canonical-term>`。
- 文件名必须稳定，标题变化不应导致 ID 变化。
- 使用 frontmatter `aliases` 保存常用名称。
- 使用 Wikilink 表达知识关系，不用目录嵌套表达从属关系。

推荐关系类型：`belongs_to`、`defines`、`realizes`、`constrained_by`、`implemented_by`、`hosted_by`、`exposed_through`、`decided_by`、`verified_by`、`depends_on`、`supersedes`、`replaces`、`related_to`。

不得创建指向不存在页面的 Wikilink。目标尚未创建时，将关系放入 `pending_relations`。

## 九、代码知识处理规则

发现代码相关内容时：

1. 使用 CodeGraph 查询当前符号、调用路径、调用者、被调用者和影响范围。
2. 对比 Project 同步凭证、Git HEAD 和工作区状态。
3. 如果 Wiki 编译 commit 与当前代码状态不同，保留 Behavior、Rule、Term 等业务语义，把 `code_refs` 和 `implemented_by` 视为待验证，重新查询 CodeGraph，不用旧行号或旧调用链作设计结论。
4. Wiki 代码引用只保存稳定锚点和验证信息：

```yaml
code_refs:
  - project: <project-id>
    revision: <git-commit>
    symbol: <qualified-symbol>
    relation: implements | validates | exposes | persists
    verified_at: <timestamp>
    codegraph_query: <可重放查询意图>
```

5. 不把 CodeGraph 返回的完整调用链复制进 Wiki。

## 十、正式页面最小 Frontmatter

每个正式页面至少包含：

```yaml
id: <全局唯一 ID>
title: <明确标题>
category: <目标目录对应类型>
summary: <1 到 2 句高密度摘要>
aliases: []
tags: []

sources:
  - source_id: <source-id>
    uri: <source-uri>
    revision: <source-revision>
    locator: <章节、页码、文件或符号>

provenance:
  extracted: <数量>
  inferred: <数量>
  ambiguous: <数量>

lifecycle: draft | reviewed | verified | disputed | archived

operational_status:
  state: active | deprecated | sunset
  replacement: null

owners: []
relations: {}
created: YYYY-MM-DD
updated: YYYY-MM-DD
```

类型特定必填字段：Behavior 使用 `given`、`when`、`then`；Rule 使用 `statement`、`scope`、`exceptions`；Decision 使用 `context`、`drivers`、`alternatives`、`decision`、`consequences`；Component 使用 `responsibility`、`hosted_by`；Interface 使用 `provider`、`consumers`、`contract_source`；Term 使用 `definition`、`domain`、`not_equivalent_to`；Change 使用 `motivation`、`scope`、`acceptance`。

## 十一、执行流程

严格按以下步骤执行：

1. 读取 Vault 的 `AGENTS.md`、`_meta/schema.json`、`_meta/rules.md` 和 `_meta/terminology-policy.md`。
2. 读取 `index.md`、相关目录标题、frontmatter 摘要和 aliases；不要一开始读取所有页面正文。
3. 把输入拆成最小原子知识，并标记 extracted、inferred 或 ambiguous。
4. 搜索已有页面，执行实体对齐、术语对齐和重复检测。
5. 为每个原子知识选择唯一主要类型、目标目录和操作：`create | merge | propose_update | skip | needs_clarification`。
6. 输出落位计划，暂不写文件。
7. 检查是否复制原文、创建代码符号页面、产生重复页面、混合多个主要类型、缺少来源、违反术语规则、产生死链或未通过 Schema。
8. 按写入模式执行：`plan` 只输出计划；`staged` 写 `_staging/<category>/`，更新写 staged patch；`direct` 仅在来源 confirmed、无冲突且 Schema 通过时写正式目录，否则自动降级 staged。
9. 使用 Ralph Flow Wiki 的标准事务流程更新 manifest、index、log 和 hot cache，不得绕过框架手工修改 manifest。

## 十二、落位计划输出格式

任何文件写入前必须输出以下 YAML：

```yaml
placement_plan:
  source:
    id: <source-id>
    type: <source-type>
    revision: <source-revision>
    status: <source-status>

  items:
    - provisional_id: <候选知识 ID>
      title: <页面标题>
      knowledge_type: <知识类型>
      target_category: <目标目录>
      target_path: <建议路径>
      action: create | merge | propose_update | skip | needs_clarification
      existing_page: null
      confidence: high | medium | low
      provenance: extracted | inferred | ambiguous
      reason: <为什么放在这里>
      scope:
        include: []
        exclude: []
      relations: []
      pending_relations: []
      codegraph_verification_required: false
      review_required: false

  splits:
    - source_fragment: <输入片段说明>
      produced_items: []
      reason: <为什么需要拆分>

  skipped_content:
    - content: <内容摘要>
      reason: <为何不进入正式知识>

  unresolved_conflicts: []
  missing_context: []

  validation:
    duplicate_check: passed | failed | pending
    terminology_check: passed | failed | pending
    relationship_check: passed | failed | pending
    schema_check: passed | failed | pending
    source_traceability: passed | failed | pending

  final_action: write | stage | ask | no_op
```

如果 `final_action=ask`，只提出最少且关键的澄清问题，不写入任何正式页面。

## 十三、分类示例

### 示例 1：跨仓拆单

输入：“本季度支持跨仓拆单；同一履约仓的商品必须进入同一个子订单。”

- `change`：本季度引入跨仓拆单的变更目标。
- `capability`：订单拆分能力。
- `behavior`：多仓订单提交后按履约仓拆分。
- `rule`：同一履约仓的商品进入同一子订单。
- `term`：子订单、履约仓；仅在术语尚不存在时创建候选。

### 示例 2：代码调用链

输入：“OrderController 调用 SplitService.calculate，再调用 OrderRepository.save。”

- 不为 Controller、Service、Repository 创建 Wiki 页面。
- 调用链由 CodeGraph 管理。
- 如果 Split Engine 具有稳定架构职责，可更新 `component` 页面并保存入口符号提示，但不复制调用链。

### 示例 3：同步拆单决策

输入：“为避免下游看到未拆分订单，选择在创建订单事务中同步拆单；异步方案因最终一致性窗口被否决。”

- `decision`：同步拆单的选择、备选方案和权衡。
- `rule`：如果“下游不得看到未拆分订单”是长期不变量，建立独立 Rule。
- `component`：仅当拆单引擎满足组件建页门槛时创建或更新。

### 示例 4：未确认术语

输入：“会议上有人说支付账户可能就是用户账户，但尚未确认。”

- 不合并两个术语。
- 在 `_staging/terms/` 创建候选冲突，或返回 `needs_clarification`。
- provenance 标记为 ambiguous。

## 十四、推荐调用与默认策略

```text
使用 software-knowledge layout 处理以下输入：

write_mode: staged
source_type: requirement
source_id: REQ-2026-0412
source_status: confirmed
project_id: order-service

source_content:
<粘贴需求、架构说明、会议纪要或其他输入>
```

生产环境默认使用 `write_mode=staged`。稳定运行后，可以对结构化代码来源和已经确认的来源开放 `direct`；术语合并、Decision 修改和冲突处理仍应强制进入 `_staging/`。
