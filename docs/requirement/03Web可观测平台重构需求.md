# Web 可观测平台重构需求规格说明书（langfuse 式）

> 本文档基于 [02 Agent 能力评估系统需求规格说明书](./02Agent评估系统需求.md) 的 Web 可视化章节，针对 Sprint 7a（Web Portal MVP）已交付的现状，提出一次系统级重构：把 Web Portal 从"本地运行结果的只读查看器"升级为"仿 Langfuse 的多租户可观测后端"，覆盖**数据接收 → 持久化存储 → 多租户隔离 → 可视化呈现 → 评估器对接**的完整闭环。
>
> 本文档**推翻** `02Agent评估系统需求.md` 第十节"已确认决策记录"中的 **决策 #9（本阶段暂不考虑用户认证、权限与租户隔离）**，并取代其中 §4.5（Web 可视化与追溯）与 §8.3/§8.4 的相关描述。架构落地细节参见（将新增）`docs/arch/09Web可观测平台架构设计.md`。

---

## 一、引言

### 1.1 编写目的

为 Web 可观测平台的全面重构建立需求基线，使后续的数据库设计、后端服务、评估器对接、前端重接、部署运维都有据可依。本文档同时给出迭代计划的调整建议（§十一），用于指导 Sprint 7b 起的开发排期。

### 1.2 背景与现状

Sprint 7a 已交付 Web Portal MVP，技术栈为 React（前端）+ Express（后端），其数据来源是**直接读取本地 workspace 的 JSON 文件**：

| 现状能力 | 实现方式 | 局限 |
|----------|----------|------|
| 项目看板 | 读取 `workspace/index/projects.json` | 索引为平面 JSON 文件，无并发控制、无事务 |
| 运行列表/趋势 | 读取 `workspace/index/runs_index.json` | 趋势靠全量扫描 + 内存聚合，规模一上来即不可用 |
| 运行/任务详情 | 直接读 `workspace/runs/{run_id}/...` | 后端进程与评估器共享本地磁盘，强耦合、不可远程部署 |
| 索引维护 | `agent-eval index` 重建 | 无增量、无去重、无版本，文件损坏即数据丢失 |
| 认证/租户 | 无 | 任何人访问 `serve` 即可见全部数据 |
| 与评估器对接 | 无对接，靠"评估器写文件 → Web 读文件" | 评估器与 Web 必须同机同盘 |

这一形态距离"生产级、可远程部署、多团队共用"的可观测系统差距明显。

### 1.3 名词术语

| 术语 | 说明 |
|------|------|
| **可观测平台 / Observability Platform** | 本文档描述的重构后的 Web 系统，作为评估数据的接收、存储、查询与可视化后端。下文简称"平台"。 |
| **组织 / Organization** | 租户的顶层容器，含若干成员与若干项目。一个团队对应一个组织。 |
| **项目 / Project** | 组织下一组评估运行的隔离单元（对应"一个被测 Agent / 一个评估课题"）。项目是数据隔离的硬边界。 |
| **API Key（公钥 public_key / 私钥 secret_key）** | 评估器用于向平台写入数据的凭据，绑定到单一项目（类 Langfuse 的 project-scoped key）。公钥标识身份，私钥用于签名/鉴权，仅展示一次。 |
| **摄取 / Ingestion** | 评估器将评估结果通过网络 API 推送到平台的过程。 |
| **ResultSink / 摄取客户端** | Python 评估器侧负责拼装、鉴权、上传、重试的组件（`agent_eval/observability/sink.py`）。 |
| **事件 / Event** | 摄取协议中的最小数据单元（run / sample / constraint / artifact 四类），类比 Langfuse 的 trace/observation/score。 |
| **运行 / Run** | 一次 `agent-eval eval` 的完整结果集合（含汇总指标与若干样本）。 |
| **样本 / Sample** | Run 内的一个被测任务（Task）的评估结果，等价于一个 `sample_id` 的 `SampleResult`。 |
| **约束结果 / ConstraintResult** | 单条规则在单样本上的判定（含 score、reason、LLM 溯源）。 |
| **制品 / Artifact** | 大体积二进制附件（截图、原始产出物、JudgeRecord、trace 文件等），存对象存储，PG 仅存引用。 |
| **Langfuse trace_id** | Langfuse SaaS 侧 LLM 调用链 ID，平台存储以建立"评估结论 ↔ LLM 调用链"的双向跳转。 |

### 1.4 与现有文档的关系

| 现有文档 | 关系 |
|----------|------|
| `02Agent评估系统需求.md` §4.5（Web 可视化与追溯，F-W-01..06） | **升级**：F-W 系列需求保留并扩充，新增 F-O（Observability）系列需求。 |
| `02Agent评估系统需求.md` §8.3/§8.4（REST API / Web Portal 接口） | **重写**：端点从"读本地文件"改为"查询数据库"，并新增 Ingestion API。 |
| `02Agent评估系统需求.md` §十 决策 #9（暂不考虑认证租户隔离） | **推翻**：本期必须实现用户账号 + 组织/项目 + API Key 多租户隔离。 |
| 早期 `08Web可视化层设计.md`（React + Express、页面设计、文件索引，已废止，平台化设计见 [09](../arch/09Web可观测平台架构设计.md)） | **演进**：前端页面布局沿用，数据层从"文件读取"重构为"数据库 + 对象存储"，部署从"读本地 workspace"改为"独立服务 + 远程存储"。 |
| 迭代开发计划 `docs/plan/01迭代开发计划.md` Sprint 7a | Sprint 7a 已交付，本文档定义其后的 Sprint 7b–7g（见 §十一）。 |

---

## 二、目标与范围

### 2.1 核心目标

构建一个**自托管、多租户、仿 Langfuse**的 Agent 评估可观测平台：

1. **项目即租户**：用户在 Web 上注册/登录，在组织下创建项目，平台为每个项目签发独立的 public_key / secret_key。
2. **评估器零侵入上报**：评估器仅在环境变量中配置 key 与平台地址，执行 `agent-eval eval` 后自动把结果（含指标、样本、约束、溯源）推送到平台，无需人工搬运文件。
3. **数据独立持久化**：评估结果落 PostgreSQL（结构化、可聚合、事务化），大制品落对象存储，彻底摆脱"文件系统索引"。
4. **多团队互不影响**：不同用户/组织的项目数据严格隔离，A 组织无法看到 B 组织的运行，同一组织内按项目再隔离。
5. **可观测的可观测系统**：平台自身具备结构化日志、摄取成功率指标、密钥使用审计，能被运维监控。

### 2.2 目标用户与场景

