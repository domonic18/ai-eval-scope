## 快速开始

三步接入 EvalScope 评估：

1. **创建 API Key** — 登录 [EvalScope 控制台](/dashboard)，进入任一项目的「API Key」页新建 Key，复制 `public_key`（`pk-eval-…`）与 `secret_key`（`sk-eval-…`）。**secret 仅展示一次，请妥善保存。**
2. **提交评估** — 用 Key 签名后向 `POST /v1/jobs` 提交内容，立即拿到 `job_id`（`202 Accepted`）。
3. **查询结果** — 轮询 `GET /v1/jobs/{job_id}`，直到 `status` 变为 `completed`，读取 `metrics` 与 `web_run_url`。

> **网关地址（线上）**：`https://eval.bj33smarter.com/gateway`
>

---

## 提交评估

```bash
POST https://eval.bj33smarter.com/gateway/v1/jobs
Authorization: Eval <public_key>:<signature>
```

请求头 `Authorization` 的签名规则：

```
signature = lowercase_hex( HMAC_SHA256( secret_key, METHOD + "\n" + PATH + "\n" + sha256(body) ) )
```

- `METHOD`：HTTP 方法大写（`POST` / `GET`）。
- `PATH`：URL 路径，不含 query string（如 `/v1/jobs`）。
- `body`：请求体的**原始字节**（GET 请求为空字符串）；务必用**实际发送的字节**计算哈希。

