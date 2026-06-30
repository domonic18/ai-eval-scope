# eval-gateway

第三方系统对接的评估接入服务。第三方以 HMAC API Key 鉴权提交待评估内容（HTML / Markdown，单页或单元文件夹），服务异步调用评估器评估、回传结果到 Web 可观测平台，并提供任务状态查询。

设计见 [`docs/arch/12第三方系统对接方案.md`](../docs/arch/12第三方系统对接方案.md)。

## 快速开始

```bash
# 1. 安装（含评估器路径依赖）
make gateway-dev          # = cd gateway && uv sync --extra dev

# 2. 建库（在共享 PG 的 gateway schema 建 jobs 表）
make gateway-db-init      # 需先配好 PLATFORM_DATABASE_URL

# 3. 起服务（容器内 9000，本地宿主 9102 避开 web）
cd gateway && uv run eval-gateway
# 或联调：make docker-up
```

## 接口（Sprint A）

| 方法 | 路径 | 鉴权 | 说明 |
|------|------|------|------|
| POST | `/v1/jobs` | HMAC | 提交评估任务（multipart 上传 zip/单文件，或 JSON 内联） |
| GET | `/v1/jobs/{id}` | HMAC | 查询任务状态与指标摘要 |
| POST | `/v1/jobs/{id}/cancel` | HMAC | 取消任务（尽力） |
| GET | `/v1/health` | 无 | 健康检查 |

鉴权头：`Authorization: Eval <publicKey>:<hmacSignature>`，签名串 = `METHOD\nPATH\nsha256(body)`（与 Web 摄取 API 一致）。

## 配置

见 [`CLAUDE.md`](./CLAUDE.md)「配置」一节；完整变量见仓库根 [`.env.example`](../.env.example) 的 `[gateway]` 段。
