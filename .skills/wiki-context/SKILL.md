---
name: wiki-context
description: "按配置解析 Wiki vault，并用确定性脚本生成共享运行时上下文"
---

# wiki-context

此 skill 直接执行下方从 `workflows/wiki-context.yaml` 同步的完整契约。内嵌 YAML 是实际指令，不是摘要或外部参考；按 `steps`、输入输出、检查、跳转、失败上限和人工审批要求逐项执行。

发生任何冲突时，以内嵌 workflow 契约为准。不要用历史 skill 文案补写、弱化或覆盖它。修改行为时先编辑 workflow，再运行 `python tools/sync_workflow_skills.py`。

<!-- BEGIN GENERATED WORKFLOW CONTRACT -->
````yaml
description: 按配置解析 Wiki vault，并用确定性脚本生成共享运行时上下文

auto_reset: true

adversarial_check:
  timeout_ms: 3600000
  system_prompt: |
    你是 Wiki Context 的只读审计者。只核对 check 列出的 artifacts 和关键磁盘事实，不得调用 context 生成脚本，不得修改 vault 或执行后续流程。
    每个 step 的 do 只生成声明的 artifact；check 只验收本步的必要不变量，不重复生成器已完成的全量扫描。

steps:
  - id: collect_vault
    desc: 从 invocation 生成不含秘密的 vault 解析输入 artifact
    do: |
      只生成 `vault-input.json`，不读取 config 或 vault 内容。

      若调用方 inputs 含 `run_condition` 且父报告证明条件不成立，不向用户询问，直接写 `{"mode":"skipped","reason":"...","evidence":"..."}`。

      否则，先解析 invocation 中的路由意图，并收集调用方 `requested_keys` 中用户显式提供的非秘密 overrides：

      - invocation 含 `@name` 时，移除该路由 token，写 `{"mode":"config","profile":"name","overrides":{...}}`；
      - 用户明确给出 vault 绝对路径时，写 `{"mode":"interactive","vault_path":"<expanded absolute path>","overrides":{...}}`；
      - 其他情况写 `{"mode":"config","overrides":{...}}`，不向用户重复询问 vault。resolver 会按最近 `.env` 再到全局 `~/.obsidian-wiki/config` 的顺序读取 wiki-setup 已写入的设置。

      准备好后输出 `<promise>done</promise>`。
    input: 调用方 invocation、run_condition（如有）、requested_keys 和用户输入
    output: vault-input.json
    check: 解析 vault-input.json；skipped 时核对 reason/evidence，config 时核对可选 profile，interactive 时核对用户明确给出的绝对 vault path；核对 requested_keys 内的非秘密 overrides；确认本步只产生该 artifact
    on_pass: resolve_context
    on_fail: collect_vault
    max_fail_count: 3

  - id: resolve_context
    desc: 调用随包发布的 resolver 生成 Wiki 共享上下文
    do: |
      使用已批准的 `vault-input.json` 和调用方 inputs 生成 `wiki-context.json`、`wiki-context.md` 与仅含非秘密策略选项的 `text-chunk-options.json`：

      ```bash
      obsidian-wiki wiki-context-resolve \
        --input "{{artifacts_dir}}/vault-input.json" \
        --source-cwd "<source-cwd>" \
        --requested-keys "<comma-separated requested_keys>" \
        --optional-reads "<comma-separated optional_reads>" \
        --setup-mode "<true-or-false>" \
        --output-dir "{{artifacts_dir}}"
      ```

      console script 不在 PATH 时使用等价的 `python3 -m obsidian_wiki wiki-context-resolve ...`。config mode 严格按 `@name` 指定 config、从 source CWD 向上找第一个含 `OBSIDIAN_VAULT_PATH` 的 `.env`、再到全局 `~/.obsidian-wiki/config` 的顺序解析；都缺失时要求运行 wiki-setup。resolver 将 effective config、owner/Writing Profile metadata、requested optional metadata、active layout 状态、text chunking 配置及 retrieval order 写入声明的 artifacts。
    input: vault-input.json + 调用方传入的 source_cwd、requested_keys、optional_reads、setup_mode
    output: wiki-context.json + wiki-context.md + text-chunk-options.json
    check: 解析 context artifacts，核对 approved canonical vault、唯一 config source、requested keys 与 mode；核对 text-chunk-options.json 与 context 中的非秘密 chunk options 一致；请求 layout 时确认 marker status/hash 和 frozen routing 存在，skipped 时不带 config/vault 内容；确认除 artifacts 外零写入
    on_pass: done
    on_fail: collect_vault
    max_fail_count: 3
````
<!-- END GENERATED WORKFLOW CONTRACT -->
