# Issue 命名与格式规范

## 标题格式

```
type: 简洁描述
```

### type 枚举

| type | 用途 | 示例 |
|------|------|------|
| `Bug` | 缺陷/错误 | `Bug: math_formula 评估器正则匹配粒度过粗导致大量误报` |
| `Feat` | 新功能/需求 | `Feat: 支持 PDF 格式课件评估` |
| `Improve` | 改进/优化 | `Improve: 评估缓存 key 增加规则集版本号` |
| `Docs` | 文档相关 | `Docs: 补充 LLM Judge 配置指南` |
| `Perf` | 性能优化 | `Perf: 大批量样本评估并行化` |
| `Test` | 测试相关 | `Test: 补充 commonsense 评估器边界用例` |
| `Chore` | 杂项 | `Chore: 升级 Python 最低版本至 3.12` |

## 描述模板

```markdown
## 问题描述

<清晰描述问题或需求>

## 复现步骤（Bug 适用）

1. ...
2. ...

## 预期行为

<应该是什么样的>

## 实际行为

<实际发生了什么>

## 建议方案（可选）

<修复或实现建议>

## 影响范围

<影响哪些模块/功能>
```

## 标签规范

| 标签 | 用途 |
|------|------|
| `bug` | 缺陷 |
| `feature` | 新功能 |
| `enhancement` | 改进 |
| `documentation` | 文档 |
| `evaluators` | 评估器相关 |
| `llm` | LLM Judge 相关 |
| `sprint-N` | 迭代跟踪 |
| `priority:high` | 高优先级 |
| `priority:low` | 低优先级 |
