# 第三方接入 EvalScope 评估器

通过 EvalScope，第三方系统（课件平台、Agent 编排、智能体客户端等）可一行请求把待评估内容提交给平台；平台异步运行评估器，并回传**可量化的指标**与**可追溯的证据**。所有结果回流到同一可观测平台，支持多项目趋势与详情查看。

EvalScope 提供**三种接入方式**，均使用同一把 API Key、同一套评测引擎与租户隔离，可按场景混合使用。

---

## 接入方式总览

| 方式 | 调用形态 | 适用场景 | 适合谁 |
|------|----------|----------|--------|
| **[HTTP API](#方式一-http-协议接入)** | REST（`POST/GET`） | 服务端系统对接、服务端编排、CI/CD | 课件平台后端、第三方服务、自动化脚本 |
| **[MCP](#方式二-mcp-接入-智能体)** | MCP 工具调用 | 让 AI 智能体直接提交/查询评测 | 使用workbuddy，claudecode等智能体进行评测 |
| **[CLI](#方式三-cli-接入-评估器直跑)** | 命令行 + `.env` | 本地开发联调、离线批跑 | 开发者本地、定时任务、不方便走 HTTP 的场景 |

**选型建议**：

- 服务端系统对接 → **HTTP API**（最通用，REST 调用）
- 让 AI 智能体在对话中评测课件 → **MCP**（客户端即插即用，无需手写 HTTP）
- 本地手跑或脚本化批跑 → **CLI**（评估器直跑，结果自动回传）

> 三种方式提交的任务都进入同一个 `eval_jobs` 队列，由 executor 异步执行，结果与制品落同一可观测平台。

---

## 准备工作

三种接入方式共用以下准备步骤：

1. **创建项目** — 登录[控制台](/dashboard) → 左侧「项目看板」→ 新建项目。
2. **签发 API Key** — 进入项目 →「设置 & API Key」→ 新建 → 复制 **API Key**（`eval-…`）。**仅创建时明文展示一次，请妥善保存。**
3. **Base URL（线上）** — `https://eval.bj33smarter.com`
4. **在线调试** — 登录后打开[调试台](/debug)，填 API Key + 上传文件即可在线提交、实时查看 request / response / 评估结果。

> **统一鉴权**：所有方式均使用 `Authorization: Bearer <api_key>`（一把 Key 走天下：提交 / 查状态 / 取速览）。**项目归属完全由 Key 决定**，提交时无需也不接受 `project_id`。

---

## 方式一：HTTP 协议接入

服务端系统通过 REST API 提交评测、轮询结果、取速览。第三方对接的**主力方式**。

### 接入流程

```text
┌──────────┐   POST /api/v1/jobs     ┌──────────────────────┐    SCF Invoke / worker   ┌──────────┐
│ 第三方系统 │  ───────────────────▶   │   EvalScope Web 后端  │ ───────────────────────▶ │ executor │
│          │  Authorization: Bearer  │  Bearer Key · 物化输入 │                         │          │
└──────────┘                         │  写 eval_jobs → 触发   │                         └──────────┘
       ▲                              └──────────────────────┘                                │
       │                                                          per-job ResultSink.flush    │
       │ GET /api/v1/jobs/{id}                                           │                    │
       └─────────────────────────────────────────────────────────────────┘                    │
                                                                                               ▼
                                                                          ┌────────────────────────────┐
                                                                          │ Web 可观测平台（PG + 对象存储）│
                                                                          └────────────────────────────┘
```

- **Base URL**：`https://eval.bj33smarter.com`
- **鉴权**：`Authorization: Bearer <api_key>`（无需计算签名，生产强制 HTTPS）
- **交互**：提交后拿 `job_id` → 轮询 `GET /api/v1/jobs/{job_id}` → 读结果

### 提交评测任务

```bash
POST https://eval.bj33smarter.com/api/v1/jobs
Authorization: Bearer <api_key>
```

按 `Content-Type` 分两种提交方式，覆盖课件的两类形态（**HTML 课件网页** 与 **Markdown 文档**，两种格式 / 两种粒度均完整支持）：

#### 上传原始字节（application/octet-stream）

适合提交已有文件。请求体为文件原始字节，元数据通过查询串传递。单文件为「单页」评估；`.zip` 解析为「单元」评估（保留目录树）。

| 查询串字段      | 必需  | 类型     | 说明                               |
| --------------- | --- | ------ | -------------------------------- |
| `filename`      | 是   | string | 文件名，如 `lesson.html`、`unit.zip`  |
| `rule_set_id`   | 否   | string | 规则集，默认 `coursework-quality`      |
| `task_id`       | 否   | string | 自定义任务标识，如 `math-2024-q1`         |
| `task_title`    | 否   | string | 任务标题，如《分数入门》                     |
| `task_subject`  | 否   | string | 任务学科                               |

> 声明为 `.zip` 但内容不是合法 zip 包会被拒绝，避免 executor 解压失败。

#### 内联内容（application/json）

适合直接传文本，无需落盘。

| 字段                                       | 必需  | 类型     | 说明                                                                                   |
| ---------------------------------------- | --- | ------ | ------------------------------------------------------------------------------------ |
| `content`                                | 是   | object | `{ filename: string, text: string }`，如 `{"filename":"lesson.html","text":"<html>…"}` |
| `rule_set_id` / `task_id` / `task_title` | 否   | string | 同上                                                                                   |

#### 大文件直传（presigned PUT，>50MB）

直接 `POST /api/v1/jobs` 的请求体上限为 50MB（超出返回 `413 PAYLOAD_TOO_LARGE`）。文件更大时——或希望客户端**直传对象存储**、不经 Web 后端中转——走**两段式上传**：先换取一个预签名 URL，客户端直传到对象存储，再用返回的 `object_key` 提交评测。

**Step 1 · 换取上传地址**

```bash
curl -X POST https://eval.bj33smarter.com/api/v1/jobs/request-upload \
  -H "Authorization: Bearer <api_key>" \
  -H "Content-Type: application/json" \
  -d '{"filename":"courseware.zip","content_type":"application/zip"}'
```

| 字段 | 必需 | 说明 |
| ---- | ---- | ---- |
| `filename` | 是 | 文件名；后缀决定存储对象扩展名（如 `.zip` / `.html`），评估粒度随之确定 |
| `content_type` | 否 | MIME 类型，默认 `application/octet-stream`；**Step 2 上传时须用同一值** |

响应（`200`）：

```json
{
  "upload_url": "https://cos.example.com/agent-eval/projects/.../input.zip?X-Amz-Algorithm=...&X-Amz-Signature=...",
  "object_key": "projects/9b30ef3c-.../eval/jobs/uploads/8a3f.../input.zip",
  "expires_at": 1722678520
}
```

- `upload_url` 有效期 **≤ 15 分钟**（默认 900 秒）；过期重新换取即可。
- `object_key` 是 Step 3 提交评测的凭证，需**原样回填**，不要自行拼接。

**Step 2 · 客户端直传到对象存储**

```bash
curl -X PUT "<upload_url>" \
  -H "Content-Type: application/zip" \
  --data-binary @courseware.zip
```

- `Content-Type` 必须与 Step 1 声明一致，否则签名校验失败。
- 预签名 URL 由 S3 兼容 SDK 签发，可能签入内容校验头。**推荐用 S3 兼容客户端上传**（AWS SDK / `aws s3 cp` / MinIO `mc`），由其自动补齐签名所涉 header 与校验值；若用 `curl` 等裸 HTTP，须保证请求 header 与 URL 中 `X-Amz-SignedHeaders` 列出的**完全一致**。

**Step 3 · 提交评测（引用已上传对象）**

```bash
curl -X POST https://eval.bj33smarter.com/api/v1/jobs \
  -H "Authorization: Bearer <api_key>" \
  -H "Content-Type: application/json" \
  -d '{"input_object_key":"<object_key>","rule_set_id":"coursework-quality"}'
```

| 字段 | 必需 | 说明 |
| ---- | ---- | ---- |
| `input_object_key` | 是 | Step 1 返回的 `object_key`，平台据此从对象存储拉取输入 |
| `rule_set_id` / `task_id` / `task_title` | 否 | 同「上传原始字节」 |

提交后的响应见下方「响应」。

#### 响应（202 Accepted）

```json
{
  "job_id": "d3f1...e8a2",
  "status": "queued",
  "project_id": "9b30ef3c-867b-4110-8799-b49c1d4db32b",
  "poll_url": "/api/v1/jobs/d3f1...e8a2",
  "scf_request_id": "6a2b..."
}
```

> `project_id` 由 API Key 验签解析后回传，提交时无需传入。`scf_request_id` 仅在生产 SCF 触发时返回；本地开发为 `null`。

### 查询结果

提交后拿 `job_id` 轮询结果；不想轮询可配置 [Webhook 回调](#webhook-结果回调)，评估完成后平台主动 POST 你的服务。

```bash
GET https://eval.bj33smarter.com/api/v1/jobs/{job_id}
Authorization: Bearer <api_key>
```

**状态机**：

```
┌─────────┐     ┌─────────┐     ┌───────────┐
│ queued  │────▶│ running │────▶│ completed │
└─────────┘     └─────────┘     └───────────┘
                    │
                    ▼
               ┌─────────┐
               │ failed  │
               └─────────┘
```

**响应字段**（`completed` 后 `metrics` 有值；`failed` 后 `error` 有值）：

| 字段                                          | 说明                                            |
| ------------------------------------------- | --------------------------------------------- |
| `job_id` / `status`                         | 任务 id 与当前状态                                   |
| `project_id` / `org_id`                     | 归属（来自 API Key）                                |
| `input_kind` / `scope`                      | `upload` / `inline`、`unit` / `single`         |
| `rule_set_id` / `task_id` / `task_title`    | 提交时传入                                         |
| `run_id`                                    | 评估运行 id（进入 running 后填充）                       |
| `web_run_url`                               | Web 平台运行详情页（完成后可访问）                           |
| `metrics`                                   | 指标 `DR` / `CPR` / `Reward` / `CondR` 等（完成后）；含 `_executor` 透明度字段 |
| `metrics.metrics`                           | 旧格式指标数值（DR/CPR/avg_reward/condR/avg_soft/avg_pref/avg_time_ms）；**含 `summary_report` 时应使用 overview 速览端点获取人话摘要** |
| `error`                                     | 失败原因（失败时）                                     |
| `created_at` / `started_at` / `finished_at` | 各阶段时间戳                                        |

> 越权访问（`job_id` 不属于当前 Key 的项目）一律返回 `404`，不泄露存在性。

以 `completed` 为例：

```json
{
  "job_id": "0bc0b717-ada1-4783-8718-7889b5982060",
  "status": "completed",
  "project_id": "d288698e-ee7c-4d4e-b1fc-a2d050ce4a9b",
  "org_id": "1968916c-9aed-4df5-b5ae-6b5c9f757a06",
  "input_kind": "inline",
  "scope": "single",
  "rule_set_id": "coursework-quality",
  "task_id": null,
  "task_title": null,
  "run_id": "2f8a1c...",
  "web_run_url": "https://eval.bj33smarter.com/run/2f8a1c...",
  "metrics": {
    "DR": 0.962,
    "CPR": 0.914,
    "avg_reward": 0.781,
    "condR": 0.842,
    "avg_time_ms": 12340
  },
  "error": null,
  "created_at": "2026-07-01T08:00:00.000Z",
  "started_at": "2026-07-01T08:00:05.000Z",
  "finished_at": "2026-07-01T08:02:30.000Z"
}
```

### 评测速览（overview）

`GET /api/v1/jobs/{job_id}` 只回顶层指标，看不到"各项为什么没过"。速览端点一次拿到**过没过 / 多少分 + 各评测项的失败原因**：

```bash
GET https://eval.bj33smarter.com/api/v1/jobs/{job_id}/overview
Authorization: Bearer <api_key>
```

响应（`completed` 后）：

```json
{
  "job_id": "ed4c0834-9120-42c1-8349-7d6a8ad1a522",
  "run_id": "20260706_083721",
  "status": "completed",
  "web_run_url": "https://eval.bj33smarter.com/run/20260706_083721",
  "verdict": "fail",
  "score": 0.669,
  "metrics": { "DR": 1.0, "CPR": 0.0, "condR": 0.0, "avg_time_ms": 125005 },
  "metrics_raw": {
    "courseware:document_rate": 1.0,
    "courseware:constraint_pass_rate": 0.0,
    "courseware:reward": 0.669,
    "courseware:soft": 0.795,
    "courseware:pref": 0.797,
    "courseware:conditional_reward": 0.0,
    "avg_time_ms": 125005
  },
  "summary": { "total": 1, "passed": 0, "failed": 1, "skipped": 0 },
  "summary_report": {
    "headline": "综合评分 0.67，内容存在明显问题需改进",
    "highlights": ["所有样本格式合规", "内容质量评分较高（0.80）"],
    "issues": [
      {
        "title": "知识准确性未达标",
        "detail": "发现算术错误：12×2+7+3+5+18=100 应为 57（经 LLM 二次确认）",
        "severity": "high",
        "files": ["解析性案例.html"]
      }
    ],
    "suggestion": "建议检查所有算术公式的计算结果，确保数据准确。"
  },
  "dimension_pass": { "format": 1, "commonsense": 0, "soft": 1, "preference": 1 },
  "items": [
    {
      "external_sample_id": "contents",
      "score": 0.669,
      "passed": false,
      "failures": [
        {
          "name": "知识准确性检查",
          "reason": "原文提到 12×2 + 7 + 3 + 5 + 18 = 100，实际应为 57，等式错误（经 LLM 二次确认）",
          "top_issues": ["算式结果错误：12×2+7+3+5+18=57 而非 100"],
          "files": ["解析性案例.html"]
        }
      ]
    }
  ]
}
```

| 字段 | 说明 |
| ---- | ---- |
| `verdict` | `pass` / `fail`：DR / CPR / Reward 达标且无 `hard_gate` 失败 = `pass` |
| `score` | 综合分 = `avg_reward` |
| `metrics` | DR / CPR / condR / 平均耗时（兼容旧格式） |
| `metrics_raw` | 完整场景化指标 JSONB（`courseware:*` 键，动态适配不同场景包） |
| `summary` | 样本通过 / 失败 / 跳过计数 |
| `summary_report` | LLM 生成的人话版摘要报告（headline / highlights / issues / suggestion）；LLM 不可用时为 `null` |
| `dimension_pass` | 各阶段（format / commonsense / soft / preference）达标样本数 |
| `items[]` | 各评测项（样本）：`score` + `passed` + `failures`（未通过约束的 `name` + `reason` + `top_issues` + `files`） |

> - 任务未完成（`queued` / `running` / `failed`）时，只回 `status` + 任务级 `error`，`items` 为空。
> - `summary_report` 由评估器在评估完成后自动调用 LLM 生成（prompt 配置在 `summary_prompt.yaml`），不是手动创建。
> - 速览**只给摘要**：逐条约束的 `details` / 制品预览等深度详情不开放 API，由 iframe 嵌入公开页查看。

### 公开访问与 iframe 嵌入

把项目设为公开后，运行 / 样本详情页可被第三方**免登录** iframe 嵌入：

1. 项目 owner 在 Web 控制台「项目设置 → 公开访问」开启**公开**。
2. 直接把运行详情页地址放进 iframe：

```html
<iframe src="https://eval.bj33smarter.com/run/{run_id}" style="width:100%;height:800px;border:0"></iframe>
```

公开 = 任何人持链接可**只读**查看该项目运行 / 样本（不含 Key / 写操作）；不公开的项目仍需登录。`run_id` 取自 `GET /jobs/{id}` 或 `/overview` 的 `run_id` / `web_run_url`。

### 代码示例

#### Python（httpx）

```python
import time
import httpx

API_KEY = "eval-..."
BASE = "https://eval.bj33smarter.com"
HEADERS = {"Authorization": f"Bearer {API_KEY}"}

# 1) 提交（JSON 内联）
job = httpx.post(
    f"{BASE}/api/v1/jobs",
    headers={**HEADERS, "Content-Type": "application/json"},
    json={"content": {"filename": "lesson.html", "text": "<html>...</html>"}},
).json()
print(job["job_id"])

# 2) 轮询结果
while True:
    r = httpx.get(f"{BASE}/api/v1/jobs/{job['job_id']}", headers=HEADERS).json()
    if r["status"] in ("completed", "failed"):
        print(r["status"], r.get("metrics") or r.get("error"))
        break
    time.sleep(3)
```

#### 上传 .zip 文件（单元评估）

```python
import httpx

API_KEY = "eval-..."
BASE = "https://eval.bj33smarter.com"

with open("unit.zip", "rb") as f:
    file_bytes = f.read()

r = httpx.post(
    f"{BASE}/api/v1/jobs",
    headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/octet-stream"},
    params={"filename": "unit.zip", "rule_set_id": "coursework-quality"},
    content=file_bytes,
)
print(r.status_code, r.json())  # 202 {"job_id":"…","status":"queued",…}
```

#### TypeScript（fetch）

```ts
const API_KEY = "eval-..."
const BASE = "https://eval.bj33smarter.com"

const res = await fetch(`${BASE}/api/v1/jobs`, {
  method: "POST",
  headers: { Authorization: `Bearer ${API_KEY}`, "Content-Type": "application/json" },
  body: JSON.stringify({ content: { filename: "lesson.html", text: "<html>...</html>" } }),
})
const job = await res.json()
console.log(job.job_id)
```

#### curl

```bash
# 上传单页
API_KEY="eval-..."
curl -X POST "https://eval.bj33smarter.com/api/v1/jobs" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/octet-stream" \
  --data-binary @lesson.html \
  -G -d "filename=lesson.html" -d "rule_set_id=coursework-quality"

# 查询
JOB="d3f1...e8a2"
curl "https://eval.bj33smarter.com/api/v1/jobs/$JOB" -H "Authorization: Bearer $API_KEY"
```

---

## 方式二：MCP 接入（智能体）

任意兼容 Streamable HTTP 的 MCP 客户端（Claude Code / Cursor / Windsurf / Claude Desktop / VS Code Copilot / 自研 Agent 等）无需手写 HTTP，直接以**工具调用**提交/查询评测。与 HTTP **同一把 API Key、同一套功能、同一租户隔离** —— MCP 只是同一接入层的新 transport。

### 客户端配置

把项目签发的 API Key 填入 `headers.Authorization`：

```jsonc
{
  "mcpServers": {
    "evalscope": {
      "url": "https://eval.bj33smarter.com/api/v1/mcp",
      "headers": { "Authorization": "Bearer eval-…" }
    }
  }
}
```

### 支持的内容格式与评估粒度

| 文件名扩展名 | 评估粒度 | 说明 |
| ------------ | -------- | ---- |
| `.zip` | **单元评估** | zip 内保留目录树，适用于多文件/多课件的单元；**必须是合法 zip 包** |
| `.html` / `.htm` | 单页评估 | 单个课件网页 |
| `.md` / `.markdown` | 单页评估 | 单个 Markdown 文档 |

> 文件名决定 `scope`：`.zip` 触发解压按单元评估；其余按单页评估。声明为 `.zip` 但内容不是合法 zip 会被拒绝。

### 使用流程

接入后，直接用**自然语言**让智能体评估课件即可，无需关心底层工具调用与上传细节。以 Claude Code 为例：

**评估单个课件**

```
你：请评估 lesson.html 这个课件

智能体：已提交评估，等待结果……
       ✅ 评估完成（综合评分 0.78，通过）
         · 交付率 DR 0.96 / 约束通过率 CPR 0.91
         ⚠️ 知识准确性检查未通过：原文等式计算有误
         详情：https://eval.bj33smarter.com/run/2f8a1c...
```

**评估整个单元（目录或 zip）**

```
你：请对 ./courseware/unit5 目录下的课件做单元评估

智能体：已将目录打包为单元评估提交……
       ✅ 完成，共 3 个课件：2 通过 / 1 未通过
         （逐项汇报分数与失败原因）
```

**智能体会自动处理的事**（你无需关心）：

- 选择规则集（默认 `coursework-quality`，可说"用 xxx 规则集评估"指定）
- 单文件直接提交；目录 / 大文件自动打包并上传，无需手动处理上传地址
- 提交后自动轮询，完成后汇报综合评分、各项指标与失败原因
- 需要看截图、逐条约束时，给出可点击的详情页链接

> 想指定任务信息直接说即可，例如"评估 unit5.zip，标题《分数入门》，学科数学"。

---

## 方式三：CLI 接入（评估器直跑）

直接使用评估器命令行 `agent-eval`，评估结果经 Web 摄取链路（ResultSink）**自动回传**，无需调用 `/api/v1/jobs`。

### 适用场景

- 本地开发联调评估流程
- CI / 定时脚本批量评估
- 不方便走 HTTP 的离线场景（结果先入离线队列，联网后重放）

### 安装

```bash
# 1. 克隆仓库
git clone https://git.code.tencent.com/domonic/agent-eval-system.git
cd agent-eval-system

# 2. 进入评估器目录并安装依赖（需先安装 uv：curl -LsSf https://astral.sh/uv/install.sh | sh）
cd evaluator
uv sync
```

### 配置

在仓库根 `.env` 配置：

| 变量                   | 默认                      | 说明                        |
| -------------------- | ----------------------- | ------------------------- |
| `AGENT_EVAL_HOST`    | `http://localhost:9000` | Web 平台地址                  |
| `AGENT_EVAL_API_KEY` | —（必填）                   | `eval-…`（单一 API Key）      |
| `AGENT_EVAL_PROJECT` | Key 所属项目                | 项目 uuid 或 slug（可省略）       |
| `AGENT_EVAL_UPLOAD`  | `false`                 | 设为 `true` 开启摄取（**需显式开启**） |

### 运行

在 `evaluator/` 目录下，配置好 `.env` 后即可用命令行运行评估：

```bash
cd evaluator
uv run agent-eval --help          # 查看可用命令
uv run agent-eval eval --help     # 查看评估子命令用法
```

运行后，`ResultSink` 会把运行 / 样本 / 约束 / 制品经 Bearer Key 自动摄取入库；网络失败自动入离线队列，联网后重放。

---

## Webhook 结果回调

三种接入方式提交的任务，在评估完成（`completed` / `failed`）后，平台可**主动 POST 回调**你的服务，免去轮询。Webhook 是**项目级配置**，对该项目下所有 job 生效，与轮询 `GET /api/v1/jobs/{id}` 互补——可单独使用，也可作轮询的兜底。

> 即便不配 Webhook，也随时可轮询 `GET /api/v1/jobs/{id}`；Webhook 投递失败时第三方应回退轮询。

### 配置

项目 **owner** 在控制台「项目设置」中填写回调地址与密钥，或调用接口：

```http
PATCH https://eval.bj33smarter.com/api/v1/projects/{project_id}
Authorization: Bearer <api_key>
```

| 字段 | 必需 | 说明 |
| ---- | ---- | ---- |
| `webhookUrl` | 是 | 回调地址（生产强制 HTTPS），如 `https://your.host/eval-callback` |
| `webhookSecret` | 否 | 签名密钥，用于校验 `X-Webhook-Signature`；AES-256-GCM 加密存储，**留空表示不改**（更新 URL 时 secret 留空即保持原值） |

> secret 不回显，前端以 `webhookSecretSet` 布尔表示是否已设置。仅项目 owner 可改 webhook 配置，变更写入审计日志（不含 secret 明文）。

### 触发与投递

评估器完成 job 后，平台内部触发回调（fire-and-forget，不阻塞任务完成）：

```text
executor 完成 ──▶ POST /api/v1/jobs/{id}/notify-completion（内部触发）
                     │
                     ▼
              查 project.webhookUrl
                     │ 已配置
                     ▼
              POST <webhookUrl>  +  X-Webhook-Signature
                     │
          3 次重试（0s / 1s / 4s 退避，单次超时 10s）
                     │
                     ▼
              落库 webhookDelivery（投递记录）
```

- **触发事件**：`job.completed`（评估成功）/ `job.failed`（评估失败）；未终态（`queued` / `running`）不触发。
- **幂等**：投递为 fire-and-forget，第三方应按 `job_id` **自行去重**（同一 job 的多次内部通知可能重复投递）。

### 请求格式

平台向你配置的 `webhookUrl` 发起 `POST`：

| Header | 说明 |
| ---- | ---- |
| `Content-Type` | `application/json` |
| `X-Webhook-Signature` | `sha256=<hex>`，HMAC-SHA256 签名（**仅配置了 secret 时携带**） |

**Payload 结构**：

| 字段 | 说明 |
| ---- | ---- |
| `source` | 固定 `agent-eval-system` |
| `event` | `job.completed` / `job.failed` |
| `timestamp` | 投递时间（ISO 8601） |
| `overview_url` | 速览端点相对路径 `/api/v1/jobs/{id}/overview` |
| 其余字段 | 完整 job DTO，与 `GET /api/v1/jobs/{id}` 完全一致（`job_id` / `status` / `run_id` / `metrics` / `error` 等） |

payload 示例（`job.completed`）：

```json
{
  "source": "agent-eval-system",
  "event": "job.completed",
  "timestamp": "2026-07-27T09:12:33.000Z",
  "overview_url": "/api/v1/jobs/0bc0b717-ada1-4783-8718-7889b5982060/overview",
  "job_id": "0bc0b717-ada1-4783-8718-7889b5982060",
  "status": "completed",
  "project_id": "d288698e-ee7c-4d4e-b1fc-a2d050ce4a9b",
  "run_id": "2f8a1c...",
  "web_run_url": "https://eval.bj33smarter.com/run/2f8a1c...",
  "metrics": { "DR": 0.962, "CPR": 0.914, "avg_reward": 0.781 },
  "error": null,
  "created_at": "2026-07-27T09:10:00.000Z",
  "finished_at": "2026-07-27T09:12:30.000Z"
}
```

> payload 已含完整 job，可直接消费；要"过没过 / 各项失败原因"的人话摘要，再请求 `overview_url`（需带 API Key）。

### 签名校验

对请求 **body 原始字节**用配置的 secret 做 HMAC-SHA256，与 `X-Webhook-Signature` 比对（仿 Stripe / GitHub 范式）。务必先验签、再解析 JSON。

**Python（FastAPI / Flask）**

```python
import hmac, hashlib

def verify(body: bytes, signature: str, secret: str) -> bool:
    if not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
```

**TypeScript（Express）**

```ts
import crypto from "crypto"

function verify(body: Buffer, signature: string, secret: string): boolean {
  const expected = `sha256=${crypto.createHmac("sha256", secret).update(body).digest("hex")}`
  return crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(signature))
}
```

> 未配置 secret 的项目不会携带签名头，此时建议辅以来源 IP 白名单或回拉 `overview_url` 校验。

### 重试与可靠性

- **重试**：HTTP 非 2xx 或网络异常时，按 `0s / 1s / 4s` 指数退避重试，**最多 3 次**；单次请求超时 **10s**。
- **落库**：每次投递在 `webhookDelivery` 记一行（`attempt` / `success` / `statusCode` / `requestBody` / `responseBody` / 耗时），可在控制台或 `GET /api/v1/projects/{id}/webhook-deliveries` 查询（默认最近 20 条，上限 50）。
- **兜底**：3 次仍失败仅记日志、不再重投——请回退轮询 `GET /api/v1/jobs/{id}`。

### 测试回调

配置后用控制台「发送测试回调」按钮（或接口）验证链路，会投递一条 `event=webhook.test` 的 payload：

```bash
POST https://eval.bj33smarter.com/api/v1/projects/{project_id}/test-webhook
Authorization: Bearer <api_key>   # 需 owner 权限
```

```json
{
  "source": "agent-eval-system",
  "event": "webhook.test",
  "project_id": "...",
  "status": "test",
  "message": "Webhook 测试回调 — 收到此消息说明配置正确。"
}
```

---

## 状态码与错误码

| HTTP  | code                | 触发场景                                        |
| ----- | ------------------- | ------------------------------------------- |
| `202` | —                   | 提交成功，任务已入队                                  |
| `400` | `INPUT_INVALID`     | 字段缺失或非法（如缺 `filename` / `content`、`.zip` 飞行检查失败） |
| `401` | `AUTH_INVALID`      | 缺少/错误的 API Key、Key 已吊销或过期、scope 不含 `ingest` |
| `404` | `JOB_NOT_FOUND`     | 任务不存在或不属于当前 Key 的项目                         |
| `413` | `PAYLOAD_TOO_LARGE` | 上传内容超限（默认 50MB；超出走 presigned 直传，见「大文件直传」） |
| `429` | `RATE_LIMITED`      | 触发令牌桶限流（按 API Key，提交 / 摄取），响应带 `Retry-After` 头 |

> MCP 工具调用错误以 `isError: true` + `{ code, message }` 返回，错误码与 HTTP 一致，不泄露资源存在性。

---

## 限额与约束

- **上传上限**：单次 50MB（`application/octet-stream` / JSON inline）；MCP `base64` 解码后 ≤5MB，超出走 `request_input_upload` presigned 直传。
- **单元评估**：`.zip` 解压总大小上限 100MB、含 zip-slip 防护。
- **限流**：按 API Key 令牌桶（提交 / 摄取共用口径）。
- **保留期**：运行 / 样本 / 制品保留期由项目设置控制。
- **鉴权**：一把 Key 绑定单一项目，所有读写按 Key 验签所得 `project_id/org_id` 过滤，越权返回 `404`。