| 用户 | 场景 | 平台需提供的能力 |
|------|------|------------------|
| **被测 Agent 的评估负责人**（团队 A） | 在平台建项目"课件 Agent"，拿 key 配到 CI，跑评估自动入库 | 注册/登录、创建项目、签发/轮换/吊销 API Key、查看本项目趋势 |
| **被测 Agent 的评估负责人**（团队 B） | 同上，但与团队 A 完全隔离 | 组织/项目级数据隔离，互不可见 |
| **评估器（Python）/ CI / Claude Code 类工具** | 携 key 把评估结果推到平台 | Ingestion API（鉴权、批量、幂等、重试）、明确的事件 schema |
| **项目经理 / 负责人** | 浏览趋势、对比版本、定位回归 | 看板、趋势图、运行/任务详情、跨运行对比 |
| **评估人员 / 算法工程师** | 抽检失败样本、查看 LLM 溯源、跳转 Langfuse 看 LLM 调用链 | 任务详情、约束溯源、制品预览、trace_id 跳转 |
| **平台运维** | 部署、备份、保留期管理、密钥审计 | 部署文档、数据生命周期、审计日志 |

### 2.3 设计原则

1. **写入与查看分离**：Ingestion API（评估器写入）与 Query API（前端查询）是两套端点、两套鉴权，互不耦合，可独立扩缩容。
2. **契约优先**：评估器（Python）与平台（Node.js）异构，二者以**版本化的 JSON 事件 schema**为唯一契约，避免数据模型漂移。
3. **可靠摄取**：网络抖动/平台不可用不得丢评估结果——客户端缓存 + 重试，服务端幂等去重（at-least-once + idempotency key）。
4. **隔离是数据库层的硬约束**：所有查询强制带 `project_id`/`org_id` 过滤，不依赖应用层自觉。
5. **大制品不入库**：JSON 结构化数据入 PG，二进制大制品入对象存储，PG 只存对象引用与摘要。
6. **平滑迁移**：重构期间 `agent-eval eval` 仍可本地输出 workspace 文件；提供文件→DB 的回填工具；二者可并存（双写）以灰度。

### 2.4 范围

**本期（Sprint 7b–7g）包含：**

- 用户账号 + 组织 + 项目 + 成员的认证授权体系（含基础 RBAC：owner / member）
- 项目级 API Key 签发/轮换/吊销与鉴权
- Ingestion API（事件批量摄取 + 制品上传）
- PostgreSQL 数据模型 + 对象存储 + 迁移
- Python 侧 ResultSink + 环境变量配置 + 离线缓存重试 + CLI 集成
- Query API + 前端登录态改造（组织/项目切换、看板/趋势/详情改为查 DB）
- 文件索引 → DB 的迁移/回填工具
- 自托管部署（Docker Compose / 腾讯云函数 + PG + 对象存储）

**本期不包含（远期）：**

- 细粒度 RBAC（viewer/editor 等多角色矩阵）、SSO/SAML
- 实时/流式评估（仍以离线批量摄取为主，接口预留流式扩展）
- 在 Web 上编辑规则集（规则管理仍在 Python 侧，见 Sprint 7）
- 人工仲裁界面、评分校准面板
- 公网 SaaS 化运营（本期为自托管）

---

## 三、总体架构

### 3.1 逻辑架构

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          评估器侧 (Python, agent-eval)                     │
│   agent-eval eval --project=... --upload                                 │
│      ├── PipelineEngine / Orchestrator   （现有评估引擎，不变）            │
│      ├── agent_eval/llm/tracing.py       （Langfuse SaaS: LLM 调用链）     │
│      └── agent_eval/observability/sink.py 【新】ResultSink 摄取客户端      │
│             ├── 拼装事件 (run/sample/constraint/artifact)                  │
│             ├── 制品 → presigned PUT 对象存储                              │
│             └── 事件 → POST /ingest （Bearer 鉴权 + 幂等 + 重试）          │
└──────────────────────┬───────────────────────────────────┬───────────────┘
                       │ ① 结构化事件 (HTTPS)              │ ② 大制品 (presigned PUT)
                       ▼                                   ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                     可观测平台后端 (Node.js / Express)                      │
│                                                                          │
│   ┌─────────────────────── Ingestion API（写入） ─────────────────────┐  │
│   │  POST /api/public/ingest          批量事件摄取（鉴权+幂等+校验）   │  │
│   │  POST /api/public/artifacts/url   申请 presigned 上传地址          │  │
│   │  GET  /api/public/health          摄取健康检查                      │  │
│   └──────────────────────────────────────────────────────────────────┘  │
│   ┌─────────────────────── Query API（读取） ─────────────────────────┐  │
│   │  GET /api/orgs/:org/projects         项目看板                       │  │
│   │  GET /api/projects/:id               项目详情 + 最新运行             │  │
│   │  GET /api/projects/:id/runs           运行列表（分页/筛选）          │  │
│   │  GET /api/projects/:id/trends         趋势聚合（DB 内计算）          │  │
│   │  GET /api/runs/:id                    运行详情                       │  │
│   │  GET /api/runs/:id/samples/:sid       样本/任务详情 + 约束 + 溯源    │  │
│   │  GET /api/artifacts/:id               制品下载（签名 URL）           │  │
│   └──────────────────────────────────────────────────────────────────┘  │
│   ┌─────────────────────── 管理 API（用户/项目/Key） ─────────────────┐  │
│   │  POST /api/auth/{register,login,logout}   认证                     │  │
│   │  /api/orgs /api/projects /api/keys        资源 CRUD + 审计          │  │
│   └──────────────────────────────────────────────────────────────────┘  │
│   中间件：JWT(Session) 鉴权 · org/project 隔离强制过滤 · 限流 · 结构化日志│
└──────────────────────┬───────────────────────────────────────────────────┘
                       │
        ┌──────────────┴───────────────┐
        ▼                              ▼
┌──────────────────────┐     ┌──────────────────────────────┐
│  PostgreSQL          │     │  对象存储 (S3 / COS / MinIO)  │
│  结构化数据：         │     │  大制品：截图 / 原始产出物 /   │
│  users/orgs/projects │     │  JudgeRecord / trace 文件      │
│  api_keys/runs/      │     │  路径：projects/{pid}/runs/    │
│  samples/constraints │     │        {rid}/artifacts/{kind}/ │
│  evidence/audit_logs │     │  PG 仅存 object_key + md5      │
└──────────────────────┘     └──────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                  前端 (React SPA, 登录态)                                  │
│  登录/注册 · 组织/项目切换器 · 项目看板 · 趋势图 · 运行详情 · 任务详情       │
│  · 制品预览 · Langfuse trace 跳转                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

### 3.2 关键架构变化（对比现状）

| 维度 | 现状（Sprint 7a） | 重构后 |
|------|-------------------|--------|
| 数据来源 | 后端读本地 `workspace/` JSON | 查 PostgreSQL（结构化）+ 对象存储（制品） |
| 评估器→平台 | 无（同机同盘共享文件） | 网络摄取（HTTPS Ingestion API） |
| 持久化 | `workspace/index/*.json` 平面文件 | PostgreSQL + 对象存储 |
| 租户 | 无 | 用户/组织/项目三级，数据库层强制隔离 |
| 鉴权 | 无 | Web 用 JWT/Session；评估器用 API Key（签名） |
| 部署 | 本地 `serve` 同机 | 独立服务 + 独立 DB + 独立对象存储，可远程 |
| 索引/趋势 | 全量扫描 + 内存聚合 | DB 索引 + SQL 聚合（可选物化视图） |

