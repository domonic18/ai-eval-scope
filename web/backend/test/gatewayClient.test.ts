/**
 * gatewayClient 单元测试（不联网、不依赖 DB）。
 *
 * 核心验证：HMAC 签名 = signHmac(secret, METHOD, PATH, rawBodyBytes)，与
 * scripts/sim_courseware_package_gateway.py、gateway/auth/crypto.py 同算法；
 * multipart body 结构合法（含 rule_set_id 字段 + file 字段）；
 * 上游非 2xx → 抛 PlatformError(502)。
 */

import { describe, it, expect, beforeEach, vi } from "vitest"
import { getJob, submitJob } from "../src/infra/gatewayClient"
import { signHmac } from "../src/infra/crypto"
import { PlatformError } from "../src/middleware/errorHandler"

const BASE = "http://gw.test"
const PK = "pk-eval-deadbeef"
const SECRET = "sk-eval-secretvalue"

let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  fetchMock = vi.fn()
  vi.stubGlobal("fetch", fetchMock)
})

function jsonResponse(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
  }
}

describe("gatewayClient.submitJob", () => {
  it("构造合法 multipart + 正确 HMAC 签名（与 signHmac 一致）", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ job_id: "j1", status: "queued", poll_url: "/v1/jobs/j1" }))

    const fileBytes = Buffer.from("<html>hi</html>")
    const result = await submitJob({
      baseUrl: BASE,
      publicKey: PK,
      secret: SECRET,
      filename: "lesson.html",
      fileBytes,
      ruleSetId: "coursework-default",
    })

    // 调用契约
    expect(fetchMock).toHaveBeenCalledOnce()
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe(`${BASE}/v1/jobs`)
    expect(opts.method).toBe("POST")

    // Content-Type 含 multipart + boundary
    const ct: string = opts.headers["Content-Type"]
    expect(ct.startsWith("multipart/form-data; boundary=")).toBe(true)

    // 签名：Authorization: Eval <pk>:<sig>，sig = signHmac over 原始 body 字节
    const sentBody = opts.body as Buffer
    const expectedSig = signHmac(SECRET, "POST", "/v1/jobs", sentBody)
    expect(opts.headers["Authorization"]).toBe(`Eval ${PK}:${expectedSig}`)

    // multipart 结构：含 rule_set_id 字段值 + filename + 文件内容
    const text = sentBody.toString("binary")
    expect(text).toContain('name="rule_set_id"')
    expect(text).toContain("coursework-default")
    expect(text).toContain('filename="lesson.html"')
    expect(text).toContain("<html>hi</html>")

    // 返回值透传
    expect(result).toEqual({ job_id: "j1", status: "queued", poll_url: "/v1/jobs/j1" })
  })

  it("上游非 2xx → 抛 PlatformError(502, GATEWAY_UPSTREAM)", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ error: "bad" }, 500))
    await expect(
      submitJob({
        baseUrl: BASE,
        publicKey: PK,
        secret: SECRET,
        filename: "a.zip",
        fileBytes: Buffer.from("PK"),
        ruleSetId: "format-only",
      }),
    ).rejects.toMatchObject({ status: 502, code: "GATEWAY_UPSTREAM" })
  })
})

describe("gatewayClient.getJob", () => {
  it("GET 无 body，签名 sha256(b'')，透传 JobResponse", async () => {
    const job = { job_id: "j1", status: "completed", run_id: "20260630", web_run_url: "http://x/run/20260630" }
    fetchMock.mockResolvedValue(jsonResponse(job))

    const result = await getJob(BASE, PK, SECRET, "j1")

    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe(`${BASE}/v1/jobs/j1`)
    expect(opts.method).toBe("GET")
    // GET 签名：body 为空
    const expectedSig = signHmac(SECRET, "GET", "/v1/jobs/j1")
    expect(opts.headers["Authorization"]).toBe(`Eval ${PK}:${expectedSig}`)
    expect(result).toEqual(job)
  })

  it("上游 404 → 抛 PlatformError(502)", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ error: "job not found" }, 404))
    await expect(getJob(BASE, PK, SECRET, "missing")).rejects.toBeInstanceOf(PlatformError)
  })
})
