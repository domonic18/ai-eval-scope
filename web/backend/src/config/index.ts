/**
 * 平台配置加载与校验（§12.3 环境变量）。
 *
 * 设计原则：
 * - 所有 PLATFORM_* 环境变量在此集中读取并提供类型化默认值，业务层只消费 config。
 * - 启动期对「必需且无默认」的变量做 fail-fast 校验；可选变量给默认值。
 * - DB/对象存储连通性的运行期探测在 /health 端点做（不阻塞启动）。
 */

export type ObjectStorageKind = "minio" | "s3" | "cos"

export interface PlatformConfig {
  databaseUrl: string
  objectStorage: ObjectStorageKind
  s3Endpoint: string
  s3ExternalEndpoint: string // presigned URL 对外端点（浏览器/客户端可达，可与 s3Endpoint 不同）
  s3Region: string
  s3Bucket: string
  s3PathStyle: boolean // MinIO 需要 path-style
  s3AccessKey: string
  s3SecretKey: string
  jwtSecret: string
  keyEncryptionKey: string // API Key secret 对称加密密钥
  allowSignup: boolean
  ingestRateLimit: number // 令牌桶配额（每分钟/每 key）
  ingestMaxBatch: number // 单批事件数上限
  ingestMaxBytes: number // 单批体积上限（字节）
  presignTtlSec: number // presigned URL 有效期（秒，≤900）
  retentionDefaultDays: number
  nodeEnv: string
  port: number
  host: string
  schemaVersion: string // 事件 schema 版本（同时为 /health 上报）
  logLevel: string
}

const REQUIRED_AT_RUNTIME = ["PLATFORM_DATABASE_URL"]

export function bool(val: string | undefined, fallback: boolean): boolean {
  if (val === undefined || val === "") return fallback
  return ["1", "true", "yes", "on"].includes(String(val).toLowerCase())
}

export function int(val: string | undefined, fallback: number): number {
  const n = parseInt(val ?? "", 10)
  return Number.isFinite(n) ? n : fallback
}

export function loadConfig(): PlatformConfig {
  const cfg: PlatformConfig = {
    databaseUrl: process.env.PLATFORM_DATABASE_URL || "",
    objectStorage: (process.env.PLATFORM_OBJECT_STORAGE as ObjectStorageKind) || "minio",
    s3Endpoint: process.env.PLATFORM_S3_ENDPOINT || "http://localhost:9000",
    // presigned URL 走对外端点（浏览器/客户端可达）；未设置则回退内部端点，行为不变
    s3ExternalEndpoint:
      process.env.PLATFORM_S3_EXTERNAL_ENDPOINT ||
      process.env.PLATFORM_S3_ENDPOINT ||
      "http://localhost:9000",
    s3Region: process.env.PLATFORM_S3_REGION || "us-east-1",
    s3Bucket: process.env.PLATFORM_S3_BUCKET || "agent-eval",
    s3PathStyle: bool(process.env.PLATFORM_S3_PATH_STYLE, true),
    s3AccessKey: process.env.PLATFORM_S3_ACCESS_KEY || "minioadmin",
    s3SecretKey: process.env.PLATFORM_S3_SECRET_KEY || "minioadmin",
    jwtSecret: process.env.PLATFORM_JWT_SECRET || "dev-insecure-jwt-secret",
    keyEncryptionKey: process.env.PLATFORM_KEY_ENCRYPTION_KEY || "dev-insecure-encryption-key",
    allowSignup: bool(process.env.PLATFORM_ALLOW_SIGNUP, true),
    ingestRateLimit: int(process.env.PLATFORM_INGEST_RATE_LIMIT, 600),
    ingestMaxBatch: int(process.env.PLATFORM_INGEST_MAX_BATCH, 500),
    ingestMaxBytes: int(process.env.PLATFORM_INGEST_MAX_BYTES, 4 * 1024 * 1024),
    presignTtlSec: int(process.env.PLATFORM_PRESIGN_TTL_SEC, 900),
    retentionDefaultDays: int(process.env.PLATFORM_RETENTION_DEFAULT_DAYS, 90),
    nodeEnv: process.env.NODE_ENV || "development",
    port: int(process.env.PORT, 9000),
    host: process.env.HOST || "0.0.0.0",
    schemaVersion: "1.0",
    logLevel: process.env.LOG_LEVEL || "info",
  }

  if (cfg.presignTtlSec > 900 || cfg.presignTtlSec < 1) {
    cfg.presignTtlSec = 900 // 安全约束：presigned URL ≤ 15min（§十三）
  }

  return cfg
}

/** 校验运行期必需变量，返回缺失项列表（空数组 = 全部就绪）。 */
export function validate(_cfg: PlatformConfig): string[] {
  const missing: string[] = []
  for (const key of REQUIRED_AT_RUNTIME) {
    const envVal = process.env[key]
    if (envVal === undefined || envVal === "") missing.push(key)
  }
  return missing
}

let _cfg: PlatformConfig | null = null

export function getConfig(): PlatformConfig {
  if (!_cfg) _cfg = loadConfig()
  return _cfg
}

/* ── SAML SSO 配置（docs/arch/12 §4.7，可选功能，独立于 PlatformConfig）── */
export interface SamlConfig {
  enabled: boolean
  spEntityId: string
  acsUrl: string
  slsUrl: string
  spCert: string // PEM（纯 base64 自动补标签）
  spKey: string
  idpEntityId: string
  idpSsoUrl: string
  idpSlsUrl: string
  idpCert: string
  strict: boolean
  debug: boolean
}

export function loadSamlConfig(): SamlConfig {
  return {
    enabled: bool(process.env.SAML_SSO_ENABLED, false),
    spEntityId: process.env.SAML_SP_ENTITY_ID || "",
    acsUrl: process.env.SAML_ACS_URL || "",
    slsUrl: process.env.SAML_SLS_URL || "",
    spCert: process.env.SAML_SP_CERT || "",
    spKey: process.env.SAML_SP_KEY || "",
    idpEntityId: process.env.SAML_IDP_ENTITY_ID || "",
    idpSsoUrl: process.env.SAML_IDP_SSO_URL || "",
    idpSlsUrl: process.env.SAML_IDP_SLS_URL || "",
    idpCert: process.env.SAML_IDP_CERT || "",
    strict: bool(process.env.SAML_STRICT, true),
    debug: bool(process.env.SAML_DEBUG, false),
  }
}

let _saml: SamlConfig | null = null

export function getSamlConfig(): SamlConfig {
  if (!_saml) _saml = loadSamlConfig()
  return _saml
}

/** 校验 SAML 配置完整性（启用时），返回缺失项列表（空 = 就绪）。 */
export function validateSamlConfig(cfg: SamlConfig): string[] {
  if (!cfg.enabled) return []
  const missing: string[] = []
  if (!cfg.idpEntityId) missing.push("SAML_IDP_ENTITY_ID")
  if (!cfg.idpSsoUrl) missing.push("SAML_IDP_SSO_URL")
  if (!cfg.idpCert) missing.push("SAML_IDP_CERT")
  if (!cfg.spEntityId) missing.push("SAML_SP_ENTITY_ID")
  if (!cfg.acsUrl) missing.push("SAML_ACS_URL")
  return missing
}
