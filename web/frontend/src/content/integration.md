# 第三方接入 EvalScope 评估器

通过 **EvalScope Gateway**，第三方系统（课件平台、Agent 编排等）一行 HTTP 请求即可把待评估内容提交给 EvalScope；平台异步运行评估器，并回传 **可量化的指标** 与 **可追溯的证据**。

## 快速开始

三步接入 EvalScope 评估：

1. **创建 API Key** — 登录 [EvalScope 控制台](/dashboard) → 左侧「项目看板」选项目 → 「API Key」页 → 新建 → 复制 **API Key**（`eval-…`，单一 Bearer Key）。**仅创建时明文展示一次，请妥善保存。**
2. **提交评估** — 携带 `Authorization: Bearer <api_key>` 向 `POST /v1/jobs` 提交内容，立即拿到 `job_id`（`202 Accepted`）。
3. **查询结果** — 轮询 `GET /v1/jobs/{job_id}`，直到 `status` 变为 `completed`，读取 `metrics` 与 `web_run_url`。

> **网关地址（线上）**：`https://eval.bj33smarter.com/gateway`
>
> 想先试一下？登录后打开 [调试台](/debug)，填 API Key + 上传文件即可在线提交、实时查看 request / response / 评估结果。

---



## 接入流程

第三方系统一行 HTTP 请求把待评估内容提交给 EvalScope，平台异步运行评估器，完成后回传指标与证据。

```text
┌──────────┐   POST /v1/jobs         ┌──────────────────────┐    调用     ┌──────────┐
│ 第三方系统 │  ───────────────▶       │  EvalScope Gateway   │ ─────────▶ │  评估器   │
│          │  Authorization: Bearer  │ Bearer Key · 异步调度 │             │          │
└──────────┘                         └──────────────────────┘            └──────────┘
                                                                              │
                                                                              ▼
                                              结果经 Web 摄取链路回传        ┌──────────────┐
                                              第三方轮询 GET /v1/jobs/{id} │ Web 可观测平台 │
                                                                          └──────────────┘
```

- **网关地址（线上）**：`https://eval.bj33smarter.com/gateway`
- **鉴权方式**：`Authorization: Bearer <api_key>`
- **交互方式**：提交后拿到 `job_id`，轮询 `GET /v1/jobs/{job_id}` 获取结果

---



## 提交评估

```bash
POST https://eval.bj33smarter.com/gateway/v1/jobs
Authorization: Bearer <api_key>
```

所有请求通过 `Authorization: Bearer <api_key>` 鉴权（`api_key` 即控制台签发的单一 Key）。**无需计算签名**，强制 HTTPS 下直接传输即可。

按 `Content-Type` 分两种提交方式：

### 上传文件（multipart/form-data）

适合提交 HTML / Markdown / 压缩包等已有文件。


| 字段            | 必需  | 类型     | 说明                               |
| ------------- | --- | ------ | -------------------------------- |
| `file`        | 是   | file   | 待评估文件，如 `lesson.html`、`unit.zip` |
| `rule_set_id` | 否   | string | 规则集，默认 `coursework-default`      |
| `task_id`     | 否   | string | 自定义任务标识，如 `math-2024-q1`         |
| `task_title`  | 否   | string | 任务标题，如《分数入门》                     |




### 内联内容（application/json）

适合直接传文本，无需落盘。


| 字段                                       | 必需  | 类型     | 说明                                                                                   |
| ---------------------------------------- | --- | ------ | ------------------------------------------------------------------------------------ |
| `content`                                | 是   | object | `{ filename: string, text: string }`，如 `{"filename":"lesson.html","text":"<html>…"}` |
| `rule_set_id` / `task_id` / `task_title` | 否   | string | 同上                                                                                   |


> 单文件为「单页」评估；`.zip` 解析为「单元」评估（保留目录结构）。



### 响应（`202 Accepted`）

```json
{
  "job_id": "d3f1...e8a2",
  "status": "queued",
  "web_run_url": null,
  "poll_url": "/v1/jobs/d3f1...e8a2"
}
```

---



## 查询结果

