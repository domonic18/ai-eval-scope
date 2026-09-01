# Agent Eval 评估器

[![PyPI](https://img.shields.io/pypi/v/ai-eval-scope.svg)](https://pypi.org/project/ai-eval-scope/)
[![Python](https://img.shields.io/pypi/pyversions/ai-eval-scope.svg)](https://pypi.org/project/ai-eval-scope/)
[![License: MIT](https://img.shields.io/pypi/l/ai-eval-scope.svg)](https://pypi.org/project/ai-eval-scope/)

Agent 能力评估框架（`agent-eval` CLI）——基于 Agent-Driven 架构，支持课件生成、
代码生成、RAG、对话等多类 Agent 评估。

## 安装（发布后）

```bash
pip install ai-eval-scope                 # 基础：规则评估（无 LLM 依赖）
pip install "ai-eval-scope[llm]"          # + LLM Judge（OpenAI/Anthropic 兼容）
pip install "ai-eval-scope[agent]"        # + ExecutionAgent 执行引擎（DeepAgents 底座）
pip install "ai-eval-scope[vision]"       # + 视觉评估（playwright 截图渲染）
pip install "ai-eval-scope[datasets]"     # + 数据集下载（HuggingFace/ModelScope）

uv tool install "ai-eval-scope[agent]"    # uv：全局 CLI 工具安装
uvx --from "ai-eval-scope[agent]" agent-eval --help   # 一次性运行，不落盘
```

> 包名 `ai-eval-scope`，import 名 `agent_eval`，CLI 命令 `agent-eval`（命令名≠包名）。
> Python ≥ 3.11。LLM 与凭证配置见 [CLI 使用教程](../docs/guide/CLI使用教程.md)。

## 开发

```bash
cd evaluator
uv sync --group dev                # 开发依赖组（PEP 735，含 llm/vision 测试依赖）
uv run playwright install chromium  # 下载 Chromium 浏览器二进制（~150MB，装到用户缓存）
uv run agent-eval --help
```

## 配置

### 交互式向导（推荐）

```bash
uv run agent-eval models login
```

向导流程：

1. **选择提供商**：`anthropic` / `openai` / `deepseek` / `custom`（自定义 OpenAI 兼容端点）
2. **API Base URL**：按提供商给默认值（anthropic 缺省 `https://api.moonshot.cn/anthropic`，即 Kimi 的 Anthropic 协议端点；openai 缺省 `https://api.openai.com/v1`；deepseek 缺省 `https://api.deepseek.com/v1`）
3. **API Key**：隐藏输入
4. **逐角色确认模型**：
   - `text` — 文本 LLM Judge（默认必配）
   - `vision` — 视觉评估模型（用视觉规则集时需要）
   - `agent` — 执行侧模型（`run`/`pipeline` 驱动被测 Agent 用；未配置时自动回退 `text`）

### 查看与验证

```bash
uv run agent-eval models list    # 查看（API Key 脱敏显示 前4…后4）
uv run agent-eval models test    # 对每个已配角色真实调用一次，打印时延
uv run agent-eval models logout  # 删除配置（含 key）
```

详见 [CLI 使用教程](../docs/guide/CLI使用教程.md) 与 [CLAUDE.md](./CLAUDE.md)。

## 运行

```bash
uv run agent-eval eval \
  --package-dir workspace/packages/<包目录>/ \
  --package courseware
```

验证是否真正执行：产物中出现 `*.png` 截图、评估耗时显著增加（视觉渲染 + 视觉 LLM 调用），
且日志无「视觉跳过」「Chromium 启动失败」字样。缓存命中时会跳过视觉重算，调试时加
`--no-cache` 强制重评。
