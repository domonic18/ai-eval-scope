# Langfuse 调用追踪可观测性设计

> 本文档描述 LLM 调用追踪可观测性的实现方案，属于 [05 LLM 模块设计](./05LLM模块设计.md) 的扩展。通过接入 Langfuse SDK，实现 LLM Judge 每次调用的输入/输出/token 用量/耗时的全链路可视化追踪。

---

## 一、设计目标

| 目标 | 说明 |
|------|------|
| **全链路追踪** | 一次 `judge()` 调用生成一条 Trace，内含 N 个 Generation Span，完整记录每次 LLM 调用 |
| **零侵入禁用** | 未配置 Langfuse 环境变量时完全无感，不影响评估流程和性能 |
| **Cloud SaaS** | 优先使用 Langfuse Cloud（零部署），配置 3 个环境变量即可启用 |
| **多模态预留** | 架构支持未来追踪图片/音频等多模态输入输出 |

---

## 二、技术选型

| 方案 | 类型 | 开源 | 自部署 | 选型结论 |
|------|------|------|--------|---------|
| **Langfuse** | LLM 可观测平台 | ✅ MIT | ✅ Docker/K8s | ✅ **首选** — 功能全（Tracing + Eval + Prompt），16k+ Stars |
| Arize Phoenix | AI 可观测工具 | ✅ MIT | ✅ | 备选 — OpenTelemetry 原生 |
| LangSmith | LangChain 官方 | ❌ 闭源 | ❌ 仅 SaaS | ❌ 数据上云 + 不使用 LangChain |
| Helicone | LLM 网关代理 | ✅ Apache | ✅ | ❌ 评估能力弱 |

详细对比参见 `docs/research/01LLM调用追踪与可观测性方案调研.md`。

**依赖声明**：

```toml
# pyproject.toml
[project.optional-dependencies]
llm = [
    "openai>=1.30",
    "anthropic>=0.30",
    "langfuse>=2.0",
]
```

> 当前安装版本为 Langfuse v4.x，其 API 与 v2/v3 有较大差异（详见 §3.3）。

---

## 三、模块设计

### 3.1 文件结构

```
agent_eval/llm/
├── tracing.py                    # Langfuse 核心模块（单例客户端 + Trace 创建 + flush）
├── judge/
│   └── orchestrator.py           # JudgeOrchestrator — 埋点位置
├── client.py                     # LLMClient ABC
├── providers/
│   └── deepseek.py               # DeepSeek 客户端
└── ...
```

### 3.2 核心模块：`agent_eval/llm/tracing.py`

Langfuse 客户端封装，提供懒初始化单例、Trace 创建、数据刷新等功能：

```python
"""Langfuse 追踪模块 — LLM 调用可观测性。"""

from __future__ import annotations

import os
from typing import Any, Optional

import structlog

logger = structlog.get_logger("tracing")

_langfuse_client: Optional[Langfuse] = None


def get_langfuse() -> Optional[Langfuse]:
    """获取 Langfuse 客户端单例。未配置时返回 None。"""
    global _langfuse_client
    if _langfuse_client is not None:
        return _langfuse_client

    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
    secret_key = os.environ.get("LANGFUSE_SECRET_KEY", "")

    if not public_key or not secret_key:
        return None

    try:
        from langfuse import Langfuse
        host = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")
        _langfuse_client = Langfuse(public_key=public_key, secret_key=secret_key, host=host)
        return _langfuse_client
    except Exception as e:
        logger.warning("Langfuse 初始化失败，追踪将不可用", error=str(e))
        return None


def create_trace(name: str, metadata: dict[str, Any] | None = None)
        -> Optional[tuple[Any, dict[str, str]]]:
    """创建 Langfuse Trace（根 Span）。

    Returns:
        (span, trace_context_dict) 元组，或 None（未启用时）。
    """
    langfuse = get_langfuse()
    if langfuse is None:
        return None

    trace_id = langfuse.create_trace_id(seed=name)
    trace_ctx = {"trace_id": trace_id}  # TraceContext 是 TypedDict，等价于 dict

    span = langfuse.start_observation(
        name=name, trace_context=trace_ctx, as_type="span", metadata=metadata or {},
    )
    return span, trace_ctx


def is_tracing_enabled() -> bool:
    """检查 Langfuse 追踪是否已启用。"""
    return get_langfuse() is not None


def flush_traces() -> None:
    """刷新所有待发送的 trace 数据。在评估结束时调用。"""
    if _langfuse_client is not None:
        _langfuse_client.flush()


def reset_langfuse() -> None:
    """重置 Langfuse 客户端（仅用于测试）。"""
    global _langfuse_client
    _langfuse_client = None
```

