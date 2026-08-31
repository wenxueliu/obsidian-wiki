---
name: wiki-page-contract
description: "将共享 Wiki context 与事务范围编译为不可变的 effective page write contract"
---

# wiki-page-contract

此 skill 直接执行下方从 `workflows/wiki-page-contract.yaml` 同步的完整契约。内嵌 YAML 是实际指令，不是摘要或外部参考；按 `steps`、输入输出、检查、跳转、失败上限和人工审批要求逐项执行。

发生任何冲突时，以内嵌 workflow 契约为准。不要用历史 skill 文案补写、弱化或覆盖它。修改行为时先编辑 workflow，再运行 `python tools/sync_workflow_skills.py`。

<!-- BEGIN GENERATED WORKFLOW CONTRACT -->
````yaml
description: 将共享 Wiki context 与事务范围编译为不可变的 effective page write contract

auto_reset: true

adversarial_check:
  timeout_ms: 3600000
  system_prompt: |
    你是 Wiki Page Contract 的只读审计者。只审计既有 contract artifacts，不生成或修改任何文件，不读取 source body、index 或页面正文。

steps:
  - id: build_page_contract
    desc: 编译并冻结本次事务的 effective page write contract
    do: |
      只读取父 workflow 传入的 `wiki-context.json`、`transaction_kind` 与 `source_scope`，以及 context 中已经冻结的 owner/taxonomy/Writing Profile/layout metadata，编译本次事务的 effective page write contract。此 workflow 只编译规则：不得扫描 index、打开候选页面、定位真实 merge target、执行 route resolution、处理真实页面质量或写入 vault。

      1. 写入 input binding：`transaction_kind`、`source_scope`、canonical vault、context/layout/routing hashes、link format 与 write mode。调用方没有提供 transaction kind/scope、layout status 不是 matched、或 frozen hashes 缺失时失败，不猜测默认值。
      2. 编译 schema policy：required frontmatter 至少包含 title、category、tags、sources、summary、created、updated；owner 可增加字段或放宽 framework 默认。保留未知 owner 字段。summary 不超过 200 字，tags 使用 effective taxonomy，relationships 只能使用 effective allowlist。
      3. 编译 canonicalization/merge policy：页面边界由 canonical topic 决定，不由 source、conversation、Packet 或 unit 边界决定；下游先做 title/aliases/tags/summary cheap pass，再仅打开高相关候选；existing-first、aggressive merge，只有真正新概念才创建页面。本 workflow 不执行该 pass。
      4. 编译 provenance policy：每条新 claim 绑定 source path/id、content hash、unit/session 与最窄 line/byte/turn locator；直接支持标 extracted，跨条目综合标 `^[inferred]`，未解决冲突并列双方并标 `^[ambiguous]`。
      5. 原样冻结 active layout 的 `routing.rules` 与 `routing.prompt`。owner rules 可以补充分类判断，但不能扩展 content_roots、placeholders 或绕过 system/skip paths。契约要求下游只从 declared page types 选择 `page_type`，并为每个真实新页面调用确定性路由器、记录 route evidence：

         ```bash
         obsidian-wiki wiki-route-resolve \
           --routing page-contract.json --page-type "<declared-type>" \
           --slug "<safe-slug>" --project "<safe-project>" --date "<YYYY-MM-DD>"
         ```

         下游只传目标模板实际需要的参数；console script 不在 PATH 时使用 `python3 -m obsidian_wiki ...`。existing target 也必须位于 content_roots；链接目标必须已存在或由同一事务创建，新增链接须具备局部双向引用。
      6. 编译 mutation policy：更新页面采用 read-modify-write，保留不相关正文、owner 字段、历史 sources 与可信度信息；compatible facts 去重。所有写入先形成 candidate/temp sibling，通过下游 page acceptance gate 后原子替换。
      7. 编译 mode policy：direct 只允许写 resolver 返回的 live content target；staged 只写 `_staging` 下绑定 canonical target 的完整新页面或 patch。patch 绑定 target/base hash/job/source/unit，并包含 Additions、Deletions、Updated Fields；staged 不得修改 live/index/manifest。
      8. 写 `page-contract.json` 与人类可读的 `page-contract.md`。JSON 包含 input binding、layout name/version/status/hash、完整 routing rules/prompt、effective fields、taxonomy、relationship allowlist、provenance、merge、mutation、mode、link 与 validation policies，以及 Writing Profile 摘要；Markdown 准确概述相同关键约束。除这两个 contract artifacts 外不得写任何文件。
    input: wiki-context.json + 调用方 transaction_kind/source_scope
    output: page-contract.json + page-contract.md
    check: |
      解析 `page-contract.json`，确认 transaction_kind、source_scope、canonical vault、context/layout/routing hashes、write mode 与 link format 已绑定输入；schema、taxonomy、relationship allowlist、provenance、canonicalization/merge、routing、mutation、mode 与 validation policies 完整。确认 layout status=matched，routing rules/hash 与 frozen context 一致，owner 没有扩展 content_roots、placeholders 或 system/skip paths；`page-contract.md` 准确概述 JSON 的关键约束。确认只产生这两个 contract artifacts，未读取 source body/index/page bodies，未修改 live/staged pages、Job、index/log/hot/manifest 或 source。不要重算上游 context，不为虚拟 page types 执行 route resolver，也不重复下游真实页面验证。
    on_pass: done
    on_fail: build_page_contract
    max_fail_count: 3
````
<!-- END GENERATED WORKFLOW CONTRACT -->
