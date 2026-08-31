# Agent Eval 评估器

本目录是评估器自包含、pip-installable 组件（对称于 `web/` 可观测平台）。

## 开发

```bash
cd evaluator
uv sync --extra dev
uv sync --extra vision              # 安装 playwright（vision extra 含 LLM 依赖）
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