### 3.3 与 Langfuse 的协作模型（并存）

| 关注点 | 负责系统 | 说明 |
|--------|----------|------|
| LLM 调用链（token、prompt/response、耗时、provider/model） | **Langfuse SaaS**（沿用 `tracing.py`） | 不变，仍由评估器侧 `create_trace/create_span` 上报。 |
| 评估结论（DR/CPR/Reward、约束判定、样本得分、溯源、趋势） | **自建平台**（本文档） | 全量结构化持久化，支持聚合/对比/长期趋势。 |
| 串联 | `langfuse_trace_id` | 评估器把当次 run 的 Langfuse trace_id 随 `run` 事件一同上报；平台存储并在任务详情页提供"在 Langfuse 中查看"跳转。 |

> 取舍：LLM 调用链数据量大、查询模式与评估结论不同，复用 Langfuse 成熟能力；评估结论是本系统的核心资产，需自主持控（自定义指标、保留期、多租户），故自建。二者通过 trace_id 弱耦合，任一侧可独立演进。

### 3.4 部署拓扑

- **单体起步**：Express 同时承载 Ingestion / Query / 管理 API；前端构建产物由 Express 托管；PG 与对象存储（MinIO）用 Docker Compose 起本地实例。
- **生产**：Express 跑在腾讯云函数 / 容器；PG 用云数据库；对象存储用 COS（或 S3 兼容）。Ingestion 与 Query 可按需拆为两个服务独立扩缩容。
- **配置**：平台自身参数（DB 连接、对象存储凭证、JWT 密钥、是否开放注册）通过环境变量注入（`PLATFORM_*` 前缀，见 §十三）。

---

## 四、功能需求

> 需求编号沿用现有命名空间并新增 **F-O（Observability）** 系列。优先级 P0 为本期必交付，P1 为本期宜交付，P2 为远期。

### 4.1 账号与组织（F-O-AUTH）

| ID | 需求 | 优先级 |
|----|------|--------|
| F-O-AUTH-01 | 用户可注册账号（邮箱 + 密码），密码以强哈希（bcrypt/argon2）存储，明文不得落库。 | P0 |
| F-O-AUTH-02 | 用户可登录/登出；登录后颁发 JWT（或 server-side session），前端全程登录态。 | P0 |
| F-O-AUTH-03 | 首次注册自动创建个人组织（或加入受邀组织）；用户可在组织下管理项目。 | P0 |
| F-O-AUTH-04 | 组织支持邀请成员（邮件邀请链接），成员角色至少区分 owner / member。 | P1 |
| F-O-AUTH-05 | 平台可通过环境变量关闭开放注册（`PLATFORM_ALLOW_SIGNUP=false`），仅允许受邀加入（面向内部部署）。 | P0 |
| F-O-AUTH-06 | 所有鉴权敏感事件（登录、邀请、成员变更）写入审计日志。 | P1 |

### 4.2 项目与 API Key 管理（F-O-PROJ / F-O-KEY）

| ID | 需求 | 优先级 |
|----|------|--------|
| F-O-PROJ-01 | 组织内可创建项目，必填名称，选填描述、默认规则集/任务集、数据保留天数。 | P0 |
| F-O-PROJ-02 | 项目具备全局唯一 `slug`（URL 友好），平台 URL 以 `/{org}/{project}` 定位。 | P0 |
| F-O-PROJ-03 | 项目可归档（只读，停止接收新数据但保留历史）与删除（软删除，可恢复期）。 | P1 |
| F-O-PROJ-04 | 项目列表页展示每项目最新一次运行的 DR/CPR/Reward 与运行总数。 | P0 |
| F-O-KEY-01 | 每个项目可签发一对或多对 API Key（public_key + secret_key）。 | P0 |
| F-O-KEY-02 | secret_key **仅在创建时明文展示一次**，平台只存哈希；丢失只能重新签发。 | P0 |
| F-O-KEY-03 | public_key 形如 `pk-eval-xxxxxxxx`，secret_key 形如 `sk-eval-...`，便于识别与脱敏。 | P0 |
| F-O-KEY-04 | API Key 可命名（如 "CI"/"本地调试"）、可设置有效期、可吊销、可轮换（签发新 key 后旧 key 仍可用至吊销）。 | P0 |
| F-O-KEY-05 | API Key 的最后使用时间、调用次数、最近来源 IP 可在管理页查看。 | P1 |
| F-O-KEY-06 | API Key 仅对其所属项目有写权限；跨项目写入被拒绝。 | P0 |

### 4.3 评估器数据摄取（F-O-INGEST）

| ID | 需求 | 优先级 |
|----|------|--------|
| F-O-INGEST-01 | 平台提供 `POST /api/public/ingest` 批量摄取端点，请求体为版本化事件数组（schema 见 §七）。 | P0 |
| F-O-INGEST-02 | 评估器侧提供 **ResultSink**（`agent_eval/observability/sink.py`），在 `agent-eval eval` 完成后自动拼装事件并上报，无需用户编写上传代码。 | P0 |
| F-O-INGEST-03 | 评估器通过环境变量配置凭据与目标（见 §八）：`AGENT_EVAL_PUBLIC_KEY` / `AGENT_EVAL_SECRET_KEY` / `AGENT_EVAL_HOST`。未配置时自动禁用摄取，不影响本地评估。 | P0 |
| F-O-INGEST-04 | 鉴权：每个请求用 secret_key 对请求体（或规范化串）计算签名（HMAC-SHA256），平台用对应 public_key 的 secret_hash 校验。 | P0 |
| F-O-INGEST-05 | 幂等：每个事件携带客户端生成的 `event_id`，平台按 `(project_id, event_id)` 去重，重复推送不产生重复数据。 | P0 |
| F-O-INGEST-06 | 可靠性：网络失败/平台不可用时，ResultSink 把待发事件持久化到本地队列（`workspace/.ingest_queue/`），后台重试至成功或超时；评估结论不因平台故障而丢失。 | P0 |
| F-O-INGEST-07 | 制品上传：ResultSink 先为每个制品申请 presigned PUT URL（`POST /api/public/artifacts/url`），直传对象存储，再把 `object_key` + `md5` 作为 `artifact` 事件随结构化事件一同摄取。 | P0 |
| F-O-INGEST-08 | 健康检查：ResultSink 启动时探测 `GET /api/public/health`，凭据/地址有误时打印明确告警而非静默失败。 | P0 |
| F-O-INGEST-09 | 链路：ResultSink 把当次评估的 Langfuse `trace_id` 随 `run` 事件上报，建立评估结论 ↔ LLM 调用链的关联。 | P1 |
| F-O-INGEST-10 | 限流与背压：平台对 Ingestion 端点做速率限制与最大批量体积限制，返回 `429` 与 `Retry-After`；ResultSink 遵守退避重试。 | P1 |
| F-O-INGEST-11 | 批量大小可配（默认每批 ≤ 500 事件或 ≤ 4MB），大 Run 自动分批发送。 | P1 |

