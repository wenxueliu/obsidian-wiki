---
name: wiki-status
description: "只读计算 Wiki 来源增量、健康优先级与 token footprint，并可生成知识图谱 insights"
---

# wiki-status

此 skill 是 `workflows/wiki-status.yaml` 的 Agent Skill 格式投影；workflow 是行为事实来源，本文件把其字段渲染为可直接执行的 Markdown 指令。

<!-- BEGIN GENERATED SKILL INSTRUCTIONS -->

## 执行规则

按下列步骤和流程控制执行。每个步骤只读取其声明的输入，只产生其声明的产出；执行与独立验收分开进行。修改行为时先编辑权威 workflow，再运行 `python tools/sync_workflow_skills.py`。

- 自动重置：开启。

## 独立验收规则

你是 Wiki Status 的事实审计者。标准模式必须只读，不能把 mtime touched 误报为 modified，不能混用非 canonical manifest keys。
insights 模式只允许重写可再生的 _insights.md、追加一条日志并按需刷新 QMD；不得修改知识页或 manifest。

单次验收超时：`3600000` 毫秒。

## 工作流

### 1. 复用共享子 workflow 解析 status 来源与 vault 上下文 (`resolve_context`)

#### 执行

调用 `wiki-context` skill，并把下列输入传给它。以被调用 skill 的验收结果作为本步骤结果。

#### 输入

status invocation 与当前 CWD

调用参数：

- `requested_keys`: OBSIDIAN_VAULT_PATH,OBSIDIAN_SOURCES_DIR,CLAUDE_HISTORY_PATH,CODEX_HISTORY_PATH,WIKI_STAGED_WRITES,WIKI_TOKEN_WARN_THRESHOLD,QMD_TRANSPORT,QMD_WIKI_COLLECTION,QMD_CLI_SEARCH_MODE

- `optional_reads`: owner AGENTS,index,hot,manifest,active layout

- `setup_mode`: false

#### 产出

wiki-context.json + wiki-context.md

#### 验收

采用被调用 skill 的验收结论，不在本步骤重复验收。

#### 流程控制

- 验收通过：转到 `resolve_and_inventory`。

- 验收失败：返回 `resolve_context`。

- 最多连续失败 `3` 次；达到上限后停止并报告阻塞。

### 2. 解析 vault、来源配置与当前 manifest (`resolve_and_inventory`)

#### 执行

使用 wiki-context.json 建立 status inventory。

1. 使用 context 中已解析的 vault、sources/history paths、write mode、token threshold 与 QMD；不得重新选择 profile。
2. 读取 .manifest.json；缺失时标记 fresh，不创建。canonicalize 所有 source keys，检测 `~`/absolute 混用但只建议 normalize。
3. 扫描 documents、Claude projects/conversations/memory、Codex session_index/sessions/history 和按请求启用的 archived rollouts；再检查 manifest 指向的非标准路径。记录 path/type/size/mtime/hash（可安全计算时）/project。
4. 读取 routing.content_roots 下 live page frontmatter 及 index/log/hot 的最低成本信息；routing.skip_dirs/system_dirs/system_paths 不算 live pages。
5. 识别 standard 或 additive insights mode，写 status-context.md 与 source-inventory.json。不得修改 vault/source/manifest。

#### 输入

wiki 状态、delta、dashboard、health 或 insights 请求（vault 由 wiki-context 交互式确认）

#### 产出

status-context.md + source-inventory.json

#### 验收

1. 复核 config precedence、canonical paths、所有标准 source inventories 与 manifest 外路径，fresh/archived coverage 判定准确

2. 抽查 page/source counts、scope exclusions 和 mode，确认只用了廉价 metadata/frontmatter 且没有任何写入

#### 流程控制

- 验收通过：转到 `compute_delta`。

- 验收失败：返回 `resolve_and_inventory`。

- 最多连续失败 `3` 次；达到上限后停止并报告阻塞。

### 3. 分类来源 delta 并计算 Wiki 概览与 token footprint (`compute_delta`)

#### 执行

1. 将每个来源分类为 new、modified、touched、unchanged、deleted：优先 content_hash；mtime 新但 hash 相同必须 touched；旧 manifest 无 hash 才 fallback mtime。
2. 分别统计 Claude 新项目/conversations/memory 与 Codex rollout/index/archive delta；manifest 缺失时全部 current sources 为 new。
3. 统计 live pages/categories、manifest sources/projects/last ingest，并 grep visibility：无 visibility 或 visibility/public 计 public，internal/pii 分列；全未标时省略 visibility 行。
4. WIKI_STAGED_WRITES=true 时统计 _staging 新页/patch 与 oldest age；否则不报告 staged queue。
5. 按 tier 聚合 page bytes/4；unset→supporting。计算 full/index-only/typical-query estimates，使用 threshold（默认100000，0禁用 warning）。
6. 写 delta.json、wiki-status-report.md 的 Overview/Delta/Summary/Token Footprint 草稿，明确 append/full recommendation 与 4 chars/token heuristic。保持只读。

#### 输入

status-context.md + source-inventory.json + manifest/page frontmatter

#### 产出

delta.json + wiki-status-report.md（概览、delta、token footprint）

#### 验收

1. 重新抽样 hash/mtime/manifest 对比，确认 new/modified/touched/unchanged/deleted 互斥且 canonical keys 无重复

