/**
 * 超级管理员后台路由（/api/v1/admin）—— 全部 requireAuth + platformAdminGuard（DB 鉴权）。
 * 跨租户管理：用户 / 工作组 / 项目 / 评估任务 / 产出物 / 审计 / 统计。
 * 参照 SquadSight 控制台的 IA；复用现有设计系统组件在前端实现。
 */
import { Router, type Request } from "express"
import { requireAuth } from "../middleware/auth"
import { platformAdminGuard } from "../middleware/adminGuard"
import { PlatformError } from "../middleware/errorHandler"
import { wrap } from "../middleware/wrap"
import { hashPassword } from "../infra/crypto"
import { adminRepository } from "../repositories/admin.repository"
import { adminStatsRepository } from "../repositories/adminStats.repository"
import { llmModelRepository, type LlmModelInput } from "../repositories/llm-model.repository"
import { llmClientService } from "../services/llm-client.service"
import { AuditService } from "../services/audit.service"
import { getLogger } from "../infra/logger"
import { getObjectStorage } from "../infra/objectStorage"
import { getPrisma } from "../infra/prisma"

const router = Router()
// 全部 admin 接口：登录 + 平台超管（DB 鉴权，即时反映 role/status 变更）
router.use(requireAuth, platformAdminGuard)

const num = (v: unknown, d: number) => {
  const n = Number(v)
  return Number.isFinite(n) ? n : d
}
const audit = (req: Request, action: string, targetId: string, metadata?: Record<string, unknown>) =>
  AuditService.log({
    orgId: null,
    actorUserId: req.user!.userId,
    action,
    targetType: "platform",
    targetId,
    metadata: metadata as never,
  }).catch(() => undefined)

/** 对象存储 best-effort 清理：失败仅 warn（DB 已删、走势以 DB 为准）。 */
async function cleanupObjects(keys: string[], label: string) {
  if (!keys.length) return
  try {
    await getObjectStorage().deleteObjects(keys)
  } catch (err) {
    getLogger().warn(
      { label, count: keys.length, error: (err as Error).message },
      "admin_delete_objects_failed",
    )
  }
}

/* ── 统计 ───────────────────────────────────────────── */
router.get(
  "/stats/overview",
  wrap(async (_req, res) => res.json(await adminStatsRepository.overview())),
)
router.get(
  "/stats/trends",
  wrap(async (req, res) =>
    res.json(
      await adminStatsRepository.trends({
        limit: num(req.query.limit, 100),
        from: req.query.from ? new Date(String(req.query.from)) : undefined,
      }),
    ),
  ),
)
router.get(
  "/stats/score-distribution",
  wrap(async (_req, res) => res.json(await adminStatsRepository.scoreDistribution())),
)

