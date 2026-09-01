---
name: wiki-setup
description: "经人工确认后安全初始化或修复 Obsidian wiki 的配置、layout、核心文件与可选集成"
---

# wiki-setup

此 skill 是 `workflows/wiki-setup.yaml` 的 Agent Skill 格式投影；workflow 是行为事实来源，本文件把其字段渲染为可直接执行的 Markdown 指令。

<!-- BEGIN GENERATED SKILL INSTRUCTIONS -->

## 执行规则

按下列步骤和流程控制执行。每个步骤只读取其声明的输入，只产生其声明的产出；执行与独立验收分开进行。修改行为时先编辑权威 workflow，再运行 `python tools/sync_workflow_skills.py`。

- 自动重置：开启。

- 人工审批步骤：`approve_setup`。

## 独立验收规则

你是 Wiki Setup 的安全审计者。批准前不得写文件；批准后不得覆盖 owner 现有配置、Writing Profile、vault 内容或 hooks。
网络、Git sync、全局 hook 等可选外部变更只能执行 setup plan 中明确获批的项目。
每个执行阶段只生成该步骤声明的状态或 artifact；独立验收阶段只核对本步目标、preserve 边界和必要副作用，不重复全量推理。

单次验收超时：`3600000` 毫秒。

## 工作流

### 1. 按共享规则解析现有配置，允许尚未初始化的 vault (`resolve_existing_context`)

#### 执行

调用 `wiki-context` skill，并把下列输入传给它。以被调用 skill 的验收结果作为本步骤结果。

#### 输入

setup invocation、source CWD 与可能存在的 config/vault metadata

调用参数：

- `requested_keys`: OBSIDIAN_VAULT_PATH,OBSIDIAN_SOURCES_DIR,CLAUDE_HISTORY_PATH,QMD_WIKI_COLLECTION,QMD_PAPERS_COLLECTION,QMD_TRANSPORT,QMD_CLI_SEARCH_MODE,WIKI_TOKEN_WARN_THRESHOLD,WIKI_STAGED_WRITES,WIKI_FOLDER_INGEST_MAX_EXTRACTION_WORKERS,WIKI_TEXT_DIRECT_EXTRACT_MAX_BYTES,WIKI_TEXT_CHUNK_TARGET_BYTES,WIKI_TEXT_CHUNK_MIN_BYTES,WIKI_TEXT_CHUNK_HARD_MAX_BYTES,WIKI_TEXT_CHUNK_STRATEGY,WIKI_TEXT_CHUNK_OPTIONS,OBSIDIAN_WIKI_REPO

- `optional_reads`: existing config, vault metadata, AGENTS.md, active layout metadata, QMD collection metadata

- `setup_mode`: true

#### 产出

wiki-context.json + wiki-context.md

#### 验收

采用被调用 skill 的验收结论，不在本步骤重复验收。

#### 流程控制

- 验收通过：转到 `load_setup_contract`。

- 验收失败：返回 `resolve_existing_context`。

- 最多连续失败 `3` 次；达到上限后停止并报告阻塞。

### 2. 生成仓库内自包含的精确初始化契约 (`load_setup_contract`)

#### 执行

调用 `wiki-setup-contract` skill，并把下列输入传给它。以被调用 skill 的验收结果作为本步骤结果。

#### 输入

wiki-context.json 中的非秘密 invocation metadata

调用参数：

- `invocation_metadata`: wiki-context.json 中的 resolution mode、canonical paths 与 configured/unconfigured 状态；不得传递秘密明文

#### 产出

setup-contract.md + setup-contract.json

#### 验收

采用被调用 skill 的验收结论，不在本步骤重复验收。

#### 流程控制

- 验收通过：转到 `plan_setup`。

- 验收失败：返回 `load_setup_contract`。

- 最多连续失败 `3` 次；达到上限后停止并报告阻塞。

### 3. 收集配置选择并形成零写入 setup plan (`plan_setup`)

#### 执行