### 4.4 数据存储与模型（F-O-STORE）

| ID | 需求 | 优先级 |
|----|------|--------|
| F-O-STORE-01 | 结构化数据（用户/组织/项目/Key/Run/Sample/Constraint/审计）持久化于 PostgreSQL。 | P0 |
| F-O-STORE-02 | 大制品（截图、原始产出物 HTML/MD、JudgeRecord、trace.json）持久化于对象存储；PG 仅存 `object_key`、`content_type`、`size`、`md5` 等引用。 | P0 |
| F-O-STORE-03 | 所有评估数据表均带 `project_id`（必要时带 `org_id`），并建立相应索引；所有查询在数据访问层强制注入项目过滤。 | P0 |
| F-O-STORE-04 | 评估核心字段（DR/CPR/avg_reward/condR/avg_time_ms、s_format/s_common/s_soft/s_pref/reward）以**一等列**存储以支持索引与聚合，其余详情（failure_breakdown、details、thresholds）用 JSONB 存储。 | P0 |
| F-O-STORE-05 | 提供 DB 迁移脚本（Alembic / sequelize-cli / prisma migrate，二选一统一），版本化管理 schema 变更。 | P0 |
| F-O-STORE-06 | 数据保留：项目级 `retention_days` 到期后自动归档/清理 Run 及其制品（可配为仅清理制品保留摘要）。 | P1 |
| F-O-STORE-07 | 支持按项目导出数据（JSON / 原始事件回放），便于备份与迁移。 | P2 |

> 数据模型详表见 §六。

### 4.5 多租户隔离（F-O-ISO）

| ID | 需求 | 优先级 |
|----|------|--------|
| F-O-ISO-01 | 组织间数据完全隔离：B 组织的成员无法通过任何 Query/管理 API 枚举或访问 A 组织的项目与运行。 | P0 |
| F-O-ISO-02 | 项目间数据隔离：同一组织内，成员仅能访问其有权访问的项目（默认组织内可见，可演进为按项目授权）。 | P0 |
| F-O-ISO-03 | API Key 隔离：key 仅能写其所属项目的数据；携带他项目 ID 的摄取请求被拒绝（403）。 | P0 |
| F-O-ISO-04 | 隔离校验作为数据访问层的强制行为（非可选项），并辅以集成测试覆盖越权用例。 | P0 |
| F-O-ISO-05 | 对象存储制品按 `projects/{project_id}/...` 前缀隔离，下载地址签发时校验调用者对该项目的访问权。 | P0 |

### 4.6 可视化呈现（F-O-VIEW，承接并升级原 F-W）

| ID | 需求 | 优先级 |
|----|------|--------|
| F-O-VIEW-01 | 登录后默认进入"组织/项目切换器"，选择项目进入项目看板；看板数据来自 Query API（查 DB）。 | P0 |
| F-O-VIEW-02 | 项目看板：项目卡片展示最新运行的 DR/CPR/Reward、运行总数、最近活跃时间（沿用现有 ProjectCard/StatCard 视觉）。 | P0 |
| F-O-VIEW-03 | 趋势图：DR/CPR/Reward 随时间曲线（ECharts），数据由 DB 聚合（`GET /api/projects/:id/trends`），叠加阈值参考线。 | P0 |
| F-O-VIEW-04 | 运行详情：汇总卡片（样本总数/DR/CPR/Reward/状态）、维度分解、任务结果表；数据来自 DB。 | P0 |
| F-O-VIEW-05 | 任务/样本详情：约束逐项结果表（tier/规则/状态/得分/reason）、LLM Judge 溯源（provider/model/置信度/JudgeRecord 跳转）、制品预览（截图/产出物）。 | P0 |
| F-O-VIEW-06 | 目录模式：检测到样本含 `module_results` 时切换为目录树可视化（沿用现有 DirectoryTree/ModuleScoreTable）。 | P1 |
| F-O-VIEW-07 | Langfuse 跳转：任务/运行详情页提供"在 Langfuse 查看 LLM 调用链"按钮，跳转到 `langfuse_host` 下对应 `trace_id`。 | P1 |

### 4.7 查询、筛选与对比（F-O-QUERY）

| ID | 需求 | 优先级 |
|----|------|--------|
| F-O-QUERY-01 | 运行列表支持分页、按时间/DR/CPR/Reward 排序，按规则集版本、SUT 版本、模式（eval_only/run/pipeline）筛选。 | P0 |
| F-O-QUERY-02 | 趋势支持时间范围选择（最近 N 次 / 日期区间）。 | P1 |
| F-O-QUERY-03 | 跨运行对比：选择 2–N 次运行并排展示指标与失败规则差异。 | P1 |
| F-O-QUERY-04 | 失败规则聚合视图：项目内"最常失败的约束"TopN（基于 `failure_breakdown` 聚合）。 | P1 |

### 4.8 运维与管理（F-O-OPS）

| ID | 需求 | 优先级 |
|----|------|--------|
| F-O-OPS-01 | 平台自身输出结构化日志（HTTP 请求、摄取事件计数、鉴权失败、限流命中）。 | P0 |
| F-O-OPS-02 | 平台暴露 `/health`（含 DB/对象存储连通性）与基本指标（摄取成功/失败计数、队列长度）。 | P1 |
| F-O-OPS-03 | 审计日志可在管理页查询（谁在何时创建/吊销了哪个 Key、归档了哪个项目）。 | P1 |
| F-O-OPS-04 | 提供一键 Docker Compose 本地起栈（Express + PG + MinIO）与生产部署文档（腾讯云函数 + 云 PG + COS）。 | P0 |

### 4.9 迁移与兼容（F-O-MIGR）

| ID | 需求 | 优先级 |
|----|------|--------|
| F-O-MIGR-01 | 重构后 `agent-eval eval` **仍默认输出本地 workspace 文件**（向后兼容），摄取为可选附加行为（由 env/`--upload` 触发）。 | P0 |
| F-O-MIGR-02 | 提供 `agent-eval upload`（或 `agent-eval observability backfill`）子命令，把历史 workspace 中的 Run 回填入库。 | P0 |
| F-O-MIGR-03 | 提供"双写"模式：eval 完成后既写本地文件又推送平台，便于灰度切换与对账。 | P1 |
| F-O-MIGR-04 | 文件索引（`projects.json`/`runs_index.json`）在平台化后标记为**废弃**，仅作为回填数据源保留。 | P0 |

---

## 五、非功能需求

### 5.1 性能

| ID | 需求 | 优先级 |
|----|------|--------|
| NF-O-01 | 单次 Run（≤ 500 样本、≤ 2000 约束）的摄取端到端（含制品上传）控制在分钟级；纯结构化事件摄取 P95 < 2s。 | P0 |
| NF-O-02 | 项目趋势查询（≤ 1000 次运行）P95 < 500ms（依赖 DB 索引与聚合）。 | P1 |
| NF-O-03 | 运行详情/任务详情查询 P95 < 300ms。 | P1 |

