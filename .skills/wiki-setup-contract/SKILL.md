---
name: wiki-setup-contract
description: "从 workflow-local 模板生成带 hash 的 Wiki 核心初始化契约，再合并可选集成与验收契约"
---

# wiki-setup-contract

此 skill 是 `workflows/wiki-setup-contract.yaml` 的 Agent Skill 格式投影；workflow 是行为事实来源，本文件把其字段渲染为可直接执行的 Markdown 指令。

<!-- BEGIN GENERATED SKILL INSTRUCTIONS -->

## 执行规则

按下列步骤和流程控制执行。每个步骤只读取其声明的输入，只产生其声明的产出；执行与独立验收分开进行。修改行为时先编辑权威 workflow，再运行 `python tools/sync_workflow_skills.py`。

- 自动重置：开启。

## 独立验收规则

你是 Wiki Setup Contract 的只读审计者。只核对验收部分列出的 contract 字段与安全边界，不得调用 builder，不得创建或修改 vault、config、hook、QMD、Git 或网络状态。
每个执行阶段只生成声明的 contract artifacts；独立验收阶段一次核对 artifact 结构、关键 hash 与零外部写入。

单次验收超时：`3600000` 毫秒。

## 工作流

### 1. 生成冻结的 setup core contract (`build_core_contract`)

#### 执行

运行 workflow-local builder 的 `core` phase：

```bash
obsidian-wiki wiki-setup-contract-build core \
  --output-dir "{{artifacts_dir}}"
```

console script 不在 PATH 时使用等价的 `python3 -m obsidian_wiki wiki-setup-contract-build core ...`。

builder 从随包发布的 `workflows/templates/wiki-setup/` 收集 `WRITING.md`、`index.md`、`log.md`、`hot.md`、`manifest.json`、`app.json`、`appearance.json`，将 source path、完整正文、allowed placeholders 和 SHA-256 写入 core artifacts。

core artifacts 同时写入动态值声明、config defaults、Writing Profile create-only 策略、core file create/minimal-repair 策略，以及每个 Knowledge Pack 的 manifest、Knowledge Profile、routing、prompt、vault inventory 和对应 hashes。

builder 先形成唯一 canonical core contract result；`setup-core-contract.json` 完整承载该 result，Markdown readout 只从同一 result 渲染、不得独立推导或补充事实，并在同一批 artifact 写入中提交二者。只生成这两个 artifacts，不修改 vault、home 或外部系统。

#### 输入

父 workflow 的 non-secret invocation metadata（仅用于 provenance，不改变模板）

#### 产出

setup-core-contract.json + setup-core-contract.md

#### 验收

解析 core JSON，核对 templates/Packs inventory、Profile/Layout/Routing/contract hashes、defaults 与 create/repair policy；核对 Markdown 的 inventory、paths、hashes、defaults、policies、warnings 是 JSON 投影且无单侧事实；拒绝 symlink/path escape/reserved target，确认仅写 artifacts

#### 流程控制

- 验收通过：转到 `build_integration_contract`。

- 验收失败：返回 `build_core_contract`。

- 最多连续失败 `3` 次；达到上限后停止并报告阻塞。

### 2. 生成冻结的 setup final contract (`build_integration_contract`)

#### 执行

使用已通过上一 step check 的 core contract 生成 final contract：

```bash
obsidian-wiki wiki-setup-contract-build finalize \
  --output-dir "{{artifacts_dir}}"
```

console script 不在 PATH 时使用等价的 `python3 -m obsidian_wiki wiki-setup-contract-build finalize ...`。

builder 将 `integrations.json` 中的 QMD、Stop hook、Git sync、required checks、manual plugins 和 next steps 合并进 core contract，先形成唯一 canonical final contract result；`setup-contract.json` 完整承载该 result，Markdown 只从同一 result 渲染、不得独立推导或补充事实，并在同一批 artifact 写入中提交二者。

只生成最终 contract artifacts，不修改 vault、home 或外部系统。

#### 输入

已验证的 setup-core-contract.json/md + templates/wiki-setup/integrations.json

#### 产出

setup-contract.json + setup-contract.md

#### 验收

解析 final JSON，核对 core/integration/final hashes、QMD exclusion、hook、Git、plugins、checks 与 next steps；核对 Markdown 的对应字段和 warnings 是 JSON 投影且无单侧事实；确认仅写 contract artifacts

#### 流程控制

- 验收通过：转到 `done`。

- 验收失败：返回 `build_integration_contract`。

- 最多连续失败 `3` 次；达到上限后停止并报告阻塞。

<!-- END GENERATED SKILL INSTRUCTIONS -->
