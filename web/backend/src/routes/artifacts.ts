/**
 * 制品下载路由（/api/v1/artifacts）。
 *  - GET /:id  校验归属后 302 重定向到 presigned GET（短时效 ≤15min，§十三）
 */

import { Router, type RequestHandler } from "express";
import { requireAuth } from "../middleware/auth";
import { artifactGuard } from "../middleware/tenantGuard";
import { createQueryService } from "../services/query.service";

const router = Router();

const wrap =
  (fn: RequestHandler): RequestHandler =>
  (req, res, next) =>
    Promise.resolve(fn(req, res, next)).catch(next);

router.get(
  "/:id",
  requireAuth,
  artifactGuard(),
  wrap(async (req, res) => {
    const svc = createQueryService(req.tenant!);
    const dl = await svc.artifactDownload(req.params.id);
    res.redirect(302, dl.url);
  })
);

export default router;
