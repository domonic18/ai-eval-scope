/**
 * gatewayClient 单元测试（不联网、不依赖 DB）。
 *
 * 核心验证：Bearer 鉴权头 `Authorization: Bearer <token>`；multipart body 结构合法
 * （含 rule_set_id 字段 + file 字段）；上游非 2xx → 抛 PlatformError(502)。
 */

import { describe, it, expect, beforeEach, vi } from "vitest"
import { getJob, submitJob } from "../src/infra/gatewayClient"
import { PlatformError } from "../src/middleware/errorHandler"

const BASE = "http://gw.test"
const TOKEN = "eval-deadbeefsecret"

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
  it("构造合法 multipart + Bearer 鉴权头", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ job_id: "j1", status: "queued", poll_url: "/v1/jobs/j1" }))

    const fileBytes = Buffer.from("<html>hi</html>")
    const result = await submitJob({
      baseUrl: BASE,
      token: TOKEN,
      filename: "lesson.html",
      fileBytes,
      ruleSetId: "coursework-default",
    })

    expect(fetchMock).toHaveBeenCalledOnce()
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe(`${BASE}/v1/jobs`)
    expect(opts.method).toBe("POST")

    const ct: string = opts.headers["Content-Type"]
    expect(ct.startsWith("multipart/form-data; boundary=")).toBe(true)

    // Bearer 鉴权头
    expect(opts.headers["Authorization"]).toBe(`Bearer ${TOKEN}`)

    // multipart 结构：含 rule_set_id 字段值 + filename + 文件内容
    const sentBody = opts.body as Buffer
    const text = sentBody.toString("binary")
    expect(text).toContain('name="rule_set_id"')
    expect(text).toContain("coursework-default")
    expect(text).toContain('filename="lesson.html"')
    expect(text).toContain("<html>hi</html>")

    expect(result).toEqual({ job_id: "j1", status: "queued", poll_url: "/v1/jobs/j1" })
  })

  it("上游非 2xx → 抛 PlatformError(502, GATEWAY_UPSTREAM)", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ error: "bad" }, 500))
    await expect(
      submitJob({
        baseUrl: BASE,
        token: TOKEN,
        filename: "a.zip",
        fileBytes: Buffer.from("PK"),
        ruleSetId: "format-only",
      }),
    ).rejects.toMatchObject({ status: 502, code: "GATEWAY_UPSTREAM" })
  })
})

describe("gatewayClient.getJob", () => {
  it("GET 带 Bearer，透传 JobResponse", async () => {
    const job = { job_id: "j1", status: "completed", run_id: "20260630", web_run_url: "http://x/run/20260630" }
    fetchMock.mockResolvedValue(jsonResponse(job))

    const result = await getJob(BASE, TOKEN, "j1")

    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe(`${BASE}/v1/jobs/j1`)
    expect(opts.method).toBe("GET")
    expect(opts.headers["Authorization"]).toBe(`Bearer ${TOKEN}`)
    expect(result).toEqual(job)
  })

  it("上游 404 → 抛 PlatformError(502)", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ error: "job not found" }, 404))
    await expect(getJob(BASE, TOKEN, "missing")).rejects.toBeInstanceOf(PlatformError)
  })
})