以 `wiki-context.json` 的磁盘事实和 `setup-contract.json/md` 的精确默认值、模板、命令与验收条款为唯一依据，形成 setup plan，不读取外部规范或示例配置。

先区分新建或 repair，并盘点唯一 config path、canonical vault、active Knowledge Pack（固定配对的 Knowledge Profile + Vault Layout）、core files、Writing Profile、QMD collection、hooks 与 Git remote。只询问尚未确定或需要用户选择的项目：vault/source/history paths、Knowledge Pack/layout、QMD、token threshold、staged writes，以及是否安装 Stop hook、配置 private Git sync和准确 repo URL。采用默认值时也要在 plan 明示。

在 `setup-plan.md` 列出 exact targets、每项 create/preserve/minimal-repair、原子写策略、required checks，以及所有需要 home/network/git/QMD 变更的 optional approvals。现有 `.env`、WRITING.md、core files、hooks、custom dirs 和 owner data 默认 preserve；此步骤零写入。

#### 输入

wiki-context.json + setup-contract.json/md + 用户的初始化/修复请求与配置选择

#### 产出

setup-plan.md（exact paths、defaults、create/preserve/repair、optional approvals、contract version/hash）

#### 验收

核对 plan 的绝对 vault path、layout、必需配置、preserve/repair 策略和可选动作选择均已明确；确认零写入

#### 流程控制

- 验收通过：转到 `approve_setup`。

- 验收失败：返回 `plan_setup`。

- 最多连续失败 `3` 次；达到上限后停止并报告阻塞。

### 4. 人工审批 setup 的全部本地与外部变更 (`approve_setup`)

#### 执行

展示 setup-plan.md 的精简变更清单与 exact targets，写 approval-request.md 和 approved-setup.json，绑定 plan hash、setup contract hash、vault、config path、create/preserve/repair 集合及 approved optional actions。

用户运行 /ralphflow-continue 表示批准当前 binding；如修改选择，先更新 plan/binding 再重新等待。拒绝则取消 workflow。批准前不得创建目录、配置、QMD collection、hook、Git repo 或 remote。准备好后输出 <promise>done</promise>。

#### 输入

setup-plan.md + 用户批准/修改/拒绝

#### 产出

approval-request.md + approved-setup.json

#### 验收

核对 approved binding 的 plan/contract hash、targets 和 optional actions 与用户明确批准一致；确认批准前零变更

#### 流程控制

- 验收通过：转到 `write_config`。

- 验收失败：返回 `approve_setup`。

- 最多连续失败 `3` 次；达到上限后停止并报告阻塞。

### 5. 生成或最小更新 Wiki 配置 (`write_config`)

#### 执行

根据 approved-setup.json 与 setup contract 的 config binding 生成目标配置。缺失时创建；repair 时 read-modify-write，保留未知字段、注释和秘密值。使用 sibling temp 原子替换。

写 `config-report.md`，记录 target、created/preserved/repaired、effective non-secret values 和秘密值的 configured/unconfigured 状态。

#### 输入

approved-setup.json + setup-contract.json/md + wiki-context.json + 现有 config（如有）

#### 产出

config + config-report.md

#### 验收

解析目标 config，核对 approved path、required typed values 和 report；repair 时确认未知字段、注释和秘密值保留，且未改变其他 setup 状态

#### 流程控制

- 验收通过：转到 `initialize_writing_profile`。

- 验收失败：返回 `write_config`。

- 最多连续失败 `4` 次；达到上限后停止并报告阻塞。

### 6. 生成缺失的全局 Writing Profile (`initialize_writing_profile`)

#### 执行

根据 approved binding 和冻结的 `WRITING.md` 模板，在目标缺失时创建全局 Writing Profile；目标已存在时保持原文并记录 preserved。

写 `writing-profile-report.md`，记录 target 与 created/preserved 状态。

#### 输入

approved-setup.json + setup-contract.json/md + config-report.md + 现有 WRITING.md（如有）

#### 产出

WRITING.md（仅缺失时）+ writing-profile-report.md

#### 验收

核对平台 target 与 report；新建时内容匹配冻结模板，已存在时保持原文；确认未改变其他 setup 状态

