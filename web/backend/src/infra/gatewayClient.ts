/**
 * eval-gateway 转发客户端（调试台用）—— Bearer 鉴权。
 *
 * web backend 以「目标项目的 API Key（单一 token）」身份向 gateway 转发：
 *   Authorization: Bearer <token>
 *
 * multipart body 仍手动构造（fetch FormData 是 opaque 流，手动构造便于统一处理 boundary
 * 与大小控制）；Bearer 无需对 body 签名。
 */

import { randomBytes } from "crypto"
import { PlatformError } from "../middleware/errorHandler"

const JOB_PATH = "/v1/jobs"

export interface GatewaySubmitInput {
  baseUrl: string
  token: string
  filename: string
  fileBytes: Buffer
  ruleSetId: string
  /** 调用方可设的任务字段；不填则 gateway builder 回退（单页恒为 contents）。 */
  taskId?: string
  taskTitle?: string
  taskSubject?: string
}

export interface GatewaySubmitResult {
  job_id: string
  status: string
  poll_url: string
}

export interface GatewayJobStatus {
  job_id: string
  status: string
  run_id?: string | null
  web_run_url?: string | null
  metrics?: unknown
  error?: { message?: string; traceback?: string } | null
  created_at?: string | null
  started_at?: string | null
  finished_at?: string | null
  [k: string]: unknown
}

/** 构造 multipart/form-data body（RFC 7578）。 */
function buildMultipart(
  fields: Array<{ name: string; value?: string } | { name: string; filename: string; mime: string; data: Buffer }>,
  boundary: string,
): Buffer {
  const parts: Buffer[] = []
  for (const f of fields) {
    parts.push(Buffer.from(`--${boundary}\r\n`))
    if ("data" in f) {
      parts.push(
        Buffer.from(
          `Content-Disposition: form-data; name="${f.name}"; filename="${f.filename}"\r\n` +
            `Content-Type: ${f.mime}\r\n\r\n`,
        ),
      )
      parts.push(f.data)
    } else {
      parts.push(Buffer.from(`Content-Disposition: form-data; name="${f.name}"\r\n\r\n`))
      parts.push(Buffer.from(f.value ?? ""))
    }
    parts.push(Buffer.from("\r\n"))
  }
  parts.push(Buffer.from(`--${boundary}--\r\n`))
  return Buffer.concat(parts)
}

async function ensureOk(res: Response, method: string, path: string): Promise<void> {
  if (res.ok) return
  const detail = await res.text().catch(() => "")
  throw new PlatformError(`gateway ${method} ${path} → HTTP ${res.status}`, {
    status: 502,
    code: "GATEWAY_UPSTREAM",
    details: { upstreamStatus: res.status, upstreamBody: detail.slice(0, 1000) },
  })
}

/** POST /v1/jobs（multipart file 上传）。返回 {job_id, status, poll_url}。 */
export async function submitJob(input: GatewaySubmitInput): Promise<GatewaySubmitResult> {
  const boundary = `----evalgw${randomBytes(12).toString("hex")}`
  const fields: Parameters<typeof buildMultipart>[0] = [
    { name: "rule_set_id", value: input.ruleSetId },
    { name: "file", filename: input.filename, mime: "application/octet-stream", data: input.fileBytes },
  ]
  // 仅在调用方提供时携带 task_*，避免空串覆盖 gateway 默认行为
  for (const [name, val] of [
    ["task_id", input.taskId],
    ["task_title", input.taskTitle],
    ["task_subject", input.taskSubject],
  ] as const) {
    if (val && val.trim()) fields.push({ name, value: val })
  }
  const body = buildMultipart(fields, boundary)
  const res = await fetch(`${input.baseUrl}${JOB_PATH}`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${input.token}`,
      "Content-Type": `multipart/form-data; boundary=${boundary}`,
    },
    body,
  })
  await ensureOk(res, "POST", JOB_PATH)
  return (await res.json()) as GatewaySubmitResult
}

/** GET /v1/jobs/{id}。返回任务态。 */
export async function getJob(
  baseUrl: string,
  token: string,
  jobId: string,
): Promise<GatewayJobStatus> {
  const path = `${JOB_PATH}/${jobId}`
  const res = await fetch(`${baseUrl}${path}`, {
    method: "GET",
    headers: { Authorization: `Bearer ${token}` },
  })
  await ensureOk(res, "GET", path)
  return (await res.json()) as GatewayJobStatus
}
