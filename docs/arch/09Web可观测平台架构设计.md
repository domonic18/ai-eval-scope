# Web 可观测平台架构设计

> 本文档是 [03Web 可观测平台重构需求](../requirement/03Web可观测平台重构需求.md) 的工程落地设计，阐述 Web 可观测平台（仿 Langfuse 的多租户评估可观测后端）的分层架构、后端工程结构、数据库 DDL、对象存储、认证与多租户、摄取服务、评估器对接（ResultSink）、Query API、前端改造、迁移回填与部署运维。
>
> 属于 [01 整体架构设计](./01整体架构设计.md) §二"Web 可观测平台"在平台化阶段的演进版；前端页面视觉沿用早期 Web Portal 设计（见本文 §十 前端改造），本文聚焦数据/服务/对接层。需求条目编号（F-O-* / NF-O-*）对齐需求文档。

---

## 一、设计目标与范围

### 1.1 设计目标

| 目标 | 说明 |
|------|------|
| **多租户可观测后端** | 用户/组织/项目三级隔离，评估结果经网络摄取、持久化、可视化 |
| **写入与查看分离** | Ingestion API（评估器写）与 Query API（前端读）独立鉴权、独立演进、独立扩缩容 |
| **可靠摄取** | at-least-once + `event_id` 幂等，断网不丢、重试不重 |
| **契约优先** | Python 评估器与 Node 后端以版本化 JSON 事件 schema 为唯一契约 |
| **自托管生产就绪** | Docker Compose 本地、云函数 + 云 PG + COS 生产 |

### 1.2 范围（本期 Sprint 7b–7g）

- 含：账号/组织/项目/API Key、Ingestion API、PG + 对象存储、ResultSink、Query API、前端重接、回填迁移、自托管部署；**SAML SSO 登录**、**团队中心模型**（注册不自动建个人 Org，申请 + 审批加入团队）、**样本级走势**、项目/运行**永久删除**、制品**同源预览代理**
- 不含：细粒度 RBAC 矩阵、实时流式评估、Web 端规则编辑、人工仲裁界面（远期）

---

## 二、总体架构

### 2.1 分层架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│  评估器侧 (Python / agent-eval)                                          │
│    PipelineEngine ── 评估 ──> MetricsReport/SampleResult/Constraint     │
│    agent_eval/llm/tracing.py ────────> Langfuse SaaS (LLM 调用链)        │
│    agent_eval/observability/sink.py ──┐                                  │
│         事件拼装 + HMAC + 队列重放     │                                  │
└────────────────────────────────────────┼─────────────────────────────────┘
                                         │ ① 结构化事件 ② presigned 制品
                                         ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  可观测平台后端 (Node.js / Express)                                       │
│ ┌──────────────────── 接入层 (routes + middleware) ────────────────────┐│
│ │ AuthMiddleware (JWT) · ApiKeyAuth (HMAC) · TenantGuard · RateLimiter ││
│ │ RequestLog · ErrorHandler                                            ││
│ └──────────────────────────────────────────────────────────────────────┘│
│ ┌────────── Ingestion 服务 ──────────┐ ┌────────── Query 服务 ─────────┐│
│ │  EventValidator (ajv)              │ │  ProjectService / RunService  ││
│ │  IngestService (幂等 upsert)       │ │  TrendService / SampleService ││
│ │  ArtifactService (presigned)       │ │  ArtifactService (签名下载)   ││
│ └────────────────────────────────────┘ └───────────────────────────────┘│
│ ┌────────── 管理服务 ────────────────┐ ┌────────── 共享 ───────────────┐│
│ │  AuthServervice / OrgService       │ │  Repositories (强制租户过滤)  ││
│ │  ProjectService / ApiKeyService    │ │  ObjectStorage (MinIO/S3/COS) ││
│ │  AuditService                      │ │  PrismaClient (PgBouncer)     ││
│ └────────────────────────────────────┘ └───────────────────────────────┘│
└───────────────────────────┬─────────────────────────────────────────────┘
                            ▼
        ┌───────────────────────┴───────────────────────┐
        ▼                                               ▼
┌──────────────────────┐                     ┌──────────────────────────┐
│  PostgreSQL          │                     │  对象存储                 │
│  结构化数据 + 审计    │                     │  S3 / COS / MinIO         │
└──────────────────────┘                     └──────────────────────────┘
        ▲
        │
┌───────┴─────────────────────────────────────────────────────────────────┐
│  前端 (React SPA)  登录态 · 组织/项目切换 · 看板/趋势/详情 · 制品预览     │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 部署拓扑

- **本地（开发/演示）**：`docker compose up` 起 express + postgres + minio；前端由 Express 托管（沿用 `serve` 模式）。
- **生产**：Express 部署到腾讯云函数（SCF）/ 容器；PostgreSQL 用云数据库；对象存储用 COS（S3 兼容）。DB 连接经 PgBouncer（SCF 为短连接，需连接池）。
- **可拆分演进**：Ingestion 与 Query 为两套路由 + 中间件，未来可拆为两个进程/服务独立扩缩容。

### 2.3 与 Langfuse 的协作

| 数据 | 系统 | 通路 |
|------|------|------|
| LLM 调用链（prompt/response/token/provider/model） | Langfuse SaaS | 评估器 `tracing.py`（不变） |
| 评估结论（指标/样本/约束/溯源/趋势） | 本平台 | 评估器 ResultSink → Ingestion API |
| 关联 | `langfuse_trace_id` | ResultSink 把当次 trace_id 随 `run` 事件上报；平台存储并支持跳转 |

---

## 三、后端工程结构

```
web/backend/
├── src/
│   ├── server.js                     # Express 入口
│   ├── config/                       # 环境配置 (env 校验)
│   │   └── index.js
│   ├── middleware/
│   │   ├── auth.js                   # JWT 解析与 req.user 注入
│   │   ├── apiKeyAuth.js             # HMAC 验签（Ingestion）
│   │   ├── tenantGuard.js            # 强制 org/project 上下文与越权拦截
│   │   ├── rateLimiter.js            # 限流（Ingestion/Query 分别配置）
│   │   ├── requestLog.js             # 结构化日志
│   │   └── errorHandler.js
│   ├── routes/
│   │   ├── public/                   # Ingestion（API Key 鉴权）
│   │   │   ├── ingest.js
│   │   │   ├── artifacts.js
│   │   │   └── health.js
│   │   ├── auth.js                   # 注册/登录/刷新
│   │   ├── orgs.js
│   │   ├── projects.js
│   │   ├── keys.js                   # API Key 管理
│   │   ├── runs.js                   # Query API
│   │   └── samples.js
│   ├── services/                     # 业务逻辑（无直接 SQL）
│   │   ├── auth.service.js
│   │   ├── project.service.js
│   │   ├── apiKey.service.js
│   │   ├── ingest.service.js         # 事件校验/幂等/事务
│   │   ├── artifact.service.js       # presigned + 签名下载
│   │   ├── run.service.js
│   │   ├── trend.service.js
│   │   └── audit.service.js
│   ├── repositories/                 # 数据访问层（强制租户过滤）
│   │   ├── base.repository.js        # 注入 orgId/projectId 过滤
│   │   ├── run.repository.js
│   │   ├── sample.repository.js
│   │   └── ...
│   ├── infra/
│   │   ├── prisma.js                 # PrismaClient 单例（PgBouncer）
│   │   ├── objectStorage.js          # ObjectStorage 工厂
│   │   └── crypto.js                 # HMAC / 哈希 / token
│   ├── schemas/                      # 事件 JSON Schema（与评估器共享）
│   │   ├── ingest.event.v1.json
│   │   └── ...
│   └── utils/
├── prisma/
│   ├── schema.prisma                 # 数据模型（§四）
│   └── migrations/
├── public/                           # 前端构建产物（生产）
├── test/                             # 单元/集成/越权
├── Dockerfile
└── package.json
```