### 5.2 可靠性

| ID | 需求 | 优先级 |
|----|------|--------|
| NF-O-04 | 摄取语义为 **at-least-once**，配合 `event_id` 幂等做到**精确一次生效**；重复/乱序不影响最终一致性。 | P0 |
| NF-O-05 | 平台短暂不可用时，评估器侧队列保留待发事件（默认 7 天或 10000 事件上限），恢复后自动重放。 | P0 |
| NF-O-06 | 制品上传失败可独立重试，不阻塞结构化事件摄取（先入库引用占位，制品随后补传）。 | P1 |

### 5.3 安全

| ID | 需求 | 优先级 |
|----|------|--------|
| NF-O-07 | 全链路 HTTPS；secret_key 仅客户端持有，服务端仅存哈希；日志与错误信息对 key 做脱敏。 | P0 |
| NF-O-08 | JWT 设置合理过期与刷新；敏感操作（Key 吊销、项目删除）要求重新认证。 | P0 |
| NF-O-09 | Ingestion 端点做速率限制与体积限制，防滥用与异常大包。 | P1 |
| NF-O-10 | 输入校验：事件 payload 严格按 schema 校验，非法 payload 返回明确错误码且不落库。 | P0 |
| NF-O-11 | 评估产出物可能含敏感内容，制品默认仅项目内有权限用户可访问（签名 URL 短时效）。 | P1 |

### 5.4 可扩展性与可维护性

| ID | 需求 | 优先级 |
|----|------|--------|
| NF-O-12 | 数据访问层抽象（Repository），便于未来替换 ORM 或拆分微服务。 | P1 |
| NF-O-13 | 事件 schema 版本化（`schema_version`），平台对多版本兼容或显式拒绝并提示升级。 | P0 |
| NF-O-14 | 后端核心模块（鉴权、摄取、查询、隔离）单元测试覆盖率 ≥ 80%，越权用例有集成测试。 | P0 |
| NF-O-15 | 对象存储抽象为接口，支持 S3/COS/MinIO 切换（仅配置差异）。 | P0 |

---

## 六、数据模型

> 表结构以 PostgreSQL 表达。`*` 为 PK，`FK` 为外键。所有评估数据表强制带 `project_id`。

### 6.1 账号与组织

```text
users
  id*              uuid
  email*           citext unique
  password_hash    text            -- argon2/bcrypt，禁明文
  name             text
  created_at       timestamptz

organizations
  id*              uuid
  name             text
  slug*            text unique     -- URL 标识
  created_by       uuid FK users
  created_at       timestamptz

org_memberships
  org_id*          uuid FK organizations
  user_id*         uuid FK users
  role             text            -- owner | member
  created_at       timestamptz
  PRIMARY KEY (org_id, user_id)

invitations        (P1)
  id*              uuid
  org_id           uuid FK organizations
  email            text
  token_hash       text
  role             text
  expires_at       timestamptz
  accepted_at      timestamptz
```

### 6.2 项目与 API Key

```text
projects
  id*              uuid
  org_id           uuid FK organizations
  slug*            text            -- 组织内唯一 (org_id, slug)
  name             text
  description      text
  default_rule_set text
  default_task_set text
  retention_days   int             -- null = 永久
  created_by       uuid FK users
  created_at       timestamptz
  archived_at      timestamptz
  UNIQUE (org_id, slug)

api_keys
  id*              uuid
  project_id       uuid FK projects
  public_key*      text unique     -- pk-eval-...
  secret_hash      text            -- 仅哈希
  name             text            -- "CI" / "本地调试"
  scopes           text[]          -- ["ingest"] 预留
  expires_at       timestamptz
  last_used_at     timestamptz
  last_ip          inet
  call_count       bigint
  created_by       uuid FK users
  created_at       timestamptz
  revoked_at       timestamptz
```

### 6.3 评估数据

```text
runs
  id*              uuid            -- 平台主键
  external_run_id* text            -- 评估器侧 run_id（如 20260616_001625），(project_id, external_run_id) 唯一
  project_id       uuid FK projects
  mode             text            -- eval_only | run | pipeline
  status           text            -- running | completed | failed | partial
  total_samples    int
  -- 一等指标列（聚合/索引友好）
  dr               double precision
  cpr              double precision
  avg_reward       double precision
  cond_r           double precision
  avg_time_ms      double precision
  rule_set_version text
  sut_version      text
  langfuse_trace_id text           -- 与 Langfuse SaaS 关联
  langfuse_host    text
  failure_breakdown jsonb          -- {constraint_id: count}
  thresholds       jsonb
  source_client    text            -- agent-eval/<ver>
  created_at       timestamptz     -- = 评估运行时间
  finished_at      timestamptz
  UNIQUE (project_id, external_run_id)

samples
  id*              uuid
  run_id           uuid FK runs
  project_id       uuid FK projects  -- 反范式，便于隔离过滤
  external_sample_id text            -- task_id / sample_id（如 "大单元学习总导"）
  status           text
  s_format         double precision
  s_common         double precision
  s_soft           double precision
  s_pref           double precision
  reward           double precision
  total_duration_ms double precision
  llm_calls        int
  token_usage      int
  extra            jsonb             -- module_results 等目录模式字段
  UNIQUE (run_id, external_sample_id)

constraint_results
  id*              uuid
  sample_id        uuid FK samples
  project_id       uuid FK projects
  constraint_id    text             -- "format.response_format"
  rule_id          text
  name             text
  tier             text             -- hard_gate | hard_score | soft | preference（评估器 ConstraintTier 四档）
  status           text             -- pass | fail | skip | error
  passed           boolean
  score            double precision
  raw_score        double precision
  reason           text
  duration_ms      double precision
  judge_provider   text             -- LLM 溯源
  judge_model      text
  judge_artifact_id uuid FK artifacts  -- JudgeRecord 制品引用
  details          jsonb
  module_results   jsonb

dimension_scores     -- 对应 scores.json 的 dimensions，预留扩展
  id*              uuid
  sample_id        uuid FK samples
  dimension_id     text
  name             text
  weight           double precision
  score            double precision
  status           text
```

### 6.4 制品与审计

```text
artifacts
  id*              uuid
  project_id       uuid FK projects
  run_id           uuid FK runs
  sample_id        uuid FK samples   -- nullable（run 级制品）
  kind             text              -- screenshot | judge_record | output | trace | manifest
  object_key       text              -- projects/{pid}/runs/{rid}/artifacts/{kind}/{name}
  storage          text              -- s3 | cos | minio
  content_type     text
  size_bytes       bigint
  md5              text
  original_name    text
  created_at       timestamptz

audit_logs
  id*              bigserial
  org_id           uuid
  actor_user_id    uuid
  action           text              -- key.create | key.revoke | project.archive | member.invite ...
  target_type      text
  target_id        text
  metadata         jsonb
  created_at       timestamptz
```

### 6.5 索引设计（关键）

