# Agent 能力评估系统需求规格说明书

> 本文档基于 [01课件生成评估体系规划.md](./01课件生成评估体系规划.md)，将评估体系规划落地为一项可执行、可扩展的评估系统，明确系统边界、模块职责、数据流转与规则规范，供人与 Agent 共同使用。

> **⚠️ 适配说明（2026-06-08）**：当前阶段评估目标已从 PPTX 课件调整为 **Markdown/HTML 文档集**（多文档组合），暂不支持 PPTX。本文档中的规则示例、数据包示例已同步更新，其余"PPT/Slides"相关描述为原始需求，具体实现以架构设计文档为准。

---

## 一、引言

### 1.1 编写目的

为“Agent 能力评估系统”建立统一的需求基线，使后续系统设计、开发、测试与验收都有据可依。本系统既可以由人类开发者/评估人员直接使用，也可以被其他 Agent 调用、理解与扩展。

### 1.2 背景

当前以**课件生成 Agent** 作为首个落地场景，覆盖功能性、效果性、安全性、性能四大维度（详见 `01课件生成评估体系规划.md`）。但系统设计上需面向**通用 Agent 评估框架**演进，未来可扩展至代码生成、数据分析、客服对话、RAG 检索等更多 Agent 类型。

为将评估体系落地执行，需要一个可运行的 Python 评估系统，该系统应当：

- 驱动被测 Agent 自动化完成各类任务（当前以课件生成为主）；
- 收集生成结果与过程数据；
- 按照指标体系对结果进行评估；
- 输出结构化评估报告；
- 允许用户（人或 Agent）灵活定制评估规则。

### 1.3 术语表

| 术语 | 说明 |
|------|------|
| **SUT** | System Under Test，被测 Agent 或被测系统。 |
| **执行引擎 (Execution Engine)** | 负责驱动 SUT 运行、采集输出与过程日志的模块。 |
| **评估引擎 (Evaluation Engine)** | 负责按照规则对结果与过程进行打分、判定、聚合的模块。 |
| **规则集 (Rule Set)** | 一组评估规则的集合，定义约束条件、检查方式、权重、阈值等。 |
| **任务集 (Task Set)** | 待评估的输入集合，每个任务对应一次 SUT 运行。 |
| **级联评估 (Cascade Evaluation)** | 先低成本 Rule-based 筛选，再高成本 LLM-as-judge 评估的流程。 |

---

## 二、系统总体定位

### 2.1 核心目标

建设一个**以 Agent 调用为主、人类可校对**的通用 Agent 能力评估框架，当前以课件生成 Agent 为切入点，未来可扩展至多类 Agent 场景。系统应当：

1. 提供可扩展的评估指标体系，当前覆盖课件生成的功能性、效果性、安全性、性能四大维度；
2. 支持**执行**与**评估**两个核心阶段独立运行，也能串联成完整 Pipeline 自动运行；
3. 提供对 Agent 自动生成与人类专家校对都友好的规则描述格式；
4. 优先支持 CLI 与程序化调用（Python SDK / REST API），便于类似 Claude Code 的 Agent 工具集成，人机界面（Web UI）在前期为非必要项。

### 2.2 目标用户

| 用户类型 | 优先级 | 使用场景 | 期望能力 |
|----------|--------|----------|----------|
| **Agent 用户 / Claude Code 类工具** | P0 | 自动化评估、CI 集成、规则自动生成、批量回归测试 | CLI / Python SDK / REST API、结构化配置、机器可读报告 |
| **人类开发者** | P1 | 本地调试 Agent、查看评估报告、校对 Agent 生成的规则 | CLI、可读的配置文件、Markdown/JSON 报告 |
| **项目经理 / 团队负责人** | P1 | 查看项目评估趋势、对比不同版本的评估结果 | Web Portal 项目看板、趋势图、运行历史 |
| **人类评估人员** | P2 | 抽检评估结果、仲裁争议案例、查看详细评估报告 | Web Portal 报告详情页、案例溯源、Markdown 报告 |
| **其他系统** | P1 | 嵌入 MLOps / AgentOps 流水线 | 标准输入输出接口、REST API、Webhook |

### 2.3 设计原则