**分层约定**：`routes`（HTTP）→ `services`（业务）→ `repositories`（数据）。`tenantGuard` 中间件从 JWT/API Key 解析出 `{ orgId, projectId, role }` 注入 `req.tenant`；所有 repository 构造时接收 `req.tenant`，查询自动追加 `WHERE org_id/project_id` 过滤——隔离是数据访问层的强制行为，而非业务层自觉。

---

## 四、数据模型详设

> 以 Prisma schema 表达（DDL 等价）。`@id` 主键，UUID 由应用层生成（`crypto.randomUUID()`）。评估数据表全部带 `projectId`（部分带 `orgId`）以支持过滤。

### 4.1 Prisma schema（核心）

```prisma
// prisma/schema.prisma
generator client { provider = "prisma-client-js" }
datasource db { provider = "postgresql"; url = env("PLATFORM_DATABASE_URL") }

// ── 账号与组织（纯团队中心：注册不自动建个人 Org）──────────
model User {
  id             String   @id @default(uuid())
  email          String   @unique                       // 应用层小写归一（不引入 citext 扩展）
  passwordHash   String?  @map("password_hash")         // 可空：SSO 用户无密码
  name           String?
  // —— SSO（SAML）字段 ——
  authType       String   @default("password") @map("auth_type")   // password | saml
  ssoProvider    String?  @map("sso_provider")                    // 如 "guanghua"
  ssoNameId      String?  @unique @map("sso_name_id")             // SAML NameID
  ssoAttributes  Json?    @map("sso_attributes") @db.JsonB
  lastSsoLoginAt DateTime? @map("last_sso_login_at")
  createdAt      DateTime @default(now()) @map("created_at")
  memberships    OrgMembership[]
  joinRequests   JoinRequest[]
  @@map("users")
}

model Organization {
  id        String   @id @default(uuid())
  name      String
  slug      String   @unique
  createdBy String   @map("created_by")
  createdAt DateTime @default(now()) @map("created_at")
  members   OrgMembership[]
  projects  Project[]
  joinRequests JoinRequest[]
  @@map("organizations")
}

// 团队加入申请（用户主动申请 → owner 审批 → 通过成 member）
model JoinRequest {
  id         String   @id @default(uuid())
  orgId      String   @map("org_id")
  userId     String   @map("user_id")
  message    String?                          // 申请留言
  status     String   @default("pending")     // pending | approved | rejected
  resolvedBy String?  @map("resolved_by")
  createdAt  DateTime @default(now()) @map("created_at")
  resolvedAt DateTime? @map("resolved_at")
  org        Organization @relation(fields: [orgId], references: [id])
  user       User         @relation(fields: [userId], references: [id])
  @@unique([orgId, userId])
  @@map("join_requests")
}

model OrgMembership {
  orgId    String @map("org_id")
  userId   String @map("user_id")
  role     String // owner | member
  createdAt DateTime @default(now()) @map("created_at")
  org      Organization @relation(fields: [orgId], references: [id])
  user     User         @relation(fields: [userId], references: [id])
  @@id([orgId, userId])
  @@map("org_memberships")
}

// ── 项目与 API Key ──────────────────────────────────────
model Project {
  id              String    @id @default(uuid())
  orgId           String    @map("org_id")
  slug            String
  name            String
  description     String?
  defaultRuleSet  String?   @map("default_rule_set")
  defaultTaskSet  String?   @map("default_task_set")
  retentionDays   Int?      @map("retention_days")
  createdBy       String    @map("created_by")
  createdAt       DateTime  @default(now()) @map("created_at")
  archivedAt      DateTime? @map("archived_at")
  org             Organization @relation(fields: [orgId], references: [id])
  apiKeys         ApiKey[]
  runs            Run[]
  @@unique([orgId, slug])
  @@map("projects")
}

model ApiKey {
  id           String    @id @default(uuid())
  projectId    String    @map("project_id")
  publicKey    String    @unique @map("public_key") // pk-eval-...
  secretHash   String    @map("secret_hash")        // 哈希态：审计/不回显
  secretEncrypted String @map("secret_encrypted")   // 加密态：HMAC 验签（§6.3 方案 A，明文永不落库）
  name         String
  scopes       String[]  @default(["ingest"])
  expiresAt    DateTime? @map("expires_at")
  lastUsedAt   DateTime? @map("last_used_at")
  lastIp       String?   @map("last_ip")
  callCount    BigInt    @default(0) @map("call_count")
  createdBy    String    @map("created_by")
  createdAt    DateTime  @default(now()) @map("created_at")
  revokedAt    DateTime? @map("revoked_at")
  project      Project   @relation(fields: [projectId], references: [id])
  @@index([projectId])
  @@map("api_keys")
}

// ── 评估数据 ────────────────────────────────────────────
model Run {
  id              String   @id @default(uuid())
  projectId       String   @map("project_id")
  externalRunId   String   @map("external_run_id")  // 评估器 run_id
  mode            String                            // eval_only | run | pipeline
  status          String   @default("completed")    // running|completed|failed|partial
  totalSamples    Int      @default(0) @map("total_samples")
  // 一等指标列（聚合/索引友好）
  dr              Float
  cpr             Float
  avgReward       Float    @map("avg_reward")
  avgSoft         Float    @default(0) @map("avg_soft")
  avgPref         Float    @default(0) @map("avg_pref")
  condR           Float    @map("cond_r")
  avgTimeMs       Float    @map("avg_time_ms")
  ruleSetVersion  String?  @map("rule_set_version")
  sutVersion      String?  @map("sut_version")
  langfuseTraceId String?  @map("langfuse_trace_id")
  langfuseHost    String?  @map("langfuse_host")
  failureBreakdown Json?   @map("failure_breakdown") @db.JsonB
  thresholds      Json?    @db.JsonB
  sourceClient    String?  @map("source_client")
  createdAt       DateTime @default(now()) @map("created_at") // = 评估运行时间
  finishedAt      DateTime? @map("finished_at")
  project         Project  @relation(fields: [projectId], references: [id])
  samples         Sample[]
  artifacts       Artifact[]
  @@unique([projectId, externalRunId])
  @@index([projectId, createdAt(sort: Desc)])
  @@map("runs")
}

model Sample {
  id                String   @id @default(uuid())
  runId             String   @map("run_id")
  projectId         String   @map("project_id")        // 反范式便于隔离过滤
  externalSampleId  String   @map("external_sample_id") // task_id/sample_id（逻辑课件标识，跨版本稳定）
  contentHash       String?  @map("content_hash")       // 内容指纹（版本标记，不参与唯一键，走势点可标注内容变更）
  status            String
  sFormat           Float    @map("s_format")
  sCommon           Float    @map("s_common")
  sSoft             Float    @map("s_soft")
  sPref             Float    @map("s_pref")
  reward            Float
  totalDurationMs   Float    @map("total_duration_ms")
  llmCalls          Int      @default(0) @map("llm_calls")
  tokenUsage        Int      @default(0) @map("token_usage")
  extra             Json?    @db.JsonB                  // module_results 等
  run               Run      @relation(fields: [runId], references: [id])
  constraintResults ConstraintResult[]
  artifacts         Artifact[]
  @@unique([runId, externalSampleId])
  @@index([projectId, externalSampleId])
  @@map("samples")
}

model ConstraintResult {
  id                 String   @id @default(uuid())
  sampleId           String   @map("sample_id")
  projectId          String   @map("project_id")
  constraintId       String   @map("constraint_id")
  ruleId             String?  @map("rule_id")
  name               String
  tier               String                              // hard_gate|hard_score|soft|preference（与评估器 ConstraintTier 四档对齐）
  status             String                              // pass|fail|skip|error
  passed             Boolean
  score              Float
  rawScore           Float?   @map("raw_score")
  reason             String
  durationMs         Float    @map("duration_ms")
  judgeProvider      String?  @map("judge_provider")
  judgeModel         String?  @map("judge_model")
  judgeArtifactId    String?  @map("judge_artifact_id")
  details            Json?    @db.JsonB
  moduleResults      Json?    @map("module_results") @db.JsonB
  sample             Sample   @relation(fields: [sampleId], references: [id])
  @@index([sampleId])
  @@index([projectId, constraintId])
  @@map("constraint_results")
}

model DimensionScore {           // scores.json dimensions，预留扩展
  id          String @id @default(uuid())
  sampleId    String @map("sample_id")
  dimensionId String @map("dimension_id")
  name        String
  weight      Float
  score       Float
  status      String
  @@index([sampleId])
  @@map("dimension_scores")
}

model Artifact {
  id           String   @id @default(uuid())
  projectId    String   @map("project_id")
  runId        String   @map("run_id")
  sampleId     String?  @map("sample_id")
  kind         String   // screenshot|judge_record|output|trace|manifest
  objectKey    String   @map("object_key")
  storage      String   // s3|cos|minio
  contentType  String   @map("content_type")
  sizeBytes    BigInt   @map("size_bytes")
  md5          String?
  originalName String?  @map("original_name")
  createdAt    DateTime @default(now()) @map("created_at")
  @@index([runId])
  @@index([sampleId])
  @@map("artifacts")
}

model AuditLog {
  id          BigInt   @id @default(autoincrement())
  orgId       String?  @map("org_id")
  actorUserId String?  @map("actor_user_id")
  action      String   // key.create|key.revoke|project.archive|member.invite...
  targetType  String?  @map("target_type")
  targetId    String?  @map("target_id")
  metadata    Json?    @db.JsonB
  createdAt   DateTime @default(now()) @map("created_at")
  @@index([orgId, createdAt(sort: Desc)])
  @@map("audit_logs")
}
```

