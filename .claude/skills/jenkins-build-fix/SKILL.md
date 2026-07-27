---
name: jenkins-build-fix
description: 自动获取 Jenkins 构建日志，分析构建失败原因，并辅助修复代码问题。当用户提到 Jenkins 构建失败、构建日志分析、CI 失败排查时触发。
---

# Jenkins 构建失败分析与修复助手

你是 Jenkins 构建失败排查专家，帮助开发者快速定位 CI 构建失败原因，并提供修复建议甚至直接修复代码。

## 前置条件

- 环境变量已配置（在 `.claude/settings.local.json` 中设置）：
  - `JENKINS_URL`：Jenkins 地址，如 `https://jenkins.example.com`
  - `JENKINS_USER`：Jenkins 用户名
  - `JENKINS_TOKEN`：Jenkins API Token（在 Jenkins 用户设置 → API Token 中生成）

如果环境变量未设置，提示用户：

> 请先配置 Jenkins 凭证：在项目 `.claude/settings.local.json` 中添加：
> ```json
> {
>   "env": {
>     "JENKINS_URL": "https://jenkins.example.com",
>     "JENKINS_USER": "your-user",
>     "JENKINS_TOKEN": "your-token"
>   }
> }
> ```

## 执行流程

### 步骤 1：收集参数

从用户请求中提取：

| 参数 | 提取方式 | 默认值 |
|------|---------|--------|
| Job 名称 | 用户指定 | 尝试从当前 Git 仓库名推导 |
| Build 编号 | 用户指定 | 自动获取该 Job 最新失败构建 |

如果用户未指定 Build 编号，执行脚本获取最新构建号：

```bash
node .claude/skills/jenkins-build-fix/scripts/jenkins_api.mjs latest "<job-name>"
```

### 步骤 2：获取构建信息

执行脚本获取构建元数据：

```bash
node .claude/skills/jenkins-build-fix/scripts/jenkins_api.mjs info "<job-name>" "<build-number>"
```

解析返回的 JSON，确认：
- `result` 字段是否为 `FAILURE`（非 FAILURE 时提醒用户构建可能已成功）
- `duration` 构建耗时
- `changeSet` 变更集（关联的 commit）

### 步骤 3：获取构建日志

```bash
node .claude/skills/jenkins-build-fix/scripts/jenkins_api.mjs log "<job-name>" "<build-number>"
```

**日志预处理策略**：
1. 如果日志超过 8000 行，截取最后 3000 行（大多数失败信息在末尾）
2. 优先提取含以下关键字的行：`ERROR`、`FAILED`、`FAILURE`、`Exception`、`Traceback`、`error TS`、`error:`、`SyntaxError`、`ModuleNotFoundError`、`ImportError`
3. 保留完整的错误堆栈上下文（错误行前后各 5 行）

### 步骤 4：AI 分析失败原因

基于日志内容，分析并输出结构化报告：

**失败分类**：
| 类型 | 识别特征 |
|------|----------|
| 编译/语法错误 | `SyntaxError`、`error TS`、`cannot find module` |
| 单元测试失败 | `FAILED (failures=`、`AssertionError`、`pytest` 失败统计 |
| Lint/格式检查失败 | `ESLint`、`ruff`、`black --check`、`prettier --check` |
| 类型检查失败 | `mypy` 错误、`tsc` 错误 |
| 依赖安装失败 | `npm ERR!`、`pip install` 失败、`Could not resolve` |
| 环境/权限问题 | `Permission denied`、`No space left`、`Connection refused` |

**分析报告格式**：
```markdown
## 构建失败分析

- **Job**: xxx
- **Build**: #123
- **构建结果**: FAILURE
- **失败类型**: 编译错误
- **关键错误**:
  ```
  [提取的日志片段]
  ```
- **涉及文件**: [文件路径列表]
- **可能原因**: [AI 分析]
```

### 步骤 5：匹配修复方案

对照 `references/error-patterns.md` 中的模式，匹配具体修复方案：

- **高置信度可自动修复**：lint 规则违反、格式化问题、简单缺失 import
- **中置信度需确认**：类型错误、简单语法问题
- **低置信度仅建议**：业务逻辑错误、架构问题、环境问题

### 步骤 6：修复执行（用户确认后）

**对于高置信度修复**：
1. 列出可修复项及对应文件
2. 询问用户是否执行修复
3. 用户确认后，使用 Edit 工具修改本地文件
4. 输出修改摘要（修改了哪些文件、什么问题）

**对于中低置信度修复**：
- 输出详细的修复步骤指南
- 由用户手动执行

**修复边界**：
- 仅修改日志中明确指出的文件
- 不添加新依赖（如需要新依赖，仅提示用户手动安装）
- 不修改 CI/CD 配置文件（如 Jenkinsfile、.github/workflows）
- 不修改测试用例本身（除非测试用例明显错误）

### 步骤 7：后续建议

修复完成后，提示用户：
1. 本地验证修复（如运行 `npm run lint`、`pytest`、`mypy` 等）
2. 提交代码并推送到远程
3. 重新触发 Jenkins 构建验证

## 错误处理

| 错误 | 处理方式 |
|------|----------|
| 环境变量未设置 | 提示配置 `.claude/settings.local.json` |
| Jenkins 无法连接 | 检查 JENKINS_URL 和网络连通性 |
| API 返回 401 | Token 无效，提示重新生成 |
| API 返回 404 | Job 或 Build 编号不存在，确认参数 |
| 构建实际为 SUCCESS | 提醒用户构建已成功，无需分析 |
| 日志为空或过小 | 可能是构建被中止，提示用户检查 |
| 无法定位具体文件 | 可能是环境问题，给出排查建议 |

## 注意事项

- 本 Skill 仅分析构建失败，不处理构建成功后的警告
- 修复操作仅修改本地文件，不涉及自动提交 Git 或触发 Jenkins 重新构建
- 所有 AI 建议仅供参考，复杂问题仍需人工判断
