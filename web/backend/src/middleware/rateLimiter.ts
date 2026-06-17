/**
 * 限流中间件（§7.4）。按 api_key 维度令牌桶；超限 429 + Retry-After。
 * 进程内内存桶（单实例够用；多实例需换 Redis 后端，远期）。
 */

import type { RequestHandler } from "express";
import { getConfig } from "../config";

interface Bucket {
  tokens: number;
  ts: number;
}

export function rateLimiter(opts?: { capacity?: number; ratePerSec?: number }): RequestHandler {
  const cfg = getConfig();
  const capacity = opts?.capacity ?? cfg.ingestRateLimit; // 桶容量（= 每分钟配额）
  const ratePerSec = opts?.ratePerSec ?? cfg.ingestRateLimit / 60;
  const buckets = new Map<string, Bucket>();

  return (req, res, next) => {
    const key = req.tenant?.apiKeyId || req.ip || "anon";
    const now = Date.now();
    let b = buckets.get(key);
    if (!b) {
      b = { tokens: capacity, ts: now };
      buckets.set(key, b);
    }
    // 按时间补充令牌
    const elapsedSec = (now - b.ts) / 1000;
    b.tokens = Math.min(capacity, b.tokens + elapsedSec * ratePerSec);
    b.ts = now;

    if (b.tokens < 1) {
      const retryAfter = Math.max(1, Math.ceil((1 - b.tokens) / ratePerSec));
      res.set("Retry-After", String(retryAfter));
      return res.status(429).json({ error: "rate limited", code: "RATE_LIMITED" });
    }
    b.tokens -= 1;
    next();
  };
}
