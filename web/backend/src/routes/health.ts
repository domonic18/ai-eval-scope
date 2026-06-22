/**
 * 健康检查（§12.4）。
 *
 * GET /health | GET /api/health
 * → { status, schema_version, components: { db, object_storage } }
 *
 * - 任一关键组件不可用 → HTTP 503（供 docker/k8s readiness 探针判定）。
 * - 全部 ok → HTTP 200。
 * - 组件探测各自捕获异常，互不短路（便于定位）。
 */

import { Router, type RequestHandler } from "express"
import { ping as dbPing } from "../infra/prisma"
import { getObjectStorage } from "../infra/objectStorage"
import { getConfig } from "../config"

const router = Router()

const healthHandler: RequestHandler = async (_req, res) => {
  const cfg = getConfig()
  const [db, objectStorage] = await Promise.all([dbPing(), safeStoragePing()])

  const components = { db, object_storage: objectStorage }
  const allOk = components.db.ok && components.object_storage.ok
  const status = allOk ? "ok" : components.db.ok ? "degraded" : "down"

  res.status(allOk ? 200 : 503).json({
    status,
    schema_version: cfg.schemaVersion,
    components,
    timestamp: new Date().toISOString(),
  })
}

async function safeStoragePing(): Promise<{ ok: boolean; bucket?: string; error?: string }> {
  try {
    const storage = getObjectStorage()
    return await storage.ping()
  } catch (err) {
    return { ok: false, error: (err as Error).message }
  }
}

router.get("/health", healthHandler)
router.get("/api/health", healthHandler)

export default router
