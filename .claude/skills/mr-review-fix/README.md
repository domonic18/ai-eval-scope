# mr-review-fix Skill

获取工蜂 MR 的 AI 代码审查评论，自动评估并修复 Critical 问题，对 Warning/Suggestion 问题给出决策建议。

## 功能

- 自动检测当前分支对应的工蜂 MR（或手动指定 MR IID）
- 获取 MR 全部评论，智能识别 AI 代码审查内容
- **Critical 问题**：评估确认后自动修复代码
- **Warning / Suggestion 问题**：评估后输出采纳/忽略建议，不自动修改
- 输出完整的处理报告，逐条标注处理状态
- 支持按 `note_id` 编辑评论，并支持“完整引用原评论后新建回复”提高可读性

## 使用示例

```
请对我刚提交的 MR 处理 AI 审查意见
```

```
处理 MR #16 的 critical 问题
```

```
只修复严重问题，warning 和 suggestion 不用管
```

```
把 MR #16 所有级别的审查问题都修复
```

## 问题级别与处理策略

| 级别 | 扣分 | 默认行为 |
|------|------|----------|
| Critical | 15 分 | 评估确认后**自动修复代码** |
| Warning | 5 分 | 评估后**给出建议**，默认不修改 |
| Suggestion | 1 分 | 评估后**给出建议**，默认不修改 |

如果用户明确要求"全部修复"，Warning 和 Suggestion 也会纳入自动修复流程。

## 安装与配置

### 1. 获取工蜂 Token

1. 登录 [腾讯工蜂](https://git.code.tencent.com)
2. 点击右上角头像 → **设置** → 左侧菜单 **访问令牌**
3. 点击 **新建令牌**
4. 名称随意填写（如 `claude-code`），权限勾选 **api**
5. 点击创建，复制生成的 Token（页面关闭后无法再次查看）

### 2. 配置 Token

在项目的 `.claude/settings.local.json` 中添加 `env` 字段：

```json
{
  "env": {
    "TENCENT_GIT_TOKEN": "你刚才复制的Token"
  }
}
```

如果文件已有其他配置（如 `permissions`、`hooks`），将 `env` 字段添加到最外层即可。

### 3. 重启 Claude Code

配置完成后重启 Claude Code，使环境变量生效。

## 文件结构

```
mr-review-fix/
├── SKILL.md           # Skill 定义（触发条件和执行流程）
├── README.md          # 本文件
└── scripts/
  ├── mr_review.mjs  # Node.js 脚本（跨平台：Windows/macOS/Linux）
  └── mr_review.sh   # Bash 脚本（macOS/Linux）
```

## 依赖

| 工具 | 用途 | 说明 |
|------|------|------|
| `curl` | HTTP 请求 | 系统自带 |
| `python3` | URL 编码 | 系统自带 |
| `git` | 分支和仓库信息 | 系统自带 |

## 执行流程

1. **定位 MR** — 从用户指定 IID 或当前分支自动查找
2. **获取评论** — 调用工蜂 API 拉取全部 notes
3. **识别 AI 审查** — 按 bot 账号、严重级别标记筛选 AI 审查评论
4. **处理 Critical** — 验证问题 → 自动修复 → 输出修复报告
5. **评估 Warning/Suggestion** — 分析后给出采纳/忽略建议
6. **汇总报告** — 输出统计表格和逐条处理结果

## 跨项目使用

将 `mr-review-fix/` 目录复制到目标项目的 `.claude/skills/` 下，并在该项目的 `.claude/settings.local.json` 中配置 `TENCENT_GIT_TOKEN` 即可。

脚本通过 `git remote get-url origin` 自动检测项目路径，无需额外配置项目信息。

## 与 tencent-mr 的关系

`tencent-mr` 负责**创建** MR，`mr-review-fix` 负责**处理** MR 上的审查意见。两个 skill 共享同一个 Token 配置和工蜂 API 封装模式，可在同一项目中配合使用。