> 幂等约束补充：Ingestion 事件级幂等不靠业务表唯一键（一个 run/sample 由多条事件分批到达），而是用独立的 `ingest_events` 去重表（见 §7.2）。上表中的 `@@unique([projectId, externalRunId])` 与 `@@unique([runId, externalSampleId])` 是**业务级**幂等兜底。

### 4.2 索引设计要点

- 趋势/看板：`runs(project_id, created_at DESC)` 直接支撑"项目最近 N 次运行"与趋势聚合。
- 详情钻取：`samples(run_id)`、`constraint_results(sample_id)` 支撑运行详情→任务详情→约束三级钻取。
- 失败聚合：`constraint_results(project_id, constraint_id)` 支撑"最常失败约束 TopN"。
- 鉴权：`api_keys(public_key) UNIQUE` 支撑 O(1) 鉴权查找。
- 可选物化视图 `project_trends_mv`：周期刷新 `(project_id, created_at, dr, cpr, avg_reward)`，加速大盘（Sprint 7g）。

### 4.3 迁移策略

- **Prisma Migrate**：`prisma migrate dev`（开发）/ `prisma migrate deploy`（CI/生产），schema 变更版本化、可回滚（生成 down 脚本由 CI 管理）。日常变更走 `prisma migrate dev --create-only`（生成 SQL 不执行）→ 手动跑 SQL → `prisma migrate resolve --applied`（见 `prisma/README.md`）。
- **本地建库（`make db-init`）**：起栈后 postgres 为空库，手动 `make db-init`（`scripts/db-init.sh`）按时间戳顺序应用 prisma migration SQL + `prisma migrate resolve --applied` + `prisma generate`；**单一来源 = prisma migrations，已废弃 `schema.sql` 自动建表**。线上库（腾讯云 CDB）迁移同理手动 deploy。
- **JSONB 优先于加列**：`details`/`failure_breakdown`/`thresholds`/`extra`/`moduleResults` 等半结构化字段用 JSONB，避免评估模型迭代时频繁改表。
- **一等列仅给"要索引/聚合"的字段**：DR/CPR/Reward 等核心指标落列，其余 JSONB。

### 4.4 serverless 连接池

腾讯云函数为短连接、高并发，PG 直连会撑爆连接数。方案：DB 前置 **PgBouncer**（transaction 模式），`PLATFORM_DATABASE_URL` 带 `?pgbouncer=true&connection_limit=1`；Prisma 该参数下可正常工作。云 PG 若提供 Serverless Data API 亦可作为备选。

---

## 五、对象存储抽象

### 5.1 接口

```ts
// src/infra/objectStorage.ts
interface ObjectStorage {
  presignPut(opts: { key: string; contentType: string; md5?: string; ttlSec: number })
    : Promise<{ url: string; method: "PUT"; headers: Record<string,string>; expiresAt: number }>;
  presignGet(opts: { key: string; ttlSec: number }): Promise<{ url: string; expiresAt: number }>;
  put(opts: { key: string; body: Buffer; contentType: string }): Promise<{ md5: string; size: number }>; // 服务端兜底直传（小文件/测试）
  get(opts: { key: string }): Promise<Buffer>;
  head(opts: { key: string }): Promise<{ size: number; contentType: string } | null>;
  deleteObjects(opts: { keys: string[] }): Promise<void>;   // 批量删除（项目/运行删除时回收制品，分批 1000）
}
```

