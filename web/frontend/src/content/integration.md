# 第三方接入 EvalScope 评估器

通过 EvalScope **Web 后端 `/api/v1/jobs`**，第三方系统（课件平台、Agent 编排等）一行 HTTP 请求即可把待评估内容提交给 EvalScope；平台异步运行评估器，并回传 **可量化的指标** 与 **可追溯的证据**。

## 快速开始

三步接入 EvalScope 评估：

1. **创建 API Key** — 登录 [EvalScope 控制台](/dashboard) → 左侧「项目看板」选项目 → 「API Key」页 → 新建 → 复制 **API Key**（`eval-…`，单一 Bearer Key）。**仅创建时明文展示一次，请妥善保存。**
2. **提交评估** — 携带 `Authorization: Bearer <api_key>` 向 `POST /api/v1/jobs` 提交内容，立即拿到 `job_id`（`202 Accepted`）。
3. **查询结果** — 轮询 `GET /api/v1/jobs/{job_id}`，直到 `status` 变为 `completed`，读取 `metrics` 与 `web_run_url`。

> **Base URL（线上）**：`https://eval.bj33smarter.com`
>
> 想先试一下？登录后打开 [调试台](/debug)，填 API Key + 上传文件即可在线提交、实时查看 request / response / 评估结果。

---

## 接入流程

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

- **Base URL（线上）**：`https://eval.bj33smarter.com`
- **鉴权方式**：`Authorization: Bearer <api_key>`（单一 Key，无需计算签名）
- **交互方式**：提交后拿到 `job_id`，轮询 `GET /api/v1/jobs/{job_id}` 获取结果

---

## 提交评估

```bash
POST https://eval.bj33smarter.com/api/v1/jobs
Authorization: Bearer <api_key>
```

所有请求通过 `Authorization: Bearer <api_key>` 鉴权（`api_key` 即控制台签发的单一 Key）。**无需计算签名**，生产强制 HTTPS 下直接传输即可。

按 `Content-Type` 分两种提交方式：

### 上传原始字节（application/octet-stream）

适合提交 HTML / Markdown / 压缩包等已有文件。请求体为文件原始字节，元数据通过**查询串**传递。

| 查询串字段      | 必需  | 类型     | 说明                               |
| --------------- | --- | ------ | -------------------------------- |
| `filename`      | 是   | string | 文件名，如 `lesson.html`、`unit.zip`  |
| `rule_set_id`   | 否   | string | 规则集，默认 `coursework-quality`      |
| `task_id`       | 否   | string | 自定义任务标识，如 `math-2024-q1`         |
| `task_title`    | 否   | string | 任务标题，如《分数入门》                     |
| `task_subject`  | 否   | string | 任务学科                               |

> 单文件为「单页」评估；`.zip` 解析为「单元」评估（保留目录结构）。

### 内联内容（application/json）

适合直接传文本，无需落盘。

| 字段                                       | 必需  | 类型     | 说明                                                                                   |
| ---------------------------------------- | --- | ------ | ------------------------------------------------------------------------------------ |
| `content`                                | 是   | object | `{ filename: string, text: string }`，如 `{"filename":"lesson.html","text":"<html>…"}` |
| `rule_set_id` / `task_id` / `task_title` | 否   | string | 同上                                                                                   |

### 响应（`202 Accepted`）

```json
{
  "job_id": "d3f1...e8a2",
  "status": "queued",
  "project_id": "9b30ef3c-867b-4110-8799-b49c1d4db32b",
  "poll_url": "/api/v1/jobs/d3f1...e8a2",
  "scf_request_id": "6a2b..."
}
```

> `project_id` 由 API Key 验签解析后回传，**提交时无需也不接受 project_id**——结果归属完全由 Key 决定。
> `scf_request_id` 仅在生产 SCF 触发时返回；本地开发为 `null`。

---

## 查询结果

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
| `metrics`                                   | 四维指标 `DR` / `CPR` / `Reward` / `CondR` 等（完成后）；含 `_executor` 透明度字段 |
| `error`                                     | 失败原因（失败时）                                     |
| `created_at` / `started_at` / `finished_at` | 各阶段时间戳                                        |

> 越权访问（`job_id` 不属于当前 Key 的项目）一律返回 `404`，不泄露存在性。

### 响应示例

以 `completed` 为例（`failed` 时 `metrics` 为 `null`、`error` 填充失败原因）：