- `runs (project_id, created_at DESC)`
- `runs (project_id, external_run_id) UNIQUE`
- `samples (run_id)`, `samples (project_id, external_sample_id)`
- `constraint_results (sample_id)`, `constraint_results (project_id, constraint_id)`
- `artifacts (run_id)`, `artifacts (sample_id)`
- `api_keys (public_key) UNIQUE`
- 可选物化视图：`project_trends_mv`（project_id, created_at, dr, cpr, avg_reward）周期刷新，加速看板/趋势。

### 6.6 对象存储布局

```text
projects/{project_id}/runs/{run_id}/artifacts/{kind}/{name}
  kind = screenshot   // 视觉评估截图
  kind = judge_record // LLM Judge 溯源 JSON
  kind = output       // 原始产出物（HTML/MD 文档集，可打包为 zip）
  kind = trace        // trace.json / agent 会话日志
  kind = manifest     // 目录 _manifest.json
```

---

## 七、接口规范

### 7.1 鉴权方案

| 端点族 | 鉴权方式 |
|--------|----------|
| Ingestion API（评估器写入） | API Key 签名：`Authorization: Eval <public_key>:<hex_hmac>`，其中 `hmac = HMAC-SHA256(secret_key, canonical_string)`，`canonical_string = METHOD + "\n" + PATH + "\n" + body_sha256`。 |
| 制品上传 | presigned PUT URL（由 Ingestion 凭据申请，短时效，限定 object_key）。 |
| Query / 管理 API（前端） | JWT Bearer（登录获取），中间件解析并把 `user_id / org_id` 注入上下文，数据访问层据此强制过滤。 |

> 选 HMAC 签名而非简单 `Bearer secret`：避免 secret 在每次请求头中明文流转，且可防重放（请求体哈希入签）。MVP 也可退化为 `Authorization: Bearer <public_key>:<secret>` 的简化方案，后续升级签名。

### 7.2 Ingestion API

#### `POST /api/public/ingest` — 批量事件摄取

请求头：
```http
Authorization: Eval <public_key>:<hex_hmac>
Content-Type: application/json
X-Eval-Client: agent-eval/0.x
```

请求体（事件信封，`schema_version` 为契约版本）：
```jsonc
{
  "schema_version": "1.0",
  "project_id": "uuid-or-slug",        // 可选；缺省取 key 所属项目
  "batch_id": "client-uuid",           // 整批幂等键
  "events": [
    {
      "event_id": "uuid",              // 单事件幂等键（必填）
      "type": "run",
      "data": { /* Run */ },
      "langfuse_trace_id": "...",      // 仅 run 事件
      "langfuse_host": "..."
    },
    { "event_id": "uuid", "type": "sample", "data": { /* Sample */ } },
    { "event_id": "uuid", "type": "constraint", "data": { /* ConstraintResult */ } },
    { "event_id": "uuid", "type": "artifact", "data": { /* Artifact 引用 */ } }
  ]
}
```

事件 `data` 各类型对齐评估器现有序列化模型（避免漂移）：

- **run**：对齐 `run_manifest.json` + `summary.json` 的并集
  ```jsonc
  { "external_run_id": "20260616_001625", "mode": "eval_only",
    "created_at": "2026-06-16T00:16:25Z", "finished_at": null,
    "metrics": { "DR": 1.0, "CPR": 0.0, "avg_reward": 2.44, "condR": 0.0, "avg_time_ms": 225475 },
    "total_samples": 1, "rule_set_version": "courseware_v1#v3", "sut_version": null,
    "failure_breakdown": { "commonsense.info_accuracy": 1 }, "thresholds": {} }
  ```
- **sample**：对齐 `SampleResult.to_dict()` + `scores.json`
  ```jsonc
  { "external_sample_id": "大单元学习总导", "status": "fail",
    "s_format": 1.0, "s_common": 0.0, "s_soft": 0.74, "s_pref": 0.70, "reward": 2.44,
    "total_duration_ms": 225475, "llm_calls": 6, "token_usage": 12340, "dimensions": {} }
  ```
- **constraint**：对齐 `rule_results.json` 元素（ConstraintResult）
  ```jsonc
  { "external_sample_id": "大单元学习总导",
    "constraint_id": "format.response_format", "rule_id": "format.response_format",
    "name": "文件格式检查", "tier": "hard_gate", "status": "pass", "passed": true,
    "score": 1.0, "reason": "输出为有效的 Markdown/HTML",
    "details": { "actual": 24, "min": 1, "max": 30 },
    "duration_ms": 1.1, "judge_provider": null, "judge_model": null,
    "judge_record_object_key": null, "module_results": null }
  ```
- **artifact**：制品引用
  ```jsonc
  { "external_run_id": "20260616_001625", "external_sample_id": "大单元学习总导",
    "kind": "judge_record", "object_key": "projects/<pid>/runs/<rid>/artifacts/judge_record/soft_teaching_logic.json",
    "content_type": "application/json", "size_bytes": 1234, "md5": "...", "original_name": "judge_soft.xxx.json",
    "linked_constraint_id": "soft.teaching_logic" }
  ```

响应：
```jsonc
{ "accepted": 12, "duplicates": 0, "errors": [ { "event_id": "...", "code": "SCHEMA_INVALID", "message": "..." } ] }
```
- HTTP 202：至少部分接受（含重复跳过）
- HTTP 400：schema 校验失败（整批拒绝或部分拒绝，依策略）
- HTTP 401/403：鉴权失败 / 跨项目
- HTTP 429：限流（带 `Retry-After`）
- HTTP 5xx：服务端错误，客户端退避重试

#### `POST /api/public/artifacts/url` — 申请制品上传地址

```jsonc
// 请求
{ "kind": "screenshot", "content_type": "image/png", "size_bytes": 102400,
  "md5": "...", "external_run_id": "...", "external_sample_id": "...", "original_name": "整体定位.png" }
// 响应
{ "object_key": "projects/<pid>/runs/<rid>/artifacts/screenshot/整体定位.png",
  "upload_url": "https://<obj>/<key>?X-Amz-Signature=...",
  "method": "PUT", "expires_in": 900, "headers": { "Content-MD5": "..." } }
```

#### `GET /api/public/health`

```jsonc
{ "status": "ok", "schema_version": "1.0", "ingestion": true, "db": true, "object_storage": true }
```

### 7.3 Query API（前端用，JWT 鉴权）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/orgs/:org/projects` | 组织下项目看板（含每项目最新运行） |
| GET | `/api/projects/:id` | 项目详情（最新运行、运行总数、聚合） |
| GET | `/api/projects/:id/runs` | 运行列表（分页/排序/筛选：`?mode=&rule_set_version=&from=&to=&order=&page=&size=`） |
| GET | `/api/projects/:id/trends` | 趋势（`?metric=DR,CPR,Reward&from=&to=&limit=`） |
| GET | `/api/runs/:id` | 运行详情（汇总 + 维度分解 + 任务结果） |
| GET | `/api/runs/:id/samples/:sid` | 样本/任务详情（约束结果 + 溯源 + 制品列表） |
| GET | `/api/artifacts/:id` | 制品下载（签名 URL 重定向，或代理流式返回） |