1. **人机双友好**：所有配置文件、接口协议、报告格式均兼顾人类可读性与机器可解析性。
2. **执行-评估解耦**：执行引擎与评估引擎通过标准化数据接口交互，可独立运行，可替换实现。
3. **规则即配置**：评估规则以声明式方式描述，支持版本管理、热加载与动态组合。
4. **级联与可扩展**：默认采用级联评估降低开销，同时允许插件化扩展新的评估维度。
5. **结果可解释**：每项评分都应追溯到具体规则、证据与原始输出片段。
6. **趋势可追溯**：系统支持按项目维度追踪评估结果变化趋势，便于回归检测与质量监控。

---

## 三、系统总体架构

### 3.1 逻辑架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                         用户接口层                                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐   │
│  │  CLI     │  │Web Portal│  │  REST API│  │  Python/TS SDK   │   │
│  │  (P0)    │  │  (P1)    │  │  (P1)    │  │     (P0)         │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         编排调度层 (Orchestrator)                    │
│  · 解析任务集与规则集                                                 │
│  · 选择执行模式（仅执行 / 仅评估 / 完整流水线）                        │
│  · 协调执行引擎与评估引擎                                             │
│  · 生成最终报告                                                      │
└─────────────────────────────────────────────────────────────────────┘
           │                                    │
           ▼                                    ▼
┌─────────────────────────┐      ┌─────────────────────────────┐
│      执行引擎            │      │         评估引擎             │
│  ┌───────────────────┐  │      │  ┌───────────────────────┐  │
│  │ 任务分发器         │  │      │ │ 规则加载器             │  │
│  │ · 读取任务集       │  │      │ │ · 解析规则集           │  │
│  │ · 并发调度 SUT     │  │      │ │ · 构建评估 DAG         │  │
│  └───────────────────┘  │      │ └───────────────────────┘  │
│  ┌───────────────────┐  │      │  ┌───────────────────────┐  │
│  │ SUT 驱动器         │  │      │ │ 评估器池               │  │
│  │ · 调用 SUT         │  │      │ │ · Rule-based Evaluator│  │
│  │ · 超时/重试控制    │  │      │ │ · LLM-as-judge       │  │
│  │ · 异常处理         │  │      │ │ · Fact-check Eval    │  │
│  └───────────────────┘  │      │ │ · Metric Aggregator  │  │
│  ┌───────────────────┐  │      │ └───────────────────────┘  │
│  │ 结果采集器         │  │      │  ┌───────────────────────┐  │
│  │ · 输出文件         │  │      │ │ 评分聚合器             │  │
│  │ · 目录遍历采集     │  │      │ │ · 约束得分 → Reward   │  │
│  │ · 执行日志         │  │      │ │ · 指标汇总            │  │
│  │ · 过程指标         │  │      │ └───────────────────────┘  │
│  └───────────────────┘  │      │                              │
└─────────────────────────┘      └─────────────────────────────┘
           │                                    │
           └────────────┬───────────────────────┘
                        ▼
           ┌────────────────────────┐
           │    标准化评估数据包       │
           │  (Evaluation Package)   │
           │  · task.json            │
           │  · output/              │
           │  · _manifest.json       │
           │  · trace.json           │
           │  · metrics.json         │
           │  · eval_result.json     │
           └────────────┬────────────┘
                        │
                        ▼
           ┌────────────────────────┐
           │    可视化服务            │
           │  · Workspace 索引       │
           │  · 项目级聚合           │
           │  · 趋势数据计算         │
           │  · Web Portal API      │
           └────────────────────────┘