/* ── 用户管理 ───────────────────────────────────────── */
router.get(
  "/users",
  wrap(async (req, res) =>
    res.json(
      await adminRepository.listUsers({
        search: req.query.search ? String(req.query.search) : undefined,
        status: req.query.status ? String(req.query.status) : undefined,
        page: num(req.query.page, 1),
        size: num(req.query.size, 50),
      }),
    ),
  ),
)
router.get(
  "/users/:id",
  wrap(async (req, res) => {
    const u = await adminRepository.getUser(req.params.id)
    if (!u) throw new PlatformError("user not found", { status: 404, code: "NOT_FOUND" })
    res.json(u)
  }),
)
router.post(
  "/users",
  wrap(async (req, res) => {
    const { email, password, name, role } = req.body || {}
    if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      throw new PlatformError("invalid email", { status: 400, code: "SCHEMA_INVALID" })
    }
    if (!password || password.length < 8) {
      throw new PlatformError("password must be >= 8 chars", { status: 400, code: "SCHEMA_INVALID" })
    }
    const dup = await getPrisma().user.findUnique({ where: { email: email.toLowerCase() } })
    if (dup) throw new PlatformError("email already registered", { status: 409, code: "EMAIL_TAKEN" })
    const user = await adminRepository.createUser({
      email,
      passwordHash: await hashPassword(password),
      name: name || null,
      role: role === "admin" ? "admin" : "user",
    })
    await audit(req, "admin.user.create", user.id, { email: user.email, role: user.role })
    res.status(201).json({
      id: user.id,
      email: user.email,
      name: user.name,
      role: user.role,
      status: user.status,
    })
  }),
)
router.patch(
  "/users/:id",
  wrap(async (req, res) => {
    const { role, status, name } = req.body || {}
    if (role && !["user", "admin"].includes(role)) {
      throw new PlatformError("invalid role", { status: 400, code: "SCHEMA_INVALID" })
    }
    if (status && !["active", "disabled"].includes(status)) {
      throw new PlatformError("invalid status", { status: 400, code: "SCHEMA_INVALID" })
    }
    // 防自锁：不允许把自己降权/禁用
    if (req.user!.userId === req.params.id && (role === "user" || status === "disabled")) {
      throw new PlatformError("cannot demote/disable yourself", { status: 400, code: "SELF_LOCKOUT" })
    }
    const data: { role?: string; status?: string; name?: string | null } = {}
    if (role) data.role = role
    if (status) data.status = status
    if (name !== undefined) data.name = name === "" ? null : name
    const user = await adminRepository.updateUser(req.params.id, data)
    await audit(req, "admin.user.update", user.id, data)
    res.json({ id: user.id, name: user.name, role: user.role, status: user.status })
  }),
)
router.delete(
  "/users/:id",
  wrap(async (req, res) => {
    // 防自锁：不允许删除自己
    if (req.user!.userId === req.params.id) {
      throw new PlatformError("cannot delete yourself", { status: 400, code: "SELF_LOCKOUT" })
    }
    await adminRepository.deleteUser(req.params.id)
    await audit(req, "admin.user.delete", req.params.id)
    res.json({ ok: true })
  }),
)

/* ── 工作组（组织）管理 ─────────────────────────────── */
router.get(
  "/orgs",
  wrap(async (req, res) =>
    res.json(
      await adminRepository.listOrgs({
        search: req.query.search ? String(req.query.search) : undefined,
        page: num(req.query.page, 1),
        size: num(req.query.size, 50),
      }),
    ),
  ),
)
router.delete(
  "/orgs/:id",
  wrap(async (req, res) => {
    await adminRepository.deleteOrg(req.params.id)
    await audit(req, "admin.org.delete", req.params.id)
    res.json({ ok: true })
  }),
)

/* ── 项目管理（跨组织）────────────────────────────── */
router.get(
  "/projects",
  wrap(async (req, res) =>
    res.json(
      await adminRepository.listProjects({
        search: req.query.search ? String(req.query.search) : undefined,
        archived: req.query.archived === "true" ? true : req.query.archived === "false" ? false : undefined,
        page: num(req.query.page, 1),
        size: num(req.query.size, 50),
      }),
    ),
  ),
)
router.delete(
  "/projects/:id",
  wrap(async (req, res) => {
    const keys = await adminRepository.deleteProject(req.params.id)
    await cleanupObjects(keys, `project:${req.params.id}`)
    await audit(req, "admin.project.delete", req.params.id, { objectKeys: keys.length })
    res.json({ ok: true })
  }),
)

/* ── 评估任务（全平台 run）────────────────────────── */
router.get(
  "/runs",
  wrap(async (req, res) =>
    res.json(
      await adminRepository.listRuns({
        status: req.query.status ? String(req.query.status) : undefined,
        from: req.query.from ? new Date(String(req.query.from)) : undefined,
        to: req.query.to ? new Date(String(req.query.to)) : undefined,
        search: req.query.search ? String(req.query.search) : undefined,
        page: num(req.query.page, 1),
        size: num(req.query.size, 50),
      }),
    ),
  ),
)
router.delete(
  "/runs/:id",
  wrap(async (req, res) => {
    const keys = await adminRepository.deleteRun(req.params.id)
    await cleanupObjects(keys, `run:${req.params.id}`)
    await audit(req, "admin.run.delete", req.params.id, { objectKeys: keys.length })
    res.json({ ok: true })
  }),
)

