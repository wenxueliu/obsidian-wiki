# Knowledge Pack Authoring Rules

本目录发布可被多个 workflow 与 skill 共用的 Knowledge Pack。每个
`knowledge-packs/<name>/` 必须作为一个原子契约维护：

- `profile.json` 定义 Knowledge Profile。
- `layout.json` 与 `vault/` 定义 Vault Layout 及初始化模板。
- `routing.md` 指导模型选择 page type。
- `routing.json` 确定性地把 page type 展开为 vault-relative path。

修改任一文件时，必须同时检查 Profile 的 `knowledge_types`、routing routes、content roots、
system paths 与模板目录是否一致。Pack 不得依赖某个 workflow 的安装路径或调用方当前目录。
