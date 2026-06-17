/**
 * 平台 Express 入口。
 *
 * 分层：routes(HTTP) → services(业务) → repositories(数据)（§三）。
 * 后端为纯 JSON API（遗留 Sprint 7a 本地 workspace 查看器与前端已于统一架构时移除，
 * 决策 D6 推翻）。前端待 Sprint 7f 按新架构重建。
 *
 * 路由：GET /health（健康检查）；/api/v1/*（认证与多租户 + 后续 Query API）。
 */

import path from "path";
import fs from "fs";
import express from "express";
import cors from "cors";
import { requestLog, getLogger, flushLogs } from "./infra/logger";
import { errorHandler, notFound } from "./middleware/errorHandler";
import { getConfig } from "./config";
import { disconnect } from "./infra/prisma";
import healthRouter from "./routes/health";

// ── 平台路由（v1，认证与多租户）──
import authRouter from "./routes/auth";
import orgsRouter from "./routes/orgs";
import projectsRouter from "./routes/projects";
import keysRouter from "./routes/keys";
import runsRouter from "./routes/runs";
import artifactsRouter from "./routes/artifacts";

// ── 摄取路由（HMAC 鉴权，7d）──
import ingestRouter from "./routes/public/ingest";
import publicArtifactsRouter from "./routes/public/artifacts";

/** 组装 Express app。供 serverless-http 复用与测试 import。 */
export function createApp(): express.Application {
  const app = express();

  // 全局中间件
  app.use(cors()); // 按需收紧；当前开放，便于多端调用
  // 捕获原始请求体字节供 API Key HMAC 验签（req.rawBody）；与发送字节严格一致
  app.use(
    express.json({
      limit: "8mb",
      // verify 回调的 req 类型为 IncomingMessage（body-parser），下转 express.Request 以写 rawBody
      verify: (req, _res, buf) => {
        (req as express.Request).rawBody = buf;
      },
    })
  );
  app.use(requestLog);

  // ── 平台路由 ──
  app.use(healthRouter); // GET /health, GET /api/health
  app.use("/api/v1/auth", authRouter); // 注册/登录/刷新/me（register·login·refresh 公开）
  app.use("/api/v1/orgs", orgsRouter); // 成员 + 组织下项目（requireAuth + orgGuard）
  app.use("/api/v1/projects", projectsRouter); // 项目管理 + Query（runs/trends）
  app.use("/api/v1/projects/:id/keys", keysRouter); // API Key 管理（嵌套于项目）
  app.use("/api/v1/runs", runsRouter); // 运行/样本详情（Query，§九）
  app.use("/api/v1/artifacts", artifactsRouter); // 制品下载（presigned 重定向）

  // ── 摄取路由（HMAC 鉴权 + 限流，7d）──
  app.use("/api/public/ingest", ingestRouter); // POST /api/public/ingest
  app.use("/api/public/artifacts", publicArtifactsRouter); // POST /api/public/artifacts/url

  // ── 前端静态托管（生产；dev 用 vite 单独跑 :5173）──
  // 以 cwd 为基准（host: web/backend/public；Docker: /app/web/backend/public）
  const publicDir = path.resolve(process.cwd(), "public");
  if (fs.existsSync(path.join(publicDir, "index.html"))) {
    app.use(express.static(publicDir, { maxAge: 0 }));
    // SPA 兜底：非 API/health 路径返回 index.html
    app.get(/^(?!\/api\/|\/health).*/, (_req, res) => {
      res.sendFile(path.join(publicDir, "index.html"));
    });
  }

  // 404 + 错误兜底（必须最后注册）
  app.use(notFound);
  app.use(errorHandler);

  return app;
}

/** 独立进程入口：监听端口 + 优雅关闭。 */
export function main(): ReturnType<express.Application["listen"]> {
  const cfg = getConfig();
  const logger = getLogger();

  const app = createApp();
  const server = app.listen(cfg.port, cfg.host, () => {
    const addr = server.address();
    logger.info(
      {
        host: cfg.host,
        port: typeof addr === "object" && addr ? addr.port : cfg.port,
        object_storage: cfg.objectStorage,
        schema_version: cfg.schemaVersion,
      },
      "server_started"
    );
  });

  const shutdown = (signal: string): void => {
    logger.info({ signal }, "server_shutting_down");
    server.close(async () => {
      await disconnect();
      await flushLogs();
      process.exit(0);
    });
    setTimeout(() => process.exit(1), 10000).unref();
  };

  process.on("SIGTERM", () => shutdown("SIGTERM"));
  process.on("SIGINT", () => shutdown("SIGINT"));

  return server;
}
