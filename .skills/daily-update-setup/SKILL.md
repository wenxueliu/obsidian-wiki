---
name: daily-update-setup
description: "经人工审批安装或验证每日 9 点 Wiki 调度、vault-scoped 状态与可选终端提醒"
---

# daily-update-setup

此 skill 直接执行下方从 `workflows/daily-update-setup.yaml` 同步的完整契约。内嵌 YAML 是实际指令，不是摘要或外部参考；按 `steps`、输入输出、检查、跳转、失败上限和人工审批要求逐项执行。

发生任何冲突时，以内嵌 workflow 契约为准。不要用历史 skill 文案补写、弱化或覆盖它。修改行为时先编辑 workflow，再运行 `python tools/sync_workflow_skills.py`。

<!-- BEGIN GENERATED WORKFLOW CONTRACT -->
````yaml
description: 经人工审批安装或验证每日 9 点 Wiki 调度、vault-scoped 状态与可选终端提醒

auto_reset: true

manual_step:
  - approve_install

adversarial_check:
  timeout_ms: 3600000
  system_prompt: |
    你是 Daily Update Setup 的安全审计者。系统 scheduler、shell rc、PowerShell profile 和 home 配置只能在人工批准后修改。
    必须幂等保留现有任务与配置，不得重复注册或覆盖无关内容。

steps:
  - id: resolve_context
    desc: 复用共享子 workflow 解析 scheduler 安装上下文
    workflow: wiki-context
    input: setup invocation 与当前 CWD
    output: wiki-context.json + wiki-context.md
    inputs:
      requested_keys: OBSIDIAN_VAULT_PATH,OBSIDIAN_WIKI_REPO
      optional_reads: owner AGENTS
      setup_mode: "false"
    on_pass: inspect_setup
    on_fail: resolve_context
    max_fail_count: 3

  - id: inspect_setup
    desc: 检查脚本、平台、现有调度与通知配置
    do: |
      使用 wiki-context.json 检查 scheduler setup。

      1. 使用 context 的 canonical OBSIDIAN_VAULT_PATH/OBSIDIAN_WIKI_REPO，并派生 vault-scoped STATE_DIR。
      2. 检测 macOS/Linux/Windows、headless 状态、shell/rc/profile、scheduler 工具与当前 9:00 task。读取但不修改现有 launchd plist/cron/Task Scheduler entry。
      3. 验证 repo scripts：daily-update.sh 或 daily-update.py、wiki-notify.sh/py、macOS plist；检查存在、可读/可执行、plist XML/Label/ProgramArguments 与绝对 repo path。
      4. 询问用户是否安装 terminal notification；headless/VPS 默认 skip。列出 exact scheduler/rc/profile targets、commands、existing/preserve/replace decision、日志路径与 rollback 方法。
      5. 写 daily-setup-plan.md。此步骤不得写 scheduler、home config、vault/state 或运行 update。
    input: “set up daily cron / install terminal notification” 请求（vault 由 wiki-context 交互式确认）
    output: daily-setup-plan.md（platform、scripts、exact changes、notification choice）
    check_voting:
      - check: 复核 config/vault/repo/state、OS/shell/headless detection 和 scripts/plist validity，所有 exact targets 存在或有明确创建计划
      - check: 审计现有 scheduler/rc/profile，plan 能幂等 preserve/replace 而不重复或覆盖无关 entries
      - check: 用户 notification 选择、9:00 schedule、logs/state/rollback 清楚，且本步骤确实零写入
    on_pass: approve_install
    on_fail: inspect_setup
    max_fail_count: 3

  - id: approve_install
    desc: 人工批准 scheduler 与可选 notification 的系统级变更
    do: |
      展示 daily-setup-plan.md 的 exact commands/targets，写 approval-request.md 和 approved-daily-setup.json（绑定 plan hash、vault、repo、platform、scheduler action、notification action）。

      用户运行 /ralphflow-continue 表示批准该 JSON；修改选择时先更新 binding 再等待，拒绝则取消。批准前不得写 LaunchAgents、crontab、Task Scheduler、shell rc/profile、state 或 vault。输出 <promise>done</promise> 后等待人工门。
    input: daily-setup-plan.md + 用户 yes/no/select
    output: approval-request.md + approved-daily-setup.json
    check: |
      确认批准绑定当前 plan hash/vault/repo，actions 是计划子集且用户明确通过人工门；此前 scheduler/home/vault/state 零变化。
    on_pass: install_schedule
    on_fail: approve_install
    max_fail_count: 3

  - id: install_schedule
    desc: 幂等安装平台调度与获批终端提醒
    do: |
      只执行 approved-daily-setup.json：

      1. macOS：将 repo placeholder 替换为 canonical path 写 `~/Library/LaunchAgents/com.obsidian-wiki.daily-update.plist`，验证 XML 后幂等 unload/load；Label 与 filename 一致。
      2. Linux：保留现有 crontab，排序去重加入 `0 9 * * * <repo>/scripts/daily-update.sh >> /tmp/obsidian-wiki-daily.log 2>&1`，不得删除其他 jobs。
      3. Windows：幂等 create/replace `ObsidianWikiDailyUpdate` 09:00 task，command/path 正确。
      4. notification 仅在批准且非 headless 时：bash/zsh 向对应 rc、PowerShell 向 PROFILE 加一个有 marker 的 source/call entry；存在则不重复。unsupported shell 只报告 manual instruction。
      5. 所有修改采用备份/验证；写 install-report.md，记录 applied/skipped/existing、targets、commands、backups、errors。不得修改 vault pages。
    input: approved-daily-setup.json
    output: 平台 scheduler + 可选 notification + install-report.md
    check_voting:
      - check: 按平台检查 scheduler 真实配置、09:00、script absolute path、log redirect/Label/task name，且其他现有 jobs/config 保留
      - check: notification 与批准/headless/shell 一致，rc/profile marker 恰好一次，script path 有效，无重复或无关覆盖
      - check: 将实际系统 diff 与 approved actions 对账，backup/rollback 可用，vault pages/manifest 未改变
    on_pass: initialize_and_verify
    on_fail: install_schedule
    max_fail_count: 4

  - id: initialize_and_verify
    desc: 运行一次 daily-update 并验证调度、状态与通知
    do: |
      1. 按平台运行 repo daily-update.sh 或 daily-update.py 一次，初始化当前 vault STATE_DIR；不得用另一个 vault 的 state。
      2. 验证 `.last_update` recent、`.pending_delta` 非负、`.vault_path` canonical，并检查 scheduler loaded/enabled/next run 与 notification script source。
      3. 写 daily-setup-completion.md：platform、schedule 9AM、missed-login 行为（仅适用时）、notification status、state dir、last run、log path、verification、rollback 与手动 `/wiki-daily-update` 命令。
      4. 若首次 daily update 失败，保留安装但明确 FAIL/修复建议，不虚报完成；修复 in-scope 配置后重验。
      5. 全部 required checks 通过后输出 <promise>done</promise>。
    input: install-report.md + scheduler/home config + 首次 daily-update 结果
    output: initialized state + daily-setup-completion.md
    check_voting:
      - check: 独立核对 scheduler loaded/enabled、09:00、exact script、state files recent/correct vault 和 daily run结果
      - check: 验证 notification approved时可加载、declined/headless时无改动，completion 对 platform/missed behavior/logs 描述准确
      - check: 重复执行 setup 不产生 duplicate cron/LaunchAgent/task/rc entry，失败真实披露且 rollback 信息有效
    on_pass: done
    on_fail: initialize_and_verify
    max_fail_count: 4
````
<!-- END GENERATED WORKFLOW CONTRACT -->