工厂按 `PLATFORM_OBJECT_STORAGE`（`minio`/`s3`/`cos`）返回实现；三者均兼容 S3 协议，差别仅在 endpoint/签名版本配置。COS/SCF 场景下 presigned URL 的签名 host 与浏览器可达域名可能不一致，故 S3 实现内部维护 `client`（内部读写）与 `presignClient`（对外签名，`externalEndpoint`）两个 S3Client。

### 5.2 布局与隔离

```
projects/{project_id}/runs/{run_id}/artifacts/{kind}/{name}
```

- 前缀含 `project_id`，下载签发时由 `tenantGuard` 校验调用者对该项目的访问权。
- 制品不直接暴露公共 URL，一律经 presigned GET（短时效 ≤ 15min）。

### 5.3 两段式上传流程

```
评估器                                平台                          对象存储
  │  POST /artifacts/url (元信息)        │                              │
  ├────────────────────────────────────>│ 校验项目/配额/大小上限          │
  │                                     ├─ presignPut(key, ttl=900) ───►│
  │  { object_key, upload_url, headers }│<─────────────────────────────┤
  │<────────────────────────────────────┤                              │
  │  PUT upload_url (二进制, MD5 校验)                                  │
  ├──────────────────────────────────────────────────────────────────►│
  │  200 / ETag                                                         │
  │<───────────────────────────────────────────────────────────────────┤
  │  POST /ingest 事件 type=artifact (object_key, md5, size)            │
  ├────────────────────────────────────>│ HEAD key 校验存在/大小/MD5      │
  │                                     │ 写 artifacts 行                │
```

> 制品上传失败可独立重试，不阻塞结构化事件：先发 `run/sample/constraint` 事件（其中 `judge_record_object_key` 可暂留 null 占位），制品补传成功后再发 `artifact` 事件回填引用（F-O-INGEST-06 / NF-O-06）。

### 5.4 制品预览代理（同源 raw + 专用 token）

制品在浏览器内嵌预览（iframe / fetch）有两个坑：① COS 默认 `Content-Disposition: attachment` 会触发下载；② `response-*` 覆盖在 COS 默认域名失效。故除下载用的 presigned 重定向外，新增**同源预览代理**：

| 端点 | 用途 | 鉴权 |
|------|------|------|
| `GET /artifacts/:id` | 下载/新窗口，302 → presigned GET（attachment 语义） | JWT + `artifactGuard` |
| `GET /artifacts/:id/preview` | 返回预览 URL + 元信息（JSON）：image → COS presigned 直链；html/text/trace → 同源 raw 代理 URL | JWT + `artifactGuard` |
| `GET /artifacts/:id/raw?token=` | 同源流式代理：拉对象后强制 `inline` + 正确 `Content-Type` 回吐 | **专用短期 artifact token**（TTL 5min，preview 端点签发） |

> iframe 导航不带 `Authorization` 头，故 raw 代理不能复用 JWT，改由 preview 端点签发专用短期 token（`issueArtifactToken` / `verifyArtifactToken`）；token 绑定 `artifactId` + `objectKey`，校验 `claims.aid === :id` 防越权。image 走 presigned 直链是为了省函数流量、规避 SCF 响应大小上限。

---

## 六、认证与多租户

### 6.1 团队中心模型（RBAC）

```
注册 → User（不自动建个人 Org）
         │ ① POST /orgs 创建团队  ──> Organization ──owner──> Project ──owns──> ApiKey
         │ ② 或申请加入已有团队（JoinRequest）──owner 审批──> OrgMembership(member)
```

- **纯团队中心**：注册仅建 `User`，无个人 Org；新用户登录后无团队，需 `POST /orgs` 创建团队，或申请加入已有团队（`JoinRequest`，owner 审批通过成 `member`）。
- 组织内角色：`owner`（管理成员/项目/Key、审批加入申请）、`member`（查看与使用）。
- `tenantGuard` **不依赖 token 中的 orgId**：以 DB membership 为准校验"用户是否属于该组织/有权访问该项目"，越权直接 403/404。
- API Key 绑定**单一项目**，仅 `ingest` scope（写权限限定本项目）。
- Web 查看权限：默认组织内成员可见组织下所有项目（本期）；远期可按项目授权。

### 6.2 JWT（Web 侧）

- 登录：`POST /api/auth/login` 校验密码 → 签发 `access_token`（短期，含 `userId/orgId/role`）+ `refresh_token`（长期）。
- 中间件 `auth.js` 解析 access_token → 注入 `req.user`；过期则前端用 refresh_token 刷新。
- 敏感操作（吊销 Key、删除/归档项目、邀请成员）可要求 recent login（`auth_time` 校验）。

### 6.3 API Key 与 HMAC 签名（Ingestion 侧）

**签名算法**（评估器与平台必须一致）：

```
canonical_string = METHOD + "\n" + PATH + "\n" + sha256(body)
signature        = hex( HMAC_SHA256(secret_key, canonical_string) )
Authorization    = "Eval " + public_key + ":" + signature
```

- `METHOD`：大写 HTTP 方法（`POST`）。
- `PATH`：请求路径（不含 query），如 `/api/public/ingest`。
- `body`：请求体字节（与发送字节严格一致，客户端须用相同字节计算）。
- 平台按 `public_key` 查 `api_keys.secret_hash`——注意：**HMAC 验签需要原 secret**，故 `api_keys` 需存可逆形态。两种取法：
  - **方案 A（推荐，本期）**：`secret_hash` 存 secret 的**哈希用于"泄露检测/不回显"**，另存 `secret_encrypted`（服务端密钥对称加密，`PLATFORM_KEY_ENCRYPTION_KEY`）用于验签；secret 明文永不落库、永不回显。
  - 方案 B（简化退路）：用 `Bearer pk:sk` 明文头，平台仅存哈希做"使用记录"，secret 不验签——安全性弱，仅用于早期联调。

**验签步骤**（`apiKeyAuth.js`）：
1. 解析 `Authorization` 得 `public_key` + `signature`。
2. 查 `api_keys`：存在、未吊销、未过期、scope 含 `ingest`。
3. 用 `secret_encrypted` 解密得 secret，重算 HMAC，常量时间比较。
4. 通过 → 注入 `req.tenant = { projectId, apiKeyId }`；失败 → `401 AUTH_INVALID`。
5. 更新 `last_used_at` / `call_count` / `last_ip`（异步，不阻塞）。

**防重放**：body 哈希入签已覆盖请求完整性；如需更强防重放，加 `X-Eval-Timestamp` 头并纳入 canonical string + 服务端时间窗校验（±5min）。本期可选。

### 6.4 隔离实现

- **中间件 `tenantGuard`**：解析 `req.user`（JWT）或 `req.tenant`（API Key），解析出 `{ orgId?, projectId?, role? }` 挂到 `req.tenant`；Query/管理路由据此校验"用户是否属于该组织/有权访问该项目"，越权直接 403/404（不泄露存在性）。
- **Repository 强制过滤**：`base.repository.js` 构造接收 `tenant`，所有 `find*` 自动追加 `WHERE org_id/project_id`；约束在数据层，业务层无法绕过。
- **对象存储**：下载签发前校验 `object_key` 的 `project_id` 前缀属于 `req.tenant`。
- **API Key 跨项目写**：`ingest.service` 以 `req.tenant.projectId`（来自 Key）为准，忽略/拒绝 payload 里的他项目 `project_id`（`403 PROJECT_FORBIDDEN`）。