```

### 3.2 执行-评估解耦设计

执行引擎与评估引擎之间通过**标准化评估数据包（Evaluation Package）** 解耦：

| 模块 | 输入 | 输出 | 运行方式 |
|------|------|------|----------|
| **执行引擎** | `task_set.json` + SUT 配置 | `eval_package/`（含输出物、日志、过程指标） | 可独立运行 |
| **评估引擎** | `eval_package/` + `rule_set.yaml` | `eval_result.json` + `report.html/md` | 可独立运行 |
| **完整流水线** | `task_set.json` + SUT 配置 + `rule_set.yaml` | 执行包 + 评估结果 + 报告 | 串行运行 |

解耦收益：

- 执行阶段可单独用于批量生成课件或回归测试；
- 评估阶段可复用历史执行包进行规则调优、人工复评、基线对比；
- 两个模块可由不同团队独立迭代；
- Agent 用户可直接生成标准数据包，接入外部评估服务。

---

## 四、功能需求

### 4.1 执行引擎功能

#### 4.1.1 任务管理

| ID | 需求 | 优先级 |
|----|------|--------|
| F-E-01 | 支持从 JSON/YAML 文件加载任务集，每项任务包含任务 ID、输入需求、期望约束、预期知识点等。 | P0 |
| F-E-02 | 支持对任务集进行分批、并发调度，可配置并发度。 | P0 |
| F-E-03 | 支持单次任务执行（Debug 模式）。 | P1 |
| F-E-04 | 支持任务模板与变量替换，便于批量生成相似任务。 | P1 |
| F-E-04a | **提供任务集构建工具**：支持从零创建任务集，提供学科、年级、知识点、约束条件等字段模板；支持通过 LLM 半自动化生成初始任务草案。 | P0 |
| F-E-04b | **支持预期答案/知识点标注**：在任务集中允许标注标准答案、知识点清单、约束期望，供后续 Accuracy、Coverage、Hallucination 等指标评估使用。 | P0 |

#### 4.1.2 SUT 接入

| ID | 需求 | 优先级 |
|----|------|--------|
| F-E-05 | 提供统一 SUT 驱动接口，**默认以 HTTP API 接入**（适配 LangGraph 封装服务、Hermes 搭建服务等）；同时保留 CLI 命令与 Python SDK 扩展能力。 | P0 |
| F-E-06 | 支持接入本地 Agent、远程 Agent 服务、容器化 Agent；HTTP 接入需支持自定义 Headers、鉴权方式与请求/响应格式映射。 | P0 |
| F-E-07 | 支持在 SUT 调用前后注入前置/后置处理脚本（如数据转换、环境准备、请求签名）。 | P1 |
| F-E-08 | 支持 SUT 调用超时、重试与异常隔离，单任务失败不影响其他任务。 | P0 |

#### 4.1.3 结果采集

| ID | 需求 | 优先级 |
|----|------|--------|
| F-E-09 | 自动收集 SUT 生成的课件文件（PPT、PDF、图片等）并归档到执行包。 | P0 |
| F-E-10 | 记录完整执行日志，包括请求输入、SUT 返回、调用耗时、错误堆栈。 | P0 |
| F-E-11 | 自动统计过程指标：总耗时、 Steps/Turns、重试次数、工具调用次数。 | P0 |
| F-E-12 | 支持从 SUT 返回中提取结构化元数据（如 Agent 自行报告的思考链、工具调用记录）。 | P1 |

### 4.2 评估引擎功能

#### 4.2.1 规则解析

| ID | 需求 | 优先级 |
|----|------|--------|
| F-V-01 | 支持从 YAML/JSON 文件加载规则集，规则格式对人类与 Agent 均友好。 | P0 |
| F-V-02 | 支持规则分组与层级结构，可按维度（功能/效果/安全/性能）组织。 | P0 |
| F-V-03 | 支持规则的依赖声明，形成评估 DAG，实现级联评估。 | P1 |
| F-V-04 | 支持规则的热加载与版本化管理。 | P1 |

#### 4.2.2 评估执行

| ID | 需求 | 优先级 |
|----|------|--------|
| F-V-05 | 支持 Rule-based 评估器：基于文件解析、正则、数值比较、枚举判定等方式检查约束。 | P0 |
| F-V-06 | 支持 LLM-as-judge 评估器：通过配置化 Prompt 调用大模型进行语义打分。 | P0 |
| F-V-06a | **LLM Provider 抽象层**：默认使用 DeepSeek，同时支持配置其他模型提供商；必须兼容 Anthropic 协议（Kimi / 智谱 / MiniMax coding plan）与 OpenAI 兼容协议。 | P0 |
| F-V-07 | 支持事实验证评估器：对接知识库 API、公式验证库、搜索引擎等外部权威来源。 | P0 |
| F-V-08 | 支持级联评估：前一层失败可配置为终止后续评估或继续记录。 | P0 |
| F-V-09 | 支持评估器插件机制，允许用户注册自定义评估器（Python 脚本）。 | P1 |
| F-V-10 | 支持评估结果的缓存，避免重复调用 LLM 或外部 API。 | P1 |
| F-V-11 | **视觉/多模态评估支持**：视觉质量评估优先调用多模态 LLM（目标为 Kimi-2.6），输入课件截图或页面资源，输出结构化评分。 | P1 |

#### 4.2.3 评分聚合

| ID | 需求 | 优先级 |
|----|------|--------|
| F-V-12 | 根据规则集自动计算约束满足率、Reward Score、DR、CPR、CondR 等核心指标。 | P0 |
| F-V-13 | 支持自定义聚合公式与权重，允许在规则集中声明。 | P1 |
| F-V-14 | 支持按任务、按维度、按规则细项输出得分与失败原因。 | P0 |
| F-V-15 | 支持生成便于人工审阅的 Markdown 报告，以及便于 Agent 消费的 JSON 报告；HTML / Web UI 为 P2 需求。 | P0 |

### 4.3 规则管理功能

| ID | 需求 | 优先级 |
|----|------|--------|
| F-R-01 | 规则使用声明式 YAML 描述，字段命名自解释，支持注释。 | P0 |
| F-R-02 | 每条规则包含：ID、名称、描述、维度、检查方式、权重、阈值、失败惩罚、Prompt（如适用）。 | P0 |
| F-R-03 | 提供规则 Schema 校验，人类编辑时由 IDE/LSP 提示错误，Agent 编辑时可程序化校验。 | P0 |
| F-R-04 | 提供规则模板库（格式约束模板、常识约束模板、软约束模板、偏好约束模板）。 | P1 |
| F-R-05 | 支持规则的继承与覆盖，便于针对不同学科/年级/场景定制规则。 | P1 |
| F-R-06 | **支持 Agent 自动生成规则**：通过 Prompt 或示例输入，由 LLM 输出符合 Schema 的规则草案，并保存为 YAML。 | P0 |
| F-R-07 | **支持 Agent 自动修改规则**：允许 Agent 通过 SDK / API 读取现有规则、定位待修改项、生成 Diff，并由人类确认或自动合并。 | P1 |
| F-R-08 | 规则变更需记录版本历史，支持 Diff 查看与回滚。 | P1 |

### 4.4 报告与可视化

| ID | 需求 | 优先级 |
|----|------|--------|
| F-RP-01 | 生成任务级报告：每个任务的通过状态、得分、失败规则、证据截图/文本。 | P0 |
| F-RP-02 | 生成聚合报告：整体指标统计、维度分布、趋势对比、失败案例 TopN。 | P0 |
| F-RP-03 | 报告优先支持 **Markdown**（便于人类审阅与 Git 版本控制）与 **JSON**（便于 Agent 消费），HTML 为可选增强。 | P0 |
| F-RP-04 | 支持历史报告对比与基线管理。 | P1 |
| F-RP-05 | Web UI 提供任务列表、报告查看、规则编辑、人工仲裁界面。 | P1 |
| F-RP-06 | 支持历史评估结果的存储与索引，便于跨运行的趋势对比与回溯。 | P1 |

### 4.5 Web 可视化与追溯

| ID | 需求 | 优先级 |
|----|------|--------|
| F-W-01 | 提供 Web Portal，支持以项目为维度分组查看评估运行历史与结果。 | P1 |
| F-W-02 | 支持项目级趋势看板，展示 DR / CPR / Reward 等核心指标随运行次数的变化曲线。 | P1 |
| F-W-03 | 支持查看单次评估运行的详细报告：任务级得分、规则结果、LLM Judge 溯源证据。 | P1 |
| F-W-04 | 支持按日期、规则集版本、SUT 版本筛选运行记录并对比结果。 | P2 |
| F-W-05 | Web Portal 可通过 CLI 命令启动（`agent-eval serve`），也可作为独立服务部署。 | P1 |
| F-W-06 | 支持"项目"概念作为评估运行的分组机制，通过 `project.yaml` 配置文件声明项目信息。 | P1 |

### 4.6 目录结构评估

| ID | 需求 | 优先级 |
|----|------|--------|
| F-D-01 | 支持指定目录路径作为评估输入目标（通过 task_set.yaml 或 CLI 参数指定）。 | P0 |
| F-D-02 | 自动遍历目录结构，收集所有 HTML 文件（或指定文件类型）用于评估。 | P0 |
| F-D-03 | 在评估数据模型中保留并呈现文件的层级关系（模块 → 子模块 → 文件）。 | P1 |
| F-D-04 | 支持评估目录结构本身（模块命名规范、层级深度、文件组织合理性）。 | P2 |
| F-D-05 | 支持按目录层级聚合评估结果（如按模块汇总），实现分维度报告。 | P1 |
| F-D-06 | 处理自包含 HTML 文件（内联 CSS/JS，无外部依赖），确保评估器可独立解析每个文件。 | P0 |

---

## 五、规则集格式规范（草案）

规则集是连接人类意图与评估引擎的核心配置，需同时满足“人易读”与“Agent 易处理”两个要求。推荐采用**YAML + JSON Schema** 组合：

```yaml
# rule_set.yaml
version: "1.0"
description: "课件生成 Agent 评估规则集"
schema: "./rule_set_schema.json"

