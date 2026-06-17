/**
 * 运行详情路由（/api/v1/runs）。
 *  - GET /:id               运行详情（含样本摘要）
 *  - GET /:id/samples/:sid  样本详情（约束 + 制品引用）
 *
 * runGuard 解析 :id(run)→project→org→成员关系，注入 req.tenant（含 projectId）。
 */

import { Router, type RequestHandler } from "express";
import { requireAuth } from "../middleware/auth";
import { runGuard } from "../middleware/tenantGuard";
import { createQueryService } from "../services/query.service";

const router = Router();

const wrap =
  (fn: RequestHandler): RequestHandler =>
  (req, res, next) =>
    Promise.resolve(fn(req, res, next)).catch(next);

router.get(
  "/:id",
  requireAuth,
  runGuard(),
  wrap(async (req, res) => {
    const svc = createQueryService(req.tenant!);
    res.json({ run: await svc.runDetail(req.tenant!.projectId!, req.params.id) });
  })
);

router.get(
  "/:id/samples/:sid",
  requireAuth,
  runGuard(),
  wrap(async (req, res) => {
    const svc = createQueryService(req.tenant!);
    res.json({ sample: await svc.sampleDetail(req.tenant!.projectId!, req.params.sid) });
  })
);

export default router;