#### 流程控制

- 验收通过：转到 `apply_layout`。

- 验收失败：返回 `initialize_writing_profile`。

- 最多连续失败 `3` 次；达到上限后停止并报告阻塞。

### 7. 生成选定的 Vault layout (`apply_layout`)

#### 执行

使用 approved Knowledge Pack/layout name、canonical vault 和 artifacts 目录运行 bundled layout copier：

```bash
obsidian-wiki wiki-layout-apply \
  --layout "<approved-layout>" \
  --vault "<canonical-vault>" \
  --output-dir "{{artifacts_dir}}"
```

console script 不在 PATH 时使用等价的 `python3 -m obsidian_wiki wiki-layout-apply ...`。同名 contract refresh 仅在 approved binding 含该动作时追加 `--refresh-layout-marker`。

copier 按 missing-only policy 生成 layout 目录、预制文件、绑定 Profile/Layout/Routing hashes 的 `_meta/layout.json` 和 `layout-apply-report.json`。Profile 与 Layout 在当前版本一对一发布；setup 不执行内容级领域识别。

#### 输入

approved-setup.json + setup-contract.json/md + config-report.md + canonical vault

#### 产出

vault layout tree + _meta/layout.json + layout-apply-report.json

#### 验收

解析 layout marker/report，核对 approved vault、Knowledge Profile/Layout name/version 和 profile/layout/routing contract hashes，确认 required inventory 存在、overwritten_files 为空，且无 path escape 或未批准 Knowledge Pack 切换

#### 流程控制

- 验收通过：转到 `initialize_core`。

- 验收失败：返回 `apply_layout`。

- 最多连续失败 `4` 次；达到上限后停止并报告阻塞。

### 8. 按精确模板幂等创建或最小修复核心文件 (`initialize_core`)

#### 执行

按 approved binding 使用 setup contract 中冻结的 index.md、log.md、hot.md、.manifest.json、app.json、appearance.json 内容，替换 timestamp、canonical vault path、active categories 和 index sections。

缺失文件按模板创建；repair 对现有内容做 minimal patch，保留 pages、manifest/log/index/hot 历史、owner frontmatter 和未知 Obsidian JSON keys。使用 sibling temp 原子替换，写 `core-files-report.md` 记录逐文件 created/preserved/repaired、diff 摘要和 contract hash。

#### 输入

approved-setup.json + setup-contract.json/md + config-report.md + writing-profile-report.md + layout-apply-report.json + 现有 core files

#### 产出

完整 core files/.obsidian config + core-files-report.md

#### 验收

核对 report 中的 approved core targets；确认 JSON 可解析、Markdown 具备必需 frontmatter/headings，新建文件包含契约动态值，repair 保留 owner 字段、历史和未知 settings

#### 流程控制

- 验收通过：转到 `configure_stop_hook`。

- 验收失败：返回 `initialize_core`。

- 最多连续失败 `4` 次；达到上限后停止并报告阻塞。

### 9. 生成已批准的 Stop hook 配置 (`configure_stop_hook`)

#### 执行

若 Stop hook 获批，按 contract 的平台脚本与 settings merge 策略写入 hook 配置；需要且获批下载时获取 canonical copy。未获批时不改变 hook 状态。

写 `stop-hook-report.md`，记录 installed/skipped/failed、目标路径、command、sentinel、卸载方式和 HIVEMIND_CAPTURE 单次开关。

#### 输入

approved-setup.json + setup-contract.json/md + 现有 hook/settings 状态

#### 产出

Stop hook 配置（如获批）+ stop-hook-report.md

#### 验收

对照 approval 核对 report 与最终 Stop hook entry；installed 时 command/sentinel 正确且保留旧 hooks，skipped 时状态未改变

#### 流程控制

- 验收通过：转到 `configure_git_sync`。

- 验收失败：返回 `configure_stop_hook`。

- 最多连续失败 `3` 次；达到上限后停止并报告阻塞。

### 10. 生成已批准的 Vault Git sync 配置 (`configure_git_sync`)

