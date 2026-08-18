# tencent-mr Skill

通过自然语言在 Claude Code 中直接创建腾讯工蜂合并请求（MR）。

## 功能

- 自动检测当前项目的工蜂仓库（通过 `git remote`）
- 自动生成符合规范的 MR 标题和描述
- 支持按姓名指定评审人
- 基于 commit 历史归纳变更内容

## 使用示例

```
请提交当前分支合并到 develop 的合并请求，评审人选江凯
```

```
创建一个 MR，把 feature/login 合到 main
```

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
tencent-mr/
├── SKILL.md              # Skill 定义（触发条件和执行流程）
├── README.md             # 本文件
├── scripts/
│   └── tencent_mr.sh     # 工蜂 API 操作脚本
└── references/
    └── pr-convention.md  # MR 标题和描述格式规范
```

## 依赖

| 工具 | 用途 | 说明 |
|------|------|------|
| `curl` | HTTP 请求 | 系统自带 |
| `jq` | JSON 构建 | macOS: `brew install jq` |
| `python3` | URL 编码 | 系统自带 |
| `git` | 分支和仓库信息 | 系统自带 |

## 跨项目使用

将 `tencent-mr/` 目录复制到目标项目的 `.claude/skills/` 下，并在该项目的 `.claude/settings.local.json` 中配置 `TENCENT_GIT_TOKEN` 即可。

脚本通过 `git remote get-url origin` 自动检测项目路径，无需额外配置项目信息。
