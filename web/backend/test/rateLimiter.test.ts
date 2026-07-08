/**
 * rateLimiter 单测（§7.4 / docs/arch/12 §6.5）：
 *  - 容量内放行
 *  - 超限 → 429 + 规范错误体 {error, code: RATE_LIMITED}（经 errorHandler）+ Retry-After 头
 */
import express from "express"
import request from "supertest"
import { describe, it, expect } from "vitest"
import { rateLimiter } from "../src/middleware/rateLimiter"
import { errorHandler } from "../src/middleware/errorHandler"

function appWithLimiter(capacity: number, ratePerSec: number) {
  const a = express()
  a.get("/", rateLimiter({ capacity, ratePerSec }), (_req, res) => res.json({ ok: true }))
  a.use(errorHandler)
  return a
}

describe("rateLimiter", () => {
  it("容量内放行；超限 → 429 RATE_LIMITED 规范体 + Retry-After", async () => {
    const a = appWithLimiter(1, 0.001) // 容量 1，回充极慢
    const r1 = await request(a).get("/")
    expect(r1.status).toBe(200)
    expect(r1.body).toEqual({ ok: true })

    const r2 = await request(a).get("/")
    expect(r2.status).toBe(429)
    expect(r2.body.code).toBe("RATE_LIMITED")
    expect(typeof r2.body.error).toBe("string")
    expect(r2.body.error.length).toBeGreaterThan(0)
    expect(r2.headers["retry-after"]).toMatch(/^\d+$/)
  })

  it("令牌回充后恢复放行", async () => {
    const a = appWithLimiter(1, 1000) // 回充极快，几乎不会限流
    await request(a).get("/")
    const r2 = await request(a).get("/")
    expect(r2.status).toBe(200)
  })
})