> 完整可运行的签名代码见 [代码示例](#6-代码示例)。

按 `Content-Type` 分两种提交方式：

### 上传文件（multipart/form-data）

适合提交 HTML / Markdown / 压缩包等已有文件。

| 字段 | 必需 | 类型 | 说明 |
| --- | --- | --- | --- |
| `file` | 是 | file | 待评估文件，如 `lesson.html`、`unit.zip` |
| `rule_set_id` | 否 | string | 规则集，默认 `coursework-default` |
| `task_id` | 否 | string | 自定义任务标识，如 `math-2024-q1` |
| `task_title` | 否 | string | 任务标题，如 `大单元总导` |

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
Authorization: Eval <public_key>:<signature>
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

| 字段 | 说明 |
| --- | --- |
| `job_id` / `status` | 任务 id 与当前状态 |
| `project_id` / `org_id` | 归属（来自 API Key） |
| `input_kind` / `scope` | `upload` / `inline`、`unit` / `single` |
| `rule_set_id` / `task_id` / `task_title` | 提交时传入 |
| `run_id` | 评估运行 id（进入 running 后填充） |
| `web_run_url` | Web 平台运行详情页（完成后可访问） |
| `metrics` | 四维指标 `DR` / `CPR` / `Reward` / `CondR` 等（完成后） |
| `error` | 失败原因（失败时） |
| `created_at` / `started_at` / `finished_at` | 各阶段时间戳 |

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

```
POST https://eval.bj33smarter.com/gateway/v1/jobs/{job_id}/cancel
Authorization: Eval <public_key>:<signature>
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

| HTTP | code | 触发场景 |
| --- | --- | --- |
| `202` | — | 提交成功，任务已入队 |
| `400` | `InputInvalidError` | 字段缺失或非法（如缺 `file` / `content`） |
| `401` | `AUTH_INVALID` | 缺少/错误的签名、Key 已吊销或过期、scope 不含 `ingest` |
| `404` | `JOB_NOT_FOUND` | 任务不存在或不属于当前 Key 的项目 |
| `409` | `CANCEL_FAILED` | 非 `queued` 态调用取消 |

---

## 代码示例

### Python（httpx）

```python
import hashlib, hmac, time, httpx

PK = "pk-eval-..."
SK = "sk-eval-..."
BASE = "https://eval.bj33smarter.com/gateway"

def sign(method, path, body: bytes, secret):
    body_hash = hashlib.sha256(body).hexdigest()
    canonical = f"{method.upper()}\n{path}\n{body_hash}"
    return hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()

# 1) 提交（JSON 内联）
body = b'{"content":{"filename":"lesson.html","text":"<html>...</html>"}}'
headers = {"Authorization": f"Eval {PK}:{sign('POST', '/v1/jobs', body, SK)}",
           "Content-Type": "application/json"}
job = httpx.post(f"{BASE}/v1/jobs", content=body, headers=headers).json()
print(job["job_id"])

# 2) 轮询结果
while True:
    path = f"/v1/jobs/{job['job_id']}"
    h = {"Authorization": f"Eval {PK}:{sign('GET', path, b'', SK)}"}
    r = httpx.get(f"{BASE}{path}", headers=h).json()
    if r["status"] in ("completed", "failed"):
        print(r["status"], r.get("metrics") or r.get("error"))
        break
    time.sleep(3)
```

### 提交 .zip 文件（单元评估）

`.zip` 会保留目录结构，按「单元」评估。注意 multipart body 必须**手工拼装**（boundary 固定），签名才能与实际发送的字节完全一致 —— 直接用 SDK 的 `files=` 会因自动生成 boundary 而导致签名失败。

```python
# 读取已打包好的 zip 文件（多文件已保留目录结构）
with open("unit.zip", "rb") as f:
    zip_bytes = f.read()

# 手工拼装 multipart（boundary 固定 → 签名字节与发送字节一致）
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
sig = sign("POST", "/v1/jobs", body, SK)  # sign 函数见上方 Python 示例
r = httpx.post(
    f"{BASE}/v1/jobs",
    content=body,
    headers={
        "Authorization": f"Eval {PK}:{sig}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    },
)
print(r.status_code, r.json())  # 202 {"job_id":"…","status":"queued",…}
```

### TypeScript（fetch + node:crypto）

```ts
import { createHmac, createHash } from "crypto"

const PK = "pk-eval-..."
const SK = "sk-eval-..."
const BASE = "https://eval.bj33smarter.com/gateway"

const sign = (method: string, path: string, body: Buffer) => {
  const bodyHash = createHash("sha256").update(body).digest("hex")
  const canonical = `${method.toUpperCase()}\n${path}\n${bodyHash}`
  return createHmac("sha256", SK).update(canonical).digest("hex")
}

const body = Buffer.from(JSON.stringify({ content: { filename: "lesson.html", text: "<html>...</html>" } }))
const res = await fetch(`${BASE}/v1/jobs`, {
  method: "POST",
  headers: { Authorization: `Eval ${PK}:${sign("POST", "/v1/jobs", body)}`, "Content-Type": "application/json" },
  body,
})
const job = await res.json()
console.log(job.job_id)
```

### curl（查询，GET 无 body 签名最简）

```bash
PK="pk-eval-..."; SK="sk-eval-..."; JOB="d3f1...e8a2"
BODY_HASH=$(printf '' | sha256sum | cut -d' ' -f1)
SIG=$(printf 'GET\n/v1/jobs/'"$JOB"'\n'"$BODY_HASH" \
      | openssl dgst -sha256 -hmac "$SK" | cut -d' ' -f2)
curl "https://eval.bj33smarter.com/gateway/v1/jobs/$JOB" -H "Authorization: Eval $PK:$SIG"
```

> curl 对带 body 的 `POST` 精确签名较繁琐，提交评估建议用 Python / TS 示例。

---


## Roadmap

以下能力**规划中**，当前版本请以轮询为准：

- **Webhook 回调** — 任务状态变更主动推送（`job.running` / `job.completed` / `job.failed`），HMAC 签名 + 指数退避重试。
- **结果端点** — `GET /v1/jobs/{id}/result`，独立获取完整结果快照。
- **细粒度 scope** — `eval:submit` / `eval:read`（当前统一为 `ingest`）。
- **限额与精细化错误码** — `429 RATE_LIMITED` / `413 PAYLOAD_TOO_LARGE` / `422 INPUT_INVALID`。

如需优先支持某项，或在接入中遇到问题，请联系平台管理员。