dimensions:
  - id: functional
    name: "功能性"
    weight: 1.0
  - id: effectiveness
    name: "效果性"
    weight: 1.0
  - id: safety
    name: "安全性"
    weight: 1.0
  - id: performance
    name: "性能"
    weight: 0.5

cascade:
  - stage: format_gate
    name: "格式门控"
    stop_on_fail: true
  - stage: commonsense_gate
    name: "常识门控"
    stop_on_fail: false
  - stage: quality_eval
    name: "质量评估"
    stop_on_fail: false

rules:
  # 格式约束
  - id: FMT_001
    name: "输出格式有效"
    dimension: functional
    stage: format_gate
    description: "SUT 必须生成有效的 Markdown 或 HTML 文件"
    evaluator: file_format
    params:
      allowed_formats: ["md", "html"]
    weight: 1.0
    penalty_on_fail: -3

  - id: FMT_002
    name: "文档数量合规"
    dimension: functional
    stage: format_gate
    description: "输出文档数量应在任务要求的范围内"
    evaluator: document_count
    params:
      min: "{{task.constraints.min_documents | default(1)}}"
      max: "{{task.constraints.max_documents | default(20)}}"
    weight: 1.0
    penalty_on_fail: -3

  # 常识约束
  - id: CSM_001
    name: "知识点准确性"
    dimension: effectiveness
    stage: commonsense_gate
    description: "课件中的知识点陈述应与标准知识库一致"
    evaluator: fact_check
    params:
      source: knowledge_base
      match_fields: ["term", "definition", "formula"]
    weight: 1.0
    penalty_on_fail: 0

  # 软约束
  - id: SFT_001
    name: "教学逻辑性"
    dimension: effectiveness
    stage: quality_eval
    description: "内容组织是否符合导入→新授→练习→总结的认知规律"
    evaluator: llm_judge
    params:
      model: "gpt-4o"
      temperature: 0
      prompt: "prompts/teaching_logic.txt"
      output_schema: "schemas/teaching_logic_score.json"
    weight: 0.2
    normalize_to: [0, 1]