**设计要点**：

| 设计决策 | 理由 |
|----------|------|
| 懒初始化单例 | 首次调用时才创建客户端，避免未安装 langfuse 时导入报错 |
| 环境变量控制 | 无需修改配置文件，3 个环境变量即可启用/禁用 |
| `create_trace()` 封装 | 屏蔽 v4 API 的 `create_trace_id` + `start_observation` 复杂度 |
| `flush_traces()` | Langfuse SDK 异步发送，需在评估结束时确保数据落盘 |

### 3.3 Langfuse v4 API 说明

Langfuse v4.x 相较于 v2/v3 有重大 API 变更。本项目基于 v4 API 实现：

| 概念 | v2/v3 API | v4 API（本项目使用） |
|------|-----------|---------------------|
| 创建客户端 | `Langfuse()` | `Langfuse(public_key, secret_key, host)` |
| 创建 Trace | `langfuse.trace(name=..., ...)` | `langfuse.create_trace_id(seed=...)` + `langfuse.start_observation(trace_context=..., as_type="span")` |
| 嵌套观察 | `trace.generation(name=..., ...)` | `span.start_observation(name=..., as_type="generation", ...)` |
| 记录输出 | `generation.end(output=..., usage=...)` | `generation.update(output=..., usage_details=...)` + `generation.end()` |
| 刷新 | `langfuse.flush()` | `langfuse.flush()`（不变） |

**v4 API 调用流程**：

```
Langfuse(public_key, secret_key, host)
  │
  ├─ create_trace_id(seed=name)       → trace_id: str
  │
  ├─ start_observation(               → root_span (as_type="span")
  │     name, trace_context={trace_id}, as_type="span",
  │     metadata={sample_id, template_id, ...})
  │
  │   ├─ root_span.start_observation( → generation (as_type="generation")
  │   │     name="sample_0",
  │   │     input={system_prompt, user_prompt},
  │   │     model="deepseek/deepseek-chat",
  │   │     model_parameters={temperature, seed})
  │   │
  │   │   ├─ generation.update(       → 更新输出和 token
  │   │   │     output=response_content,
  │   │   │     usage_details={prompt_tokens, completion_tokens, total_tokens})
  │   │   │
  │   │   └─ generation.end()
  │   │
  │   ├─ (sample_1, sample_2 ... 同上)
  │   │
  │   ├─ root_span.update(output={scores, confidence})
  │   └─ root_span.end()
  │
  └─ flush()                           → 发送到 Langfuse 服务端
```

---

## 四、埋点设计

### 4.1 调用链与埋点位置

```
eval_packages()
  → Orchestrator.eval_only()
    → PipelineEngine.evaluate_sample()
      → PipelineStage.execute()
        → Evaluator.evaluate()
          → JudgeOrchestrator.judge()            ← ① 创建 Trace (root_span)
            → TemplateManager.render()
            → StabilityController.evaluate_stable()
              → single_judge(0)                   ← ② 创建 Generation (sample_0)
                → client.chat()                   ← ③ LLM API 调用
                → generation.update(output, usage)
                → generation.end()
              → single_judge(1)                   ← ② 创建 Generation (sample_1)
              → single_judge(2)                   ← ② 创建 Generation (sample_2)
            → root_span.update(output=scores)
            → root_span.end()
  → flush_traces()                                ← ④ 确保数据落盘
```

### 4.2 JudgeOrchestrator.judge() 埋点

