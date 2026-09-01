---
name: daily-update-setup
description: "经人工审批安装或验证每日 9 点 Wiki 调度、vault-scoped 状态与可选终端提醒"
---

# daily-update-setup

此 skill 是 `workflows/daily-update-setup.yaml` 的 Agent Skill 格式投影；workflow 是行为事实来源，本文件把其字段渲染为可直接执行的 Markdown 指令。

<!-- BEGIN GENERATED SKILL INSTRUCTIONS -->

## 执行规则

按下列步骤和流程控制执行。每个步骤只读取其声明的输入，只产生其声明的产出；执行与独立验收分开进行。修改行为时先编辑权威 workflow，再运行 `python tools/sync_workflow_skills.py`。

- 自动重置：开启。

- 人工审批步骤：`approve_install`。

## 独立验收规则

你是 Daily Update Setup 的安全审计者。系统 scheduler、shell rc、PowerShell profile 和 home 配置只能在人工批准后修改。
必须幂等保留现有任务与配置，不得重复注册或覆盖无关内容。

单次验收超时：`3600000` 毫秒。

## 工作流

### 1. 复用共享子 workflow 解析 scheduler 安装上下文 (`resolve_context`)

#### 执行

调用 `wiki-context` skill，并把下列输入传给它。以被调用 skill 的验收结果作为本步骤结果。

#### 输入

setup invocation 与当前 CWD

调用参数：

- `requested_keys`: OBSIDIAN_VAULT_PATH,OBSIDIAN_WIKI_REPO

- `optional_reads`: owner AGENTS

- `setup_mode`: false

#### 产出

wiki-context.json + wiki-context.md

#### 验收

采用被调用 skill 的验收结论，不在本步骤重复验收。

#### 流程控制

- 验收通过：转到 `inspect_setup`。

- 验收失败：返回 `resolve_context`。

- 最多连续失败 `3` 次；达到上限后停止并报告阻塞。

### 2. 检查脚本、平台、现有调度与通知配置 (`inspect_setup`)

#### 执行

使用 wiki-context.json 检查 scheduler setup。

1. 使用 context 的 canonical OBSIDIAN_VAULT_PATH/OBSIDIAN_WIKI_REPO，并派生 vault-scoped STATE_DIR。
2. 检测 macOS/Linux/Windows、headless 状态、shell/rc/profile、scheduler 工具与当前 9:00 task。读取但不修改现有 launchd plist/cron/Task Scheduler entry。
3. 验证 repo scripts：daily-update.sh 或 daily-update.py、wiki-notify.sh/py、macOS plist；检查存在、可读/可执行、plist XML/Label/ProgramArguments 与绝对 repo path。
4. 询问用户是否安装 terminal notification；headless/VPS 默认 skip。列出 exact scheduler/rc/profile targets、commands、existing/preserve/replace decision、日志路径与 rollback 方法。
5. 写 daily-setup-plan.md。此步骤不得写 scheduler、home config、vault/state 或运行 update。

#### 输入

“set up daily cron / install terminal notification” 请求（vault 由 wiki-context 交互式确认）

#### 产出

daily-setup-plan.md（platform、scripts、exact changes、notification choice）

#### 验收

1. 复核 config/vault/repo/state、OS/shell/headless detection 和 scripts/plist validity，所有 exact targets 存在或有明确创建计划

2. 审计现有 scheduler/rc/profile，plan 能幂等 preserve/replace 而不重复或覆盖无关 entries

3. 用户 notification 选择、9:00 schedule、logs/state/rollback 清楚，且本步骤确实零写入

#### 流程控制

- 验收通过：转到 `approve_install`。

- 验收失败：返回 `inspect_setup`。

- 最多连续失败 `3` 次；达到上限后停止并报告阻塞。

### 3. 人工批准 scheduler 与可选 notification 的系统级变更 (`approve_install`)

#### 执行

展示 daily-setup-plan.md 的 exact commands/targets，写 approval-request.md 和 approved-daily-setup.json（绑定 plan hash、vault、repo、platform、scheduler action、notification action）。

