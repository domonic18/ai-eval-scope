# 🎯 Claude Code Skills

欢迎来到 Claude Code Skills 目录！这里包含了一系列专业的 skills，用于扩展 Claude Code 的能力，让 AI 助手能够更好地完成特定领域的任务。

## 什么是 Skills？

Skills 是 Claude Code 的一项强大功能，它允许你创建**模块化的能力扩展**。每个 skill 是一个包含指令、脚本和资源的组织化文件夹，可以被 Claude 动态发现和加载。

### 核心特性

- **模型调用**：Claude 根据你的请求和 skill 的描述自动决定何时使用
- **渐进式披露**：只在需要时加载完整的 skill 内容，节省上下文空间
- **易于创建**：只需一个包含 YAML frontmatter 的 SKILL.md 文件
- **灵活部署**：可全局安装或项目级别安装

## Skills 目录结构

```
.claude/skills/
├── README.md           # 本文件
├── news/              # Anthropic 新闻追踪 skill
│   ├── SKILL.md      # skill 定义和指令
│   └── README.md     # 使用文档
└── [其他 skills]/
```

## 可用的 Skills

### 📰 [News Skill](./news/README.md)

**用途**：追踪和深度分析 Anthropic 官方新闻

**主要功能**：
- 自动获取 Anthropic 最新新闻
- 多维度分析（技术、商业、用户、行业）
- 深度思考框架（SWOT、5W1H）
- 结构化知识整理
- 可选历史记录保存

**使用场景**：
- 每周技术动态追踪
- 产品规划参考
- 竞争分析
- 学习资源整理

**快速开始**：
```bash
# 安装
cp -r news ~/.claude/skills/

# 使用
你：分析最新的 Anthropic 新闻
```

[查看详细文档 →](./news/README.md)

---

## 如何使用 Skills

### 安装 Skills

#### 方法 1：全局安装（推荐）

将 skills 复制到用户的全局目录：

```bash
cp -r templates/.claude/skills/* ~/.claude/skills/
```

全局安装的 skills 在所有项目中都可用。

#### 方法 2：项目级别安装

将 skills 复制到特定项目：

```bash
mkdir -p .claude/skills
cp -r templates/.claude/skills/news .claude/skills/
```

项目级别的 skills 只在该项目中可用，适合项目特定的工作流。

#### 方法 3：通过插件安装

Claude Code 支持从官方 skills 市场安装：

```bash
# 未来功能
claude code install skill news
```

### 使用 Skills

Skills 使用非常简单，Claude 会自动识别何时需要调用：

```
你：分析 Anthropic 的最新新闻

Claude：
[自动检测到这个请求需要 news skill]
[加载 news skill 的指令]
[执行新闻获取和分析]
[输出结构化的分析报告]
```

你**不需要**显式调用 skill，只需自然地描述你的需求即可。

### Skills 工作原理

1. **启动时加载**：Claude Code 启动时，会扫描所有已安装的 skills，提取名称和描述
2. **智能匹配**：当你提出请求时，Claude 会根据 skills 的描述判断是否需要使用
3. **动态加载**：如果需要，Claude 会加载完整的 skill 指令
4. **执行任务**：按照 skill 中定义的工作流程和策略执行任务

这种设计确保了：
- **高效**：不使用的 skills 不会占用上下文空间
- **智能**：Claude 自动选择合适的 skills
- **灵活**：可以轻松添加、修改或移除 skills

## 创建自己的 Skills

### 基本结构

一个最简单的 skill 只需要：

```markdown
---
name: my-skill
description: 这个 skill 的简短描述，帮助 Claude 决定何时使用
---

# Skill 标题

skill 的详细指令和工作流程...
```

### 完整示例

查看 [news/SKILL.md](./news/SKILL.md) 获取一个完整的 skill 示例。

### 最佳实践

#### 1. 清晰的描述

description 应该简洁但信息丰富：

```yaml
# ✅ 好的描述
description: 追踪和分析 Anthropic 官方新闻，提供深度阅读分析、知识整理和趋势洞察

# ❌ 不好的描述
description: 新闻分析工具
```

#### 2. 结构化的指令

使用清晰的章节组织 skill 内容：

```markdown
## 核心能力
[列出 skill 的主要功能]

## 工作流程
[详细说明执行步骤]

## 使用示例
[提供具体的使用场景]

## 输出格式
[定义输出的结构]
```

#### 3. 实用的模板

为常见任务提供模板：

```markdown
## 分析模板

### 技术更新模板
```markdown
[模板内容...]
```
```

#### 4. 工具使用指南

明确说明应该使用哪些工具：

