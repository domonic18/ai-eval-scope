/**
 * 制品 raw 代理端点单测（不连 DB/COS）：
 *  token 鉴权（缺失/无效/过期/aid 错配）、access token 不可复用、
 *  合法 token → 200 且强制 inline + text/html 响应头、对象不存在 → 404。
 */

import { vi } from "vitest"
import request from "supertest"
import jwt from "jsonwebtoken"
import { createApp } from "../src/server"
import { issueArtifactToken, issueTokenPair } from "../src/infra/crypto"
import { getConfig } from "../src/config"

const { storageGet, storagePresignGet } = vi.hoisted(() => ({
  storageGet: vi.fn(),
  storagePresignGet: vi.fn(),
}))

vi.mock("../src/infra/objectStorage", async (importActual) => {
  const actual = await importActual<typeof import("../src/infra/objectStorage")>()
  return {
    ...actual,
    getObjectStorage: () => ({ get: storageGet, presignGet: storagePresignGet }),
  }
})

const app = createApp()

const ART = "00000000-0000-4000-8000-000000000001"
const KEY = "projects/p/runs/r/artifacts/output/x.html"

beforeEach(() => {
  storageGet.mockReset()
  storagePresignGet.mockReset()
})

function tok(over: { aid?: string; ct?: string; name?: string } = {}): string {
  return issueArtifactToken({
    artifactId: over.aid ?? ART,
    objectKey: KEY,
    contentType: over.ct ?? "text/html",
    filename: over.name ?? "x.html",
  })
}

describe("GET /api/v1/artifacts/:id/raw", () => {
  it("缺失 token → 401", async () => {
    const r = await request(app).get(`/api/v1/artifacts/${ART}/raw`)
    expect(r.status).toBe(401)
  })

  it("无效 token → 401", async () => {
    const r = await request(app).get(`/api/v1/artifacts/${ART}/raw?token=garbage`)
    expect(r.status).toBe(401)
  })

  it("过期 token → 401", async () => {
    const expired = jwt.sign(
      {
        kind: "artifact",
        aid: ART,
        key: KEY,
        ct: "text/html",
        name: "x.html",
        exp: Math.floor(Date.now() / 1000) - 60,
      },
      getConfig().jwtSecret,
    )
    const r = await request(app).get(`/api/v1/artifacts/${ART}/raw?token=${expired}`)
    expect(r.status).toBe(401)
  })

  it("access token（kind=access）不可用于 raw → 401", async () => {
    const pair = issueTokenPair({ userId: "u1", orgId: "o1", role: "owner" })
    const r = await request(app).get(`/api/v1/artifacts/${ART}/raw?token=${pair.access_token}`)
    expect(r.status).toBe(401)
  })

  it("token aid 与路径不匹配 → 403", async () => {
    const r = await request(app).get(`/api/v1/artifacts/${ART}/raw?token=${tok({ aid: "other" })}`)
    expect(r.status).toBe(403)
  })

  it("对象不存在 → 404", async () => {
    storageGet.mockRejectedValueOnce({ name: "NoSuchKey" })
    const r = await request(app).get(`/api/v1/artifacts/${ART}/raw?token=${tok()}`)
    expect(r.status).toBe(404)
  })

  it("合法 html token → 200，强制 text/html;charset=utf-8 + inline + nosniff", async () => {
    storageGet.mockResolvedValueOnce(Buffer.from("<html>hi</html>"))
    const r = await request(app).get(`/api/v1/artifacts/${ART}/raw?token=${tok()}`)
    expect(r.status).toBe(200)
    expect(r.headers["content-type"]).toBe("text/html; charset=utf-8")
    expect(r.headers["content-disposition"]).toBe("inline")
    expect(r.headers["x-content-type-options"]).toBe("nosniff")
    expect(r.text).toBe("<html>hi</html>")
  })

  it("非 html（json）→ 按记录 contentType 回吐 + inline", async () => {
    storageGet.mockResolvedValueOnce(Buffer.from('{"a":1}'))
    const token = tok({ ct: "application/json", name: "x.json" })
    const r = await request(app).get(`/api/v1/artifacts/${ART}/raw?token=${token}`)
    expect(r.status).toBe(200)
    expect(r.headers["content-type"]).toBe("application/json")
    expect(r.headers["content-disposition"]).toBe("inline")
  })
})