响应格式沿用现有前端 `types/index.ts` 的契约（Project / RunSummary / TrendDataPoint 等），保持前端改动最小——仅把"数据源"从 workspace 文件换成 Query API。

### 7.4 管理 API（JWT 鉴权，操作写审计日志）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/register` `/login` `/logout` | 注册/登录/登出 |
| GET/POST | `/api/orgs/:org/projects` | 创建项目 |
| GET/POST/DELETE | `/api/projects/:id/keys` | 列出/签发/吊销 API Key（签发时返回一次性明文 secret） |
| POST | `/api/projects/:id/archive` | 归档项目 |

---

## 八、评估器对接方案

### 8.1 环境变量清单（评估器侧）

| 变量 | 必填 | 说明 |
|------|------|------|
| `AGENT_EVAL_HOST` | 是 | 平台地址，如 `https://eval.example.com` |
| `AGENT_EVAL_PUBLIC_KEY` | 是 | 项目公钥 `pk-eval-...` |
| `AGENT_EVAL_SECRET_KEY` | 是 | 项目私钥 `sk-eval-...`（仅客户端） |
| `AGENT_EVAL_PROJECT` | 否 | 项目 slug/UUID 覆盖（默认取 key 所属项目） |
| `AGENT_EVAL_UPLOAD` | 否 | `auto`（默认，配置了 key 即上传）/ `on` / `off` |
| `AGENT_EVAL_INGEST_TIMEOUT` | 否 | 单次请求超时（默认 30s） |
| `AGENT_EVAL_INGEST_BATCH` | 否 | 每批事件上限（默认 500） |
| `AGENT_EVAL_QUEUE_DIR` | 否 | 离线队列目录（默认 `workspace/.ingest_queue`） |

> 与现有 Langfuse 变量（`LANGFUSE_*`）并存，互不干扰：`LANGFUSE_*` 控制 LLM 调用链上报，`AGENT_EVAL_*` 控制评估结论上报。

### 8.2 ResultSink 设计

新增模块 `agent_eval/observability/`：
```text
agent_eval/observability/
  __init__.py
  sink.py              # ResultSink：拼装事件、鉴权、上传、重试
  client.py            # IngestionClient：HTTP + HMAC 签名 + presigned
  queue.py             # 离线队列（SQLite 或 JSON 文件）+ 重放
  events.py            # Run/Sample/Constraint/Artifact → 事件映射
  tracing.py           # 暂沿用 agent_eval/llm/tracing.py 的 trace_id 透传
```

调用时机：在 `cli.py` 的 `eval` 命令末尾、`flush_traces()` 之后调用 `ResultSink.flush(run_result)`；若配置 `--upload` 或 env 启用，则触发上传，否则跳过。

### 8.3 与本地 workspace 输出的关系

| 模式 | 行为 |
|------|------|
| 默认（无 env key） | 仅写本地 workspace（与现状一致，零破坏） |
| 仅上传（`AGENT_EVAL_UPLOAD=on` + 配置 `--no-local`） | 仅推平台，不写本地索引（省空间，远端为权威） |
| 双写（默认开启上传时） | 既写本地文件又推平台，便于灰度对账（F-O-MIGR-03） |

### 8.4 CLI 集成

```bash
# 配好 env 后，常规评估即自动上传
agent-eval eval --package-dir ... --rule-set ... --project courseware-agent

# 显式控制
agent-eval eval ... --upload                 # 强制上传（即便无 env）
agent-eval eval ... --no-upload              # 本次不上传

# 历史数据回填
agent-eval upload --workspace ./workspace [--project courseware-agent]
agent-eval upload --run 20260616_001625 --project courseware-agent
```

### 8.5 错误与降级

- 平台/网络不可用 → 写入离线队列，后台守护或下次 eval 时重放；终端打印告警但不阻塞评估。
- 凭据无效 → 启动健康检查即告警，提示检查 `AGENT_EVAL_*`；本次评估照常完成（本地结果仍可用）。
- schema 不兼容（平台版本更新）→ 平台返回明确错误码，客户端提示升级 `agent-eval`。

---

## 九、迁移策略

1. **并行期**：上线新后端 + DB + 对象存储；评估器发布支持摄取的版本；默认仍本地输出 + 可选上传（双写）。
2. **回填**：用 `agent-eval upload` 把历史 workspace 的 Run 批量入库；提供对账脚本（本地 summary ↔ DB run 行数与指标比对）。
3. **切换**：组织/项目切换为"平台为权威数据源"；`agent-eval index` 与 `workspace/index/*.json` 标记废弃（保留作为回填源）。
4. **清理**：稳定后下线文件索引依赖，前端 `serve` 模式仅作为本地开发便利入口（仍连同一后端/DB）。

---

## 十、安全与合规要点

- **密钥**：secret 仅哈希存储；展示一次；轮换不中断（新旧并存至吊销）；吊销即时生效。
- **隔离**：DB 层强制 `project_id`/`org_id` 过滤；集成测试覆盖"用 A 的 key 写 B 项目""B 用户查 A 项目"等越权用例（NF-O-14）。
- **传输**：生产强制 HTTPS；presigned URL 短时效（≤ 15min）。
- **脱敏**：日志/错误对 key 与邮箱做掩码（`pk-eval-ab**`）。
- **数据驻留**：自托管，数据不出用户自有云；保留期可配（F-O-STORE-06）。

---

## 十一、迭代计划调整建议

> 现状：Sprint 7a（Web Portal MVP，文件系统）已交付。Sprint 8/9（ExecutionAgent / 集成交付）规划不变。本次重构作为 **Sprint 7 系列（7b–7g）** 插入，可在 Sprint 8/9 之外并行推进（后端/前端/评估器对接三条线相对独立）。

### 11.1 新增迭代

| 迭代 | 名称 | 周期 | 目标 | 主要工作 |
|------|------|------|------|----------|
| **Sprint 7b** | 后端基础设施与数据模型 | 1 周 | PG + 对象存储地基就绪 | Express 工程化（分层/配置/日志）、PG 接入与 ORM 选型、§六 全表 schema + 迁移脚本、对象存储抽象（MinIO 本地）、Docker Compose 起栈、`/health` |
| **Sprint 7c** | 认证与多租户 | 1 周 | 用户/组织/项目/Key 可用 | 注册/登录/JWT、组织与成员（owner/member）、项目 CRUD、API Key 签发/哈希/轮换/吊销、隔离中间件与数据访问层强制过滤、审计日志、注册开关 |
| **Sprint 7d** | 摄取服务（Ingestion） | 1.5 周 | 评估结果可入库 | 事件 schema（§七）与校验、`/api/public/ingest`（批量/幂等/去重）、`/api/public/artifacts/url`（presigned）、HMAC 鉴权、限流、schema_version 兼容 |
| **Sprint 7e** | 评估器对接（ResultSink） | 1 周 | eval 完成自动上报 | `agent_eval/observability/` 全套（sink/client/queue/events）、env 配置、离线队列重放、CLI `--upload/--no-upload` 与 `upload` 回填子命令、双写、trace_id 透传、与 Langfuse 并存 |
| **Sprint 7f** | 前端重接 + Query API | 1.5 周 | 浏览器登录查看 | Query API（§7.3）、前端登录态/组织项目切换器、看板/趋势/运行详情/任务详情改为查 DB、制品预览、Langfuse 跳转、文件→DB 回填对账 |
| **Sprint 7g** | 高级与运维（可裁剪） | 1 周 | 生产可用收尾 | 跨运行对比、失败 TopN、保留期清理、平台自身指标/监控、生产部署文档（云函数 + 云 PG + COS） |