### 6.5 审计日志

`AuditService.log(action, target, metadata)` 在 key/project/org/member 敏感操作处调用，落 `audit_logs` 表，管理页可查（F-O-OPS-03）。

### 6.6 SAML SSO 登录

接入企业 IdP（光华平台）的 SAML 2.0 登录，与密码登录并存：

| 端点 | 用途 |
|------|------|
| `GET /auth/sso/config` | 返回 IdP 元信息（entrySSOUrl / issuer），前端渲染 SSO Tab |
| `POST /auth/sso/login` | 生成 `AuthnRequest`（含防重放 state）并重定向到 IdP |
| `POST /auth/sso/acs` | Assertion Consumer Service：校验 SAML Response → 匹配/建号 → 签发一次性 code |
| `POST /auth/sso/exchange` | 用一次性 code 换 JWT（access + refresh） |

- **建号策略**：按 `ssoNameId` 匹配现有 User；未匹配则自动建 `authType=saml` 用户（`passwordHash` 为空）。
- **SSO-only 用户禁止密码登录**：`passwordHash` 为空时密码登录接口直接拒绝。
- `User` 表的 SSO 字段（`authType` / `ssoProvider` / `ssoNameId` / `ssoAttributes` / `lastSsoLoginAt`）见 §四.1。
- 前端登录页提供「密码 / SSO」Tab 切换（见 §十）。

---

## 七、摄取服务（Ingestion）

### 7.1 事件 schema v1.0

请求信封（`POST /api/public/ingest`，HMAC 鉴权）：

```jsonc
{
  "schema_version": "1.0",
  "batch_id": "client-uuid",          // 整批幂等键（可选，可 null）
  "project_id": "uuid-or-slug",       // 可选，可 null；缺省/null = Key 所属项目
  "events": [ /* run | sample | constraint | artifact */ ]
}
```

各事件公共字段：`event_id`（客户端 UUID，幂等键，必填）、`type`、`data`。

| type | data 关键字段 | 来源映射（评估器侧） |
|------|--------------|----------------------|
| `run` | `external_run_id, mode, created_at, finished_at, metrics{DR,CPR,avg_reward,condR,avg_time_ms}, total_samples, rule_set_version, sut_version, failure_breakdown, thresholds` | `run_manifest.json` + `summary.json(MetricsReport)` |
| `sample` | `external_sample_id, status, s_format, s_common, s_soft, s_pref, reward, total_duration_ms, llm_calls, token_usage, dimensions` | `SampleResult.to_dict()` + `scores.json` |
| `constraint` | `external_sample_id, constraint_id, rule_id, name, tier, status, passed, score, raw_score, reason, details, duration_ms, judge_provider, judge_model, judge_record_object_key, module_results` | `rule_results.json[]` 元素（ConstraintResult） |
| `artifact` | `external_run_id, external_sample_id?, kind, object_key, content_type, size_bytes, md5, original_name, linked_constraint_id?` | 制品上传后的引用 |

> run/sample 事件可携带 `langfuse_trace_id`/`langfuse_host`（run 顶级字段）。

JSON Schema（`src/schemas/ingest.event.v1.json`）逐类型校验：必填、类型、枚举（`tier`/`status`/`mode`/`kind`）、数值范围。
- `tier` 枚举须与评估器 `ConstraintTier` 四档完全一致：`hard_gate | hard_score | soft | preference`（`hard_score` = 硬性评分，失败归零；曾因 schema 漏列该档导致真实评估被拒，已纳入回归测试）。
- `project_id`/`batch_id` 可为 `null`（未指定项目时用 Key 所属项目）。
**该 schema 文件同时拷贝到评估器 `evaluator/agent_eval/observability/schemas/`，作为双方契约并由 CI 校验一致性**（NF-O-13 防漂移）。

### 7.2 幂等去重

```prisma
model IngestEvent {           // 去重表
  id           BigInt  @id @default(autoincrement())
  projectId    String  @map("project_id")
  eventId      String  @map("event_id")
  type         String
  receivedAt   DateTime @default(now()) @map("received_at")
  @@unique([projectId, eventId])     // 幂等键
  @@index([projectId, receivedAt])
  @@map("ingest_events")
}
```

处理流程（`ingest.service.js`，单批一个事务）：
1. 校验全批 schema（ajv）；非法事件 → 收集到 `errors[]`，不中断合法事件。
2. 对每个事件：`INSERT ... ON CONFLICT (project_id, event_id) DO NOTHING` 到 `ingest_events`；若冲突 → 计入 `duplicates`，跳过业务写入。
3. 新事件按 type 路由到 repository 的 **upsert**：
   - `run` → `run.repo.upsert(projectId, externalRunId, ...)`
   - `sample` → 需其 `run` 已存在（按 `external_run_id` 解析 runId），否则暂存待重放或拒绝
   - `constraint` → 需其 `sample` 已存在
   - `artifact` → 校验对象存在（HEAD）后写 `artifacts` 行，并回填关联约束的 `judge_artifact_id`
4. 返回 `{ accepted, duplicates, errors }`。

> upsert + 去重表 = at-least-once 投递下的精确一次生效。乱序到达（constraint 先于 sample）由"依赖缺失则返回错误让客户端重试"或"服务端暂存补齐"处理；本期采用前者（实现简单，客户端本就按 run→sample→constraint 顺序发送）。

### 7.3 schema 校验

- `ajv` 编译 JSON Schema，**两阶段**校验（`src/schemas/validate.ts`）：
  1. **浅层信封**（`validateEnvelope`）：校验 `schema_version`/`events` 结构与每事件含 `event_id`/`type`/`data`；`project_id`/`batch_id` 可空。非法 → 整批 `400 SCHEMA_INVALID`。
  2. **逐事件深度**（`validateEvent`，按 `type` 走 `oneOf`+`discriminator` 分支）：必填/枚举/数值范围。单事件非法只计入 `errors[]`（HTTP 202 部分接受），不影响合法事件。
- ⚠️ 浅层与全量 schema 的可空性须一致（曾因浅层把 `project_id` 定义为不可空 `string`，致未设 `AGENT_EVAL_PROJECT` 的客户端 `project_id:null` 被拒，已修+回归）。
- `schema_version` 不兼容（如 `2.0` 到来而平台仅支持 `1.0`）→ 整批 `400 SCHEMA_VERSION_UNSUPPORTED` + 明确提示升级（错误码见 §7.5）。

### 7.4 限流与背压

- Ingestion 路由独立限流：按 `api_key` 维度（令牌桶），超限 `429` + `Retry-After`。
- 批量体积上限（默认 ≤ 500 事件 / 4MB body）；超限 `413 PAYLOAD_TOO_LARGE`，客户端分批。