```python
# agent_eval/llm/judge/orchestrator.py

from agent_eval.llm.tracing import create_trace

def judge(self, *, constraint_id, sample_id, template_id, variables, evidence_dir, provider_name=None):
    # ... Provider 获取、模板渲染 ...

    # ① 创建 Langfuse Trace
    trace_info = create_trace(
        name=f"judge:{constraint_id}",
        metadata={"sample_id": sample_id, "template_id": template_id,
                  "provider": provider_info.name, "model": provider_info.model},
    )
    root_span = trace_info[0] if trace_info else None

    def single_judge(sample_index: int):
        # ② 创建 Generation Span
        generation = None
        if root_span:
            generation = root_span.start_observation(
                name=f"sample_{sample_index}",
                as_type="generation",
                input={"system": system_prompt, "user": user_prompt},
                model=f"{provider_info.name}/{provider_info.model}",
                model_parameters={"temperature": template.temperature,
                                  "seed": template.seed + sample_index},
            )

        response = client.chat(...)  # ③ LLM API 调用

        # 更新输出和 token 用量
        if generation:
            generation.update(output=response.content, usage_details={...})
            generation.end()

        return parsed_scores

    # ... 稳定性控制、JudgeRecord 生成 ...

    # ⑦ 结束 Trace
    if root_span:
        root_span.update(output={"scores": stable_result.scores,
                                  "confidence": stable_result.confidence})
        root_span.end()
```

### 4.3 flush 位置

在两个入口处确保 Langfuse SDK 缓冲区数据发送完成：

| 入口 | 文件 | 位置 |
|------|------|------|
| SDK `eval_packages()` | `agent_eval/orchestrator/orchestrator.py` | 函数末尾 |
| CLI `agent-eval eval` | `cli.py` | eval 命令末尾 |

```python
from agent_eval.llm.tracing import flush_traces
flush_traces()
```

---

## 五、配置

### 5.1 环境变量

通过 `.env` 文件或环境变量配置，无需修改 YAML 配置文件：

| 变量 | 必需 | 默认值 | 说明 |
|------|------|--------|------|
| `LANGFUSE_PUBLIC_KEY` | ✅ | — | 公钥，`pk-lf-` 前缀 |
| `LANGFUSE_SECRET_KEY` | ✅ | — | 密钥，`sk-lf-` 前缀 |
| `LANGFUSE_HOST` | ❌ | `https://cloud.langfuse.com` | 服务端地址 |

**启用方式**：在 `.env` 中填入 3 个变量即可。注释或留空则自动禁用。

**Cloud SaaS**（推荐）：

```bash
LANGFUSE_PUBLIC_KEY=pk-lf-xxx
LANGFUSE_SECRET_KEY=sk-lf-xxx
LANGFUSE_HOST=https://us.cloud.langfuse.com
```

**自部署**：

```bash
LANGFUSE_PUBLIC_KEY=your-key
LANGFUSE_SECRET_KEY=your-secret
LANGFUSE_HOST=http://localhost:3000
```

### 5.2 .env.example 模板

```bash
# Langfuse 追踪（可选 — 留空或注释掉则禁用追踪）
# 注册 https://cloud.langfuse.com 获取密钥
# LANGFUSE_PUBLIC_KEY=pk-lf-...
# LANGFUSE_SECRET_KEY=sk-lf-...
# LANGFUSE_HOST=https://us.cloud.langfuse.com
```

---

## 六、Langfuse Dashboard 数据结构

一次 `judge()` 调用在 Langfuse Dashboard 上展示为：

```
Trace: judge:commonsense.logical_consistency
├── metadata: {sample_id: "大单元学习总导", template_id: "logical_consistency",
│              provider: "deepseek_judge", model: "deepseek-chat"}
├── Span: sample_0                          ← Generation
│   ├── input: {system: "你是一位专业的教育...", user: "请评估以下课件..."}
│   ├── output: {"internal_consistency": 8, "causal_logic": 7, ...}
│   ├── model: deepseek_judge/deepseek-chat
│   ├── model_parameters: {temperature: 0.0, seed: 42}
│   └── usage_details: {prompt_tokens: 1234, completion_tokens: 567, total_tokens: 1801}
├── Span: sample_1                          ← Generation
│   └── ... (同上，seed=43)
├── Span: sample_2                          ← Generation
│   └── ... (同上，seed=44)
└── output: {scores: {"internal_consistency": 8.0, ...}, confidence: {...}}
```

