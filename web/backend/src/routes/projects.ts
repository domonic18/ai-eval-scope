/**
 * 项目管理路由（/api/v1/projects）。
 *  - GET   /:id            详情
 *  - PATCH /:id            更新
 *  - POST  /:id/archive    归档（owner）
 *  - POST  /:id/unarchive  恢复（owner）
 *
 * projectGuard 解析 :id → 校验归属与成员关系 → 注入 req.tenant（含 projectId）。
 */

import { Router, type RequestHandler } from "express";
import { requireAuth } from "../middleware/auth";
import { projectGuard } from "../middleware/tenantGuard";
import { createProjectService } from "../services/project.service";

const router = Router();

const wrap =
  (fn: RequestHandler): RequestHandler =>
  (req, res, next) =>
    Promise.resolve(fn(req, res, next)).catch(next);

router.get(
  "/:id",
  requireAuth,
  projectGuard(),
  wrap(async (req, res) => {
    const svc = createProjectService(req.tenant!);
    res.json({ project: await svc.get(req.params.id) });
  })
);

router.patch(
  "/:id",
  requireAuth,
  projectGuard(),
  wrap(async (req, res) => {
    const svc = createProjectService(req.tenant!);
    res.json({ project: await svc.update(req.params.id, req.body || {}) });
  })
);

router.post(
  "/:id/archive",
  requireAuth,
  projectGuard({ role: "owner" }),
  wrap(async (req, res) => {
    const svc = createProjectService(req.tenant!);
    res.json({ project: await svc.setArchived(req.params.id, true) });
  })
);

router.post(
  "/:id/unarchive",
  requireAuth,
  projectGuard({ role: "owner" }),
  wrap(async (req, res) => {
    const svc = createProjectService(req.tenant!);
    res.json({ project: await svc.setArchived(req.params.id, false) });
  })
);

export default router;