#### 执行

若 Git sync 获批，使用 contract 声明的首选 CLI 为 canonical vault 配置 Git 与用户提供的 remote；console binary 不可用时使用 contract 的本地 repo/PYTHONPATH fallback。未获批时不改变 Git 状态。

写 `git-sync-report.md`，记录 configured/skipped/failed、vault root、remote、所用入口和后续 sync 命令；秘密仅记录 configured/unconfigured。

#### 输入

approved-setup.json + setup-contract.json/md + canonical vault + 现有 Git 状态

#### 产出

Vault Git sync 配置（如获批）+ git-sync-report.md

#### 验收

对照 approval 核对 report、vault Git root 和 origin；configured 时 remote 精确且无 credential 泄露，skipped 时 Git 状态未改变

#### 流程控制

- 验收通过：转到 `configure_qmd_collection`。

- 验收失败：返回 `configure_git_sync`。

- 最多连续失败 `3` 次；达到上限后停止并报告阻塞。

### 11. 生成已批准的 QMD collection 配置 (`configure_qmd_collection`)

#### 执行

若 QMD 配置获批，按 contract 和 approved names/path 写入 wiki/papers collection 配置以及 `_raw/**` exclusion；未获批或未配置时不改变 QMD 配置。

写 `qmd-collection-report.md`，记录 configured/skipped/failed、collection names、paths、patterns 和 exclusions。

#### 输入

approved-setup.json + setup-contract.json/md + canonical vault + 现有 QMD config

#### 产出

QMD collection 配置（如获批）+ qmd-collection-report.md

#### 验收

对照 approval 解析 QMD config/report；configured 时确认 canonical paths、`_raw/**` exclusion、wiki/papers disjoint 且无 duplicate，skipped 时 QMD 配置未改变

#### 流程控制

- 验收通过：转到 `refresh_qmd_index`。

- 验收失败：返回 `configure_qmd_collection`。

- 最多连续失败 `3` 次；达到上限后停止并报告阻塞。

### 12. 生成已批准的 QMD 索引刷新结果 (`refresh_qmd_index`)

#### 执行

若 approved binding 要求刷新且上一 step 的 collection check 已通过，运行 `qmd update`；初始空 vault 按 contract 生成 skipped 结果。

写 `qmd-refresh-report.md`，记录 updated/skipped/failed、命令结果与 collection。

#### 输入

approved-setup.json + setup-contract.json/md + qmd-collection-report.md

#### 产出

QMD index refresh（如获批）+ qmd-refresh-report.md

#### 验收

核对 approval、collection guard 与 refresh report 的 command/exit status；updated 时只改变目标 QMD index/cache，skipped/failed 时未损坏 setup 已生成状态

#### 流程控制

- 验收通过：转到 `render_setup_completion`。

- 验收失败：返回 `refresh_qmd_index`。

- 最多连续失败 `3` 次；达到上限后停止并报告阻塞。

### 13. 生成 setup 交付报告 (`render_setup_completion`)

#### 执行

汇总 approved plan、contract hash、config/layout/core 及各 optional report，写 `setup-completion.md`。逐项列出 reported pass/fail、created/preserved/repaired/skipped、warnings、四个手动插件及用途，以及 Open Vault、status、ingest、Claude history、Codex history、再次 status 六个 next steps。

当输入 reports 均为 pass/skipped 时输出 `<promise>done</promise>`；否则在 completion 中列出失败及所属 step。

#### 输入

setup-contract.json/md + approved-setup.json + config/layout/core/optional reports + 最终 config/vault

#### 产出

setup-completion.md

#### 验收

仅对账 approved plan 与各 step report，确认 required 状态均为 pass、optional 状态如实、completion 包含 plugins/next steps；有 required failure 时不得输出完成 promise

#### 流程控制

- 验收通过：转到 `done`。

- 验收失败：返回 `plan_setup`。

- 最多连续失败 `4` 次；达到上限后停止并报告阻塞。

<!-- END GENERATED SKILL INSTRUCTIONS -->