用户运行 /ralphflow-continue 表示批准该 JSON；修改选择时先更新 binding 再等待，拒绝则取消。批准前不得写 LaunchAgents、crontab、Task Scheduler、shell rc/profile、state 或 vault。输出 <promise>done</promise> 后等待人工门。

#### 输入

daily-setup-plan.md + 用户 yes/no/select

#### 产出

approval-request.md + approved-daily-setup.json

#### 验收

确认批准绑定当前 plan hash/vault/repo，actions 是计划子集且用户明确通过人工门；此前 scheduler/home/vault/state 零变化。

#### 流程控制

- 验收通过：转到 `install_schedule`。

- 验收失败：返回 `approve_install`。

- 最多连续失败 `3` 次；达到上限后停止并报告阻塞。

### 4. 幂等安装平台调度与获批终端提醒 (`install_schedule`)

#### 执行

只执行 approved-daily-setup.json：

1. macOS：将 repo placeholder 替换为 canonical path 写 `~/Library/LaunchAgents/com.obsidian-wiki.daily-update.plist`，验证 XML 后幂等 unload/load；Label 与 filename 一致。
2. Linux：保留现有 crontab，排序去重加入 `0 9 * * * <repo>/scripts/daily-update.sh >> /tmp/obsidian-wiki-daily.log 2>&1`，不得删除其他 jobs。
3. Windows：幂等 create/replace `ObsidianWikiDailyUpdate` 09:00 task，command/path 正确。
4. notification 仅在批准且非 headless 时：bash/zsh 向对应 rc、PowerShell 向 PROFILE 加一个有 marker 的 source/call entry；存在则不重复。unsupported shell 只报告 manual instruction。
5. 所有修改采用备份/验证；写 install-report.md，记录 applied/skipped/existing、targets、commands、backups、errors。不得修改 vault pages。

#### 输入

approved-daily-setup.json

#### 产出

平台 scheduler + 可选 notification + install-report.md

#### 验收

1. 按平台检查 scheduler 真实配置、09:00、script absolute path、log redirect/Label/task name，且其他现有 jobs/config 保留

2. notification 与批准/headless/shell 一致，rc/profile marker 恰好一次，script path 有效，无重复或无关覆盖

3. 将实际系统 diff 与 approved actions 对账，backup/rollback 可用，vault pages/manifest 未改变

#### 流程控制

- 验收通过：转到 `initialize_and_verify`。

- 验收失败：返回 `install_schedule`。

- 最多连续失败 `4` 次；达到上限后停止并报告阻塞。

### 5. 运行一次 daily-update 并验证调度、状态与通知 (`initialize_and_verify`)

#### 执行

1. 按平台运行 repo daily-update.sh 或 daily-update.py 一次，初始化当前 vault STATE_DIR；不得用另一个 vault 的 state。
2. 验证 `.last_update` recent、`.pending_delta` 非负、`.vault_path` canonical，并检查 scheduler loaded/enabled/next run 与 notification script source。
3. 写 daily-setup-completion.md：platform、schedule 9AM、missed-login 行为（仅适用时）、notification status、state dir、last run、log path、verification、rollback 与手动 `/wiki-daily-update` 命令。
4. 若首次 daily update 失败，保留安装但明确 FAIL/修复建议，不虚报完成；修复 in-scope 配置后重验。
5. 全部 required checks 通过后输出 <promise>done</promise>。

#### 输入

install-report.md + scheduler/home config + 首次 daily-update 结果

#### 产出

initialized state + daily-setup-completion.md

#### 验收

1. 独立核对 scheduler loaded/enabled、09:00、exact script、state files recent/correct vault 和 daily run结果

2. 验证 notification approved时可加载、declined/headless时无改动，completion 对 platform/missed behavior/logs 描述准确

3. 重复执行 setup 不产生 duplicate cron/LaunchAgent/task/rc entry，失败真实披露且 rollback 信息有效

#### 流程控制

- 验收通过：转到 `done`。

- 验收失败：返回 `initialize_and_verify`。

- 最多连续失败 `4` 次；达到上限后停止并报告阻塞。

<!-- END GENERATED SKILL INSTRUCTIONS -->
