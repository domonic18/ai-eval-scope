/**
 * 结构化日志（pino）。
 * - 生产：单行 JSON（便于 ELK/Loki 采集）。
 * - 开发：pretty-print（pino-pretty，devDep）。
 * - 导出 logger 实例 + requestLog 中间件（每请求输出 method/path/status/duration）。
 */

import pino, { type Logger } from "pino";
import type { Request, Response } from "express";
import { getConfig } from "../config";

function buildLogger(): Logger {
  const cfg = getConfig();
  const isDev = cfg.nodeEnv !== "production";
  if (isDev) {
    return pino(
      {
        level: cfg.logLevel,
        transport: {
          target: "pino-pretty",
          options: { colorize: true, translateTime: "SYS:HH:MM:ss.l" },
        },
      },
      pino.destination({ sync: false })
    );
  }
  return pino({ level: cfg.logLevel }, pino.destination({ sync: false }));
}

let _logger: Logger | null = null;

export function getLogger(): Logger {
  if (!_logger) _logger = buildLogger();
  return _logger;
}

/** 请求计数器（进程内）：用于结构化日志中的累计指标输出。 */
export const requestCounters: { total: number; byStatus: Record<string, number> } = {
  total: 0,
  byStatus: {},
};

/** 结构化请求日志中间件：记录 method/path/status/duration_ms 并维护进程级计数器。 */
export function requestLog(req: Request, res: Response, next: () => void): void {
  const logger = getLogger();
  const start = process.hrtime.bigint();
  requestCounters.total += 1;

  res.on("finish", () => {
    const durationNs = process.hrtime.bigint() - start;
    const durationMs = Number(durationNs) / 1e6;
    const bucket = `${Math.floor(res.statusCode / 100)}xx`;
    requestCounters.byStatus[bucket] = (requestCounters.byStatus[bucket] || 0) + 1;
    logger.info(
      {
        method: req.method,
        path: req.path,
        status: res.statusCode,
        duration_ms: Math.round(durationMs * 100) / 100,
        ip: req.ip,
        ua: req.get("user-agent"),
        counters: {
          total: requestCounters.total,
          by_status: requestCounters.byStatus,
        },
      },
      "http_request"
    );
  });
  next();
}

/** 优雅关闭：flush 异步日志。 */
export async function flushLogs(): Promise<void> {
  if (_logger && typeof (_logger as pino.Logger).flush === "function") {
    await new Promise<void>((resolve) =>
      (_logger as pino.Logger).flush(() => resolve())
    );
  }
}
