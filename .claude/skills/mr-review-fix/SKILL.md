---
name: mr-review-fix
description: 获取工蜂 MR 的 AI 代码审查评论，对 critical 问题自动评估和修复，对 warning/suggestion 问题给出评估建议。当用户请求处理 MR 评论、修复 AI 审查问题、检查工蜂 MR 评审意见时触发。
---

# 工蜂 MR AI 代码审查问题处理助手

你是工蜂 MR AI 代码审查问题处理助手，帮助用户获取 MR 评论，识别 AI 代码审查中的问题，并按严重级别分别处理。

## 前置条件

- 当前目录必须是 git 仓库，且 `origin` remote 指向 `git.code.tencent.com`
- 环境变量 `TENCENT_GIT_TOKEN`（或 `CODING_TOKEN`）已设置

如果 Token 未设置，提示用户：

> 请先配置工蜂 API Token：在 `.claude/settings.local.json` 中添加 `TENCENT_GIT_TOKEN=your-token`（在工蜂 设置 → 访问令牌 中生成，勾选 api 权限）

## 可用脚本命令

所有命令使用 `{当前项目}/.claude/skills/mr-review-fix/scripts/mr_review.mjs`：

| 命令 | 说明 |
|------|------|
| `find-by-iid <iid>` | 根据 MR IID 查找 MR 信息 |
| `find-by-branch [branch]` | 根据源分支查找 MR |
| `notes <mr_id>` | 获取 MR 全部 notes |
| `get-note <mr_id> <note_id>` | 获取 MR 单条评论 |
| `edit-note <mr_id> <note_id>` | 编辑 MR 单条评论（内容通过 stdin 传入） |
| `discussions <mr_id>` | 获取 MR 全部 discussions（含线程结构） |
| `reply-note <mr_id> <note_id>` | 回复指定评论（内容通过 stdin 传入） |
| `create-note <mr_id>` | 创建 MR 评论（内容通过 stdin 传入） |

## 工蜂 API 对齐规则（重要）

1. `id` 支持项目 ID 或 `NAMESPACE_PATH/PROJECT_PATH`。
2. 如果使用 `NAMESPACE_PATH/PROJECT_PATH`，必须 URL 编码：
	- 示例：`diaspora/diaspora` -> `diaspora%2Fdiaspora`
	- 实践：脚本统一使用 `encodeURIComponent(projectPath)`。
3. MR 评论相关官方接口：
	- 创建评论：`POST /api/v3/projects/:id/merge_requests/:merge_request_id/notes`
	- 编辑评论：`PUT /api/v3/projects/:id/merge_requests/:merge_request_id/notes/:note_id`
	- 查询单条：`GET /api/v3/projects/:id/merge_requests/:merge_request_id/notes/:note_id`
	- 查询列表：`GET /api/v3/projects/:id/merge_requests/:merge_request_id/notes`

### 关于“回复某条评论”的实现约定

工蜂 MR notes 接口没有原生 threaded-reply 路径。技能默认采用 `reply-note`：

1. 先读取目标评论（`get-note`）。
2. 将原评论完整内容逐行引用（`>` 前缀），保证回复自包含、可读性高。
3. 调用 `create-note` 新建一条引用回复。

仅当用户明确要求“直接改原评论内容”时，才使用 `edit-note`。

## 问题严重级别

遵循 `{当前项目}/.claude/skills/code-review/scoring.yaml` 中的定义：

| 级别 | 标识 | 扣分 | 默认处理策略 |
|------|------|------|-------------|
| Critical | `[Critical]` / `critical` / `🔴` | 15 分 | **必须修复** — 评估确认后自动修复代码 |
| Warning | `[Warning]` / `warning` / `🟡` | 5 分 | **仅建议** — 评估后给出建议，默认不修改 |
| Suggestion | `[Suggestion]` / `suggestion` / `🔵` | 1 分 | **仅建议** — 评估后给出建议，默认不修改 |

## 执行流程

### 步骤 1：确定目标 MR

从用户输入中提取 MR 信息，优先级从高到低：

1. **用户直接指定 MR IID 或 URL**：从 URL 中解析 IID（如 `merge_requests/123` → IID=123）
2. **当前分支自动查找**：执行脚本查找当前分支对应的开放 MR

```bash
node {当前项目}/.claude/skills/mr-review-fix/scripts/mr_review.mjs find-by-branch
```

如果找不到对应的 MR，提示用户手动指定 IID 或确认分支。

**获取 MR 全局 ID**：

```bash
node {当前项目}/.claude/skills/mr-review-fix/scripts/mr_review.mjs find-by-iid <iid>
```

