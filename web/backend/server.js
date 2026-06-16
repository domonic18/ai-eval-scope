"use strict";

const express = require("express");
const path = require("path");
const cors = require("cors");

const projectsRouter = require("./routes/projects");
const runsRouter = require("./routes/runs");
const indexRouter = require("./routes/index");

function createApp() {
  const app = express();
  app.use(cors());
  app.use(express.json());

  // API routes
  app.use("/api/projects", projectsRouter);
  app.use("/api/runs", runsRouter);
  app.use("/api/index", indexRouter);

  // Health check
  app.get("/api/health", (req, res) => {
    res.json({ status: "ok" });
  });

  // Static frontend build
  const publicDir = path.join(__dirname, "public");

  // 带 hash 的资源（JS/CSS）可长期缓存，因为文件名变化即内容变化
  app.use(
    "/assets",
    express.static(path.join(publicDir, "assets"), {
      maxAge: "1y",
      immutable: true,
    })
  );

  // 不带 hash 的资源（如 index.html, vite.svg, favicon）不缓存，避免更新后浏览器仍用旧版本
  app.use(
    express.static(publicDir, {
      maxAge: 0,
      setHeaders: (res, filePath) => {
        if (path.basename(filePath) === "index.html") {
          res.setHeader("Cache-Control", "no-cache, no-store, must-revalidate");
          res.setHeader("Pragma", "no-cache");
          res.setHeader("Expires", "0");
        }
      },
    })
  );

  // SPA fallback — index.html 永不缓存
  app.get("*", (req, res) => {
    const indexHtml = path.join(publicDir, "index.html");
    if (require("fs").existsSync(indexHtml)) {
      res.setHeader("Cache-Control", "no-cache, no-store, must-revalidate");
      res.setHeader("Pragma", "no-cache");
      res.setHeader("Expires", "0");
      res.sendFile(indexHtml);
    } else {
      res.status(404).json({
        error: "Frontend build not found. Please build web/frontend and copy dist/ to web/backend/public/.",
      });
    }
  });

  // Global error handler
  app.use((err, req, res, next) => {
    console.error(err);
    res.status(500).json({ error: err.message || "Internal server error" });
  });

  return app;
}

function main() {
  const app = createApp();
  const port = parseInt(process.env.PORT || "3000", 10);
  const host = process.env.HOST || "localhost";

  const server = app.listen(port, host, () => {
    const actualPort = server.address().port;
    console.log(`Agent Eval Web Portal running at http://${host}:${actualPort}`);
    console.log(`Workspace: ${process.env.WORKSPACE_DIR || "./workspace"}`);
  });
  return server;
}

module.exports = { createApp, main };

if (require.main === module) {
  main();
}
