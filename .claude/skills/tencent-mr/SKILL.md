---
name: tencent-mr
description: 在腾讯工蜂上创建合并请求（MR）。当用户请求提交MR、创建合并请求、发起代码评审、合并代码到某分支时触发。支持自动填充标题、描述和按姓名选择评审人。
---

# 腾讯工蜂合并请求助手

你是腾讯工蜂 MR 创建助手，帮助用户通过命令行快速创建合并请求。

## 前置条件

- 当前目录必须是 git 仓库，且 `origin` remote 指向 `git.code.tencent.com`
- 环境变量 `TENCENT_GIT_TOKEN`（或 `CODING_TOKEN`）已设置

如果 Token 未设置，提示用户：

> 请先配置工蜂 API Token：在 `{当前项目}/.claude/settings.local.json` 中添加一行 `TENCENT_GIT_TOKEN=your-token`（在工蜂 设置 → 访问令牌 中生成，勾选 api 权限）

## 执行流程

### 步骤 1：收集参数

从用户请求中提取以下信息，缺失时使用默认值或主动询问：

| 参数 | 提取方式 | 默认值 |
|------|---------|--------|
| 源分支 | 用户指定 或 当前分支 | `git branch --show-current` |
| 目标分支 | 用户指定 | `develop` |
| 评审人 | 用户指定的姓名（支持多人） | 无（可选） |

### 步骤 2：确认当前状态

执行以下命令，了解当前分支和变更情况：

```bash
# 获取源分支
git branch --show-current

# 确认远程仓库指向工蜂
git remote get-url origin

# 查看待合并的 commit 历史
git log <target_branch>..HEAD --oneline

# 查看变更文件
git diff <target_branch>...HEAD --stat
```

如果源分支有未提交的变更，先提醒用户提交或暂存。

### 步骤 3：解析评审人（如用户指定）

执行脚本获取项目全部成员列表：

```bash
bash {当前项目}/.claude/skills/tencent-mr/scripts/tencent_mr.sh members
```

API 返回 JSON 数组，每条包含 `id`、`name`、`username`、`state` 等字段。

从返回结果中：
- 按 `name` 字段匹配用户指定的评审人姓名
- 如果匹配到多人，列出候选项让用户确认
- 如果未匹配，提示用户检查姓名是否正确

多个评审人时，收集所有 ID 组成 JSON 数组，如 `[123, 456]`。

### 步骤 4：生成 MR 标题和描述

**先读取 PR 规范**：使用 Read 工具读取 `{当前项目}/.claude/skills/tencent-mr/references/pr-convention.md`，按照其中的格式生成标题和描述。

标题生成规则：
- 格式：`type(scope): 描述`
- 从 commit 历史中识别 type（feat/fix/refactor/docs 等）
- 归纳所有 commit 为一句简洁描述

描述生成规则：
- 从 `git log <target_branch>..HEAD --oneline` 和 `git diff --stat` 中归纳变更要点
- 使用中文
- 控制在 5-10 行

### 步骤 5：创建 MR

执行脚本创建合并请求：

```bash
bash {当前项目}/.claude/skills/tencent-mr/scripts/tencent_mr.sh create \
  "<source_branch>" \
  "<target_branch>" \
  "<title>" \
  "<description>" \
  "[reviewer_id1,reviewer_id2]"
```

注意：
- `description` 如果包含换行，使用 `$'...\n...'` 语法
- `reviewer_ids` 参数是可选的，仅当用户指定了评审人时才传入
- `reviewer_ids` 格式为 JSON 数组字符串，如 `"[123, 456]"`，脚本内部会自动转为工蜂 API 要求的逗号分隔字符串

### 步骤 6：返回结果

API 返回创建结果 JSON，提取以下信息告知用户：

- MR 标题
- MR 链接（`web_url` 字段）
- 评审人

成功示例输出：
> MR 已创建：feat(report): 周报工作项增加项目名称标识
> 链接：https://git.code.tencent.com/group/project/merge_requests/123
> 评审人：江凯

## 错误处理

| 错误 | 处理方式 |
|------|---------|
| Token 未设置 | 提示用户配置 `{当前项目}/.claude/settings.local.json` |
| 非 git 仓库 | 提示用户进入正确目录 |
| remote 非 git.code.tencent.com | 提示当前仓库非工蜂项目，无法创建 MR |
| 源分支不存在于远程 | 先执行 `git push origin <branch>` 推送分支，再创建 MR（需用户确认） |
| 评审人未找到 | 提示用户检查姓名拼写，列出可能的候选人 |
| API 返回 401 | Token 无效或过期，提示重新生成 |
| API 返回 409（分支无差异） | 提示源分支和目标分支之间没有差异 |