```bash
GET https://eval.bj33smarter.com/gateway/v1/jobs/{job_id}
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
| `metrics`                                   | 四维指标 `DR` / `CPR` / `Reward` / `CondR` 等（完成后） |
| `error`                                     | 失败原因（失败时）                                     |
| `created_at` / `started_at` / `finished_at` | 各阶段时间戳                                        |


> 越权访问（`job_id` 不属于当前 Key 的项目）一律返回 `404`，不泄露存在性。



### 响应

以 `completed` 为例（`failed` 时 `metrics` 为 `null`、`error` 填充失败原因）：

```json
{
  "job_id": "0bc0b717-ada1-4783-8718-7889b5982060",
  "status": "completed",
  "project_id": "d288698e-ee7c-4d4e-b1fc-a2d050ce4a9b",
  "org_id": "1968916c-9aed-4df5-ba5e-6b5c9f757a06",
  "input_kind": "inline",
  "scope": "single",
  "rule_set_id": "coursework-default",
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

---



## 取消任务

```bash
POST https://eval.bj33smarter.com/gateway/v1/jobs/{job_id}/cancel
Authorization: Bearer <api_key>
```

仅 `queued` 状态可取消；已进入 `running` 返回 `409 CANCEL_FAILED`。

### 响应

取消成功后返回更新后的任务，`status` 转为 `failed`：

```json
{
  "job_id": "0bc0b717-ada1-4783-8718-7889b5982060",
  "status": "failed",
  "error": { "code": "CANCELLED", "message": "cancelled by user" },
  "created_at": "2026-07-01T08:00:00.000Z",
  "started_at": null,
  "finished_at": "2026-07-01T08:00:10.000Z"
}
```

---



## 状态码与错误码


| HTTP  | code                | 触发场景                                        |
| ----- | ------------------- | ------------------------------------------- |
| `202` | —                   | 提交成功，任务已入队                                  |
| `400` | `InputInvalidError` | 字段缺失或非法（如缺 `file` / `content`）              |
| `401` | `AUTH_INVALID`      | 缺少/错误的 API Key、Key 已吊销或过期、scope 不含 `ingest` |
| `404` | `JOB_NOT_FOUND`     | 任务不存在或不属于当前 Key 的项目                         |
| `409` | `CANCEL_FAILED`     | 非 `queued` 态调用取消                            |


---



## 代码示例



### Python（httpx）

```python
import time
import httpx

API_KEY = "eval-..."
BASE = "https://eval.bj33smarter.com/gateway"
HEADERS = {"Authorization": f"Bearer {API_KEY}"}

# 1) 提交（JSON 内联）
job = httpx.post(
    f"{BASE}/v1/jobs",
    headers={**HEADERS, "Content-Type": "application/json"},
    json={"content": {"filename": "lesson.html", "text": "<html>...</html>"}},
).json()
print(job["job_id"])

# 2) 轮询结果
while True:
    r = httpx.get(f"{BASE}/v1/jobs/{job['job_id']}", headers=HEADERS).json()
    if r["status"] in ("completed", "failed"):
        print(r["status"], r.get("metrics") or r.get("error"))
        break
    time.sleep(3)
```



### 提交 .zip 文件（单元评估）

`.zip` 会保留目录结构，按「单元」评估。multipart body 仍建议**手工拼装**（boundary 固定，便于精确控制）：

```python
# 读取已打包好的 zip 文件（多文件已保留目录结构）
with open("unit.zip", "rb") as f:
    zip_bytes = f.read()

# 手工拼装 multipart（boundary 固定）
boundary = "----evalboundary"
body = (
    f"--{boundary}\r\n".encode()
    + b'Content-Disposition: form-data; name="file"; filename="unit.zip"\r\n'
    + b"Content-Type: application/zip\r\n\r\n"
    + zip_bytes
    + b"\r\n"
    + f"--{boundary}\r\n".encode()
    + b'Content-Disposition: form-data; name="rule_set_id"\r\n\r\n'
    + b"coursework-default\r\n"
    + f"--{boundary}--\r\n".encode()
)
r = httpx.post(
    f"{BASE}/v1/jobs",
    content=body,
    headers={**HEADERS, "Content-Type": f"multipart/form-data; boundary={boundary}"},
)
print(r.status_code, r.json())  # 202 {"job_id":"…","status":"queued",…}
```



### TypeScript（fetch）

```ts
const API_KEY = "eval-..."
const BASE = "https://eval.bj33smarter.com/gateway"

const res = await fetch(`${BASE}/v1/jobs`, {
  method: "POST",
  headers: { Authorization: `Bearer ${API_KEY}`, "Content-Type": "application/json" },
  body: JSON.stringify({ content: { filename: "lesson.html", text: "<html>...</html>" } }),
})
const job = await res.json()
console.log(job.job_id)
```



### curl（查询）

```bash
API_KEY="eval-..."; JOB="d3f1...e8a2"
curl "https://eval.bj33smarter.com/gateway/v1/jobs/$JOB" -H "Authorization: Bearer $API_KEY"
```

---



## 用评估器 CLI 接入

如果你直接使用评估器命令行（`agent-eval`），评估结果可经 Web 摄取链路自动回传，无需调用 gateway。在 `.env` 配置：


| 变量                   | 默认                      | 说明                        |
| -------------------- | ----------------------- | ------------------------- |
| `AGENT_EVAL_HOST`    | `http://localhost:9000` | Web 平台地址                  |
| `AGENT_EVAL_API_KEY` | —（必填）                   | `eval-…`（单一 API Key）      |
| `AGENT_EVAL_PROJECT` | Key 所属项目                | 项目 uuid 或 slug（可省略）       |
| `AGENT_EVAL_UPLOAD`  | `false`                 | 设为 `true` 开启摄取（**需显式开启**） |


配置后正常运行评估命令，`ResultSink` 会把运行 / 样本 / 约束 / 制品经 Bearer Key 摄取入库；网络失败自动入离线队列重放。

---



## Roadmap

以下能力**规划中**，当前版本请以轮询为准：

- **Webhook 回调** — 任务状态变更主动推送（`job.running` / `job.completed` / `job.failed`）。
- **结果端点** — `GET /v1/jobs/{id}/result`，独立获取完整结果快照。
- **细粒度 scope** — `eval:submit` / `eval:read`（当前统一为 `ingest`）。
- **限额与精细化错误码** — `429 RATE_LIMITED` / `413 PAYLOAD_TOO_LARGE` / `422 INPUT_INVALID`。

如需优先支持某项，或在接入中遇到问题，请联系平台管理员。