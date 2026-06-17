/**
 * 认证路由（/api/v1/auth）。
 *  - POST /register  注册（PLATFORM_ALLOW_SIGNUP 开关）
 *  - POST /login     登录
 *  - POST /refresh   刷新 token
 *  - GET  /me        当前用户（需鉴权）
 */

import { Router, type RequestHandler } from "express";
import { AuthService } from "../services/auth.service";
import { requireAuth } from "../middleware/auth";

const router = Router();

const wrap =
  (fn: RequestHandler): RequestHandler =>
  (req, res, next) =>
    Promise.resolve(fn(req, res, next)).catch(next);

router.post(
  "/register",
  wrap(async (req, res) => {
    const result = await AuthService.register(req.body || {});
    res.status(201).json(result);
  })
);

router.post(
  "/login",
  wrap(async (req, res) => {
    res.json(await AuthService.login(req.body || {}));
  })
);

router.post(
  "/refresh",
  wrap(async (req, res) => {
    res.json(await AuthService.refresh(req.body || {}));
  })
);

router.get(
  "/me",
  requireAuth,
  wrap(async (req, res) => {
    res.json(await AuthService.me(req.user!.userId));
  })
);

export default router;
