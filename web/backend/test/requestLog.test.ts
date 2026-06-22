/**
 * 验证标准 #5：结构化日志中间件记录 HTTP 请求并维护计数。
 * 断言 requestCounters 在请求完成后递增、按状态码分桶；next() 被调用。
 */

import { requestLog, requestCounters, getLogger } from "../src/infra/logger"
import type { Request, Response } from "express"

function mockRes(statusCode?: number) {
  const handlers: Record<string, () => void> = {}
  const res = {
    statusCode: statusCode || 200,
    on(ev: string, fn: () => void) {
      handlers[ev] = fn
      return res
    },
    emit(ev: string) {
      if (handlers[ev]) handlers[ev]()
    },
  }
  return res
}

describe("requestLog middleware", () => {
  beforeEach(() => {
    requestCounters.total = 0
    requestCounters.byStatus = {}
  })

  it("calls next() and records the request + status bucket on finish", () => {
    const req = {
      method: "GET",
      path: "/health",
      ip: "127.0.0.1",
      get: () => "test-agent",
    } as unknown as Request
    const res = mockRes(200) as unknown as Response
    let nextCalled = false
    requestLog(req, res, () => {
      nextCalled = true
    })
    res.emit("finish")

    expect(nextCalled).toBe(true)
    expect(requestCounters.total).toBe(1)
    expect(requestCounters.byStatus["2xx"]).toBe(1)
  })

  it("buckets 5xx and 4xx separately", () => {
    for (const code of [500, 503]) {
      const res = mockRes(code) as unknown as Response
      requestLog(
        { method: "POST", path: "/x", ip: "1.1.1.1", get: () => "" } as unknown as Request,
        res,
        () => {},
      )
      res.emit("finish")
    }
    const r404 = mockRes(404) as unknown as Response
    requestLog(
      { method: "GET", path: "/y", ip: "1.1.1.1", get: () => "" } as unknown as Request,
      r404,
      () => {},
    )
    r404.emit("finish")

    expect(requestCounters.total).toBe(3)
    expect(requestCounters.byStatus["5xx"]).toBe(2)
    expect(requestCounters.byStatus["4xx"]).toBe(1)
  })

  it("structured logger is available and emits without throwing", () => {
    const log = getLogger()
    expect(typeof log.info).toBe("function")
    expect(() => log.info({ k: 1 }, "smoke")).not.toThrow()
  })
})