### 7.5 错误码与响应

```jsonc
// 成功（部分接受）
HTTP 202
{ "accepted": 12, "duplicates": 1, "errors": [] }

// 部分事件非法
HTTP 202  // 合法的已入库
{ "accepted": 10, "duplicates": 0, "errors": [ { "event_id": "...", "code": "SCHEMA_INVALID", "message": "metrics.DR required" } ] }
```

| code | HTTP | 客户端动作 |
|------|------|-----------|
| `SCHEMA_INVALID` | 400/202 | 修正后重发该事件 |
| `AUTH_INVALID` | 401 | 检查 key/签名 |
| `PROJECT_FORBIDDEN` | 403 | 校正 project |
| `SCHEMA_VERSION_UNSUPPORTED` | 400 | 升级 agent-eval |
| `RATE_LIMITED` | 429 | 退避重试 |
| `PAYLOAD_TOO_LARGE` | 413 | 分批 |
| `DEPENDENCY_MISSING` | 409 | sample/constraint 依赖未到，按原序重试 |
| `INTERNAL` | 500 | 指数退避重试 |

### 7.6 摄取时序（端到端）

```
评估器 ResultSink                        平台 Ingestion                 对象存储
  │ eval 完成，拼装事件                     │                              │
  │ 对每个大制品: POST /artifacts/url       │                              │
  ├───────────────────────────────────────>│ presignPut ──────────────────>│
  │<───────────────────────────────────────┤                              │
  │ PUT 制品                                                              │
  ├──────────────────────────────────────────────────────────────────────>│
  │ POST /ingest [run,sample,constraint,artifact 事件]                    │
  ├───────────────────────────────────────>│ schema 校验                  │
  │                                        │ 去重 + upsert(事务)           │
  │                                        │ artifact HEAD 校验            │
  │                                        │ 回填 judge_artifact_id        │
  │  202 {accepted, duplicates, errors}    │                              │
  │<───────────────────────────────────────┤                              │
```

---

## 八、评估器对接（ResultSink）

### 8.1 模块结构（evaluator/ 下）

```
evaluator/agent_eval/observability/
  __init__.py
  sink.py            # ResultSink：编排拼装→上传制品→发事件→失败入队
  client.py          # IngestionClient：HTTP + HMAC 签名 + presigned + 重试退避
  queue.py           # 离线队列（SQLite）+ 重放 + 死信
  events.py          # 现有模型 → 事件 dict 映射
  config.py          # 读 AGENT_EVAL_* env
  schemas/           # 与后端共享的 JSON Schema（契约）
```

### 8.2 现有模型 → 事件映射

| 评估器对象 | 事件 | 映射要点 |
|-----------|------|---------|
| `run_manifest.json` + `MetricsReport` | `run` | `run_id → external_run_id`；`metrics → DR/CPR/...`；`failure_breakdown/thresholds` 直传 |
| `SampleResult` + `scores.json` | `sample` | `sample_id → external_sample_id`；`s_format/s_common/s_soft/s_pref/reward` 直传；`dimensions` 从 scores.json |
| `ConstraintResult`（rule_results.json 元素） | `constraint` | `constraint_id/rule_id/name/tier/status/passed/score/reason/details/duration_ms/judge_*` 直传；`judge_record_path → judge_record_object_key`（制品上传后替换） |
| 截图 / 原始产出物 / JudgeRecord / trace.json | `artifact` | 上传后生成 `object_key`，附 `kind/md5/size/content_type` |
| Langfuse `trace_id` | run 字段 | `tracing.get_current_trace_id()` 透传 |

> **字段名对齐**：评估器序列化的 `passed`/`rule_id`（见现状 `rule_results.json`）与 dataclass `to_dict` 的 `status`/`constraint_id` 存在差异——`events.py` 统一以**事件 schema**为准输出，兼容两种来源，确保后端只认 schema。

### 8.3 HMAC 客户端（`client.py`）

```python
def sign(method, path, body: bytes, secret: str) -> str:
    canon = f"{method.upper()}\n{path}\n{hashlib.sha256(body).hexdigest()}"
    return hmac.new(secret.encode(), canon.encode(), hashlib.sha256).hexdigest()

def post_ingest(events, *, public_key, secret_key, host):
    body = json.dumps({"schema_version":"1.0","events":events}, separators=(",",":")).encode()
    sig = sign("POST","/api/public/ingest", body, secret_key)
    headers = {"Authorization": f"Eval {public_key}:{sig}",
               "Content-Type":"application/json", "X-Eval-Client": client_version()}
    # 指数退避重试（429/5xx），尊重 Retry-After
```

### 8.4 离线队列与重放（`queue.py`）

- 队列存储：`workspace/.ingest_queue/queue.sqlite`（表 `pending_events(id, payload, attempts, last_error, next_retry_at)`）。
- 发送失败（网络/5xx/429）→ 入队；后台线程/下次 eval 启动时重放。
- 退避：指数退避 + 抖动；超过阈值（默认 7 天或 attempts 上限）→ 死信区，终端告警。
- 制品上传与事件发送解耦：制品上传失败的制品引用不随事件发送（留 null），后续补传。

### 8.5 双写与 trace_id 透传

- 双写（默认开启上传时）：eval 同时写本地 workspace 文件 + 推平台，便于灰度对账（F-O-MIGR-03）。
- `--no-local`：仅推平台。
- trace_id：eval 流程中 `tracing.create_trace` 返回的 trace_id，由 ResultSink 注入 run 事件 `langfuse_trace_id` + `langfuse_host`。

### 8.6 调用时机与 CLI

- 时机：`cli.py` 的 `eval` 命令，在 `flush_traces()` 之后调用 `ResultSink.flush(eval_result)`；配置 `--upload` 或 env 启用则触发，否则跳过。
- 健康检查：ResultSink 初始化时 `GET /api/public/health`，凭据/地址错误 → 明确告警，不静默失败（F-O-INGEST-08）。
- CLI：
  - `agent-eval eval ... [--upload|--no-upload]`
  - `agent-eval upload [--workspace ./workspace] [--project <slug>] [--run <id>]`（回填历史）

---

## 九、Query API 与聚合

### 9.1 端点（JWT 鉴权，`tenantGuard` 注入过滤）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/orgs/:org/projects` | 组织下项目看板（每项目最新运行、运行总数、创建者） |
| GET | `/api/projects/:id` | 项目详情 |
| GET | `/api/projects/:id/runs` | 运行列表（`?mode&rule_set_version&from&to&order&page&size`） |
| GET | `/api/projects/:id/trends` | Run 级趋势（`?from&to&limit`） |
| GET | `/api/projects/:id/samples` | 样本清单（distinct `externalSampleId` + 评估次数 + 最近指标） |
| GET | `/api/projects/:id/sample-trends` | 样本级走势（`?sample_id&limit`，某样本跨 run 指标时序） |
| GET | `/api/runs/:id` | 运行详情 |
| GET | `/api/runs/:id/samples/:sid` | 样本详情（约束 + 溯源 + 制品） |
| DELETE | `/api/projects/:id` | 永久删除项目（owner；DB 级联 + 对象存储回收 + 审计） |
| DELETE | `/api/runs/:id` | 永久删除运行（owner；同上） |
| GET | `/api/artifacts/:id` | 制品下载（presigned 重定向） |
| GET | `/api/artifacts/:id/preview` | 制品预览元信息（image 直链 / 其余同源 raw 代理 URL） |
| GET | `/api/artifacts/:id/raw` | 制品同源流式代理（专用 artifact token 鉴权，见 §5.4） |

