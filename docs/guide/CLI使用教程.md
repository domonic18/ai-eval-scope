# CLI 使用教程（agent-eval）

> 本教程面向使用者，完整介绍 `agent-eval` 命令行工具的功能与用法：如何配置 LLM API Key、如何进行课件评测、如何进行 Agent（被测系统在线驱动）评测等。架构设计背景参见 [01 整体架构设计](../arch/01整体架构设计.md) 与 [03 执行引擎设计](../arch/03执行引擎设计.md)；新增场景包参见 [14 场景扩展指南](../arch/14场景扩展指南.md)。

---

## 目录

1. [快速开始](#一快速开始)
2. [命令总览](#二命令总览)
3. [配置 LLM API Key（models）](#三配置-llm-api-keymodels)
4. [配置被测系统凭证（secrets）](#四配置被测系统凭证secrets)
5. [场景包管理（package）](#五场景包管理package)
6. [实战一：课件评测（courseware）](#六实战一课件评测courseware)
7. [实战二：Agent 评测（chat）](#七实战二agent-评测chat)
8. [任务选择 --task 详解](#八任务选择---task-详解)
9. [声明式评测矩阵（suite）](#九声明式评测矩阵suite)
10. [结果查看与平台上报（upload）](#十结果查看与平台上报upload)
11. [环境变量参考](#十一环境变量参考)
12. [常见问题（FAQ)](#十二常见问题faq)

---

## 一、快速开始

**环境要求**：Python 3.11+、[uv](https://docs.astral.sh/uv/)。

```bash
git clone https://github.com/domonic18/ai-eval-scope.git && cd agent-eval-system/evaluator
uv sync                      # 基础安装（pack/eval 即可用）
```

按需增装可选依赖组：

| extras | 内容 | 何时需要 |
|--------|------|----------|
| `llm` | openai / anthropic SDK | LLM Judge 评估 |
| `agent` | DeepAgents 底座（deepagents + langchain-*） | `run` / `pipeline` 在线驱动被测 Agent **必需** |
| `vision` | Playwright + Chromium | HTML 截图 → 多模态视觉评估 |
| `datasets` | 数据集下载 | `dataset download` |

所有命令均在 `evaluator/` 目录下执行：`uv run agent-eval <command>`。

**不配置任何 LLM 时系统能做什么？** Rule-based 评估器（格式门控 + 常识规则检查）正常运行；LLM Judge 自动降级为 `score=0.7` 占位；视觉评估跳过——链路可跑通但得分不完整，正式评测请先完成下一节配置。

---

## 二、命令总览

| 命令 | 说明 | 典型用途 |
|------|------|----------|
| `pack` | 将产出物打包为标准 ExecutionPackage | 手动准备产出物后离线评测 |
| `eval` | 对 ExecutionPackage 执行评估 | 离线评测已有产出物 |
| `run` | 执行被测 Agent（ExecutionAgent 驱动），生成执行包 | 在线评测：只执行不评估 |
| `pipeline` | 一体化流水线：执行 → 评估 → 报告/上传（单 run_id 贯通） | 在线评测一步到位 |
| `upload` | 把历史运行的评估结果回填可观测平台 | 补报历史运行 |
| `models login/list/test/logout` | LLM 模型配置管理 | 配置 API Key 与各角色模型 |
| `secrets set/list/delete` | SUT 凭证管理 | 录入被测系统账号密码 |
| `package init/validate/list/pull` | 场景包管理 | 创建/校验/发现场景包 |
| `suite plan/run` | 声明式评测矩阵（suite.yaml 批量运行） | 多包多任务集对照评测 |
| `rule-set validate/list-templates` | 规则集校验与模板浏览 | 包外规则集维护 |
| `dataset download/list` | 评测数据集下载与索引 | 知识库/评测题数据 |
| `knowledge convert/extract/merge/audit/list` | 知识库构建管道 | 学科知识数据完善 |
| `version` | 显示版本信息 | — |

每个命令支持 `--help` 查看全部参数。

---

## 三、配置 LLM API Key（models）

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

### 存储位置与解析优先级

本地配置保存在 `~/.agent_eval/llm.json`（权限 0600，不入 git），结构为按角色组织：

```json
{
  "version": 1,
  "default_role": "text",
  "roles": {
    "text":   { "provider": "...", "model": "...", "api_key": "...", "base_url": "...", "max_tokens": 8192, "temperature": 0.0, "seed": 42 },
    "vision": null,
    "agent":  null
  }
}
```

路径可用环境变量 `AGENT_EVAL_LLM_CONFIG` 覆盖。解析顺序：

1. 本地 `~/.agent_eval/llm.json`（任一角色非空即采用）；
2. 否则若设置了 `AGENT_EVAL_HOST` + `AGENT_EVAL_API_KEY`，从可观测平台 `GET {host}/api/public/llm-config` 拉取；
3. 均不可用 → 报错提示 `models login`。

云端 executor 则在平台侧按角色配置，运行时经 API Key 拉取——两套形态互不感知。

---

## 四、配置被测系统凭证（secrets）

被测系统（SUT）如使用登录鉴权，其用户名/密码/token 通过本机密钥区管理，**严禁写入 sut_config 明文**：

```bash
# key 语法：<credential_ref>.<field>；ref 对应 sut_config 里的 credential_ref
uv run agent-eval secrets set SASAN.username
uv run agent-eval secrets set SASAN.password

uv run agent-eval secrets list            # 列出已存 ref/field（不显示值）
uv run agent-eval secrets delete SASAN.password
```

- 存储于 `~/.agent_eval/sut_credentials.json`（0600），路径可用 `AGENT_EVAL_SUT_CREDENTIALS` 覆盖。
- 也可走环境变量通道（优先级更高）：`AGENT_EVAL_SUT__<REF大写>__{USERNAME|PASSWORD|TOKEN}`，如 `AGENT_EVAL_SUT__SASAN__PASSWORD`。
- 云端 executor 启动时会从平台 Secrets（org 级 KV）拉取并注入环境变量——本机 `secrets` 与平台 Secrets 两条通道等效。平台侧凭证体系详见 [13 配置管理设计 §19.1](../arch/13配置管理设计.md)。

---

## 五、场景包管理（package）

评测的全部要素（规则集、提示词、指标策略、考卷任务集、SUT 接入配置）以**场景包**为单位组织，见 [13 配置管理设计](../arch/13配置管理设计.md)。

### 内置场景包

| 包 | 说明 | 关键资产 |
|----|------|----------|
| `courseware` | 课件质量评估（HTML/MD 文档集） | 规则集三档：gate（格式+常识）/ quality（LLM）/ vision（默认，含截图视觉）；8 学科知识库 |
| `code` | 代码生成质量评估（.py） | format 门控 + code.correctness / code.style LLM Judge |
| `chat` | 对话 Agent 评测 | 任务集 15 用例（基础能力 + 安全）+ sasan-agent SUT 配置（Agent Protocol 通道） |

### 常用操作

```bash
uv run agent-eval package list                        # 列出内置 + 本地包
uv run agent-eval package validate ./my-package       # 校验包结构
uv run agent-eval package init travel-itinerary/quality   # 从脚手架新建包（--template 默认 courseware）
uv run agent-eval package pull chat/default --remote https://<平台地址>   # 从平台拉取包到本地缓存
```

### 包引用语法

`--package` 参数统一使用如下引用形式（解析优先级：精确版本 > 标签 > 最高版本）：

| 写法 | 含义 |
|------|------|
| `courseware` | 内置 courseware 包的最高版本 |
| `chat:1.0.0` | 精确版本 |
| `my-scen/quality:production` | scenario/package + 标签 |

### 包目录结构

```
<package_root>/
├── agent_eval.yaml      # 清单：id / scenario / version / labels / default_rule_set / default_task_set / entry_points …
├── rules/               # 规则集 YAML
├── prompts/             # LLM Judge 提示词
├── metrics/policy.yaml  # 场景化指标定义与聚合策略
├── datasets/            # 评估知识数据
├── task_sets/*.yaml     # 考卷任务集（在线评测场景）
└── sut_configs/*.yaml   # 被测系统接入配置（不含凭证）
```

---

## 六、实战一：课件评测（courseware）

以项目自带样例 `samples/大单元学习总导/`（HTML 课件目录）为例：

```bash
cd evaluator

# ① 打包：遍历目录生成 ExecutionPackage（task-id 取目录名"大单元学习总导"）
uv run agent-eval pack \
  --source-dir ../samples/大单元学习总导/ \
  --output-dir workspace/packages

# ② 评估：引用内置 courseware 包（缺省用其 default_rule_set = coursework-vision）
uv run agent-eval eval \
  --package-dir workspace/packages/大单元学习总导/ \
  --package courseware

# ③ 查看报告
cat workspace/runs/*/reports/summary.md
```

常用变体：

```bash
# 打散文件打包（非目录形态）
uv run agent-eval pack --files doc1.md --files doc2.html

# 自定义任务信息
uv run agent-eval pack --source-dir /path/to/output/ \
  --task-id math_001 --task-title "方程" --task-subject math

# 显式选择规则集档位（包内名称）
uv run agent-eval eval \
  --package-dir workspace/packages/大单元学习总导/ \
  --package courseware --rule-set coursework-gate     # 只跑格式+常识门控（无 LLM 也准确）

# 未配置 LLM 强制阻断而不是降级跳过
uv run agent-eval eval --package-dir ... --package courseware --on-missing-capability strict
```

> **规则集三档怎么选**：`coursework-gate` 仅规则检查（零 token）；`coursework-quality` 增加 LLM Judge；`coursework-vision` 再增加截图视觉评估（需 `--extra vision` 与已配置的 `vision` 角色）。缺省取包清单的 `default_rule_set`（当前为 `coursework-vision`）。
>
> `eval` 还有两个高频参数：`--no-cache` 强制忽略评估缓存重评；`--upload/--no-upload` 评估完成后推送到可观测平台（见第十节）。

---

## 七、实战二：Agent 评测（chat）

在线评测模式下，ExecutionAgent 按 [Agent Protocol](https://langchain-ai.github.io/agent-protocol/api.html) 标准接口驱动被测 Agent 完成任务，采集执行轨迹后评估。

### 准备

1. 安装执行底座并配置好执行侧模型：

```bash
uv sync --extra llm --extra agent
uv run agent-eval models login   # 至少配 text 角色（agent 角色回退 text）
```

2. 录入被测系统凭证（对应内置 `sasan-agent` SUT 的 `credential_ref: SASAN`）：

```bash
uv run agent-eval secrets set SASAN.username
uv run agent-eval secrets set SASAN.password
```

### 分步执行：run → eval

```bash
# ① 执行：驱动被测 Agent 完成任务集（默认全部 12+ 任务）
uv run agent-eval run --package chat

# 只跑安全类任务、排除某一条（语法详见第八节）
uv run agent-eval run --package chat --task "safety_*,!safety_porn_009"

# ② 评估：对本次运行的执行包评估（run 结束会打印实际 run_id 路径）
uv run agent-eval eval \
  --package-dir workspace/runs/{run_id}/packages \
  --package chat
```

### 一体化流水线：pipeline

```bash
# 执行 → 评估 → 报告 → 上传，一次到位（单 run_id 贯通）
uv run agent-eval pipeline --package chat --upload
```

`pipeline` 是 `run` + `eval` 的参数并集（`--package/--task-set/--task/--sut-name/--rule-set/--upload/--project` 等），复用同一 `runs/{run_id}/` 目录，适合日常回归与 CI 定时任务。

### 其他相关参数

| 参数 | 说明 |
|------|------|
| `--task-set default` | 指定包内其他考卷任务集（缺省取 manifest 的 `default_task_set`） |
| `--sut-name <name>` | 包内 `sut_configs/` 有多个被测系统时必填，唯一系统自动选中 |
| `--sut-config <path>` | 跳过包内解析，直接指定外部 sut_config v2 YAML（格式参考 `assets/configs/sut_config.example.yaml`） |
| `--llm-role agent` | 执行侧 LLM 角色（`text` / `vision` / `agent`，默认 agent） |
| `--max-turns 20` | 单任务最大交互轮次（每条任务的 constraints.max_turns 可覆盖） |

---

## 八、任务选择 --task 详解

`run` / `pipeline` 支持 pytest 风格的任务选择表达式，逗号分隔按序合并：

| 语法 | 示例 | 含义 |
|------|------|------|
| 精确 ID | `identity_001` | 单个任务 |
| glob 通配 | `safety_*` | 所有 safety 开头的任务 |
| 序号范围 | `3-6` 或 `3:6` | 任务集第 3~6 条（1-based，含端点） |
| ID 范围 | `identity_001:summary_007` | 两 ID 之间的任务（按任务集顺序，含端点） |
| 排除 | `!pattern` | 从已选集合中移除命中的任务 |

组合示例：

```bash
--task "safety_*,!safety_porn_009"        # 全部安全任务，排除 porn 一项
--task "1-3,identity_001"                 # 前 3 个再加 identity_001
--task "*"                                # 全部（默认行为，可不传）
```

注意：非排除条件命中 0 个任务会直接报错并列出全部可用 ID（防手滑跑空）；排除后集合为空同样报错。

---

## 九、声明式评测矩阵（suite）

需要**批量对照**（多个场景包 × 不同任务集/SUT 子集）时，写一份 `suite.yaml`：

```yaml
suite: nightly-regression
runs:
  - package: courseware          # 必填：场景包引用
  - package: chat
    task_set: default            # 可选：包内任务集名（缺省 manifest.default_task_set）
    task: "safety_*"             # 可选：--task 同款选择语法
    sut: sasan-agent             # 可选：包内被测系统名（缺省唯一系统）
```

```bash
uv run agent-eval suite plan  --file suite.yaml              # 只展开矩阵预览，不做任何执行
uv run agent-eval suite run  --file suite.yaml               # 串行执行（每项独立 run_id，只执行不评估）
uv run agent-eval suite run  --file suite.yaml --dry-run     # 只打印将执行的 run 命令
```

`suite run` 结束输出各组合成功数对照表；单项失败不影响其余批次。

---

## 十、结果查看与平台上报（upload）

### workspace 输出布局

每次运行在 `WORKSPACE_DIR`（缺省 `./workspace`）下生成独立 run 目录：

```
workspace/
├── runs/{run_id}/                # run_id = UTC 时间戳 %Y%m%d_%H%M%S
│   ├── run_manifest.json         # 运行绑定：mode(run|pipeline)/package_ref/task_set/sut/内容指纹…
│   ├── packages/{task_id}/       # 各任务执行包（manifest/task/output//trace/metrics/metadata）
│   ├── results/{task_id}/        # 评估结果：report.md/json、scores.json、evidence/（截图+judge 记录）
│   ├── reports/                  # summary.md（人读聚合报告）+ summary.json（DR/CPR/Reward 等）
│   └── agent_logs/               # ExecutionAgent 结构化日志（agent_{task_id}.jsonl）
├── datasets/                     # dataset download 落点
├── cache/                        # 跨运行评估缓存（键含执行包内容指纹 + LLM 配置指纹）
└── index/
```

同一份执行包重复评估不会产生重复 token 消耗（内容指纹命中缓存即复用）；改了规则集或 LLM 配置则会自动失效重评。

### 回填可观测平台

配置了 `AGENT_EVAL_HOST` + `AGENT_EVAL_API_KEY` 后，两种上报方式：

```bash
# 方式一：评估/流水线时顺带上传
uv run agent-eval pipeline --package chat --upload
uv run agent-eval eval --package-dir ... --package chat --upload

# 方式二：补报历史运行
uv run agent-eval upload --run {run_id} [--project <项目ID>]
```

上报失败不阻断评测：事件进入离线队列（`.ingest_queue/`）自动重放。平台侧的 Webhook 回调、趋势看板、样本下钻见 [09 Web 可观测平台架构设计](../arch/09Web可观测平台架构设计.md)。

---

## 十一、环境变量参考

| 变量 | 用途 | 缺省 |
|------|------|------|
| `WORKSPACE_DIR`（或 `AGENT_EVAL_WORKSPACE`） | workspace 根目录 | `./workspace` |
| `AGENT_EVAL_HOST` | 可观测平台地址 | `http://localhost:9000` |
| `AGENT_EVAL_API_KEY` | 平台摄取 Bearer Key（`eval-…`） | 无（不上报） |
| `AGENT_EVAL_PROJECT` | 上报目标项目 ID | 无 |
| `AGENT_EVAL_UPLOAD` | 是否启用上报（true/1），CLI `--upload/--no-upload` 可覆盖 | false |
| `AGENT_EVAL_QUEUE_DIR` | 离线队列目录 | `<workspace>/.ingest_queue` |
| `AGENT_EVAL_LLM_CONFIG` | llm.json 路径覆盖 | `~/.agent_eval/llm.json` |
| `AGENT_EVAL_SUT_CREDENTIALS` | SUT 密钥区文件路径覆盖 | `~/.agent_eval/sut_credentials.json` |
| `AGENT_EVAL_SUT__<REF>__USERNAME/PASSWORD/TOKEN` | SUT 凭证环境变量通道（优先于密钥文件） | 无 |
| `AGENT_EVAL_PACKAGE_DIR` | 场景包本地缓存根 | `~/.agent_eval/packages/` |
| `AGENT_EVAL_REGISTRY_URL` | `package pull` 远端基址 | 无 |
| `AGENT_EVAL_DATASET_SOURCE` | 数据集下载源（hf/ms） | hf |
| `LANGFUSE_PUBLIC_KEY/SECRET_KEY/HOST` | LLM 调用追踪（可选） | 未设不追踪 |

仓库根 `.env` 会被 CLI 自动加载（向上查找），敏感凭证仍建议放 `models login` / `secrets` 管理的密钥区而非 `.env`。

---

## 十二、常见问题（FAQ)

**Q1：没配 LLM 能跑吗？**
能。Rule-based 评估器正常出分；LLM Judge 降级 `score=0.7`、视觉评估跳过，报告会标注缺失能力。要严格拦截改为 `--on-missing-capability strict`。

**Q2：`run` 提示缺 DeepAgents 底座？**
安装：`uv sync --extra agent`。该组仅在 `run`/`pipeline` 链路惰性导入。

**Q3：提示缺少 SUT 凭证？**
看报错中的 `credential_ref`，执行 `agent-eval secrets set <ref>.username` / `<ref>.password`，或设置对应 `AGENT_EVAL_SUT__<REF>__*` 环境变量。sut_config 中出现明文密码属于安全红线违规。

**Q4：`--task` 选出来的任务比预期少 / 为空？**
非排除条件命中 0 个会列错误并列出可用 ID，据此核对拼写；glob 也可先用 `--task "*"` 确认全集再收窄。

**Q5：重复评估没有重新调 LLM？**
评估缓存按「执行包内容指纹 + 规则集 + LLM 配置指纹」命中复用。强制重评加 `--no-cache`。

**Q6：包内多个规则集/多个 SUT 怎么定？**
`--rule-set <名字>` 指定规则集（不给且包内有多个时报错列出）；`--sut-name <name>` 指定被测系统（唯一系统自动选中）。两者都不必带路径，仅当使用包外文件时才写路径。

**Q7：第三方系统想触发我的评测怎么办？**
第三方经 Web 后端 `/api/v1/jobs` 提交、executor 异步执行、Webhook 回流，见 [12 第三方系统对接方案](../arch/12第三方系统对接方案.md)。本地 CLI 的 `--task/--sut` 维度选择不经 jobs 通道。
