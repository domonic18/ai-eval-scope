# syntax=docker/dockerfile:1
#
# Agent Eval 可观测平台镜像（多阶段）：前端(Vite/React/TS) + 后端(Node/TS)。
# 构建上下文 = 仓库根（docker compose 的 context: .），故 COPY 路径以 web/ 开头。
# Debian bookworm 自带 libssl3（Prisma 引擎依赖）。

# ─── Stage 1: 前端构建 ───
FROM node:22.15.1-bookworm AS frontend-builder
WORKDIR /app/web/frontend
COPY web/frontend/package*.json ./
RUN npm ci
COPY web/frontend/ ./
# 版本号由 Jenkins 经 --build-arg VITE_APP_VERSION 注入（a.b.c.<BUILD>）；本地构建回退默认 1.0.0
ARG VITE_APP_VERSION=1.0.0
ENV VITE_APP_VERSION=$VITE_APP_VERSION
RUN npm run build

# ─── Stage 2: 后端编译 ───
FROM node:22.15.1-bookworm AS backend-builder
WORKDIR /app/web/backend
COPY web/backend/package*.json ./
RUN npm ci
COPY web/backend/prisma ./prisma
RUN npx prisma generate
COPY web/backend/tsconfig.json web/backend/tsconfig.build.json ./
COPY web/backend/src ./src
COPY web/backend/server.ts ./server.ts
RUN npm run build

# ─── Stage 3: 运行时（精简）───
FROM node:22.15.1-bookworm
WORKDIR /app/web/backend
COPY web/backend/package*.json ./
RUN npm ci --omit=dev
COPY web/backend/prisma ./prisma
RUN npx prisma generate
COPY --from=backend-builder /app/web/backend/dist ./dist
COPY --from=frontend-builder /app/web/frontend/dist ./public

ENV PORT=9000 \
    HOST=0.0.0.0 \
    NODE_ENV=production

EXPOSE 9000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=5 \
    CMD node -e "require('http').get('http://localhost:9000/health', (r) => process.exit(r.statusCode === 200 ? 0 : 1))"

# 表由 `make db-init` 手动应用 prisma migrations 创建（单一来源，docs/standard/数据库迁移规范.md）；此处仅启动服务
CMD ["node", "dist/server.js"]