```

**规范说明**：

- 使用 YAML 作为主格式，人类可读、支持注释、层级清晰；
- 所有动态值使用 `{{ }}` 模板语法，便于引用任务属性；
- 每个 `evaluator` 对应评估引擎中的一个评估器实现；
- `stage` 字段明确规则属于哪一级联阶段；
- 提供 JSON Schema 对规则集进行自动校验。

---

## 六、数据包规范

### 6.1 执行包结构

```
eval_package/
├── manifest.json              # 数据包元信息
├── task.json                  # 原始任务定义
├── output/                    # SUT 输出物（Markdown/HTML 文档集）
│   ├── index.md               # 主文档
│   ├── chapter_01.html
│   └── assets/
│       └── image_01.png
├── trace.json                 # 执行过程日志
├── metrics.json               # 过程指标
└── metadata.json              # SUT 与运行环境元信息
```

### 6.2 评估结果结构

```
eval_result/
├── manifest.json              # 评估元信息（规则集版本、时间戳）
├── rule_results.json          # 每条规则的判定结果
├── scores.json                # 各维度与综合得分
├── evidence/                  # 证据文件
│   ├── FMT_001_screenshot.png
│   └── CSM_001_diff.json
└── report.md / report.html    # 可视化报告
```

---

## 七、非功能需求

### 7.1 性能

| ID | 需求 | 优先级 |
|----|------|--------|
| NF-01 | 支持任务级并发执行，并发度可配置。 | P0 |
| NF-02 | 评估阶段优先使用 Rule-based 与缓存，降低 LLM 调用成本。 | P0 |
| NF-03 | 单次 Rule-based 评估耗时控制在秒级。 | P1 |

### 7.2 可扩展性

| ID | 需求 | 优先级 |
|----|------|--------|
| NF-04 | 评估器插件化，新增维度无需改动核心引擎。 | P0 |
| NF-05 | 规则集与任务集格式版本化，向后兼容。 | P0 |
| NF-06 | SUT 驱动接口标准化，便于接入不同类型的 Agent。 | P0 |

### 7.3 可维护性

| ID | 需求 | 优先级 |
|----|------|--------|
| NF-07 | 核心模块均有单元测试覆盖，关键路径覆盖率达到 80% 以上。 | P1 |
| NF-08 | 提供清晰的日志与错误码，便于定位执行与评估失败原因。 | P0 |
| NF-09 | 规则集、任务集、Prompt 文件均使用文本格式，纳入版本控制。 | P0 |

### 7.4 安全性

| ID | 需求 | 优先级 |
|----|------|--------|
| NF-10 | SUT 运行在隔离环境（沙箱/容器）中，避免恶意输出影响主机。 | P1 |
| NF-11 | LLM 评估调用中的敏感数据支持脱敏或本地模型替代。 | P1 |

---

## 八、接口需求

### 8.1 CLI 接口

```bash
# 仅执行
agent-eval run \
  --task-set ./tasks/math_grade7.yaml \
  --sut ./sut_configs/agent_a.yaml \
  --output ./packages/run_20250608/

