# syntax=docker/dockerfile:1

# ─── Stage 1: Build frontend ───
FROM node:22.15.1-alpine AS frontend-builder

WORKDIR /app/web/frontend

# Copy package files first for layer caching
COPY web/frontend/package*.json ./
RUN npm ci

# Copy source and build
COPY web/frontend/ ./
RUN npm run build

# ─── Stage 2: Production image ───
FROM node:22.15.1-alpine

WORKDIR /app/web/backend

# Install backend production dependencies
COPY web/backend/package*.json ./
RUN npm ci --only=production

# Copy backend source code
COPY web/backend/ ./

# Copy built frontend from stage 1 into backend/public/
COPY --from=frontend-builder /app/web/frontend/dist ./public/

# Create default workspace directory (will be overridden by volume mount)
RUN mkdir -p /app/workspace

EXPOSE 3000

ENV WORKSPACE_DIR=/app/workspace \
    PORT=3000 \
    HOST=0.0.0.0

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD node -e "require('http').get('http://localhost:3000/api/health', (r) => process.exit(r.statusCode === 200 ? 0 : 1))"

CMD ["node", "server.js"]
