/**
 * PrismaClient 单例（§三 infra/prisma）。
 *
 * - 全局单例，避免热重载 / serverless 复用进程时实例泄漏。
 * - serverless 经 PgBouncer（transaction 模式）时，连接串带
 *   ?pgbouncer=true&connection_limit=1，Prisma 在该模式下可正常工作（§4.4）。
 */

import { PrismaClient } from "@prisma/client";

const globalForPrisma = globalThis as unknown as {
  __PRISMA_CLIENT__?: PrismaClient;
};

let _client: PrismaClient | null = null;

/** 获取 PrismaClient 单例。 */
export function getPrisma(): PrismaClient {
  if (_client) return _client;
  if (globalForPrisma.__PRISMA_CLIENT__) return globalForPrisma.__PRISMA_CLIENT__;
  _client = new PrismaClient({
    log: process.env.PRISMA_LOG === "1" ? (["warn", "error"] as const) : (["error"] as const),
  });
  globalForPrisma.__PRISMA_CLIENT__ = _client;
  return _client;
}

export interface DbPingResult {
  ok: boolean;
  latency_ms?: number;
  error?: string;
}

/** DB 连通性探测（/health 用）。 */
export async function ping(): Promise<DbPingResult> {
  const start = process.hrtime.bigint();
  try {
    const client = getPrisma();
    await client.$queryRaw`SELECT 1`;
    const latencyMs = Number(process.hrtime.bigint() - start) / 1e6;
    return { ok: true, latency_ms: Math.round(latencyMs * 100) / 100 };
  } catch (err) {
    return { ok: false, error: (err as Error).message };
  }
}

export async function disconnect(): Promise<void> {
  if (_client) {
    await _client.$disconnect();
    _client = null;
    globalForPrisma.__PRISMA_CLIENT__ = undefined;
  }
}