/* ── 产出物（制品）管理 ─────────────────────────────── */
router.get(
  "/artifacts",
  wrap(async (req, res) =>
    res.json(
      await adminRepository.listArtifacts({
        kind: req.query.kind ? String(req.query.kind) : undefined,
        page: num(req.query.page, 1),
        size: num(req.query.size, 50),
      }),
    ),
  ),
)
router.delete(
  "/artifacts/:id",
  wrap(async (req, res) => {
    const key = await adminRepository.deleteArtifact(req.params.id)
    if (key) await cleanupObjects([key], `artifact:${req.params.id}`)
    await audit(req, "admin.artifact.delete", req.params.id)
    res.json({ ok: true })
  }),
)
router.delete(
  "/artifacts",
  wrap(async (req, res) => {
    const ids: unknown = (req.body || {}).ids
    if (!Array.isArray(ids) || !ids.every((x) => typeof x === "string") || !ids.length) {
      throw new PlatformError("ids must be a non-empty string array", { status: 400, code: "SCHEMA_INVALID" })
    }
    if (ids.length > 500) {
      throw new PlatformError("batch delete limited to 500 items", { status: 400, code: "SCHEMA_INVALID" })
    }
    const keys = await adminRepository.deleteArtifacts(ids)
    await cleanupObjects(keys, `artifacts:batch:${ids.length}`)
    await audit(req, "admin.artifact.batch_delete", ids.join(","), { count: ids.length, ids })
    res.json({ ok: true, deleted: ids.length })
  }),
)

/* ── 审计日志（全平台）────────────────────────────── */
router.get(
  "/audit",
  wrap(async (req, res) => {
    const r = await adminRepository.listAudit({
      action: req.query.action ? String(req.query.action) : undefined,
      page: num(req.query.page, 1),
      size: num(req.query.size, 50),
    })
    // AuditLog.id 为 BigInt，JSON 无法直接序列化 → 转 string
    res.json({
      ...r,
      items: r.items.map((a) => ({ ...a, id: a.id.toString() })),
    })
  }),
)

/* ── LLM 模型配置（docs/arch/13）────────────────────── */
router.get(
  "/llm-models",
  wrap(async (_req, res) => res.json(await llmModelRepository.list())),
)

router.post(
  "/llm-models",
  wrap(async (req, res) => {
    const vo = await llmModelRepository.create(req.body as LlmModelInput)
    await audit(req, "llm_model.create", vo.id, { name: vo.name, provider: vo.provider })
    res.status(201).json(vo)
  }),
)

router.patch(
  "/llm-models/:id",
  wrap(async (req, res) => {
    const vo = await llmModelRepository.update(req.params.id, req.body as Partial<LlmModelInput>)
    await audit(req, "llm_model.update", vo.id, { name: vo.name })
    res.json(vo)
  }),
)

router.delete(
  "/llm-models/:id",
  wrap(async (req, res) => {
    await llmModelRepository.remove(req.params.id)
    await audit(req, "llm_model.delete", req.params.id, {})
    res.status(204).end()
  }),
)

router.post(
  "/llm-models/:id/set-default",
  wrap(async (req, res) => {
    const vo = await llmModelRepository.setDefault(req.params.id)
    await audit(req, "llm_model.set_default", vo.id, {})
    res.json(vo)
  }),
)

router.post(
  "/llm-models/:id/test",
  wrap(async (req, res) => {
    const model = await llmModelRepository.getRaw(req.params.id)
    if (!model) throw new PlatformError("model not found", { status: 404, code: "NOT_FOUND" })
    const result = await llmClientService.testModel(model)
    res.json(result)
  }),
)

router.post(
  "/llm-models/export-yaml",
  wrap(async (_req, res) => {
    const yaml = await llmClientService.exportYaml()
    res.type("text/yaml").send(yaml)
  }),
)

export default router
