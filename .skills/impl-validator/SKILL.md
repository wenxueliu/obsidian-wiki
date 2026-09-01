---
name: impl-validator
description: "对照明确目标逐项验证实现与产物，给出可复核的 PASS、WARN 或 FAIL 结论"
---

# impl-validator

此 skill 是 `workflows/impl-validator.yaml` 的 Agent Skill 格式投影；workflow 是行为事实来源，本文件把其字段渲染为可直接执行的 Markdown 指令。

<!-- BEGIN GENERATED SKILL INSTRUCTIONS -->

## 执行规则

按下列步骤和流程控制执行。每个步骤只读取其声明的输入，只产生其声明的产出；执行与独立验收分开进行。修改行为时先编辑权威 workflow，再运行 `python tools/sync_workflow_skills.py`。

- 自动重置：开启。

## 独立验收规则

你是 Implementation Validator 的复核者。只验证目标、产物与指定 checks，不修复实现，不扩张到风格偏好、未要求的性能或假设性未来风险。
每个结论必须有可定位证据；任一 FAIL 必须使 overall=FAIL，只有 WARN 时 overall=WARN。

单次验收超时：`3600000` 毫秒。

## 工作流

### 1. 绑定目标、产物与逐项检查清单 (`bind_validation`)

#### 执行

本 skill 是 implementation validation 的完整运行时规范。解析用户输入或调用方提供的 `impl-validator check:` block。

1. 将 goal 重述为一个可验证句子；subagent 模式严格使用 goal/artifacts/checks，不自行扩大范围。
2. 用户模式从当前对话识别目标和实际产物；若关键目标含糊，在继续前只问一个必要问题，不凭猜测做关键检查。
3. canonicalize 每个本地 artifact 路径，记录文件、命令输出、配置或文本产物的类型、预期与允许的只读验证命令。
4. 明确排除 style preference、目标本身是否值得做、未在目标内的性能与纯假设问题。
5. 写 validation-mandate.md 和 validation-input.json。不得修改任何被验证产物。

#### 输入

用户描述，或结构化 goal + artifacts + checks

#### 产出

validation-mandate.md + validation-input.json

#### 验收

对照原始请求复核 goal 可判定、artifact 列表完整、每条 provided check 原样保留且 scope 未扩大；路径解析有依据，被验证产物没有变化。

#### 流程控制

- 验收通过：转到 `inspect_artifacts`。

- 验收失败：返回 `bind_validation`。

- 最多连续失败 `3` 次；达到上限后停止并报告阻塞。

### 2. 检查产物存在性、完整性、正确性与项目约定 (`inspect_artifacts`)

#### 执行

对 validation-input.json 中每个 artifact 执行 impl-validator 的四类检查：

1. existence：真实读取文件/输出/config，缺失即记录 FAIL，不把声称存在当证据。
2. completeness：按 goal 检查所有 required sections/fields/artifacts。
3. correctness：检查 TODO、未解析 placeholder、错误路径/工具/日期、复制粘贴残留、逻辑矛盾、空集与边界错误。
4. convention：只应用当前项目可证实的约定；frontmatter、wiki required fields、script shebang/set -e、plist XML/Label/path 等按 artifact 类型选择。
5. 对二进制、外部状态或无法安全读取的 artifact 明确记为 WARN/FAIL 和原因，不伪造验证。
6. 写 artifact-findings.json，每条包含 artifact、check、result、evidence、locator、severity。全程只读。

#### 输入

validation-mandate.md + validation-input.json + 实际 artifacts

#### 产出

artifact-findings.json

#### 验收

1. 抽样重新打开每类 artifact，核对 existence/completeness/correctness/convention 结论都有实际证据与准确 locator

2. 检查 TODO/placeholder、错路径、缺字段、矛盾和边界情况未漏查，无法验证项没有被误报 PASS

3. 确认检查范围严格受 goal 与 provided checks 约束，所有 artifact 与外部状态保持未修改

#### 流程控制

- 验收通过：转到 `run_checks`。

- 验收失败：返回 `inspect_artifacts`。

- 最多连续失败 `4` 次；达到上限后停止并报告阻塞。

### 3. 显式执行并裁决每一条指定检查 (`run_checks`)

#### 执行

逐条处理 validation-input.json.checks，不能跳过、合并或用笼统结论代替。

对每条 check 运行安全且必要的只读命令/测试，保存真实命令、退出码和关键输出；不能运行时说明限制。结果只能为：PASS（已证实）、WARN（大体成立但有具体疑点）、FAIL（明确错误或缺失）。把 artifact findings 映射到对应 check，并写 check-results.json；数量和顺序必须与输入清单一致。

#### 输入

validation-input.json + artifact-findings.json

#### 产出

check-results.json（每条输入 check 的 PASS/WARN/FAIL、证据与命令）

#### 验收

1. 对照原始 checks 逐项核对数量、顺序、措辞和 verdict，确认没有遗漏或无证据 PASS

2. 复跑关键命令并核对退出码/输出；FAIL、WARN 的事实与 locator 准确，命令没有修改被验证对象

#### 流程控制

- 验收通过：转到 `render_verdict`。

- 验收失败：返回 `run_checks`。

- 最多连续失败 `4` 次；达到上限后停止并报告阻塞。

### 4. 生成严格聚合的 Implementation Validator 报告 (`render_verdict`)

#### 执行

按 impl-validator Report 格式写 impl-validator-report.md：Goal、Checks 表、Overall、Issues to fix、Worth noting。

1. 任一 FAIL → Overall FAIL；无 FAIL 但有 WARN → WARN；全 PASS → PASS。
2. 每个 FAIL 给出具体 artifact path、locator 与可执行修复方向；WARN 只放非阻塞观察。
3. 用户模式可在 FAIL 时提出后续修复，但本 workflow 不实施修复；调用方模式仅返回完整报告供 caller 决策。
4. 写 verdict.json，包含 counts、overall、goal、artifact/check 数、生成时间。确认报告与 JSON 一致后输出 <promise>done</promise>。

#### 输入

validation-mandate.md + artifact-findings.json + check-results.json

#### 产出

impl-validator-report.md + verdict.json

#### 验收

1. 从 check-results 和 findings 重算 PASS/WARN/FAIL counts 与 overall，确认聚合规则严格且报告无遗漏

2. 抽查每条 issue 的 path/locator/evidence 可定位，报告未混入风格偏好、越界评价或未经验证的断言

3. 确认 workflow 仅产出 artifacts，没有修复或修改任何被验证实现

#### 流程控制

- 验收通过：转到 `done`。

- 验收失败：返回 `render_verdict`。

- 最多连续失败 `3` 次；达到上限后停止并报告阻塞。

<!-- END GENERATED SKILL INSTRUCTIONS -->