```json
{
  "job_id": "0bc0b717-ada1-4783-8718-7889b5982060",
  "status": "completed",
  "project_id": "d288698e-ee7c-4d4e-b1fc-a2d050ce4a9b",
  "org_id": "1968916c-9aed-4df5-ba5e-6b5c9f757a06",
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

> 想看"过没过 / 各项为什么没过"，用下面的速览端点；想看逐条约束 / 制品，用 iframe 嵌入（见「公开访问与 iframe 嵌入」）。

---

## 评测速览（overview）

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
  "summary": { "total": 1, "passed": 0, "failed": 1, "skipped": 0 },
  "dimension_pass": { "format": 1, "commonsense": 0, "soft": 1, "preference": 1 },
  "items": [
    {
      "external_sample_id": "contents",
      "score": 0.669,
      "passed": false,
      "failures": [
        {
          "name": "知识准确性检查",
          "reason": "原文提到 12×2 + 7 + 3 + 5 + 18 = 100，实际应为 57，等式错误（经 LLM 二次确认）"
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
| `metrics` | DR / CPR / condR / 平均耗时 |
| `summary` | 样本通过 / 失败 / 跳过计数 |
| `dimension_pass` | 各阶段（format / commonsense / soft / preference）达标样本数 |
| `items[]` | 各评测项（样本）：`score` + `passed` + `failures`（未通过约束的 `name` + `reason`） |

> - 任务未完成（`queued` / `running` / `failed`）时，只回 `status` + 任务级 `error`，`items` 为空。
> - 速览**只给摘要**：逐条约束的 `details` / 制品预览等深度详情不开放 API，由 iframe 嵌入公开页查看。
> - 越权（`job_id` 不属于当前 Key 的项目）一律 `404`，不泄露存在性。

---

## 公开访问与 iframe 嵌入

把项目设为公开后，运行 / 样本详情页可被第三方**免登录** iframe 嵌入（详见 `docs/arch/12第三方系统对接方案.md` §3.5）：

1. 项目 owner 在 Web 控制台「项目设置 → 公开访问」开启**公开**。
2. 直接把运行详情页地址放进 iframe：

```html
<iframe src="https://eval.bj33smarter.com/run/{run_id}" style="width:100%;height:800px;border:0"></iframe>
```

公开 = 任何人持链接可**只读**查看该项目运行 / 样本（不含 Key / 写操作）；不公开的项目仍需登录。`run_id` 取自 `GET /jobs/{id}` 或 `/overview` 的 `run_id` / `web_run_url`。

---

## 状态码与错误码

| HTTP  | code                | 触发场景                                        |
| ----- | ------------------- | ------------------------------------------- |
| `202` | —                   | 提交成功，任务已入队                                  |
| `400` | `INPUT_INVALID`     | 字段缺失或非法（如缺 `filename` / `content`）              |
| `401` | `AUTH_INVALID`      | 缺少/错误的 API Key、Key 已吊销或过期、scope 不含 `ingest` |
| `404` | `JOB_NOT_FOUND`     | 任务不存在或不属于当前 Key 的项目                         |
| `413` | `PAYLOAD_TOO_LARGE` | 上传内容超限（默认 50MB）                              |
| `429` | `RATE_LIMITED`      | 触发令牌桶限流（按 API Key，提交 / 摄取），响应带 `Retry-After` 头 |

---

## 代码示例

### Python（httpx）

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

### 上传 .zip 文件（单元评估）

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

### TypeScript（fetch）

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

### curl（octet-stream 上传）

```bash
API_KEY="eval-..."
curl -X POST "https://eval.bj33smarter.com/api/v1/jobs" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/octet-stream" \
  --data-binary @lesson.html \
  -G -d "filename=lesson.html" -d "rule_set_id=coursework-quality"
```

### curl（查询）

```bash
API_KEY="eval-..."; JOB="d3f1...e8a2"
curl "https://eval.bj33smarter.com/api/v1/jobs/$JOB" -H "Authorization: Bearer $API_KEY"
```

---

## 用评估器 CLI 接入

如果你直接使用评估器命令行（`agent-eval`），评估结果可经 Web 摄取链路自动回传，无需调用 `/api/v1/jobs`。在 `.env` 配置：

| 变量                   | 默认                      | 说明                        |
| -------------------- | ----------------------- | ------------------------- |
| `AGENT_EVAL_HOST`    | `http://localhost:9000` | Web 平台地址                  |
| `AGENT_EVAL_API_KEY` | —（必填）                   | `eval-…`（单一 API Key）      |
| `AGENT_EVAL_PROJECT` | Key 所属项目                | 项目 uuid 或 slug（可省略）       |
| `AGENT_EVAL_UPLOAD`  | `false`                 | 设为 `true` 开启摄取（**需显式开启**） |

配置后正常运行评估命令，`ResultSink` 会把运行 / 样本 / 约束 / 制品经 Bearer Key 摄取入库；网络失败自动入离线队列重放。

---

## Roadmap

以下能力**规划中**：

- **Webhook 回调** — 任务状态变更主动推送（`job.running` / `job.completed` / `job.failed`）。