从返回的 JSON 中提取 `id`（全局 ID）和 `iid`、`title`、`web_url` 等关键信息，展示给用户确认。

### 步骤 2：获取 MR 评论

使用 MR 全局 ID 获取全部 notes：

```bash
node {当前项目}/.claude/skills/mr-review-fix/scripts/mr_review.mjs notes <mr_id>
```

API 返回 JSON 数组，每条 note 包含：
- `id`：note ID
- `body`：评论内容（Markdown 格式）
- `author.name`：评论者名称
- `author.username`：评论者用户名
- `created_at`：创建时间
- `position`：代码位置（代码行评论时有值，普通评论为 null）
- `resolvable` / `resolved`：是否可解决及解决状态

### 步骤 3：识别 AI 代码审查评论

从所有 notes 中筛选 AI 代码审查评论。满足以下任一条件即判定为 AI 审查评论：

- `author.username` 匹配常见 AI/机器人账号（如 `ai-reviewer`、`code-review-bot`、`ai-cr`、`claude` 等，不区分大小写）
- `body` 中包含明确的严重级别标记（`[Critical]`、`[Warning]`、`[Suggestion]`）
- `body` 中包含评分信息或扣分说明（如"扣 15 分"、"severity: critical"）

在输出中展示给用户：
- 评论总数、AI 审查评论数
- 按级别统计：Critical X 条 / Warning Y 条 / Suggestion Z 条
- 每条 AI 审查评论的摘要（级别、文件、简要描述）

### 步骤 4：处理 Critical 问题

对每一条标记为 `critical` 的评论，执行以下流程：

#### 4a. 问题评估

读取评论中引用的代码文件和上下文，确认问题是否真实存在：

- 如果评论指向具体代码行，读取相关文件验证
- 评估问题描述与代码实际是否匹配
- 判断修复是否会引入副作用

**如果评估认为问题不成立**（如已修复、误报、不适用于当前场景），说明理由并跳过。

**如果评估确认问题成立**，进入修复流程。

#### 4b. 自动修复

1. 使用 Read 工具读取目标文件，理解上下文
2. 使用 Edit 工具进行代码修复
3. 修复完成后，汇总展示修复内容：

```
### Critical 修复完成

**MR #123 — 评论 #456**（作者：AI Reviewer）
- **问题**：SQL 注入风险，用户输入未做参数化处理
- **文件**：src/api/user.go:45
- **修复**：将字符串拼接改为参数化查询
- **变更**：[展示 diff 摘要]
```

#### 4c. 无法自动修复的情况

如果遇到以下情况，标记为"需人工处理"并说明原因：
- 问题描述不清晰，无法确定具体修改方案
- 涉及架构级变更，需要更广泛的上下文
- 修复可能影响其他模块，需要作者确认

### 步骤 5：处理 Warning 和 Suggestion 问题

对 `warning` 和 `suggestion` 级别的评论，**不修改代码**，仅进行评估并输出建议：

对每条 warning/suggestion 评论：

1. 读取相关代码，评估问题有效性
2. 给出处理建议（采纳/忽略/需讨论），简述理由
3. 按以下格式汇总输出：

```
### Warning 评估结果（共 Y 条）

**MR #123 — 评论 #789**（作者：AI Reviewer）
- **问题**：函数过长（120 行），建议拆分
- **文件**：src/service/report.go:30-150
- **评估**：建议采纳 — 该函数包含三个独立逻辑（查询、聚合、格式化），可拆分为三个子函数，提高可测试性

**MR #123 — 评论 #790**（作者：AI Reviewer）
- **问题**：建议使用 async/await 替代 Promise.then
- **文件**：src/utils/fetch.ts:12
- **评估**：可忽略 — 项目中统一使用 Promise 链式调用风格，改动收益不大
```

### 步骤 5b：回填评估结果到工蜂 MR

对每条已评估的 AI 审查评论，将评估结果回填为该评论的回复。

#### 回填命令（默认引用回复）

默认使用 `reply-note`，将评估结果作为引用回复发布，内容通过 stdin 传入：

```bash
cat <<'EOF' | node {当前项目}/.claude/skills/mr-review-fix/scripts/mr_review.mjs reply-note <mr_id> <note_id>
回复内容（Markdown）
EOF
```

PowerShell 等价写法：

```powershell
@"
回复内容（Markdown）
"@ | node {当前项目}/.claude/skills/mr-review-fix/scripts/mr_review.mjs reply-note <mr_id> <note_id>
```

若用户要求直接修改某条既有评论，使用：

```bash
cat <<'EOF' | node {当前项目}/.claude/skills/mr-review-fix/scripts/mr_review.mjs edit-note <mr_id> <note_id>
修改后的评论内容（Markdown）
EOF
```

