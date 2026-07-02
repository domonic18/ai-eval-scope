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

## 多模态视觉评估

视觉评估（截图渲染 + 视觉 LLM 判断版式/可读性）是 opt-in 能力，依赖 Playwright 的
Chromium 浏览器。**仅装 Python 包不够，还必须下载浏览器二进制**，否则会降级为
「视觉跳过，不计入得分」。

前置两步（每次新环境/新机器各跑一次）：

```bash
cd evaluator
uv sync --extra vision              # 安装 playwright（vision extra 含 LLM 依赖）
uv run playwright install chromium  # 下载 Chromium 浏览器二进制（~150MB，装到用户缓存）
```

启用评估（`--enable-vision`）：

```bash
uv run agent-eval eval \
  --package-dir workspace/packages/<pkg> \
  --rule-set agent_eval/assets/rules/default_rule_set.yaml \
  --enable-vision
```

验证是否真正执行：产物中出现 `*.png` 截图、评估耗时显著增加（视觉渲染 + 视觉 LLM 调用），
且日志无「视觉跳过」「Chromium 启动失败」字样。缓存命中时会跳过视觉重算，调试时加
`--no-cache` 强制重评。
