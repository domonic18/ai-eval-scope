/**
 * 错误处理中间件：PlatformError 映射、脱敏、404 兜底。
 */

import {
  PlatformError,
  errorHandler,
  notFound,
  maskSecret,
} from "../src/middleware/errorHandler";
import type { Request, Response } from "express";

function mockRes() {
  const res: { statusCode: number; body: unknown; status: (c: number) => typeof res; json: (b: unknown) => typeof res } = {
    statusCode: 200,
    body: null,
    status(code) {
      this.statusCode = code;
      return this;
    },
    json(b) {
      this.body = b;
      return this;
    },
  };
  return res;
}
const noopReq = { method: "POST", path: "/x", get: () => null } as unknown as Request;

describe("errorHandler", () => {
  it("PlatformError carries status + code", () => {
    const e = new PlatformError("boom", { status: 409, code: "DEPENDENCY_MISSING" });
    expect(e.status).toBe(409);
    expect(e.code).toBe("DEPENDENCY_MISSING");
    expect(e.message).toBe("boom");
  });

  it("renders code + error body and status", () => {
    const res = mockRes();
    const err = new PlatformError("auth bad", { status: 401, code: "AUTH_INVALID" });
    errorHandler(err, noopReq, res as unknown as Response, () => {});
    expect(res.statusCode).toBe(401);
    expect((res.body as { code: string }).code).toBe("AUTH_INVALID");
    expect((res.body as { error: string }).error).toBe("auth bad");
  });

  it("defaults unknown errors to 500 INTERNAL", () => {
    const res = mockRes();
    errorHandler(new Error("oops"), noopReq, res as unknown as Response, () => {});
    expect(res.statusCode).toBe(500);
    expect((res.body as { code: string }).code).toBe("INTERNAL");
  });

  it("notFound returns 404 JSON with path", () => {
    const res = mockRes();
    notFound({ method: "GET", path: "/api/nope" } as unknown as Request, res as unknown as Response, () => {});
    expect(res.statusCode).toBe(404);
    expect((res.body as { code: string }).code).toBe("NOT_FOUND");
    expect((res.body as { path: string }).path).toBe("/api/nope");
  });

  it("maskSecret masks public keys and emails", () => {
    expect(maskSecret("pk-eval-abcd1234efgh")).toBe("pk-eval-**");
    expect(maskSecret("alice@example.com")).toBe("a**@example.com");
  });
});
