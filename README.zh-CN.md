# EvalScope（ai-eval-scope）

[English](README.md) | [简体中文](README.zh-CN.md)

[![CI](https://github.com/domonic18/ai-eval-scope/actions/workflows/ci.yml/badge.svg)](https://github.com/domonic18/ai-eval-scope/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/ai-eval-scope.svg)](https://pypi.org/project/ai-eval-scope/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![Code Style: ruff](https://img.shields.io/badge/code%20style-ruff-261230.svg)](https://docs.astral.sh/ruff/)

基于 **Agent 驱动**的新一代评测系统：把 Agent 评测变成一条**可执行、可复用、可量化**的标准流水线——

```
描述评测需求 → 生成"考卷"（场景包） → 被测 Agent 真实答题 → 规则 + AI 双层判分 → 报告 → 平台看趋势
```

**👇 先看一段 60 秒的直观感受——CLI 里对话式自动创建评测包：**

![CLI 对话式自动创建评测包 · 动画演示](./docs/assets/demo.gif)

## 为什么需要它

大模型 Agent（智能客服、课件生成、代码助手……）的输出是**非确定的**：同一问题每次回答都不同，传统"脚本回放 + `预期 == 实际`"的自动化测试直接失效。本系统的解法是**执行智能化、评估确定性**——

| | 传统自动化测试 | EvalScope |
|------|------------------|------------------------|
| 执行方式 | 脚本逐步回放，环境稍变即失败 | ExecutionAgent 理解任务、自主决策、遇阻应对 |
| 判分方式 | 硬编码断言 | 规则引擎（硬性检查）+ LLM Judge（语义质量） |
| 用例维护 | 人工维护脚本 | 场景包（YAML），对话式生成、可版本化 |
| 适用对象 | UI / API 等确定性系统 | LLM / Agent 等非确定性系统 |

## 适用场景

- **对话 Agent 评测**：安全性（风险提问正确拒绝）、任务完成质量、多轮对话
- **知识库检索评测**：找对找全、不编造（幻觉陷阱用例）、交付可定位
- **生成质量评测**：课件生成、代码生成等多维质量组合评估
- **版本回归对比**：统一口径持续评测，量化回答"比上一版变好了吗"

内置 courseware / code / chat 三类场景包，新增场景（RAG、自定义）只需写一个 YAML 包，无需改代码。

## 核心特性

- **会聊天就会用**：用自然语言描述"我想测什么"，工作台 Agent 自动生成全套评测资产（考卷、判分规则、Judge 提示词、被测系统配置），每份文件先看 diff、确认后才落盘
- **被测系统自动接入**：给一个系统入口地址（登录页 URL 都行），自动分析登录接口、实测登录、探测对话 API；凭证隐藏输入、不落任何配置文件
- **双层判分**：格式门控 → 规则引擎 → LLM Judge → 视觉截图评估（Playwright），每个得分都能说清理由
- **执行器在线评测**：ExecutionAgent（DeepAgents 底座）驱动被测 Agent 完成任务——多轮对话、遇阻应对、预算兜底
- **可观测平台**：仿 Langfuse 的多租户平台，运行 / 趋势 / 指标 / 样本对话轨迹全可视化

## 快速开始：三步开启第一次评测

环境要求：Python 3.11+。

```bash
# ① 安装（[agent] 执行引擎必装，[llm] AI 判分必装；uv 或 pip 任选）
uv tool install "ai-eval-scope[agent,llm]"
agent-eval --version

# ② 配置评测模型（选厂商 → 粘 API Key → 自动连通性测试）
agent-eval models set

# ③ 启动 CLI 工作台，对话式说需求即可：建包 → 探测被测系统 → 执行评测 → 看报告
agent-eval start
```

工作台里选「1. 工作台 Agent」，一句话描述评测需求（如"给这个在线 Agent 做安全性评测"）+ 给被测系统入口地址，剩下的自动完成。也可以直接命令行一条龙（执行 → 评估 → 报告 → 上传）：

```bash
agent-eval pipeline --package chat --task "safety_*" --upload
```

![CLI 一条龙执行与结果摘要](./docs/assets/cli-pipeline-result.png)

> 完整命令与参数（run / pipeline / suite / models / secrets / package / dataset …）、`--task` 选择语法、场景包目录结构与五类资产、FAQ 见 **[CLI 使用教程](./docs/guide/CLI使用教程.md)**。

## 可观测平台

项目内置仿 Langfuse 的多租户可观测平台（`web/`）：项目与 API Key 管理、场景化指标动态渲染、逐样本对话轨迹与判分明细、跨运行趋势对比、Webhook 回调。CLI 连接平台（`agent-eval auth login`）后每次评测自动上报。

```bash
cp .env.example .env     # 填入 DB / 对象存储 / 安全密钥
make docker-up           # 启动 postgres + minio + web（本地 http://localhost:9000）
```

![平台运行详情：场景化指标 + 摘要报告 + 逐样本得分](./docs/assets/platform-run-detail.png)

平台架构与部署细节见 [Web 可观测平台架构设计](./docs/arch/09Web可观测平台架构设计.md)。

## 文档索引

| 文档 | 内容 |
|------|------|
| [CLI 使用教程](./docs/guide/CLI使用教程.md) | 全命令手册、场景包目录结构与五类资产、课件 / Agent 评测实战、CI 集成 |
| [整体架构设计](./docs/arch/01整体架构设计.md) | evaluator / web / executor 三域架构与数据流 |
| [评估引擎设计](./docs/arch/04评估引擎设计.md) | 门控 / 规则 / LLM Judge / 视觉评估与指标聚合 |
| [数据管理与配置规范](./docs/arch/06数据管理与配置规范.md) | 场景包重组、数据集抽象、workspace 布局 |
| [第三方系统对接方案](./docs/arch/12第三方系统对接方案.md) | HTTP API / Webhook / MCP 接入指南 |
| [贡献指南](./CONTRIBUTING.md) | 提交 / 分支 / PR 规范，开发环境搭建 |

## 贡献

欢迎提交 Issue 和 Pull Request！开发流程、提交规范、PR 流程见 [CONTRIBUTING.md](./CONTRIBUTING.md)。

## 致谢

本项目在评测数据集下载、数据集索引等设计上参考了 [OpenCompass](https://github.com/open-compass/opencompass)，部分数据集的 HuggingFace / ModelScope 来源元数据（`evaluator/agent_eval/assets/datasets/dataset_index.yaml`）移植自 OpenCompass。感谢 OpenCompass 团队优秀的开源工作。

## License

[MIT](./LICENSE)
