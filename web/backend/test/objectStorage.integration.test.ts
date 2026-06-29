/**
 * 验证标准 #3 / #4：
 *  - ObjectStorage put/get/head 经 MinIO 验证通过
 *  - presigned PUT 可上传；签名过期后上传失败
 *  - key 布局含 project_id（租户隔离前缀）
 * 依赖：docker compose 起的 minio。
 */

import { createObjectStorage, buildObjectKey, projectIdFromKey } from "../src/infra/objectStorage"
import { loadConfig } from "../src/config"

function uniqueSuffix(): string {
  return `${Date.now()}-${Math.floor(Math.random() * 1e6)}`
}

async function httpPut(url: string, body: string, headers: Record<string, string>) {
  const res = await fetch(url, { method: "PUT", body, headers, redirect: "manual" })
  return { status: res.status, text: await res.text().catch(() => "") }
}
async function httpGet(url: string) {
  const res = await fetch(url, { method: "GET", redirect: "manual" })
  return { status: res.status, text: await res.text().catch(() => "") }
}

describe("ObjectStorage (MinIO)", () => {
  let storage: ReturnType<typeof createObjectStorage>
  beforeAll(() => {
    storage = createObjectStorage(loadConfig())
  })

  it("buildObjectKey embeds project_id and projectIdFromKey extracts it", () => {
    const key = buildObjectKey({
      projectId: "p-123",
      runId: "r-1",
      kind: "screenshot",
      name: "a.png",
    })
    expect(key).toBe("projects/p-123/runs/r-1/artifacts/screenshot/a.png")
    expect(projectIdFromKey(key)).toBe("p-123")
  })

  it("put / get / head round-trips a binary object", async () => {
    const key = `projects/p-${uniqueSuffix()}/runs/r-1/artifacts/output/data.txt`
    const body = Buffer.from("hello-agent-eval-平台")
    const ct = "text/plain; charset=utf-8"

    const put = await storage.put({ key, body, contentType: ct })
    expect(put.size).toBe(body.length)
    expect(put.md5).toMatch(/^[0-9a-f]{32}$/)

    const head = await storage.head({ key })
    expect(head).not.toBeNull()
    expect(head!.size).toBe(body.length)
    expect(head!.contentType).toContain("text/plain")

    const got = await storage.get({ key })
    expect(got.equals(body)).toBe(true)
  })

  it("head returns null for missing object", async () => {
    const head = await storage.head({
      key: `projects/p-${uniqueSuffix()}/runs/r-x/artifacts/output/nope.txt`,
    })
    expect(head).toBeNull()
  })

  it("presigned PUT uploads successfully then is readable via presigned GET", async () => {
    const key = `projects/p-${uniqueSuffix()}/runs/r-2/artifacts/manifest/run.json`
    const body = JSON.stringify({ ok: true })
    const ct = "application/json"

    const presigned = await storage.presignPut({ key, contentType: ct, ttlSec: 60 })
    expect(presigned.method).toBe("PUT")
    expect(presigned.headers["Content-Type"]).toBe(ct)
    expect(presigned.expiresAt).toBeGreaterThan(0)

    const up = await httpPut(presigned.url, body, { "Content-Type": ct })
    expect(up.status).toBe(200)

    const head = await storage.head({ key })
    expect(head!.size).toBe(Buffer.byteLength(body))

    const g = await storage.presignGet({ key, ttlSec: 60 })
    const down = await httpGet(g.url)
    expect(down.status).toBe(200)
    expect(down.text).toBe(body)
  })

  it("presigned PUT fails after signature expiry (verify #4)", async () => {
    const key = `projects/p-${uniqueSuffix()}/runs/r-3/artifacts/output/expired.txt`
    const ct = "text/plain"

    // 先确认未过期可成功（证明 URL 本身有效）
    const presigned = await storage.presignPut({ key, contentType: ct, ttlSec: 1 })
    const ok = await httpPut(presigned.url, "v1", { "Content-Type": ct })
    expect([200, 204]).toContain(ok.status)

    // 重新签一个 1s 的，等待过期后再上传
    const expiring = await storage.presignPut({ key, contentType: ct, ttlSec: 1 })
    await new Promise((r) => setTimeout(r, 2500))

    const expired = await httpPut(expiring.url, "should-fail", { "Content-Type": ct })
    // 过期签名：S3 返回 403 Forbidden
    expect(expired.status).toBe(403)
  })
})