### 9.2 趋势聚合 SQL（示例）

```sql
SELECT external_run_id AS run_id,
       created_at,
       dr AS "DR", cpr AS "CPR", avg_reward AS "Reward",
       avg_soft AS "Soft", avg_pref AS "Pref"
FROM runs
WHERE project_id = $1
  AND project_id IN (SELECT id FROM projects WHERE org_id = $2)   -- orgId 双层隔离
  AND created_at BETWEEN $3 AND $4
ORDER BY created_at ASC
LIMIT $5;
```

> 因核心指标已为一等列（含 `avg_soft`/`avg_pref`），趋势查询走索引扫描，无需 JSONB 解包；`project_id IN (org 的 projects)` 是租户隔离的强制条件（与 §六.4 同范式），越权 404。

### 9.3 物化视图（可选，Sprint 7g）

```sql
CREATE MATERIALIZED VIEW project_trends_mv AS
SELECT project_id, date_trunc('day', created_at) AS day,
       avg(dr) AS dr, avg(cpr) AS cpr, avg(avg_reward) AS reward, count(*) AS runs
FROM runs GROUP BY project_id, day;
CREATE INDEX ON project_trends_mv (project_id, day);
-- REFRESH MATERIALIZED VIEW CONCURRENTLY project_trends_mv;  （定时任务）
```

### 9.4 样本级走势（Run 级 vs Sample 级）

走势分两个粒度，二者并存、互不替代：

| 走势类型 | 粒度 | 主指标 | 数据来源 |
|----------|------|--------|----------|
| Run 走势（§9.2） | Run（一次评估） | DR / CPR / Reward（跨样本聚合率） | `runs` 表 |
| **样本走势** | Sample（一个样本） | `reward`（综合评分）+ `s_format`/`s_common` 达标 | `samples` 表，按 `externalSampleId` 跨 run 聚合 |

> 单 Project 多样本是生产常态（API Key 一次配置、绑定单一 Project，同 Project 下评估多个样本）。Run 走势看整体水位，**样本走势看每个样本随时间的演进**。样本以 `externalSampleId`（**逻辑课件标识**，跨版本稳定）为唯一键聚合；内容变更（课件优化）记录在 `content_hash`、不改变 `sample_id`，故同课件走势连续——内容哈希会随优化而变，不能作为聚合键。

**样本清单 SQL**（`GET /projects/:id/samples`，窗口函数取每个样本最近一次评估）：

```sql
WITH ranked AS (
  SELECT s.external_sample_id, s.reward, s.status, s.content_hash, r.created_at,
         COUNT(*) OVER (PARTITION BY s.external_sample_id)::bigint AS eval_count,
         ROW_NUMBER() OVER (PARTITION BY s.external_sample_id ORDER BY r.created_at DESC) AS rn
  FROM samples s JOIN runs r ON s.run_id = r.id
  WHERE s.project_id = $1
    AND s.project_id IN (SELECT id FROM projects WHERE org_id = $2)
)
SELECT external_sample_id, eval_count, created_at, reward, status, content_hash
FROM ranked WHERE rn = 1
ORDER BY created_at DESC;
```

**样本走势 SQL**（`GET /projects/:id/sample-trends?sample_id=<externalSampleId>`）：

```sql
SELECT r.external_run_id AS run_id, r.created_at,
       s.reward, s.s_format, s.s_common, s.s_soft, s.s_pref, s.status, s.content_hash
FROM samples s JOIN runs r ON s.run_id = r.id
WHERE s.project_id = $1
  AND s.external_sample_id = $2
  AND s.project_id IN (SELECT id FROM projects WHERE org_id = $3)
ORDER BY r.created_at ASC
LIMIT $4;
```

> 样本走势主轴用 `reward`（连续综合分，能反映样本质量随迭代/规则演进的变化）；单样本的 DR/CPR 是布尔值、走势呈 0/1 阶跃、信息量低，故仅作 `s_format`/`s_common` 达标辅助。隔离仍由 `project_id IN (org 的 projects)` 强制（与 §9.2 同范式），越权 404。

---

## 十、前端改造

- **登录态**：独立「登录页 / 注册页 / 团队加入页」三页面；登录页提供「密码 / SSO」Tab 切换（SSO 流程：GET config → POST login → ACS callback → POST exchange）；`App.tsx` 顶层路由守卫，无 token 跳登录；axios 拦截器自动刷新 access_token。
- **团队中心流程**：注册成功后若无团队，引导「创建团队」或「发现团队并申请加入」（`join_requests`）；顶栏组织切换器，切换后写入 context，所有 API 调用带上当前 `org/project`。
- **API client**：`src/api/client.ts` 调用 Query API（连 DB，不再读 workspace 文件）；TS 类型定义 Project / RunSummary / TrendDataPoint / SampleSummary / SampleTrendPoint 等。
- **页面映射**：ProjectList/ProjectDetail/RunDetail/TaskDetail 等页面**新建**（Sprint 7a 的本地查看器前端已移除），数据源为 Query API；目录模式（DirectoryTree/ModuleScoreTable）按 `module_results` 字段切换。
- **样本 Tab（项目页）**：项目页新增「样本」Tab——样本清单表（`externalSampleId` / 最近评估时间 / 最近 Reward / 评估次数 / 状态 / 内容版本）；点样本进入样本走势视图：该样本 `reward` 跨 run 走势图（复用 LineChart）+ 历次评估明细表（时间 / run / reward / s_format / s_common / 状态 / `content_hash`）。与运行视图互补：运行视图看「每次评估评了什么」，样本视图看「每个样本随时间的演进」。
- **制品预览**：任务详情页对 `artifact.kind`（screenshot/judge_record/output）提供预览，经 `GET /api/artifacts/:id/preview` 取 URL——image 走 presigned 直链，html/text/trace 走同源 raw 代理（`/raw?token=`，见 §5.4）。
- **Langfuse 跳转**：运行/任务详情页，若 `langfuse_trace_id` 存在，渲染"在 Langfuse 查看"按钮 → `${langfuse_host}/trace/${langfuse_trace_id}`。
- **危险操作**：项目/运行永久删除置于「危险区」，需输入项目 slug 二次确认（owner only）。

---

## 十一、数据迁移与回填

### 11.1 回填工具（`agent-eval upload`）

