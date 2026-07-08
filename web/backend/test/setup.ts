/**
 * vitest setupFile —— 在任何被测模块加载前注入测试环境变量。
 * 指向 docker compose 起的本地 postgres + minio。
 */

process.env.NODE_ENV = "test"
process.env.LOG_LEVEL = "warn" // 测试时降噪

process.env.PLATFORM_DATABASE_URL =
  process.env.PLATFORM_DATABASE_URL ||
  "postgresql://eval:evalpassword@localhost:5432/agent_eval?schema=public"

process.env.PLATFORM_OBJECT_STORAGE = "minio"
// MinIO 宿主端口为 9100（compose 把 9000 让给 web，见 docker-compose.yml:38）；
// 测试在宿主运行，须用 9100，否则会打到 web 容器、被 SPA 兜底回 index.html。
process.env.PLATFORM_S3_ENDPOINT = process.env.PLATFORM_S3_ENDPOINT || "http://localhost:9100"
process.env.PLATFORM_S3_EXTERNAL_ENDPOINT =
  process.env.PLATFORM_S3_EXTERNAL_ENDPOINT || "http://localhost:9100"
process.env.PLATFORM_S3_REGION = "us-east-1"
process.env.PLATFORM_S3_BUCKET = "agent-eval"
process.env.PLATFORM_S3_ACCESS_KEY = "eval"
process.env.PLATFORM_S3_SECRET_KEY = "evalpassword123"
process.env.PLATFORM_S3_PATH_STYLE = "true"
process.env.PLATFORM_JWT_SECRET = "test-jwt-secret"
process.env.PLATFORM_KEY_ENCRYPTION_KEY = "test-encryption-key"
