/**
 * 超级管理员后台路由（/api/v1/admin）—— 全部 requireAuth + platformAdminGuard（DB 鉴权）。
 * 跨租户管理：用户 / 工作组 / 项目 / 评估任务 / 产出物 / 审计 / 统计。
 * 参照 SquadSight 控制台的 IA；复用现有设计系统组件在前端实现。
 */
import { Router, type Request, type RequestHandler } from "express"
import { requireAuth } from "../middleware/auth"
import { platformAdminGuard } from "../middleware/adminGuard"
import { PlatformError } from "../middleware/errorHandler"
import { hashPassword } from "../infra/crypto"
import { adminRepository } from "../repositories/admin.repository"
import { adminStatsRepository } from "../repositories/adminStats.repository"
import { AuditService } from "../services/audit.service"
import { getPrisma } from "../infra/prisma"

const router = Router()
// 全部 admin 接口：登录 + 平台超管（DB 鉴权，即时反映 role/status 变更）
router.use(requireAuth, platformAdminGuard)

const wrap =
  (fn: RequestHandler): RequestHandler =>
  (req, res, next) =>
    Promise.resolve(fn(req, res, next)).catch(next)

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
    const { role, status } = req.body || {}
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
    const data: { role?: string; status?: string } = {}
    if (role) data.role = role
    if (status) data.status = status
    const user = await adminRepository.updateUser(req.params.id, data)
    await audit(req, "admin.user.update", user.id, data)
    res.json({ id: user.id, role: user.role, status: user.status })
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

export default router