如果用户要求“不要引用，直接新建独立评论”，使用 `create-note`。

如果需要在 MR 上发布一条新的独立评论（不针对某条具体评论），使用 `create-note`：

```bash
cat <<'EOF' | node {当前项目}/.claude/skills/mr-review-fix/scripts/mr_review.mjs create-note <mr_id>
评论内容（Markdown）
EOF
```

#### 回复格式模板

**Critical 已修复：**

```markdown
✅ **已修复**

**处理方式**：已自动修复
**修改说明**：[简要说明修复内容，如"将字符串拼接改为参数化查询"]
```

**Critical 跳过（误报/不适用）：**

```markdown
⏭️ **评估后跳过**

**原因**：[说明为何该问题不成立，如"该接口仅内部调用，输入已在上层校验"]
```

**Warning/Suggestion 建议采纳：**

```markdown
💡 **建议采纳**

**理由**：[说明为何建议采纳此建议]
**预期收益**：[采纳后的预期改进]
```

**Warning/Suggestion 建议忽略：**

```markdown
➖ **建议忽略**

**理由**：[说明为何建议忽略此建议，如"项目中统一使用该风格"、"改动收益不大"]
```

**需讨论：**

```markdown
❓ **需讨论**

**原因**：[说明为何需要进一步讨论]
**建议方向**：[讨论方向或方案建议]
```

#### 操作确认

回填评论前，向用户展示将要追加的评论列表摘要，征求确认：

```
### 即将回填以下评论到 MR：

| 评论 | 级别 | 评估结果 | 回复摘要 |
|------|------|---------|---------|
| #456 | Critical | ✅ 已修复 | 将字符串拼接改为参数化查询 |
| #789 | Warning | 💡 建议采纳 | 函数过长，建议拆分为三个子函数 |
| #790 | Suggestion | ➖ 建议忽略 | 项目统一使用 Promise 链式风格 |

确认回填以上评论？（用户确认后逐条执行 reply-note）
```

如果用户明确说"自动回填"或"全部回填"，则跳过确认直接发布。

如果用户只想回填部分评论，仅对用户指定的评论执行回填。

### 步骤 6：汇总报告

最终向用户输出完整的问题处理报告：

```
## MR AI 代码审查处理报告

**MR**：[标题]（[链接]）

### 问题统计
| 级别 | 总数 | 已修复 | 需人工 | 建议采纳 | 建议忽略 |
|------|------|--------|--------|----------|----------|
| Critical | X | X | X | - | - |
| Warning | Y | 0 | 0 | Y₁ | Y₂ |
| Suggestion | Z | 0 | 0 | Z₁ | Z₂ |

### Critical 修复清单
- [x] 问题描述 → 已修复（文件:行号）
- [ ] 问题描述 → 需人工处理（原因）

### Warning/Suggestion 建议清单
- [ ] 问题描述 → 建议：xxx（文件:行号）

### 回填状态
- [x] 已回填 X 条评估结果到工蜂 MR
- [ ] 跳过 Y 条（用户选择不回填）
```

## 辅助功能

### 查看指定评论详情

如果用户只想查看某条评论的详细内容而不执行修复，跳过步骤 4-6，仅展示评论正文。

### 只处理 Critical 问题

如果用户明确说"只修复 critical"或"只处理严重问题"，跳过步骤 5（warning/suggestion 评估）和步骤 5b。

### 处理全部问题（含 warning/suggestion）

如果用户明确说"全部修复"或"warning 也修复"，则将 warning 和 suggestion 也纳入修复流程（同步骤 4）。

### 只回填不修复

如果用户明确说"只回填"、"只回复评论"或"不修复只评估"，则跳过步骤 4 的代码修复，仅做评估并在步骤 5b 中回填所有评估结果。

## 错误处理

| 错误 | 处理方式 |
|------|---------|
| Token 未设置 | 提示用户配置 `.claude/settings.local.json` |
| 非 git 仓库 | 提示用户进入正确目录 |
| remote 非 git.code.tencent.com | 提示当前仓库非工蜂项目 |
| 找不到 MR | 提示用户手动指定 IID 或确认分支名称 |
| API 返回 401 | Token 无效或过期，提示重新生成 |
| API 返回空 notes | 提示该 MR 暂无评论 |
| 评论不包含代码位置 | 仅根据文字描述定位，无法确定文件时标记为"需人工处理" |
| get-note 返回 404 | note_id 不存在、已删除，或无权限访问 |
| reply-note 获取原评论失败 | 退化为“仅引用 note_id”后发布新评论 |
