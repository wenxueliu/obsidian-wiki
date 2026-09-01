---
name: wiki-rebuild
description: "经人工确认先归档，再安全执行 Wiki snapshot、清空重建准备或 archive restore"
---

# wiki-rebuild

此 skill 是 `workflows/wiki-rebuild.yaml` 的 Agent Skill 格式投影；workflow 是行为事实来源，本文件把其字段渲染为可直接执行的 Markdown 指令。

<!-- BEGIN GENERATED SKILL INSTRUCTIONS -->

## 执行规则

按下列步骤和流程控制执行。每个步骤只读取其声明的输入，只产生其声明的产出；执行与独立验收分开进行。修改行为时先编辑权威 workflow，再运行 `python tools/sync_workflow_skills.py`。

- 自动重置：开启。

- 人工审批步骤：`approve_operation`。

## 独立验收规则

你是 Wiki Rebuild 的破坏性操作审计者。任何 clear/restore 前必须有完整可验证 archive 与人工批准。
永远不得删除 _archives 或触碰 .obsidian/.env；rebuild 只清空 live wiki 并停止，不自动重 ingest。

单次验收超时：`3600000` 毫秒。

## 工作流

### 1. 复用共享子 workflow 解析 archive/rebuild/restore 上下文 (`resolve_context`)

#### 执行

调用 `wiki-context` skill，并把下列输入传给它。以被调用 skill 的验收结果作为本步骤结果。

#### 输入

operation invocation 与当前 CWD

调用参数：

- `requested_keys`: OBSIDIAN_VAULT_PATH,QMD_TRANSPORT,QMD_WIKI_COLLECTION,QMD_CLI_SEARCH_MODE

- `optional_reads`: owner AGENTS,index,manifest,active layout

- `setup_mode`: false

#### 产出

wiki-context.json + wiki-context.md

#### 验收

采用被调用 skill 的验收结论，不在本步骤重复验收。

#### 流程控制

- 验收通过：转到 `inspect_and_plan`。

- 验收失败：返回 `resolve_context`。

- 最多连续失败 `3` 次；达到上限后停止并报告阻塞。

### 2. 解析模式、vault 与精确 archive/rebuild/restore 计划 (`inspect_and_plan`)

#### 执行

使用 wiki-context.json 规划 rebuild/archive/restore。

