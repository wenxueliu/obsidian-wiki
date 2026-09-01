---
name: daily-update
description: "运行 vault-scoped 的每日 Wiki 维护：source freshness、index、hot cache、状态文件、独立验证与日志"
---

# daily-update

此 skill 是 `workflows/daily-update.yaml` 的 Agent Skill 格式投影；workflow 是行为事实来源，本文件把其字段渲染为可直接执行的 Markdown 指令。

<!-- BEGIN GENERATED SKILL INSTRUCTIONS -->

## 执行规则

按下列步骤和流程控制执行。每个步骤只读取其声明的输入，只产生其声明的产出；执行与独立验收分开进行。修改行为时先编辑权威 workflow，再运行 `python tools/sync_workflow_skills.py`。

- 自动重置：开启。

## 独立验收规则

你是 Daily Update 的独立维护审计者。严格核对 manifest/source mtime、live page inventory、hot freshness 和 vault-scoped state。
不得摄取 stale source、删除 missing source 的页面或 manifest，也不得把 pending delta 伪装成已同步。

单次验收超时：`3600000` 毫秒。

## 工作流

### 1. 复用共享子 workflow 解析 daily maintenance 上下文 (`resolve_context`)

#### 执行

调用 `wiki-context` skill，并把下列输入传给它。以被调用 skill 的验收结果作为本步骤结果。

#### 输入

daily invocation 与当前 CWD

调用参数：

- `requested_keys`: OBSIDIAN_VAULT_PATH,OBSIDIAN_WIKI_REPO,QMD_TRANSPORT,QMD_WIKI_COLLECTION,QMD_CLI_SEARCH_MODE

- `optional_reads`: owner AGENTS,index,hot,manifest,active layout

- `setup_mode`: false

#### 产出

wiki-context.json + wiki-context.md

#### 验收

采用被调用 skill 的验收结论，不在本步骤重复验收。

#### 流程控制

- 验收通过：转到 `resolve_and_check_sources`。

- 验收失败：返回 `resolve_context`。

- 最多连续失败 `3` 次；达到上限后停止并报告阻塞。

### 2. 解析 vault-scoped 状态并检查全部 source freshness (`resolve_and_check_sources`)

#### 执行

使用 wiki-context.json 检查 vault-scoped state 与 source freshness。

1. 使用 context 的 canonical OBSIDIAN_VAULT_PATH、OBSIDIAN_WIKI_REPO、QMD 设置和 owner rules；不得重新选择 profile。
2. 用 canonical vault path 的 MD5 前 8 位派生 `$HOME/.obsidian-wiki/state/<vault-id>`，记录准确算法和 STATE_DIR；不得复用其他 vault 的全局状态。
3. 读取并兼容解析 `.manifest.json` 的 source list/dict 与 project metadata。对每个文件 source 比较 filesystem mtime 和 manifest ingested_at/last_ingested：mtime<=ingested 为 fresh，mtime>ingested 为 stale，不存在为 missing。
4. timestamp 必须 timezone/epoch 可比较；无效或缺失字段单列 warning，不猜为 fresh。Missing 只报告潜在 stale pages，绝不删除页面或 manifest。
5. 写 artifacts/daily-context.md、source-freshness.json 和 freshness-report.md，包含 stable cycle_id、vault/state/config、fresh/stale/missing/invalid counts、paths、timestamps 与建议的 sync workflow。此步骤不修改 vault/state/QMD。

#### 输入

/daily-update 或 morning sync 请求（vault 由 wiki-context 交互式确认）

#### 产出

daily-context.md + source-freshness.json + freshness-report.md

#### 验收

1. 独立复核 interactive canonical vault、config defaults/overrides 与 vault-id/state-dir derivation，确认多 vault state 不碰撞

2. 从 manifest 和 stat 重算每个 source 的 fresh/stale/missing/invalid 分类与计数，时区比较正确，missing 未触发删除

3. 确认 artifacts 完整且本步骤没有修改 vault、state files、sources、manifest 或 QMD

#### 流程控制

- 验收通过：转到 `reconcile_index`。

- 验收失败：返回 `resolve_and_check_sources`。

- 最多连续失败 `3` 次；达到上限后停止并报告阻塞。

### 3. 将 index.md 与 live knowledge page inventory 对齐 (`reconcile_index`)

#### 执行

1. 用 `rg --files` 或等价 find 枚举 vault live `.md` 页面；只纳入 active layout content_roots，排除其 skip/system dirs，并区分 root special files；不得硬编码 default layout 目录。
2. 读取 index.md 及每个 live page 的 title/category/tags/summary frontmatter，不为 index refresh 全读 page body。
3. 比较实际 inventory 与 index links：添加缺失 live page，移除不存在/非 live/staged entry，修正重复、category、summary/tags drift；每页在 index 恰好一次。
4. 保持 owner index conventions 与 header；没有差异时字节不变。写入使用 temporary sibling + atomic replacement。
5. 写 index-reconciliation.json 和 index-report.md，列出 before/after count、added/removed/updated/duplicates、validation 与是否实际刷新。

#### 输入

daily-context.md + vault/index.md + live page frontmatter inventory

#### 产出

已对齐或保持不变的 index.md + index-reconciliation.json + index-report.md

#### 验收

1. 独立重建 live page inventory，确认所有排除目录/special files正确，index 中每个 live knowledge page 恰好一次且无 phantom/staged entry

2. 抽样核对 index title/category/summary/tags 与页面 frontmatter，added/removed/updated/duplicate counts 可复算