```markdown
## 工具使用策略

### WebFetch 工具
- 优先使用 WebFetch 获取内容
- URL: [目标 URL]
- Prompt: [提取指令]

### Read/Write 工具
- 保存结果到指定位置
- 文件格式：Markdown
```

#### 5. 质量标准

定义输出应该达到的标准：

```markdown
## 输出质量标准

### 准确性
- ✅ 信息来源可靠
- ✅ 数据准确无误

### 完整性
- ✅ 覆盖所有重要信息
- ✅ 多维度分析
```

## Skills 开发指南

### Skill 命名规范

- 使用小写字母和连字符
- 简短但描述性强
- 示例：`news`, `code-review`, `api-analyzer`

### 目录结构

```
my-skill/
├── SKILL.md          # 必需：skill 定义
├── README.md         # 推荐：使用文档
├── examples/         # 可选：示例文件
│   └── example1.md
└── resources/        # 可选：额外资源
    └── templates.md
```

### YAML Frontmatter 字段

#### 必需字段

```yaml
---
name: skill-name          # skill 的唯一标识符
description: 简短描述     # 帮助 Claude 决定何时使用
---
```

#### 可选字段

```yaml
---
name: skill-name
description: 简短描述
version: 1.0.0           # skill 版本
author: Your Name        # 作者
tags:                    # 标签
  - analysis
  - news
  - automation
dependencies:            # 依赖的工具或其他 skills
  - WebFetch
  - Write
---
```

### 编写高质量的 Skills

#### 明确目标受众

```markdown
# 为开发者设计的 skill
你是一位专业的代码审查专家...

# 为产品经理设计的 skill
你是一位经验丰富的产品分析师...
```

#### 提供具体的工作流程

```markdown
## 工作流程

### 第一步：信息收集
1. 使用 WebFetch 获取数据
2. 验证数据完整性
3. 提取关键信息

### 第二步：数据分析
[详细步骤...]
```

#### 包含错误处理

```markdown
## 特殊场景处理

### 网络请求失败
1. 尝试备用方案（WebSearch）
2. 使用缓存的数据（如果可用）
3. 通知用户并提供建议
```

#### 提供丰富的示例

```markdown
## 使用示例

### 场景 1：基础用法
**目标**：分析单个新闻

用户：分析最新的产品发布新闻
助手：[执行流程...]

### 场景 2：批量分析
**目标**：分析一周的新闻

用户：分析本周所有新闻
助手：[执行流程...]
```

## Skills 集成

### 与 Commands 集成

Skills 可以被 commands 调用：

```markdown
# 在 .claude/commands/weekly-report.md 中

生成每周报告，包括：
1. 调用 news skill 分析本周新闻
2. 整理关键发现
3. 生成摘要报告
```

### 与 Agents 集成

Agents 可以使用 skills 来完成特定任务：

```markdown
# 在 .claude/agents/research-assistant.md 中

你可以使用以下 skills：
- news: 追踪行业新闻
- api-analyzer: 分析 API 文档
```

### 与 Hooks 集成

通过 hooks 可以在特定事件触发 skills：

```bash
# .claude/hooks/daily-news.sh
# 每天自动运行新闻分析
claude code exec "分析今天的 Anthropic 新闻"
```

## Skills 管理

### 列出已安装的 Skills

```bash
ls ~/.claude/skills/
ls .claude/skills/
```

### 更新 Skills

```bash
# 更新单个 skill
cp -r templates/.claude/skills/news ~/.claude/skills/

# 更新所有 skills
cp -r templates/.claude/skills/* ~/.claude/skills/
```

### 禁用 Skills

```bash
# 临时禁用（重命名）
mv ~/.claude/skills/news ~/.claude/skills/news.disabled

# 启用
mv ~/.claude/skills/news.disabled ~/.claude/skills/news
```

### 删除 Skills

```bash
rm -rf ~/.claude/skills/news
```

## 故障排除

### Skill 没有被激活

**问题**：发出请求后，Claude 没有使用相应的 skill

**可能原因**：
1. Description 不够清晰，Claude 无法匹配
2. Skill 文件格式错误
3. Skill 没有正确安装

**解决方案**：
1. 改进 description，使其更具体
2. 检查 YAML frontmatter 格式
3. 确认 skill 目录位置正确

示例：
```
# 显式提示 Claude 使用 skill
你：使用 news skill 分析最新新闻
```

### Skill 执行出错

**问题**：Skill 被激活但执行过程中出错

**排查步骤**：
1. 检查 skill 依赖的工具是否可用（如 WebFetch）
2. 验证网络连接
3. 检查文件权限
4. 查看 Claude Code 日志

### Skill 输出不符合预期