1. 遍历 `workspace/runs/{run_id}/`，读 `run_manifest.json` + `reports/summary.json` + `results/*/`。
2. 拼装 run/sample/constraint/artifact 事件。
3. 制品（JudgeRecord、截图、原始产出物）按 §5.3 两段式上传。
4. 经 Ingestion API 摄取（与正常 eval 同路径，复用 ResultSink）。

### 11.2 对账

- 脚本比对：本地 `summary.json` 的 DR/CPR/Reward 与 DB 中 `runs` 对应行一致；本地样本数与 DB `samples` 行数一致；制品数与 `artifacts` 行数一致。
- 差异输出报告，支撑双写灰度切换决策。

### 11.3 双写灰度

- 阶段一：eval 双写（本地 workspace + 平台），对账确认一致。
- 阶段二：前端（Sprint 7f 新建）连平台 Query API；遗留本地查看器已移除，`workspace/index/*.json` 不再被 Web 侧消费（仅供评估器/回填工具）。
- 阶段三：可选 `--no-local`，平台为权威。

---

## 十二、部署与运维

### 12.1 本地 Docker Compose

```yaml
# docker-compose.yml（平台）
services:
  postgres: { image: postgres:16, env: [POSTGRES_PASSWORD=...], volumes: ["pgdata:/var/lib/postgresql/data"] }
  minio:    { image: minio/minio, command: server /data, ports: ["9000:9000"], env: [MINIO_ROOT_USER=..., MINIO_ROOT_PASSWORD=...] }
  web: { build: ./web/backend, env_file: .env, ports: ["9000:9000"], depends_on: [postgres, minio] }
volumes: { pgdata: {} }
```

`PLATFORM_DATABASE_URL=postgresql://...@postgres:5432/eval`，`PLATFORM_OBJECT_STORAGE=minio`，指向 minio endpoint。

### 12.2 生产（腾讯云）

- Express → 云函数（SCF）/ 容器服务；经 API 网关 + HTTPS。
- PostgreSQL → 云数据库（前置 PgBouncer 或用 Serverless DB）。
- 对象存储 → COS（`PLATFORM_OBJECT_STORAGE=cos`）。
- 前端 → 构建产物由 Express 托管，或独立 CDN。

### 12.3 配置（环境变量）

| 变量 | 说明 |
|------|------|
| `PLATFORM_DATABASE_URL` | PG 连接串（含 `?pgbouncer=true`） |
| `PLATFORM_OBJECT_STORAGE` | `minio` / `s3` / `cos` |
| `PLATFORM_S3_ENDPOINT/REGION/BUCKET/ACCESS_KEY/SECRET_KEY` | 对象存储凭证（cos 用 S3 兼容 endpoint） |
| `PLATFORM_JWT_SECRET` | JWT 签名密钥 |
| `PLATFORM_KEY_ENCRYPTION_KEY` | API Key secret 对称加密密钥（§6.3 方案 A） |
| `PLATFORM_ALLOW_SIGNUP` | 是否开放注册（默认 true） |
| `PLATFORM_INGEST_RATE_LIMIT` | 摄取限流（令牌桶配额） |
| `PLATFORM_INGEST_MAX_BATCH` | 单批事件/体积上限 |
| `PLATFORM_RETENTION_DEFAULT_DAYS` | 项目默认保留天数 |

### 12.4 健康检查与监控

- `/health`：DB ping + 对象存储 ping + schema_version；供 K8s/SCF 探针。
- 平台自身指标：摄取 accepted/duplicated/errors 计数、队列长度、限流命中、DB 连接数（Prometheus `/metrics`，Sprint 7g）。

### 12.5 备份与保留期

- PG 定时逻辑备份（云 DB 快照）。
- 保留期：`retention_days` 到期的 Run 及其制品清理任务（cron/SCF 定时）；可选保留摘要行（`status=archived`、制品置空）。

---

## 十三、安全

- 密钥：secret 明文仅客户端持有；服务端存加密态用于验签 + 哈希态用于审计/不回显；轮换不中断（新旧并存至吊销）；吊销即时生效。
- 传输：生产强制 HTTPS；presigned URL 短时效（≤ 15min）。
- 脱敏：日志/错误对 key、邮箱掩码（`pk-eval-ab**`）。
- 输入校验：事件严格过 schema；非法不落库。
- 隔离：数据访问层强制过滤 + 越权集成测试（见 §十四）。
- 永久删除：项目/运行删除为 owner 专属，DB 级联 + 对象存储批量回收（`deleteObjects`）+ 审计日志，不可恢复（前端二次确认）。
- 制品预览 token：raw 代理专用短期 token（TTL 5min，绑定 `artifactId` + `objectKey`），不暴露长期凭证。
- 最小权限：API Key 仅 `ingest` + 仅本项目；Web 用户按组织/项目。

---

## 十四、测试策略

| 层级 | 范围 | 通过标准 |
|------|------|----------|
| 单元测试 | services / repositories / crypto(HMAC) / event 映射 | 覆盖率 ≥ 80% |
| 契约测试 | 评估器与后端共享 JSON Schema 一致性（CI diff 校验） | schema 漂移即 CI 失败 |
| 集成测试 | 摄取端到端（注册→建项目→签 key→eval→入库→查询） | 全链路通过 |
| 越权测试 | A 组织/B 用户枚举/直查/跨项目写、吊销 key 后写、过期 key | 全部被拒（403/401/404） |
| 幂等测试 | 重复 event_id / 重复 external_run_id | 不产生重复数据 |
| 可靠性测试 | 断网→入队→恢复→重放；429/5xx 退避 | 数据不丢失 |
| 性能测试 | 单 Run（500 样本/2000 约束）摄取；趋势查询 | 满足 NF-O-01/02/03 |

---

## 十五、版本记录

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v1.0 | 2026-06-16 | 初版：基于 [03Web 可观测平台重构需求](../requirement/03Web可观测平台重构需求.md) 给出分层架构、后端工程结构、Prisma 数据模型 DDL、对象存储抽象、JWT+HMAC 认证与多租户隔离、Ingestion 摄取服务（事件 schema/幂等/校验/限流/两段式制品上传）、评估器 ResultSink 对接、Query API 与聚合、前端改造、迁移回填、部署运维、安全与测试策略 |
| v1.1 | 2026-06-29 | 同步代码 + 合并原 14《样本级评估走势设计》：数据模型补 User SSO 字段 / `JoinRequest` / `ApiKey.secretEncrypted` / `Run.avgSoft,avgPref` / `Sample.contentHash`；§6.1 改团队中心模型（注册不自动建 Org + 申请审批），新增 §6.6 SAML SSO；§九 Query API 补 `samples`/`sample-trends`/DELETE 端点 + §9.4 样本级走势（Run 级 vs Sample 级，合并自原 doc 14）；§5.4 制品同源预览代理（raw + artifact token）；ObjectStorage 补 `deleteObjects`；§4.3 `make db-init` 替代 schema.sql；趋势 SQL 补 orgId 隔离 + Soft/Pref；前端补样本 Tab + 走势视图 + 登录/注册/加入页拆分 + SSO Tab |