### 11.2 里程碑更新

| 里程碑 | 对应迭代 | 交付标志 |
|--------|----------|----------|
| **M4b：数据持久化与多租户就绪** | Sprint 7b + 7c 完成 | PG/对象存储就绪，可注册登录建项目签发 Key，DB 层隔离经集成测试验证 |
| **M4c：端到端摄取闭环就绪** | Sprint 7d + 7e 完成 | 评估器配 key 后 `agent-eval eval` 结果自动入库，离线队列/重试/幂等验证通过 |
| **M4d：可观测平台上线** | Sprint 7f 完成 | 浏览器登录后可查看多项目趋势与运行/任务详情，文件索引已废弃、数据源切换为 DB |
| **M4e：生产可托管** | Sprint 7g 完成 | 平台可自托管部署并运维，具备保留期/审计/监控 |

### 11.3 对 `docs/plan/01迭代开发计划.md` 的修订点（建议落地）

1. §1.2 迭代概览表：在 Sprint 7a 后新增 7b–7g（或合并标注为"Sprint 7 系列：可观测平台重构"），总工期相应增加约 6–7 周（可并行，实际关键路径约 +4 周）。
2. §1.3 里程碑：新增 M4b/M4c/M4d/M4e。
3. §1.4 依赖：Sprint 7b 依赖 7a；7c 依赖 7b；7d 依赖 7b；7e 依赖 7d 与 Sprint 5；7f 依赖 7c+7d。7 系列与 8/9 系列可并行。
4. §三 阶段一验收清单第 10 项（Web Portal）：更新为"可观测平台化"标准（多租户 + DB + 摄取闭环）。
5. §四 风险：新增"多租户隔离越权""摄取可靠性/数据丢失""异构（Python/Node）schema 漂移""对象存储成本/保留期"四项风险及应对。
6. 版本记录新增一行（见本文档版本记录），并标注推翻决策 #9。

> 是否把上述修订正式写入 `docs/plan/01迭代开发计划.md`，待确认后执行（见文末"待确认事项"）。

---

## 十二、风险与决策记录

### 12.1 风险与应对

| 风险 | 影响 | 应对 |
|------|------|------|
| 多租户隔离越权 | 数据泄露 | 数据访问层强制过滤 + 越权集成测试（NF-O-14）；API Key 限定项目 |
| 异构语言（Python 评估器 / Node 后端）schema 漂移 | 摄取失败/数据错乱 | 版本化 JSON 事件 schema 为唯一契约；双方共享 schema 描述文件并加 CI 校验 |
| 摄取可靠性不足导致丢评估结果 | 数据缺失 | 客户端持久化队列 + 重试 + 服务端幂等；双写灰度对账 |
| 对象存储/DB 成本随数据增长 | 运维成本 | 项目级保留期（F-O-STORE-06）；制品可选仅保留摘要；趋势用物化视图降负载 |
| 评估器与平台必须联网 | 离线场景不可用 | 离线队列兜底；保留本地输出模式（F-O-MIGR-01） |
| 密钥泄露 | 数据被冒写 | 仅哈希存储 + 轮换 + 吊销 + 审计；签名而非明文 secret |

### 12.2 本期已确认决策（覆盖 02 文档相关项）

| 序号 | 决策 | 选择 | 说明 |
|------|------|------|------|
| D1 | Web 后端技术栈 | **Node.js / Express（沿用）** | 复用现有 Web Portal 后端；与 Python 评估器以 HTTP 契约对接 |
| D2 | 持久化方案 | **PostgreSQL + 对象存储** | 结构化数据入 PG，大制品入对象存储（S3/COS/MinIO 抽象） |
| D3 | 多租户模型 | **用户账号 + 组织/项目** | 注册/登录、组织下建项目、项目级 API Key，数据按项目隔离；含基础 RBAC（owner/member） |
| D4 | 与 Langfuse 关系 | **并存** | Langfuse 看 LLM 调用链，自建看评估结论，经 `langfuse_trace_id` 关联 |
| D5 | 鉴权方式 | Ingestion 用 API Key（HMAC 签名）/ Query·管理用 JWT | 写入与查看分离鉴权 |
| D6 | 向后兼容 | 重构期保留本地 workspace 输出 + 双写 + 回填工具 | 零破坏切换 |

---

## 十三、附录

### 13.1 平台环境变量速查（`PLATFORM_*`）

| 变量 | 说明 |
|------|------|
| `PLATFORM_DATABASE_URL` | PostgreSQL 连接串 |
| `PLATFORM_OBJECT_STORAGE` | `minio` / `s3` / `cos` |
| `PLATFORM_S3_ENDPOINT` / `_REGION` / `_BUCKET` / `_ACCESS_KEY` / `_SECRET_KEY` | 对象存储凭证 |
| `PLATFORM_JWT_SECRET` | JWT 签名密钥 |
| `PLATFORM_ALLOW_SIGNUP` | 是否开放注册（默认 true，内部部署设 false） |
| `PLATFORM_INGEST_RATE_LIMIT` | 摄取限流配置 |
| `PLATFORM_RETENTION_DEFAULT_DAYS` | 项目默认保留天数 |

### 13.2 评估器环境变量速查（`AGENT_EVAL_*`）

见 §8.1。

### 13.3 Ingestion 错误码

| code | 含义 | 客户端动作 |
|------|------|------------|
| `SCHEMA_INVALID` | 事件不符合 schema | 修正后重发，不可盲目重试 |
| `AUTH_INVALID` | 鉴权失败 | 检查 key/签名 |
| `PROJECT_FORBIDDEN` | 跨项目写 | 校正 project |
| `DUPLICATED` | 事件已存在（幂等跳过） | 无需动作 |
| `RATE_LIMITED` | 限流 | 退避重试 |
| `INTERNAL` | 服务端错误 | 指数退避重试 |

---

## 版本记录

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v1.0 | 2026-06-16 | 初版：提出 Web 可观测平台 langfuse 式重构；定义账号/组织/项目/API Key/摄取/存储/隔离/可视化/查询/运维/迁移需求（F-O 系列）；给出数据模型、Ingestion/Query API 规范、评估器对接方案（ResultSink）；提出 Sprint 7b–7g 迭代调整与 M4b–M4e 里程碑；推翻 02 文档决策 #9 |
