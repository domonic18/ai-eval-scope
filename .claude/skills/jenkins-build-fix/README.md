# jenkins-build-fix Skill

自动获取 Jenkins 构建日志，分析构建失败原因，并辅助修复代码问题。

## 功能

- 自动获取 Jenkins 构建日志和测试报告
- AI 智能分析失败原因（编译错误、测试失败、lint 问题、依赖问题等）
- 识别可自动修复的问题（lint、格式、简单 import 缺失）
- 输出结构化分析报告，支持人工确认后一键修复

## 使用示例

```
分析一下京小帮主干的最新构建
```

```
jenkins-fix my-project 123
```

```
看看 job/backend-api 的 #45 构建为什么失败
```

## 安装与配置

### 1. 获取 Jenkins API Token

1. 登录 Jenkins Web 界面
2. 点击右上角用户名 → **设置** → **API Token**
3. 点击 **添加新 Token**，输入名称（如 `claude-code`）
4. 点击 **生成**，复制生成的 Token

### 2. 配置凭证

在项目的 `.claude/settings.local.json` 中添加 `env` 字段：

```json
{
  "env": {
    "JENKINS_URL": "https://jenkins.example.com",
    "JENKINS_USER": "your-username",
    "JENKINS_TOKEN": "your-api-token"
  }
}
```

如果文件已有其他配置，将 `env` 字段添加到最外层即可。

### 3. 重启 Claude Code

配置完成后重启 Claude Code，使环境变量生效。

## 文件结构

```
jenkins-build-fix/
├── SKILL.md                      # Skill 定义和指令
├── README.md                     # 本文件
├── scripts/
│   └── jenkins_api.mjs           # Jenkins API 操作脚本（跨平台）
└── references/
    └── error-patterns.md         # 常见错误模式与修复对照表
```

## 依赖

| 工具 | 用途 | 说明 |
|------|------|------|
| `node` | 执行脚本 | 前端开发者必备，v14+ |

**零外部依赖**：`jenkins_api.mjs` 仅使用 Node.js 标准库，无需 npm install。

## 跨平台支持

| 平台 | 支持状态 |
|------|----------|
| macOS | 原生支持 |
| Linux | 原生支持 |
| Windows | 原生支持（需 Node.js） |

## 跨项目使用

将 `jenkins-build-fix/` 目录复制到目标项目的 `.claude/skills/` 下，并在该项目的 `.claude/settings.local.json` 中配置 Jenkins 凭证即可。

## 安全提示

- API Token 仅保存在本地 `.claude/settings.local.json`，**不要提交到 Git**
- 建议 `.gitignore` 中已排除 `.claude/settings.local.json`
- 所有修复操作需用户确认后才执行，不会自动修改代码