1. 使用 context 的 canonical vault、QMD、manifest/index 与 active layout；按需只读 log，不得重新解析 profile。
2. 识别且只允许 archive-only、archive+rebuild、restore 三种模式；未明确时列出选择，不猜 destructive intent。
3. 按 routing.content_roots 统计 live pages、sources/projects 和需要归档的 index/log/manifest；列出必须保留的 archive/config 及其他 routing system/skip dirs。
4. restore 模式扫描 _archives/*/archive-meta.json，canonicalize 候选，验证目录边界、metadata、必需内容与可读性；绑定用户选择的唯一 archive。
5. 生成 timestamped destination（不得已存在）、copy manifest、clear allowlist、restore source、验证步骤、failure recovery 和 QMD plan。
6. 先在内存中形成唯一 canonical rebuild plan result；`rebuild-plan.json` 完整承载 stable plan_id、模式、inventory、所有路径/hash、动作与恢复方法，Markdown 只从同一 result 渲染、不得独立推导或补充事实，并在同一批 artifact 写入中提交二者。不得创建 archive 或修改 vault。

#### 输入

archive、archive+rebuild 或 restore 请求（可含 archive id）

#### 产出

rebuild-plan.md + rebuild-plan.json

#### 验收

1. 复核 config/vault/mode、live inventory/counts、active layout 和 archive candidate metadata，所有 canonical paths 无 escape

2. 审计 copy/clear/restore allowlists，确认 _archives/.obsidian/.env 永不在删除/覆盖集合且 rebuild 不自动 ingest

3. 解析 rebuild plan JSON，逐项核对 Markdown 的 plan_id、mode、counts、paths/hashes、actions、QMD、warnings 与恢复方法是同一 canonical result 的准确投影；确认当前 vault 完全未改变

#### 流程控制

- 验收通过：转到 `approve_operation`。

- 验收失败：返回 `inspect_and_plan`。

- 最多连续失败 `3` 次；达到上限后停止并报告阻塞。

### 3. 人工批准绑定当前 vault 与 hash 的归档或破坏性操作 (`approve_operation`)

#### 执行

展示 rebuild-plan.md：模式、exact source/destination、pages/sources counts、将 copy/clear/restore 的路径、保留项、QMD 与回退方法。archive+rebuild/restore 明确警告 live wiki 会被替换；restore 再确认 archive id。

将用户确认写 approved-rebuild.json，绑定 plan_id/hash、canonical vault、mode、destination、restore source 与当前 state hashes。拒绝则取消。输出 <promise>done</promise> 后等待人工门；批准前不得写 vault。

#### 输入

rebuild-plan.md + 用户明确 confirm/cancel/archive selection

#### 产出

approved-rebuild.json（绑定 plan hash 的明确批准）

#### 验收

确认批准与用户选择一致，vault/mode/paths/hashes 绑定当前 plan；destructive 模式有明确 overwrite consent；人工门前没有 archive 或 vault 写入。

#### 流程控制

- 验收通过：转到 `create_archive`。

- 验收失败：返回 `approve_operation`。

- 最多连续失败 `3` 次；达到上限后停止并报告阻塞。

### 4. 创建并验证不可变的 pre-operation archive (`create_archive`)

#### 执行

只按 approved-rebuild.json 创建 `_archives/YYYY-MM-DDTHH-MM-SSZ/`：

1. archive-only/rebuild reason 为 snapshot/rebuild；restore 先以 pre-restore reason 归档当前 live state。
2. 复制 active routing.content_roots、index.md、log.md、manifest 和 owner-required live special files；绝不递归复制 routing system/skip dirs、config 或 archive root，避免 archive-in-archive。
3. 写 archive-meta.json：archived_at/reason/counts/vault_path/manifest_snapshot/source hashes/plan_id。
4. 对源与副本逐文件 inventory、size/hash/count 验证；archive 必需文件缺失或不一致即停止，不能进入 mutation。
5. 写 archive-verification.md，记录 destination、hash manifest、counts 与恢复说明。archive-only 模式可在后续步骤只执行日志/no-op。

#### 输入

approved-rebuild.json + 当前 live wiki

#### 产出

完整 timestamped archive + archive-verification.md

#### 验收

1. 独立比较 archive 与批准时 live inventory/hash/counts，active layout content_roots/special/manifest 内容完整且 archive-meta 准确

2. 确认没有复制 nested _archives/.obsidian/.env，没有修改/删除 live knowledge，archive destination 唯一且在 vault/_archives 内

3. archive+rebuild/restore 只有在 archive 完全可恢复时才可继续，失败没有执行 destructive mutation

#### 流程控制

- 验收通过：转到 `mutate_live`。

- 验收失败：返回 `create_archive`。

- 最多连续失败 `3` 次；达到上限后停止并报告阻塞。

### 5. 按获批模式保持、清空或恢复 live wiki (`mutate_live`)

#### 执行

先验证 approved plan/current state 与 archive-verification；不一致停止。

1. archive-only：保持 live knowledge/manifest/index 不变，只记录 no-op mutation。
2. archive+rebuild：仅清除 allowlisted routing.content_roots 内容；保留根目录、routing system/skip dirs 与 config。将 index.md 重置为空模板，log.md 重置为 rebuild entry，删除 manifest 使后续来源均为 new。不得启动任何 ingest。
3. restore：验证 selected archive 后仅清除 active layout routing 声明的 allowlisted live content_roots，再复制 archive content roots/index/log/manifest 回 live；system/skip dirs 来自 frozen routing，绝不从 archive 覆盖 config、layout marker 或 archive root。向恢复后的 log 追加 RESTORE。
4. 所有写入采用 staging/temp + atomic rename 可行处；失败时停止并在报告中给 pre-operation archive，不虚报成功。
5. 写 live-mutation-report.md，列实际 deletes/copies/preserved、before/after counts/hash、log/manifest 状态。

#### 输入

approved-rebuild.json + verified archive + 当前 live state

#### 产出

按模式处理的 live wiki + live-mutation-report.md

#### 验收

1. 将实际 filesystem diff 与 mode/allowlist 对账；archive-only live 不变，rebuild 仅保留模板，restore 与 selected archive 内容一致

2. 确认 _archives（含新 archive）、.obsidian、.env 全部完整，未删除 archive、未越界修改且无自动 ingest

3. 核对 rebuild/RESTORE log、manifest delete/restore、index template/restore 和 counts/hash；失败状态真实且 recovery 可用

#### 流程控制

- 验收通过：转到 `refresh_and_report`。

- 验收失败：返回 `mutate_live`。

- 最多连续失败 `3` 次；达到上限后停止并报告阻塞。

### 6. 验证最终状态、条件刷新 QMD 并交付恢复路线 (`refresh_and_report`)

#### 执行

1. archive-only 向 live log 幂等追加 ARCHIVE plan_id（pages/destination），live content 不变；QMD 仅在 log 被索引且已配置时可选刷新，否则记录 live unchanged。
2. archive+rebuild 必须 QMD update，需时 embed，并验证 collection 不再返回已清除页；restore 必须 update+按需 embed，并 get 一个 restored page。QMD unset/unavailable/error 分别报告，不回滚 Markdown。
3. 写 wiki-rebuild-completion.md：mode、archive destination/meta、previous/final counts、preserved dirs、manifest/index/log、QMD、warnings 与 recovery。
4. rebuild 模式只建议下一步依次选择 wiki-status、claude-history-ingest、codex-history-ingest、wiki-folder-ingest；不自动执行。restore 建议 wiki-lint。
5. 最终事实与磁盘一致后输出 <promise>done</promise>。

#### 输入

archive verification + live mutation report + 最终 vault/QMD

#### 产出

幂等 archive/rebuild/restore tracking + completion + 条件 QMD refresh

#### 验收

1. 从最终 vault/archive 重算 pages/sources/projects 和 hashes，确认 completion、log、manifest/index 与 mode 一致且 archive 可恢复

2. 核对 QMD mode guard/update/embed/verification 与报告；失败未回滚 vault，archive-only 未做不必要变更

3. 确认最终没有自动 ingest、没有删除 archive/修改 .obsidian/.env，next workflow 建议符合本 skill 的模式边界

#### 流程控制

- 验收通过：转到 `done`。

- 验收失败：返回 `refresh_and_report`。

- 最多连续失败 `3` 次；达到上限后停止并报告阻塞。

<!-- END GENERATED SKILL INSTRUCTIONS -->
