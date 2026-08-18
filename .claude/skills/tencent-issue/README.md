# tencent-issue — 腾讯工蜂 Issue 管理技能

通过命令行管理腾讯工蜂项目上的 Issue（缺陷、需求、任务）。

## 功能

| 操作 | 说明 |
|------|------|
| 创建 Issue | 自动填充标题、描述、标签和指派人 |
| 列出 Issue | 按状态、标签筛选 |
| 查看 Issue | 获取 Issue 详情 |
| 关闭/重开 | 变更 Issue 状态 |
| 评论 | 在 Issue 下添加评论 |
| 更新 | 修改标题、标签、指派人 |

## 使用示例

在 Claude Code 中直接对话触发：

```
"在工蜂上创建一个 Issue：评估器 math_formula 有误报问题"
"列出工蜂上所有打开的 Issue"
"关闭 Issue #1"
"在 Issue #3 上评论：已修复，请验证"
```

## Token 配置

在项目根目录 `.claude/settings.local.json` 中添加：

```json
{
  "env": {
    "TENCENT_GIT_TOKEN": "your-token"
  }
}
```

脚本会自动从此文件读取 Token，无需手动 export。

Token 获取路径：腾讯工蜂 → 设置 → 访问令牌 → 创建令牌（勾选 `api` 权限）。

## 文件结构

```
tencent-issue/
├── SKILL.md                          # 技能定义（Claude 读取的执行流程）
├── README.md                         # 本文件
├── scripts/
│   └── tencent_issue.mjs             # Node.js 跨平台脚本（无外部依赖）
└── references/
    └── issue-convention.md           # Issue 命名与格式规范
```

## 手动测试脚本

```bash
node .claude/skills/tencent-issue/scripts/tencent_issue.mjs list
node .claude/skills/tencent-issue/scripts/tencent_issue.mjs get 1
```

## 跨项目安装

将 `tencent-issue/` 目录复制到目标项目的 `.claude/skills/` 下，并配置 `TENCENT_GIT_TOKEN` 即可。
