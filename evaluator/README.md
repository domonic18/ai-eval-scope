# EvalScope Evaluator (`agent-eval`)

[![PyPI](https://img.shields.io/pypi/v/ai-eval-scope.svg)](https://pypi.org/project/ai-eval-scope/)
[![Python](https://img.shields.io/pypi/pyversions/ai-eval-scope.svg)](https://pypi.org/project/ai-eval-scope/)
[![License: MIT](https://img.shields.io/pypi/l/ai-eval-scope.svg)](https://pypi.org/project/ai-eval-scope/)

The evaluator of [EvalScope](https://github.com/domonic18/ai-eval-scope) — an agent-driven evaluation framework. It ships the `agent-eval` CLI: scenario packages as versioned YAML "exam papers", an ExecutionAgent that drives the system under test, and layered scoring (format gate → rule engine → LLM judge → vision).

> Package name `ai-eval-scope`, import name `agent_eval`, CLI command `agent-eval`. Python ≥ 3.11.

## Install

```bash
pip install ai-eval-scope                 # core: rule-based evaluation (no LLM deps)
pip install "ai-eval-scope[llm]"          # + LLM judge (OpenAI / Anthropic compatible)
pip install "ai-eval-scope[agent]"        # + ExecutionAgent runtime (DeepAgents-based)
pip install "ai-eval-scope[vision]"       # + vision evaluation (Playwright screenshots)
pip install "ai-eval-scope[datasets]"     # + dataset download (HuggingFace / ModelScope)
pip install "ai-eval-scope[agent,llm]"    # typical setup: execute + judge

uv tool install "ai-eval-scope[agent,llm]"          # uv: global CLI install
uvx --from "ai-eval-scope[agent,llm]" agent-eval --help   # one-off run, nothing installed
```

## Quickstart

```bash
# ① Configure the judging model (interactive wizard: provider → API key → connectivity test)
agent-eval models set

# ② Open the workbench and describe what you want to evaluate in plain language
agent-eval start

# …or run the whole chain non-interactively (execute → evaluate → report → upload)
agent-eval pipeline --package chat --task "safety_*" --upload
```

### Model configuration

`agent-eval models set` walks you through provider / protocol selection (any OpenAI- or Anthropic-compatible endpoint, including a custom `base_url`), hidden API-key input, and per-role model confirmation:

- `text` — LLM judge (required for AI scoring)
- `vision` — screenshot evaluation (needed by vision rule sets)
- `agent` — execution-side model that drives the system under test (falls back to `text`)

```bash
agent-eval models list    # show config (API keys masked)
agent-eval models test    # one live call per configured role, with latency
agent-eval models clear   # remove stored config (including keys)
```

Keys are stored in `~/.agent_eval/llm.json` with `0600` permissions and are never printed or logged.

## Development

```bash
git clone https://github.com/domonic18/ai-eval-scope.git
cd ai-eval-scope/evaluator
uv sync --group dev                 # dev toolchain (PEP 735 dependency group)
uv run playwright install chromium  # only needed for vision-evaluation tests
uv run agent-eval --help
uv run pytest tests/unit -q         # fast gate; `make test` at the repo root for the full suite
```

## Documentation

Full command handbook, scenario-package layout, and evaluation walkthroughs live in the repo docs:

- [CLI Tutorial](https://github.com/domonic18/ai-eval-scope/blob/main/docs/guide/CLI使用教程.md) (Chinese)
- [Architecture overview](https://github.com/domonic18/ai-eval-scope/blob/main/docs/arch/01整体架构设计.md) (Chinese)
- [Contributing](https://github.com/domonic18/ai-eval-scope/blob/main/CONTRIBUTING.md)

## License

[MIT](https://github.com/domonic18/ai-eval-scope/blob/main/LICENSE)
