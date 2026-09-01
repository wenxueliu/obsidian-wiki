# Workflow Authoring Rules

本文件适用于 `workflows/` 下的 workflow、辅助脚本、模板和 layout 资源。更具体目录中的 `AGENTS.md` 可以补充规则，但不能放宽以下职责边界。

## Workflow 与 Skill 同步

顶层 `workflows/<name>.yaml` 是运行行为的唯一事实来源，并且必须存在对应的
`.skills/<name>/SKILL.md`。同步器必须把 workflow 的字段完整、确定性地渲染为可直接执行的
Agent Skill Markdown 指令，不得把 YAML 原文交给 agent 在运行时解释；workflow 仍是行为事实来源。

修改任何顶层 workflow 后运行：

```bash
python tools/sync_workflow_skills.py
python tools/sync_workflow_skills.py --check
```

同步器只重写同名 `SKILL.md`，保留 skill 目录中的 `references/`、`scripts/` 与其他资源。

## Step 单一职责

每个 step 只负责生成一种明确的目标状态或一组内聚 artifacts。若一个 step 同时处理彼此可以独立执行、失败或回滚的事项，必须拆分。

例如，config、Writing Profile、layout、core files、Stop hook、Git sync、QMD collection 和 QMD refresh 应分别属于不同 step。为本次生成动作记录 report，与生成目标状态属于同一职责。

## `do` 是 Producer

`do` 只生成该 step 在 `output` 中声明的状态或 artifacts：

- 只读取 `input` 中声明的输入。
- 执行本 step 唯一职责所需的创建、更新或外部动作。
- 写出目标及对应 report。
- 可以采用原子写、missing-only、create-only 等生成策略。
- 不得在 `do` 中执行验收、校验、审计或通过/失败判定。
- 不得在 `do` 中重算 hash 来证明自己的输出正确。
- 不得调用 doctor、lint 或同一个生成器作为 verifier。
- 不得根据校验结果顺手修复其他职责的状态；需要修复时回到拥有该状态的 Producer step。

生成器内部可以保留防止路径逃逸、破坏性覆盖或非法输入的 fail-closed 安全护栏；这些护栏不替代 workflow 的独立 `check`。

## `check` 是 Verifier

每个包含本地 `do` 的 step 必须提供 `check` 或 `check_voting`，负责必要的独立验收：

- 独立读取声明的输入、输出和磁盘事实。
- 校验 schema、类型、路径、权限、完整性和副作用边界。
- 需要时独立重算 hash、inventory、routing 或 diff。
- 核对 output/report 与实际状态一致。
- 不得通过再次运行同一个生成器来证明生成结果正确。
- 失败时返回拥有该状态的 Producer step；无法定位单一责任时回到 plan step 重新规划。

调用子 workflow 的 delegation step 可以不重复子 workflow 的 check，但子 workflow 自身必须遵守本文件。

## 编写检查

提交 workflow 变更前确认：

1. step 的 `desc` 能用一个动词描述。
2. `do` 只产生 `output`，不包含“验证、校验、检查、核对、审计、重算”等 verifier 行为。
3. 每个本地 `do` 都有对应 `check` 或 `check_voting`。
4. 可独立失败或回滚的动作已经拆成不同 step。
5. 所有 `on_pass` / `on_fail` 都指向已声明 step 或 `done`。
6. 最终 completion step 只渲染交付 artifact；doctor 和最终对账位于其 check。