**问题**：Skill 运行了但输出质量不佳

**改进方法**：
1. 在 skill 中增加更详细的指令
2. 提供更多示例和模板
3. 明确输出质量标准
4. 在请求中提供更多上下文

示例：
```
你：使用 news skill 深度分析最新的 Claude API 更新，重点关注技术实现和迁移指南
```

## 贡献你的 Skills

我们欢迎社区贡献新的 skills！

### 贡献流程

1. **设计 Skill**
   - 确定 skill 的目标和范围
   - 设计工作流程和输出格式
   - 编写 SKILL.md 和 README.md

2. **测试 Skill**
   - 在多个场景下测试
   - 确保输出质量
   - 收集用户反馈

3. **提交 Skill**
   - Fork 这个仓库
   - 在 `templates/.claude/skills/` 下创建新目录
   - 提交 Pull Request

4. **文档和示例**
   - 提供详细的 README
   - 包含多个使用示例
   - 说明局限性和注意事项

### Skill 质量检查清单

提交前请确保：

- [ ] YAML frontmatter 格式正确
- [ ] description 清晰且描述性强
- [ ] 包含详细的工作流程说明
- [ ] 提供至少 3 个使用示例
- [ ] 包含错误处理指南
- [ ] 有完整的 README 文档
- [ ] 输出格式清晰一致
- [ ] 在多个场景下测试通过

## 资源和学习

### 官方资源

- [Claude Code 文档](https://docs.claude.com/en/docs/claude-code/)
- [Skills 功能介绍](https://www.anthropic.com/news/skills)
- [官方 Skills 仓库](https://github.com/anthropics/skills)

### 社区资源

- [Awesome Claude Code](https://github.com/hesreallyhim/awesome-claude-code)
- [Skills 开发教程](https://simonwillison.net/2025/Oct/16/claude-skills/)
- [Skills 最佳实践](https://blog.fsck.com/2025/10/16/skills-for-claude/)

### 示例 Skills

查看官方仓库中的示例：
- PDF 处理 skill
- Excel 分析 skill
- API 测试 skill
- 代码审查 skill

## 常见问题

### Q: Skills 和 Commands 有什么区别？

**A**:
- **Skills**：模块化的能力扩展，由 Claude 自动调用，专注于特定领域的专业知识
- **Commands**：用户显式调用的工作流程（/command），通常编排多个步骤和子代理

### Q: Skills 和 Agents 有什么区别？

**A**:
- **Skills**：给 Claude 提供特定领域的知识和工作流程，增强主对话能力
- **Agents**：独立运行的专家代理，通常由 commands 生成，并行执行复杂任务

### Q: 一个 Skill 可以调用另一个 Skill 吗？

**A**: 可以。在 skill 的指令中可以提示 Claude 使用其他 skills：

```markdown
如果需要分析 API，请使用 api-analyzer skill
如果需要追踪新闻，请使用 news skill
```

### Q: Skills 会占用多少上下文空间？

**A**: Skills 使用渐进式披露策略：
- 启动时只加载名称和描述（很小）
- 只在需要时加载完整内容
- 不使用的 skills 不占用上下文

### Q: 可以创建私有的 Skills 吗？

**A**: 当然！Skills 可以：
- 全局安装（~/.claude/skills/）- 个人使用
- 项目级别安装（.claude/skills/）- 团队共享
- 不公开发布 - 保持私有

### Q: Skills 支持哪些编程语言的脚本？

**A**: Skills 本身是 Markdown 格式的指令，但可以：
- 调用 Bash 命令
- 使用 Claude Code 的所有工具
- 引用外部脚本（Python、Node.js 等）

## 路线图

### 即将推出

- [ ] 更多示例 skills（API 分析、代码审查、文档生成）
- [ ] Skill 模板生成器
- [ ] Skill 测试框架
- [ ] Skill 性能监控

### 未来计划

- [ ] Skill 市场和发现机制
- [ ] Skills 之间的依赖管理
- [ ] 可视化的 skill 编辑器
- [ ] Skills 的版本控制和更新机制

## 获取帮助

- **文档问题**：查看 [Claude Code 文档](https://docs.claude.com/en/docs/claude-code/)
- **Bug 报告**：在 [GitHub Issues](https://github.com/cfrs2005/claude-init/issues) 提交
- **功能建议**：在 [Discussions](https://github.com/cfrs2005/claude-init/discussions) 讨论
- **社区交流**：加入 Claude Code 社区

## 许可证

这些 skills 是 claude-init 项目的一部分，遵循项目的开源许可证。

---

**开始创建你的第一个 Skill，扩展 Claude Code 的无限可能！** 🚀

*最后更新: 2025-10-21*
