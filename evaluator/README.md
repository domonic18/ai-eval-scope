# Agent Eval 评估器

本目录是评估器自包含、pip-installable 组件（对称于 `web/` 可观测平台）。

## 开发

```bash
cd evaluator
uv sync --extra dev
uv run agent-eval --help
uv run pytest tests/unit -v
```

## 配置

环境变量从仓库根 `.env` 读取（`load_dotenv()` 自动向上查找）。
LLM 配置放在 `assets/configs/llm_config.yaml`（从 `.example.yaml` 复制，CLI 自动发现）。

详见仓库根 [README.md](../README.md) 与 [CLAUDE.md](./CLAUDE.md)。
