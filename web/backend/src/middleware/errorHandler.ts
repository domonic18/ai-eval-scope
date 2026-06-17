/**
 * 统一错误处理（§三 errorHandler）。
 *
 * 约定：业务层抛出 / next(err) 的错误携带 `code`（§7.5 错误码）与 `status`（HTTP）。
 * 该中间件统一兜底，输出结构化错误体，并对敏感字段（key、邮箱）脱敏（§十三）。
 */

import type { ErrorRequestHandler, RequestHandler } from "express";
import { getLogger } from "../infra/logger";

const DEFAULT_STATUS = 500;
const DEFAULT_CODE = "INTERNAL";

export interface PlatformErrorOptions {
  status?: number;
  code?: string;
  details?: unknown;
}

/** 构造平台错误对象。 */
export class PlatformError extends Error {
  status: number;
  code: string;
  details?: unknown;

  constructor(message: string, opts: PlatformErrorOptions = {}) {
    super(message);
    this.name = "PlatformError";
    this.status = opts.status || DEFAULT_STATUS;
    this.code = opts.code || DEFAULT_CODE;
    if (opts.details) this.details = opts.details;
  }
}

/** 脱敏：pk-eval-xxxx → pk-eval-xx**；邮箱 a@b.com → a**@b.com */
export function maskSecret(str: string): string {
  if (!str || typeof str !== "string") return str;
  if (str.startsWith("pk-")) {
    return str.length > 8 ? str.slice(0, 8) + "**" : "**";
  }
  if (str.includes("@")) {
    const [name, domain] = str.split("@");
    return `${name!.slice(0, 1)}**@${domain}`;
  }
  return str.length > 4 ? str.slice(0, 2) + "**" : "**";
}

export const errorHandler: ErrorRequestHandler = (err, req, res, _next) => {
  const logger = getLogger();
  const status = (err as PlatformError).status || DEFAULT_STATUS;
  const code = (err as PlatformError).code || DEFAULT_CODE;

  const logFn = status >= 500 ? "error" : "warn";
  logger[logFn](
    {
      code,
      status,
      method: req.method,
      path: req.path,
      message: err.message,
      stack: status >= 500 ? err.stack : undefined,
    },
    "request_failed"
  );

  const body: { error: string; code: string; details?: unknown; hint?: string } = {
    error: err.message || "Internal server error",
    code,
  };
  if ((err as PlatformError).details) body.details = (err as PlatformError).details;
  if (req.get("authorization")) body.hint = "auth header present";

  res.status(status).json(body);
};

/** 404 兜底（未知路由），避免暴露存在性差异。 */
export const notFound: RequestHandler = (req, res) => {
  res.status(404).json({ error: "Not found", code: "NOT_FOUND", path: req.path });
};
