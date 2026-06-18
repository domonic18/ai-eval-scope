# agent-eval

Agent 能力评估系统 — 基于 Agent-Driven 架构的评测框架。

以课件生成为切入点，支持代码生成、RAG、对话等多类 Agent 评估。

## 安装

```bash
git clone <repo-url> && cd agent-eval-system
uv sync                      # 基础安装
uv sync --extra dev          # 开发依赖
uv sync --extra llm          # LLM 依赖（可选）
```

环境要求：Python 3.11+、[uv](https://docs.astral.sh/uv/)

> 评估器代码在 `evaluator/` 子目录（自包含，对称 `web/` 可观测平台）。
> 所有 `uv run` / `agent-eval` 命令需从 `evaluator/` 执行，或用 `make` 目标自动切换。

## 使用

### 示例：评估课件产出物

以项目自带的 `docs/reference/大单元学习总导/`（HTML 课件目录）为例：

```bash
cd evaluator

# ① 打包（自动遍历目录，task-id 取目录名"大单元学习总导"）
uv run agent-eval pack \
  --source-dir ../docs/reference/大单元学习总导/

# ② 评估
uv run agent-eval eval \
  --package-dir ../workspace/packages/大单元学习总导/ \
  --rule-set agent_eval/assets/rules/default_rule_set.yaml

# ③ 查看报告
cat ../workspace/runs/*/reports/summary.md
```

不配置 LLM 时，9 项 Rule-based 评估器正常运行，5 项 LLM 评估器自动降级（score=0.7）。

### pack 命令

```bash
cd evaluator

# 指定目录（task-id 自动取目录名）
uv run agent-eval pack --source-dir /path/to/output/

# 指定文件
uv run agent-eval pack --files doc1.md --files doc2.html

# 自定义任务信息
uv run agent-eval pack --source-dir /path/to/output/ \
  --task-id math_001 --task-title "方程" --task-subject math

# 打包并验证
uv run agent-eval pack --source-dir /path/to/output/ --validate
```

### eval 命令

```bash
cd evaluator

# 最简模式（无 LLM；llm_config 自动从 agent_eval/assets/configs/ 发现）
uv run agent-eval eval \
  --package-dir ../workspace/packages/math_001 \
  --rule-set agent_eval/assets/rules/default_rule_set.yaml

# 含 LLM Judge（--llm-config 省略时自动查找 CWD 或包内配置）
uv run agent-eval eval \
  --package-dir ../workspace/packages/math_001 \
  --rule-set agent_eval/assets/rules/default_rule_set.yaml \
  --llm-provider deepseek_judge
```

### LLM 配置（可选）

```bash
cd evaluator
cp agent_eval/assets/configs/llm_config.example.yaml agent_eval/assets/configs/llm_config.yaml
# 编辑填入 API Key（支持 ${DEEPSEEK_API_KEY} 语法，值从 .env 读取）
# CLI 自动发现此文件，无需 --llm-config
```

### 输出

评估完成后查看 `workspace/` 目录（默认在 `WORKSPACE_DIR`，缺省 `./workspace`）：

- `runs/{id}/results/{task}/report.md` — 任务报告（人类可读）
- `runs/{id}/reports/summary.md` — 聚合报告（DR/CPR/Reward）
- `cache/evaluation_cache.json` — 跨运行缓存

## 开发

```bash
make test        # 运行测试（= cd evaluator && uv run pytest）
make test-cov    # 覆盖率报告
make lint        # 代码检查
make format      # 格式化
```

或直接用 uv（从 evaluator/）：

```bash
uv run pytest tests/ -v
uv run pytest tests/ -v --cov=agent_eval --cov-report=term-missing
uv run ruff format agent_eval/ tests/ && uv run ruff check --fix agent_eval/ tests/
```

## 文档

| 文档 | 说明 |
|------|------|
| [CLAUDE.md](./CLAUDE.md) | 开发指南与编码约定 |
| [docs/arch/](./docs/arch/) | 架构设计文档 |
| [docs/plan/01迭代开发计划.md](./docs/plan/01迭代开发计划.md) | Sprint 迭代计划 |

## License

MIT