**Dashboard 功能**：

| 功能 | 说明 |
|------|------|
| Trace 列表 | 查看所有评估调用的 Trace |
| 搜索/过滤 | 按 name、metadata、时间范围搜索 |
| 输入/输出预览 | 直接查看 Prompt 和 LLM 响应 |
| Token 统计 | 自动统计 prompt_tokens / completion_tokens |
| 耗时分析 | 每个 Generation 的 duration |
| 多模型对比 | 不同 Provider 的 Trace 对比 |

---

## 七、测试策略

### 7.1 Mock 策略

在 `tests/conftest.py` 中全局 mock langfuse 模块：

```python
import sys
from unittest.mock import MagicMock

sys.modules.setdefault("langfuse", MagicMock())
```

**效果**：
- 测试环境无需安装 langfuse 依赖
- `from langfuse import Langfuse` 返回 MagicMock
- 所有 Langfuse 调用静默成功，不影响业务逻辑测试

### 7.2 追踪模块测试

`tests/llm/test_tracing.py` — 14 个测试用例：

| 测试类 | 覆盖场景 |
|--------|---------|
| `TestGetLangfuse` | 无环境变量→None、空 key→None、仅 public key→None、双 key→客户端实例、自定义 host、单例复用、导入失败→None |
| `TestIsTracingEnabled` | 禁用判断、启用判断 |
| `TestFlushTraces` | 禁用时无异常、启用时调用 flush |
| `TestCreateTrace` | 禁用时→None、启用时返回 (span, trace_ctx) |
| `TestResetLangfuse` | 重置后单例清空 |

### 7.3 集成验证

```bash
# 1. 不配置 Langfuse — 评估正常运行
uv run python scripts/eval_sample.py --llm-config assets/configs/llm_config.example.yaml

# 2. 配置 Langfuse — Trace 上传到 Cloud Dashboard
#    在 .env 中填入 LANGFUSE_PUBLIC_KEY / SECRET_KEY / HOST
uv run python scripts/eval_sample.py --llm-config assets/configs/llm_config.example.yaml
#    → 日志显示 "Langfuse 已启用" + "Langfuse trace 数据已刷新"
#    → Dashboard 上可见 Trace 列表
```

---

## 八、未来扩展

### Phase 2：评估结果 Score 关联（1 天）

将评估结果（scores/confidence）写入 Langfuse Score，与 Trace 关联：

```python
langfuse.score(trace_id=trace_id, name="internal_consistency", value=8.0)
```

### Phase 3：Prompt 版本管理（1-2 天）

将 `assets/prompts/*.yaml` 迁移到 Langfuse Prompt 管理，支持版本控制和在线编辑：

```python
prompt = langfuse.get_prompt("logical_consistency")
```

### Phase 4：多模态追踪（按需）

扩展追踪图片/音频输入，支持多模态评估场景：

```python
generation = root_span.start_observation(
    name="multimodal_eval",
    as_type="generation",
    input={"system": "评估课件截图", "user": [
        {"type": "text", "text": "请评估"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}},
    ]},
)
```

Langfuse UI 自动在 Trace 详情页渲染图片预览。

---

## 九、涉及文件

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `agent_eval/llm/tracing.py` | 新增 | Langfuse 核心模块（单例客户端、Trace 创建、flush） |
| `agent_eval/llm/judge/orchestrator.py` | 修改 | `judge()` 方法中创建 Trace + Generation 埋点 |
| `agent_eval/orchestrator/orchestrator.py` | 修改 | `eval_packages()` 末尾 `flush_traces()` |
| `cli.py` | 修改 | eval 命令末尾 `flush_traces()` |
| `pyproject.toml` | 修改 | `[project.optional-dependencies] llm` 新增 `langfuse>=2.0` |
| `.env.example` | 修改 | 新增 LANGFUSE 环境变量模板 |
| `tests/conftest.py` | 修改 | mock langfuse 模块 |
| `tests/llm/test_tracing.py` | 新增 | tracing 模块单元测试（14 个用例） |

---

## 十、版本记录

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v1.0 | 2026-06-10 | 初始版本：Langfuse v4 SDK 集成、Trace + Generation 埋点、Cloud SaaS 支持 |