# 仅评估
agent-eval eval \
  --package ./packages/run_20250608/ \
  --rule-set ./rules/courseware_v1.yaml \
  --output ./results/eval_20250608/

# 完整流水线
agent-eval pipeline \
  --task-set ./tasks/math_grade7.yaml \
  --sut ./sut_configs/agent_a.yaml \
  --rule-set ./rules/courseware_v1.yaml \
  --output ./results/full_20250608/
```

### 8.2 Python SDK 接口（示例）

```python
from agent_eval import Executor, Evaluator, TaskSet, RuleSet

# 仅执行
tasks = TaskSet.load("tasks/math_grade7.yaml")
executor = Executor.from_config("sut_configs/agent_a.yaml")
packages = executor.run_all(tasks, output_dir="./packages/run_20250608/")

# 仅评估
rules = RuleSet.load("rules/courseware_v1.yaml")
evaluator = Evaluator(rules=rules)
results = evaluator.evaluate(packages[0])
results.save("./results/eval_20250608/")
```

### 8.3 REST API 接口（可选）

- `POST /runs`：提交执行任务
- `GET /runs/{id}`：查询执行状态
- `POST /evaluations`：提交评估任务
- `GET /evaluations/{id}`：查询评估结果
- `GET /reports/{id}`：下载评估报告

**Web Portal 所需端点**：

- `GET /projects`：列出所有项目
- `GET /projects/{id}`：获取项目详情（含最新运行状态）
- `GET /projects/{id}/runs`：列出项目下的评估运行历史
- `GET /projects/{id}/trends`：获取项目趋势数据（DR/CPR/Reward 随时间变化）
- `GET /runs/{id}/report`：获取单次运行的详细报告
- `GET /runs/{id}/tasks/{task_id}`：获取任务级评估详情（含规则结果、LLM 溯源）

### 8.4 Web Portal 接口

**技术选型**：React + Express，适配腾讯云函数部署。

**页面结构**：

| 页面 | 路由 | 功能 |
|------|------|------|
| 项目列表 | `/` | 展示所有项目、最新运行状态、快速统计卡片 |
| 项目详情 | `/project/{id}` | 趋势图表（DR/CPR/Reward）、运行历史列表、阈值线 |
| 运行详情 | `/run/{id}` | 汇总卡片、维度分解、任务级结果表 |
| 任务详情 | `/run/{id}/task/{task_id}` | 约束逐项结果、LLM Judge 溯源、输出文件预览 |

**启动方式**：

```bash
# 启动 Web Portal
agent-eval serve [--port 3000] [--workspace ./workspace]
```

---

## 九、实施阶段建议

| 阶段 | 周期 | 目标 |
|------|------|------|
| **Phase 1: 基础骨架** | 2 周 | Python 项目初始化；搭建执行引擎与评估引擎基础框架；完成 CLI 入口；定义数据包格式；实现 HTTP SUT 驱动器；完成基础 Rule-based 评估器；**提供任务集构建工具与标注模板，支持从零创建测试数据**。|
| **Phase 2: 指标体系落地** | 3 周 | 实现课件生成场景的格式约束、常识约束、LLM-as-judge 评估器；引入 **LLM Provider 抽象层**（支持 DeepSeek / Anthropic 协议 / OpenAI 协议）；输出 Reward Score、DR、CPR 等核心指标与 Markdown/JSON 报告。 |
| **Phase 3: 规则与扩展** | 2 周 | 完善规则集 YAML 规范与 JSON Schema；建立规则模板库；实现 Agent 自动生成/修改规则的 SDK 接口；实现评估器插件机制、结果缓存、规则版本管理。 |
| **Phase 4: 通用化与接口** | 2 周 | 将课件生成专用逻辑抽象为可扩展维度；补充 REST API；支持多模态视觉评估器（Kimi-2.6 目标接入）；Web UI 作为可选增强。 |

---

## 十、已确认决策记录

以下问题已与用户确认，并据此更新本需求文档：

| 序号 | 问题 | 确认决策 | 对需求的影响 |
|------|------|----------|--------------|
| 1 | 目标 Agent 类型 | **通用 Agent 评估框架**，当前以课件生成 Agent 为切入点 | 系统架构需插件化、可扩展，指标体系需支持后续新增维度 |
| 2 | 技术栈 | **Python** | 执行引擎、评估引擎、SDK、CLI 均基于 Python 构建 |
| 3 | SUT 接入方式 | **以 HTTP 服务为主**（LangGraph 封装服务、Hermes 搭建服务等），保留其他扩展方式 | SUT 驱动器默认实现为 HTTP Client，支持自定义请求模板、鉴权、重试 |
| 4 | 规则编辑者身份 | **主要由 Agent 自动生成，人类专家校对或修改** | 规则集格式必须对 Agent 极其友好（YAML + Schema），需提供 Agent 生成/修改规则的 SDK 接口 |
| 5 | 部署形态 | **CLI + Web Portal + REST API**，优先方便 Claude Code 类 Agent 调用，同时提供 Web 可视化 | CLI 与 Python SDK 为 P0，REST API 与 Web Portal 为 P1 |
| 6 | LLM 评估模型 | **默认 DeepSeek**，可配置其他模型；必须兼容 Anthropic 协议（Kimi / 智谱 / MiniMax coding plan）与 OpenAI 兼容协议 | 引入 LLM Provider 抽象层，统一封装不同协议客户端 |
| 7 | 视觉评估深度 | **使用多模态 LLM（目标 Kimi-2.6）** 进行视觉质量评估 | 视觉评估器基于多模态模型，输入课件截图或页面资源，输出结构化评分 |
| 8 | 测试数据集 | **从零构建**，暂无现有数据集 | 系统需提供任务集构建工具与模板，支持人工标注与半自动化生成 |
| 9 | SaaS 认证 | **本阶段暂不考虑** 用户认证、权限与租户隔离 | 前期聚焦单机/团队 CLI 与 API 使用，认证授权为后续演进项 |
| 10 | 实时评估 | **前期以离线批量评估为主**，未来逐步演化为实时/流式评估 | 执行引擎按批次调度，评估引擎按完整数据包处理；接口设计预留流式扩展空间 |
| 11 | Web 可视化技术选型 | **React + Express**，适配腾讯云函数部署 | 前端 React、后端 Express，提供 REST API 供前端调用；通过 CLI `agent-eval serve` 启动 |
| 12 | 目录结构评估 | **一个目录 = 一个任务**，目录内 HTML 文件逐个评估，通过 manifest 记录层级 | 引入 DirectoryCollector 组件和 output/_manifest.json 规范；支持按模块聚合结果 |

**当前遗留待确认项**：无。

---

## 十一、附录

### 11.1 参考文档

- [01课件生成评估体系规划.md](./01课件生成评估体系规划.md)

### 11.2 版本记录

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v0.1 | 2026-06-08 | 初始草案，基于用户反馈与评估体系规划整理 |
| v0.2 | 2026-06-08 | 根据用户澄清更新：明确通用框架定位、Python 技术栈、HTTP SUT 接入、Agent 生成规则、LLM Provider 抽象层、多模态视觉评估、CLI/SDK 优先策略 |
| v0.3 | 2026-06-08 | 确认测试数据从零构建、本阶段不考虑 SaaS 认证、离线批量评估优先；补充任务集构建工具与标注需求 |
| v0.4 | 2026-06-08 | 新增 Web 可视化与追溯需求（F-W）、目录结构评估需求（F-D）；Web Portal 升级为 P1；新增 VisualizationService；新增项目管理需求 |