3. 审计 index diff 仅含必要 reconciliation、owner conventions preserved、无差异时字节不变且写入原子

#### 流程控制

- 验收通过：转到 `refresh_hot_and_state`。

- 验收失败：返回 `reconcile_index`。

- 最多连续失败 `4` 次；达到上限后停止并报告阻塞。

### 4. 条件刷新 hot.md 并原子写 vault-scoped runtime state (`refresh_hot_and_state`)

#### 执行

1. 读取 hot.md 的 `updated:`。若有效且距现在<=48h，保持 hot.md 字节不变；缺失、无效或>48h 才刷新。
2. 刷新时只读取 10 个最近修改的 live knowledge pages，按 wiki-context.json 的 retrieval order 生成约 500 字 semantic snapshot；保持 `# Hot Cache`、updated、Recent Activity、Active Threads、Key Takeaways、Flagged Contradictions，并保留最近 3 次 operations。不得把 staged 内容说成 live。
3. 用 source-freshness.json 的 stale_count 写 STATE_DIR：`.last_update`=当前 epoch、`.pending_delta`=非负 stale count、`.vault_path`=canonical vault。mkdir/write 使用安全 exact path 与 atomic replacement。
4. `.last_update` 必须在写入完成时接近当前时间；state files 不混入其他 vault。写 hot-state-report.md，记录 hot age/refreshed、selected pages、state paths/values/timestamps。

#### 输入

daily-context.md + freshness/index reports + hot.md + 最近修改 live pages

#### 产出

条件更新的 hot.md + vault-scoped state files + hot-state-report.md

#### 验收

1. 复算 hot age；<=48h 确认字节不变，过期时确认约500字、required headings、last-3、语义内容与10个最近 live pages一致且无 staged 声称

2. 检查 .last_update 为最近 epoch、.pending_delta 为 freshness stale_count 非负整数、.vault_path 为 canonical vault，STATE_DIR vault-id 正确

3. 审计写入只限 hot.md（必要时）和当前 vault state files，source/pages/manifest/index/log/QMD 未被越权修改

#### 流程控制

- 验收通过：转到 `validate_cycle`。

- 验收失败：返回 `refresh_hot_and_state`。

- 最多连续失败 `4` 次；达到上限后停止并报告阻塞。

### 5. 调用 impl-validator 复核维护产物并修复 FAIL (`validate_cycle`)

#### 执行

调用 `impl-validator` skill，并把下列输入传给它。以被调用 skill 的验收结果作为本步骤结果。

#### 输入

freshness/index/hot-state artifacts 与实际 vault/state files

调用参数：

- `goal`: Daily wiki maintenance — index reconciled, hot.md refreshed when stale, vault-scoped state written

- `artifacts`: index.md、hot.md、STATE_DIR/.last_update、.pending_delta、.vault_path、freshness/index/hot-state reports

- `checks`: - .last_update 是 60 秒内 Unix timestamp
- .pending_delta 是与 stale_count 相等的非负整数
- hot.md 若本轮刷新则 updated 为今天；未刷新则原时间<=48h
- index.md 精确覆盖 live knowledge page inventory，而非仅“至少一样多”
- vault path/state scope 与 cycle report 一致

#### 产出

impl-validation.md（结构化 verdict，必须无 FAIL）

#### 验收

采用被调用 skill 的验收结论，不在本步骤重复验收。

#### 流程控制

- 验收通过：转到 `log_refresh_report`。

- 验收失败：返回 `validate_cycle`。

- 最多连续失败 `3` 次；达到上限后停止并报告阻塞。

### 6. 幂等记录 DAILY-UPDATE、条件刷新 QMD 并交付报告 (`log_refresh_report`)

#### 执行

1. impl-validator 无 FAIL 后，向 log.md 幂等追加一条带 cycle_id 的 parseable `DAILY-UPDATE fresh=N stale=N missing=N index_added=N hot_refreshed=true|false`；重试时同 cycle_id 只保留一条。
2. 若本 workflow 写过 vault Markdown 且 QMD_WIKI_COLLECTION 配置、CLI 可用，则运行 `${QMD_CLI:-qmd} update`；只在提示 vectors stale/missing 时 embed，再 qmd ls/get 验证。未配置/不可用/失败按 daily-update 标准状态报告，QMD 失败不回滚 vault。
3. 写 daily-update-completion.md：source counts、index total/added/removed/updated、hot refreshed/up-to-date、state paths、impl verdict、stale paths及对应 wiki-history-ingest/wiki-folder-ingest 建议、QMD 状态。
4. 本 workflow 不 ingest stale sources，不更新 permanent manifest，不安装 cron/notification；安装请使用 `wiki/daily-update-setup`。
5. 磁盘事实一致后输出 <promise>done</promise>。

#### 输入

已验证的 cycle artifacts + log.md + QMD config

#### 产出

唯一 DAILY-UPDATE log + daily-update-completion.md + 可选 QMD refresh

#### 验收

1. 核对 log 中 cycle_id 恰好一次且 counts 与 freshness/index/hot reports 一致，completion 报告逐项可复算

2. 确认 stale source 仅报告未摄取、missing 未删除、manifest 未改变，cron/rc/scheduler 未被修改

3. QMD guard/update/embed/verify 与标准状态正确，失败未回滚 vault；最终 impl verdict 无 FAIL

#### 流程控制

- 验收通过：转到 `done`。

- 验收失败：返回 `log_refresh_report`。

- 最多连续失败 `3` 次；达到上限后停止并报告阻塞。

<!-- END GENERATED SKILL INSTRUCTIONS -->
