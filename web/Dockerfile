# syntax=docker/dockerfile:1
#
# Agent Eval 可观测平台后端镜像（TypeScript，编译到 dist，纯 JSON API）。
# Debian bookworm 自带 libssl3（Prisma 引擎依赖）；本沙箱对 binaries.prisma.sh /
# 包仓库 CDN 不可达为已知限制，常规 CI/生产可构建。

# ─── Stage 1: builder（编译 TS）───
FROM node:22.15.1-bookworm AS builder
WORKDIR /app/web/backend

COPY web/backend/package*.json ./
RUN npm ci

COPY web/backend/prisma ./prisma
RUN npx prisma generate

COPY web/backend/tsconfig.json web/backend/tsconfig.build.json ./
COPY web/backend/src ./src
COPY web/backend/server.ts ./server.ts
RUN npm run build

# ─── Stage 2: runtime（精简，仅生产依赖 + dist）───
FROM node:22.15.1-bookworm
WORKDIR /app/web/backend

COPY web/backend/package*.json ./
RUN npm ci --omit=dev

COPY web/backend/prisma ./prisma
RUN npx prisma generate

COPY --from=builder /app/web/backend/dist ./dist

ENV PORT=3000 \
    HOST=0.0.0.0 \
    NODE_ENV=production

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=5 \
    CMD node -e "require('http').get('http://localhost:3000/health', (r) => process.exit(r.statusCode === 200 ? 0 : 1))"

# 应用待决迁移后启动（migrate deploy 幂等）
CMD ["sh", "-c", "npx prisma migrate deploy && node dist/server.js"]
