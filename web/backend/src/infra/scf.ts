/**
 * 腾讯云 SCF Invoke 客户端（异步触发 executor 事件函数）。
 *
 * 手写 TC3-HMAC-SHA256 签名调用 `scf.<region>.tencentcloudapi.com`，`InvocationType=Event`
 * 异步触发（fire-and-forget），Web 立即返回 jobId。参考 SasanLens backend/src/tencentcloud.js。
 *
 * executor 是「事件函数 + Job 镜像 + 异步执行」（docs/arch/14），事件经
 * SCF_CUSTOM_CONTAINER_EVENT 注入。
 */

import crypto from "crypto"
import { getConfig } from "../config"

/** 传给 executor 的 ClientContext 载荷（经 SCF 事件注入）。 */
export interface ScfInvokePayload {
  job_id: string
  rule_set_id: string
  input_kind: string
  scope: string
  input_object_key: string
  input_presigned_url: string
  task_id?: string
  task_title?: string
  task_subject?: string
}

export interface ScfInvokeResult {
  RequestId?: string
}

function sha256Hex(data: string): string {
  return crypto.createHash("sha256").update(data).digest("hex")
}

function hmacSha256(key: Buffer | string, data: string): Buffer {
  return crypto.createHmac("sha256", key).update(data).digest()
}

function hmacSha256Hex(key: Buffer | string, data: string): string {
  return crypto.createHmac("sha256", key).update(data).digest("hex")
}

/** 异步调用 SCF executor 函数（Event）。仅返回 RequestId，不等待执行结果。 */
export async function invokeScf(clientContext: ScfInvokePayload): Promise<ScfInvokeResult> {
  const cfg = getConfig()
  const secretId = cfg.tencentSecretId
  const secretKey = cfg.tencentSecretKey
  if (!secretId || !secretKey) {
    throw new Error("TENCENT_SECRET_ID / TENCENT_SECRET_KEY not configured")
  }

  const region = cfg.scfRegion
  const host = `scf.${region}.tencentcloudapi.com`
  const service = "scf"
  const action = "Invoke"
  const version = "2018-04-16"
  const timestamp = Math.floor(Date.now() / 1000)
  const date = new Date(timestamp * 1000).toISOString().slice(0, 10)

  const payload = JSON.stringify({
    FunctionName: cfg.scfExecutorFunctionName,
    Namespace: cfg.scfNamespace,
    InvocationType: "Event",
    ClientContext: JSON.stringify(clientContext),
  })

  const hashedPayload = sha256Hex(payload)
  const canonicalHeaders = `content-type:application/json\nhost:${host}\nx-tc-action:${action.toLowerCase()}\n`
  const signedHeaders = "content-type;host;x-tc-action"
  const canonicalRequest = ["POST", "/", "", canonicalHeaders, signedHeaders, hashedPayload].join(
    "\n",
  )

  const algorithm = "TC3-HMAC-SHA256"
  const credentialScope = `${date}/${service}/tc3_request`
  const stringToSign = [
    algorithm,
    timestamp.toString(),
    credentialScope,
    sha256Hex(canonicalRequest),
  ].join("\n")

  const secretDate = hmacSha256(`TC3${secretKey}`, date)
  const secretService = hmacSha256(secretDate, service)
  const secretSigning = hmacSha256(secretService, "tc3_request")
  const signature = hmacSha256Hex(secretSigning, stringToSign)

  const authorization = `${algorithm} Credential=${secretId}/${credentialScope}, SignedHeaders=${signedHeaders}, Signature=${signature}`

  const res = await fetch(`https://${host}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Host: host,
      "X-TC-Action": action,
      "X-TC-Version": version,
      "X-TC-Timestamp": timestamp.toString(),
      "X-TC-Region": region,
      Authorization: authorization,
    },
    body: payload,
  })

  const json = (await res.json()) as {
    Response?: { Error?: { Message: string }; RequestId?: string }
  }
  if (json.Response?.Error) {
    throw new Error(`SCF Invoke failed: ${json.Response.Error.Message}`)
  }
  return { RequestId: json.Response?.RequestId }
}
