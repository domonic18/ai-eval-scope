/** Webhook 签名工具 — HMAC-SHA256（Stripe/GitHub 范式）。 */

import crypto from "crypto"

/**
 * 对 webhook payload 做 HMAC-SHA256 签名。
 *
 * @param payload JSON 序列化后的 payload 字符串
 * @param secret  项目的 webhook secret（明文，已从加密态解密）
 * @returns 签名头值，格式 `sha256=<hex>`
 */
export function signWebhookPayload(payload: string, secret: string): string {
  return `sha256=${crypto.createHmac("sha256", secret).update(payload, "utf8").digest("hex")}`
}
