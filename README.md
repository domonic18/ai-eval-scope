# EvalScope (ai-eval-scope)

[English](README.md) | [简体中文](README.zh-CN.md)

[![CI](https://github.com/domonic18/ai-eval-scope/actions/workflows/ci.yml/badge.svg)](https://github.com/domonic18/ai-eval-scope/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/ai-eval-scope.svg)](https://pypi.org/project/ai-eval-scope/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![Code Style: ruff](https://img.shields.io/badge/code%20style-ruff-261230.svg)](https://docs.astral.sh/ruff/)

A new-generation, **agent-driven** evaluation system that turns Agent evaluation into a repeatable, quantifiable pipeline:

```
describe what to test → generate an "exam paper" (scenario package) → the Agent under test takes it for real
→ rule engine + LLM judge scoring → report → platform trends
```

**👇 Watch a 60-second intro — conversational scenario-package creation in the CLI:**

![Conversational scenario package creation in the CLI](./docs/assets/demo.gif)

## Why

LLM Agents (support assistants, slide generators, coding helpers, ...) are **non-deterministic**: the same prompt yields a different answer every time, so classic "replay script + `expected == actual`" testing breaks down. EvalScope's answer: **intelligent execution, deterministic evaluation**.

| | Traditional test automation | EvalScope |
|------|------------------|------------------------|
| Execution | Scripted replay; breaks on any environment drift | ExecutionAgent understands the task, decides autonomously, recovers from blockers |
| Scoring | Hard-coded assertions | Rule engine (hard checks) + LLM Judge (semantic quality) |
| Case maintenance | Hand-maintained scripts | Scenario packages (YAML) — generated conversationally, version-controlled |
| Target | Deterministic UI / API systems | Non-deterministic LLM / Agent systems |

## Use cases

- **Conversational Agent QA** — safety (correctly refusing risky prompts), task completion quality, multi-turn coherence
- **RAG retrieval QA** — right and complete results, no hallucination (trap questions), traceable delivery
- **Generation quality** — slide decks, code generation, and other multi-dimension quality combos
- **Version regression** — one consistent yardstick over time: "did this version actually get better?"

Courseware / code / chat scenario packages ship built-in; a new scenario (RAG, custom) is just a YAML package — no code changes.

## Features

- **If you can chat, you can use it** — describe what you want to test in plain language; the Workbench Agent drafts the full asset set (exam paper, scoring rules, judge prompts, SUT config), and every file lands on disk only after you review its diff
- **Automatic SUT onboarding** — give it an entry URL (even just a login page); it analyzes the login API, performs a real login, and probes the conversation API; credentials are hidden-input and never written to any config file
- **Layered scoring** — format gate → rule engine → LLM judge → vision screenshot evaluation (Playwright); every score comes with its reasons
- **Online execution** — ExecutionAgent (DeepAgents-based) drives the Agent under test: multi-turn dialogue, blocker recovery, budget guardrails
- **Observability platform** — a Langfuse-style multi-tenant platform: runs, trends, metrics, per-sample conversation traces

## Quickstart: your first evaluation in 3 steps

Requires Python 3.11+.

```bash
# ① Install ([agent] execution engine and [llm] AI judging recommended; uv or pip)
uv tool install "ai-eval-scope[agent,llm]"
agent-eval --version

# ② Configure the judging model (pick a provider → paste API key → auto connectivity test)
agent-eval models set

# ③ Open the CLI workbench and just describe the task: create package → probe SUT → run evaluation → read report
agent-eval start
```

In the workbench choose "Workbench Agent", describe the requirement in one sentence (e.g. "run a safety evaluation on this online Agent") plus the SUT entry URL, and the rest is automated. Or run the whole chain from the command line (execute → evaluate → report → upload):

```bash
agent-eval pipeline --package chat --task "safety_*" --upload
```

![CLI pipeline run and result summary](./docs/assets/cli-pipeline-result.png)

> Full command reference (run / pipeline / suite / models / secrets / package / dataset …), `--task` selection syntax, scenario-package layout and its five asset kinds, FAQ — see the **[CLI Tutorial](./docs/guide/CLI使用教程.md)** (Chinese).

## Observability platform

A Langfuse-style multi-tenant platform ships in `web/`: projects and API keys, scenario-aware metric rendering, per-sample conversation traces with scoring details, cross-run trends, and webhooks. Once the CLI is connected (`agent-eval auth login`), every evaluation is reported automatically.

```bash
cp .env.example .env     # fill in DB / object storage / secrets
make docker-up           # starts postgres + minio + web (http://localhost:9000)
```

![Platform run detail: scenario metrics + summary report + per-sample scores](./docs/assets/platform-run-detail.png)

## Documentation

| Document | Contents |
|------|------|
| [CLI Tutorial](./docs/guide/CLI使用教程.md) (Chinese) | Full command handbook, package layout & five asset kinds, courseware/Agent evaluation walkthroughs, CI integration |
| [Architecture Overview](./docs/arch/01整体架构设计.md) (Chinese) | evaluator / web / executor domains and data flow |
| [Evaluation Engine](./docs/arch/04评估引擎设计.md) (Chinese) | Gates, rules, LLM judge, vision evaluation, metric aggregation |
| [Data & Configuration](./docs/arch/06数据管理与配置规范.md) (Chinese) | Package composition, dataset abstraction, workspace layout |
| [Third-party Integration](./docs/arch/12第三方系统对接方案.md) (Chinese) | HTTP API / Webhook / MCP integration guide |
| [Contributing](./CONTRIBUTING.md) | Commit / branch / PR conventions, dev environment |

## Contributing

Issues and pull requests are welcome! See [CONTRIBUTING.md](./CONTRIBUTING.md) for the development workflow, commit conventions, and PR process.

## Acknowledgements

Dataset download and dataset-index design reference [OpenCompass](https://github.com/open-compass/opencompass); HuggingFace / ModelScope source metadata for some datasets (`evaluator/agent_eval/assets/datasets/dataset_index.yaml`) is ported from OpenCompass. Thanks to the OpenCompass team for their excellent open-source work.

## License

[MIT](./LICENSE)
