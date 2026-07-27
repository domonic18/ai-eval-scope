/**
 * Webhook 回调投递服务（docs/arch/12 §6.5）。
 *
 * executor 完成 job 后 POST /api/v1/jobs/:id/notify-completion → 本服务查 job + project
 * → 有 webhook 配置则构造 payload + HMAC 签名 + POST 到 webhookUrl（3 次重试）。
 * payload 轻量（event/job_id/status/run_id/overview_url），不含全量 metrics——第三方按
 * overview_url 拉详情。投递异步（fire-and-forget），不阻塞通知端点响应。
 */

import { decryptToken } from "../infra/crypto"
import { getLogger } from "../infra/logger"
import { getPrisma } from "../infra/prisma"
import { signWebhookPayload } from "../infra/webhook"
import { serializeJob } from "./evalJob.service"

/**
 * 查 job + project，若有 webhook 配置则投递。fire-and-forget（调用方不 await）。
 * 幂等：同一 job 多次调用不会重复投递（第三方应自行按 job_id 去重）。
 */
export async function notifyJobCompletion(jobId: string): Promise<void> {
  const prisma = getPrisma()
  const logger = getLogger()

  const job = await prisma.evalJob.findUnique({ where: { id: jobId } })
  if (!job) {
    logger.warn({ jobId }, "webhook.job_not_found")
    return
  }
  if (job.status !== "completed" && job.status !== "failed") {
    logger.info({ jobId, status: job.status }, "webhook.job_not_done")
    return
  }

  const project = await prisma.project.findUnique({
    where: { id: job.projectId },
    select: { webhookUrl: true, webhookSecretEncrypted: true },
  })
  if (!project?.webhookUrl) return // 无 webhook 配置，静默跳过

  // 解密 secret
  let secret = ""
  if (project.webhookSecretEncrypted) {
    try {
      secret = decryptToken(project.webhookSecretEncrypted)
    } catch {
      logger.warn({ jobId }, "webhook.secret_decrypt_failed")
    }
  }

  // payload = webhook 元信息 + 完整 job DTO（与 GET /api/v1/jobs/:id 一致）
  const payload = {
    source: "agent-eval-system",
    event: job.status === "completed" ? "job.completed" : "job.failed",
    timestamp: new Date().toISOString(),
    overview_url: `/api/v1/jobs/${job.id}/overview`,
    ...serializeJob(job),
  }

  await deliverWebhook(project.webhookUrl, secret, payload, job.projectId, job.id)
}

/**
 * 投递 webhook：HMAC 签名 + POST + 3 次重试（0s/1s/4s 指数退避）。
 * 失败仅日志（第三方可回退轮询 GET /api/v1/jobs/:id）。
 */
/**
 * 发送测试回调（供前端「测试回调」按钮）：用项目 webhook 配置投递一条测试 payload。
 * 返回投递结果（是否已发送 + URL）。
 */
export async function sendTestWebhook(
  projectId: string,
): Promise<{ sent: boolean; url: string | null }> {
  const prisma = getPrisma()
  const project = await prisma.project.findUnique({
    where: { id: projectId },
    select: { webhookUrl: true, webhookSecretEncrypted: true },
  })
  if (!project?.webhookUrl) return { sent: false, url: null }

  let secret = ""
  if (project.webhookSecretEncrypted) {
    try {
      secret = decryptToken(project.webhookSecretEncrypted)
    } catch {
      /* 解密失败则不签名 */
    }
  }

  await deliverWebhook(project.webhookUrl, secret, {
    source: "agent-eval-system",
    event: "webhook.test",
    project_id: projectId,
    status: "test",
    timestamp: new Date().toISOString(),
    message: "Webhook 测试回调 — 收到此消息说明配置正确。",
  }, projectId, null)
  return { sent: true, url: project.webhookUrl }
}

async function deliverWebhook(
  url: string,
  secret: string,
  payload: Record<string, unknown>,
  projectId: string,
  jobId: string | null,
): Promise<void> {
  const logger = getLogger()
  const prisma = getPrisma()
  const body = JSON.stringify(payload)
  const signature = secret ? signWebhookPayload(body, secret) : ""
  const headers: Record<string, string> = { "Content-Type": "application/json" }
  if (signature) headers["X-Webhook-Signature"] = signature

  const event = String(payload.event ?? "unknown")
  const maxAttempts = 3
  const backoffMs = [0, 1000, 4000]

  // 跟踪最终结果（跨重试，只落一行）
  let finalSuccess = false
  let finalStatusCode: number | null = null
  let finalError: string | null = null
  let finalRespBody: string | null = null
  let finalDurationMs = 0
  let attemptsMade = 0

  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    if (backoffMs[attempt] > 0) await sleep(backoffMs[attempt])
    attemptsMade = attempt + 1
    const t0 = Date.now()
    try {
      const resp = await fetch(url, {
        method: "POST",
        headers,
        body,
        signal: AbortSignal.timeout(10_000),
      })
      finalStatusCode = resp.status
      finalSuccess = resp.ok
      try {
        finalRespBody = (await resp.text()).slice(0, 10240)
      } catch {
        finalRespBody = null
      }
      finalDurationMs = Date.now() - t0
      if (finalSuccess) {
        logger.info({ url, attempt: attemptsMade, status: resp.status }, "webhook.delivered")
        break
      }
      logger.warn({ url, attempt: attemptsMade, status: resp.status }, "webhook.http_error")
    } catch (e) {
      finalError = String(e)
      finalDurationMs = Date.now() - t0
      logger.warn({ url, attempt: attemptsMade, error: finalError }, "webhook.fetch_error")
    }
  }
  if (!finalSuccess) {
    logger.error({ url, job_id: jobId }, "webhook.exhausted")
  }

  // 落库（一次投递一行，含请求体 + 最终响应体 + 重试次数）
  await prisma.webhookDelivery
    .create({
      data: {
        projectId,
        jobId,
        event,
        url,
        attempt: attemptsMade,
        success: finalSuccess,
        statusCode: finalStatusCode,
        error: finalError,
        durationMs: finalDurationMs,
        requestBody: payload as never,
        responseBody: finalRespBody,
      },
    })
    .catch(() => {})
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}
