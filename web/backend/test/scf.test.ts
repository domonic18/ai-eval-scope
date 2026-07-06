/**
 * scf 客户端单测 — mock fetch，断言 TC3-HMAC-SHA256 调用形态与事件体。
 */

import { describe, expect, it, vi, beforeEach } from "vitest"

vi.mock("../src/config", () => ({
  getConfig: () => ({
    tencentSecretId: "test-secret-id",
    tencentSecretKey: "test-secret-key",
    scfRegion: "ap-guangzhou",
    scfNamespace: "test-ns",
    scfExecutorFunctionName: "agent-eval-executor",
  }),
}))

import { invokeScf } from "../src/infra/scf"

const PAYLOAD = {
  job_id: "job-1",
  rule_set_id: "coursework-quality",
  input_kind: "upload",
  scope: "single",
  input_object_key: "projects/p/eval/jobs/job-1/input.md",
  input_presigned_url: "http://presigned",
}

describe("invokeScf", () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it("POSTs Event invoke to scf.<region>.tencentcloudapi.com and returns RequestId", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue({ json: async () => ({ Response: { RequestId: "rid-1" } }) } as Response)

    const r = await invokeScf(PAYLOAD)
    expect(r.RequestId).toBe("rid-1")
    expect(fetchMock).toHaveBeenCalledOnce()

    const [url, init] = fetchMock.mock.calls[0]!
    expect(url).toBe("https://scf.ap-guangzhou.tencentcloudapi.com")
    const headers = (init as RequestInit).headers as Record<string, string>
    expect(headers["X-TC-Action"]).toBe("Invoke")
    expect(headers["X-TC-Version"]).toBe("2018-04-16")
    expect(headers["X-TC-Region"]).toBe("ap-guangzhou")
    expect(headers["Authorization"]).toMatch(/^TC3-HMAC-SHA256 Credential=test-secret-id\//)

    const body = JSON.parse((init as RequestInit).body as string)
    expect(body.FunctionName).toBe("agent-eval-executor")
    expect(body.Namespace).toBe("test-ns")
    expect(body.InvocationType).toBe("Event")
    expect(JSON.parse(body.ClientContext).job_id).toBe("job-1")
  })

  it("throws on SCF Error response", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      json: async () => ({ Response: { Error: { Message: "Function not found" } } }),
    } as Response)
    await expect(invokeScf(PAYLOAD)).rejects.toThrow(/Function not found/)
  })
})
