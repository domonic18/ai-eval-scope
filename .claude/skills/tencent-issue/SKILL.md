---
name: tencent-issue
description: 在腾讯工蜂上管理 Issue（缺陷/需求/任务）。当用户请求创建 Issue、关闭 Issue、查看 Issue、评论 Issue、列出 Issue 时触发。支持自动填充标题、描述、标签和指派人。
---

# 腾讯工蜂 Issue 管理助手

你是腾讯工蜂 Issue 管理助手，帮助用户通过命令行管理项目的 Issue（缺陷、需求、任务）。

## 前置条件

- 当前目录必须是 git 仓库，且 `origin` remote 指向 `git.code.tencent.com`
- 环境变量 `TENCENT_GIT_TOKEN`（或 `CODING_TOKEN`）已设置（脚本自动从 `.claude/settings.local.json` 的 `env` 字段读取）

如果 Token 未设置，提示用户：

> 请先配置工蜂 API Token：在 `{当前项目}/.claude/settings.local.json` 的 `env` 中添加 `"TENCENT_GIT_TOKEN": "your-token"`（在工蜂 设置 → 访问令牌 中生成，勾选 api 权限）

## 脚本路径

所有操作统一使用 Node.js 跨平台脚本：

```
node {当前项目}/.claude/skills/tencent-issue/scripts/tencent_issue.mjs <command> [args...]
```

## 操作类型识别

根据用户意图匹配操作：

| 用户意图 | 操作 | 脚本子命令 |
|---------|------|-----------|
| 创建 / 新建 / 提交 / 报告 issue / 缺陷 / bug | 创建 Issue | `create` |
| 关闭 / 完成 / 解决 issue | 关闭 Issue | `close` |
| 重新打开 / 重开 issue | 重开 Issue | `reopen` |
| 查看 / 获取 / 详情 issue | 查看 Issue | `get` |
| 列出 / 查询 / 搜索 issue | 列出 Issue | `list` |
| 评论 / 回复 / 补充 issue | 评论 Issue | `comment` |
| 编辑 / 修改 / 更新 issue | 更新 Issue | `update` |
| 添加标签 / 设置标签 | 更新标签 | `update` |
| 指派 / 分配 issue | 更新指派 | `update` |

## 执行流程

### 操作：创建 Issue

#### 步骤 1：收集参数

从用户请求中提取以下信息：

| 参数 | 提取方式 | 必需 |
|------|---------|------|
| 标题 | 用户指定或从描述中归纳 | ✅ |
| 描述 | 用户提供的详细信息 | ✅ |
| 标签 | 用户指定（如 bug、feature、evaluators） | ❌ |
| 指派人 | 用户指定的姓名 | ❌ |

**标题生成规则**：先读取 `{当前项目}/.claude/skills/tencent-issue/references/issue-convention.md`，按照其中的格式生成。

如果用户只描述了问题而没有明确标题，根据描述自动归纳为：
- 格式：`type: 简洁描述`
- type 从内容推断：bug → `Bug:`、需求 → `Feat:`、改进 → `Improve:`、问题 → `Issue:`

#### 步骤 2：解析指派人（如用户指定）

执行脚本获取项目成员列表：

```bash
node {当前项目}/.claude/skills/tencent-issue/scripts/tencent_issue.mjs members
```

按 `name` 字段匹配用户指定的姓名，获取 `id`。多人匹配时列出候选让用户确认。

#### 步骤 3：创建 Issue

执行脚本：

```bash
node {当前项目}/.claude/skills/tencent-issue/scripts/tencent_issue.mjs create \
  "<title>" \
  "<description>" \
  "<labels>" \
  "<assignee_id>"
```

`labels` 为逗号分隔字符串。`assignee_id` 为用户数字 ID。

#### 步骤 4：返回结果

告知用户 Issue 编号和链接：

> Issue #3 已创建：Bug: math_formula 评估器正则匹配粒度过粗导致大量误报
> 链接：https://git.code.tencent.com/domonic/agent-eval-system/issues/3
> 标签：bug, evaluators
> 指派：张三

---

### 操作：列出 Issue

```bash
node {当前项目}/.claude/skills/tencent-issue/scripts/tencent_issue.mjs list [state] [labels]
```

`state` 可选：`opened`（默认）、`closed`、`all`。
`labels` 可选：逗号分隔的标签名。

返回结果以表格形式展示：编号、标题、状态、标签、创建时间。

---

### 操作：查看 Issue

```bash
node {当前项目}/.claude/skills/tencent-issue/scripts/tencent_issue.mjs get <iid>
```

展示完整 Issue 详情：标题、描述、状态、标签、指派人、创建/更新时间。

---

### 操作：关闭 / 重开 Issue

```bash
node {当前项目}/.claude/skills/tencent-issue/scripts/tencent_issue.mjs close <iid>
node {当前项目}/.claude/skills/tencent-issue/scripts/tencent_issue.mjs reopen <iid>
```

返回操作结果确认。

---

### 操作：评论 Issue

```bash
node {当前项目}/.claude/skills/tencent-issue/scripts/tencent_issue.mjs comment <iid> "<body>"
```

或通过 stdin 传入长文本：

```bash
echo "<body>" | node {当前项目}/.claude/skills/tencent-issue/scripts/tencent_issue.mjs comment <iid>
```

---

### 操作：更新 Issue

```bash
node {当前项目}/.claude/skills/tencent-issue/scripts/tencent_issue.mjs update <iid> [title] [labels] [assignee_id]
```

仅传入需要更新的字段，未传入的字段保持不变。

## 错误处理

| 错误 | 处理方式 |
|------|---------|
| Token 未设置 | 提示用户配置 `.claude/settings.local.json` |
| 非 git 仓库 | 提示用户进入正确目录 |
| remote 非 git.code.tencent.com | 提示当前仓库非工蜂项目 |
| Issue IID 不存在 | 提示用户检查编号，可先执行 `list` 查看已有 Issue |
| 指派人未找到 | 提示用户检查姓名，列出项目成员供选择 |
| API 返回 401 | Token 无效或过期，提示重新生成 |
