# Agent Eval Web Portal

Sprint 7a 交付的 Web Portal MVP，基于 React 18 + Express + ECharts。

## 目录结构

```
web/
├── backend/    Express API 服务
└── frontend/   React SPA
```

## 开发流程

### 1. 安装依赖

```bash
cd web/backend && npm install
cd web/frontend && npm install
```

### 2. 启动后端

```bash
cd web/backend
WORKSPACE_DIR=./workspace npm run dev
```

### 3. 启动前端

```bash
cd web/frontend
npm run dev
```

前端开发服务器运行在 http://localhost:5173，API 请求通过 Vite proxy 转发到 http://localhost:3000。

## 生产构建

```bash
make web-build
```

构建完成后，前端产物会复制到 `web/backend/public/`，可直接通过 `agent-eval serve` 启动。

## 通过 Python CLI 启动

```bash
# 重建索引
uv run agent-eval index --workspace ./workspace

# 启动 Web Portal
uv run agent-eval serve --workspace ./workspace --port 3000
```

## Docker 部署

### 构建镜像

```bash
make docker-build
```

或手动执行：

```bash
docker build -f web/Dockerfile -t agent-eval-web:latest .
```

Dockerfile 使用 Node.js v22.15.1 多阶段构建：先构建前端，再安装后端生产依赖并复制构建产物到 `public/`。

### 启动容器

```bash
make docker-up
```

或手动执行：

```bash
docker compose up -d
```

Web Portal 将运行在 http://localhost:3000。

### 目录挂载说明

`docker-compose.yml` 默认挂载：

- `./workspace:/app/workspace` — 评估运行数据（需要可写，支持 API 重建索引）
- `./assets:/app/assets:ro` — 项目配置（projects/*.yaml）只读

启动前请确保宿主机 `workspace/` 目录存在；若不存在，Docker 会自动创建一个空目录。

### 重建索引

容器内 Web Portal 只读取 `workspace/index/`。启动后可通过以下方式重建索引：

1. 在项目列表页点击右上角 **重建索引** 按钮
2. 调用 API：

```bash
curl -X POST http://localhost:3000/api/index/rebuild
```

3. 在宿主机重建后再启动容器：

```bash
uv run agent-eval index --workspace ./workspace
make docker-up
```

### 停止与日志

```bash
# 停止容器
make docker-down

# 查看日志
make docker-logs
```

## 腾讯云函数 SCF 部署

1. 执行 `make web-build`
2. 将 `web/backend/`（含 `public/`）打包为 zip
3. 创建 SCF，运行时选择 Node.js 18+
4. 入口函数填写 `scf_bootstrap.main_handler`
5. 配置 API Gateway 触发器，路由 `/*` 指向 SCF

## API 列表

- `GET /api/projects`
- `GET /api/projects/:id`
- `GET /api/projects/:id/runs`
- `GET /api/projects/:id/trends`
- `GET /api/runs/:id`
- `GET /api/runs/:id/tasks`
- `GET /api/runs/:id/tasks/:task_id`
- `GET /api/runs/:id/tasks/:task_id/evidence/:file`
- `GET /api/runs/:id/tasks/:task_id/manifest`
- `POST /api/index/rebuild`