2. 重算 pages/categories/visibility/staging/source/project counts，fresh manifest 与 archive coverage 没有误报

3. 重算各 tier、full/index/typical token estimate 与 threshold guard，确认报告只写 artifacts

#### 流程控制

- 验收通过：转到 `rank_actions`。

- 验收失败：返回 `compute_delta`。

- 最多连续失败 `4` 次；达到上限后停止并报告阻塞。

### 4. 按固定优先级生成 What to Do Next (`rank_actions`)

#### 执行

收集并排序 7 类信号：0 staged pending、1 _raw top-level pending（排除 .gitkeep/_archived）、2 updated>=90d 且 incoming>=5 的 stale core、3 zero-incoming orphans、4 synthesis opportunities/14d overdue、5 new+modified sources、6 lint issues/30d overdue。

最多展示 6 项，严格按上述优先级；orphans 最多列 5 个名称，overflow 写剩余数。全部为空时输出 healthy empty state。将结果追加到 wiki-status-report.md，并写 next-actions.json；不得运行推荐 workflow 或修改 vault。

#### 输入

delta.json + index/log/hot + live link/frontmatter metadata

#### 产出

next-actions.json + 完整 standard wiki-status-report.md

#### 验收

1. 独立重算 raw/stale/orphan/synthesis/source/lint/staging signals，阈值、排除项与 counts 准确

2. 核对 priority 0-6、最多 6 项、overflow/empty state 和推荐 workflow，未把 touched 算作 ingest delta

3. 确认 standard report 全程只读，未修改 vault/log/hot/manifest/QMD

#### 流程控制

- 验收通过：转到 `insights`。

- 验收失败：返回 `rank_actions`。

- 最多连续失败 `3` 次；达到上限后停止并报告阻塞。

### 5. 条件生成 Wiki 图谱 insights 与 snapshot (`insights`)

#### 执行

若不是 insights mode，写 insights-report.md 标记 skipped: standard mode，不修改 vault。

insights mode 时：
1. 若 live pages<20 或 fresh rebuild 后尚无 ingest，写明确 skip 原因，不创建/改写 _insights.md。
2. 否则优先运行 `obsidian-wiki graph-analyse "$OBSIDIAN_VAULT_PATH" --pretty`；不可用才解析 wikilinks 构建 graph。
3. 计算 top-10 incoming anchors、top-5 bridges、n>=5 tag cohesion（<0.15 fragmented）、top-5 surprising cross-category connections、orphan-adjacent、rough clusters。
4. 读取旧 _insights.md GRAPH_SNAPSHOT 并计算 nodes/edges add/remove、新连接与 lost incoming；首次无 snapshot 则略过 delta。
5. 只建议 tier，不改页面：incoming>=5 或 top-5 bridge 提升 core；incoming<=1 且 stale>=90d 降 peripheral，最多10项。问题最多7项，ambiguous→bridge→isolated。
6. 写 artifacts/insights-report.md 与 insights-data.json；通过内部一致性检查后原子重写 vault/_insights.md，末尾嵌 compact JSON snapshot。除该文件外保持 vault 不变。

#### 输入

status report + graph metadata + optional previous _insights.md

#### 产出

insights-report.md + insights-data.json；适用时重写 _insights.md

#### 验收

1. 重跑 graph analyzer/fallback，核对 anchors/bridges/communities/dead ends/isolates/surprising 与 stats，skip guards 准确

2. 重算 cohesion、graph delta、tier thresholds/questions priority，确认 snapshot JSON 完整可供下次 diff

3. standard/skip 模式 vault 零变化；active insights 只改 _insights.md，未改知识页/manifest/index/hot

#### 流程控制

- 验收通过：转到 `finalize_status`。

- 验收失败：返回 `insights`。

- 最多连续失败 `4` 次；达到上限后停止并报告阻塞。

### 6. 交付状态报告并仅为 insights 记录可选写入 (`finalize_status`)

#### 执行

1. standard 或 skipped insights：不写 log、不刷新 QMD，写 wiki-status-completion.md 指向 report 并注明 read-only。
2. active insights：向 log.md 幂等追加 STATUS_INSIGHTS，包含 stable run_id、anchors/bridges/cohesion/surprising/questions/delta/tier_suggestions；不改 hot/manifest/index。
3. 只有 _insights.md 实际写入且 QMD_WIKI_COLLECTION 已配置时运行 `${QMD_CLI:-qmd} update`，需要时 embed，并用 ls/get 验证；错误不回滚 Markdown。
4. completion 记录 Overview/Delta/What Next、insights/QMD 状态和 artifacts。事实一致后输出 <promise>done</promise>。

#### 输入

wiki-status-report.md + insights reports + log/QMD config

#### 产出

wiki-status-completion.md + 条件 STATUS_INSIGHTS/QMD refresh

#### 验收

1. 对照最终 source/vault metadata 抽查 status report、delta、token footprint 与 next actions，无过期或虚构 counts

2. standard/skip 保持完全只读；active insights 的 log run_id 恰好一次且只有 _insights.md/log.md 为 vault diff

3. QMD 仅在 insights write 后执行，guard/update/embed/verify 与 completion 状态准确

#### 流程控制

- 验收通过：转到 `done`。

- 验收失败：返回 `finalize_status`。

- 最多连续失败 `3` 次；达到上限后停止并报告阻塞。

<!-- END GENERATED SKILL INSTRUCTIONS -->
