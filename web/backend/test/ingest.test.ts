/**
 * Sprint 7d 摄取服务验证（§7.5 / 计划验证标准 1-6）：
 *  1. 合法事件入库；重复 event_id 幂等（duplicates）
 *  2. schema 非法 → SCHEMA_INVALID 且不落库
 *  3. HMAC 验签正确（已在 apiKeyAuth.test 覆盖）；此处补充 ingestion 成功路径
 *  4. A 项目 Key 携 B project_id → PROJECT_FORBIDDEN
 *  5. 限流触发 429 + Retry-After
 *  6. 超批量 → PAYLOAD_TOO_LARGE（不静默截断）
 *  + 依赖缺失、制品 presigned url、run→sample→constraint 链路落库
 */

import express from "express";
import { createApp } from "../src/server";
import { getPrisma } from "../src/infra/prisma";
import { requireApiKey } from "../src/middleware/apiKeyAuth";
import { rateLimiter } from "../src/middleware/rateLimiter";
import { errorHandler } from "../src/middleware/errorHandler";
import { registerUser, createProject, issueKey, signedPost } from "./helpers";
import { buildObjectKey } from "../src/infra/objectStorage";

const prisma = getPrisma();
let app: express.Application;
let user: Awaited<ReturnType<typeof registerUser>>;
let project: Awaited<ReturnType<typeof createProject>>;
let key: Awaited<ReturnType<typeof issueKey>>;

function uid(p: string): string {
  return `${p}_${Date.now()}_${Math.floor(Math.random() * 1e6)}`;
}

function runEvent(externalRunId: string, eventId: string, dr = 0.9) {
  return {
    event_id: eventId,
    type: "run",
    data: {
      external_run_id: externalRunId,
      mode: "eval_only",
      status: "completed",
      metrics: { DR: dr, CPR: 0.7, avg_reward: 0.6, condR: 0.65, avg_time_ms: 1200 },
      total_samples: 1,
    },
  };
}
function sampleEvent(externalRunId: string, externalSampleId: string, eventId: string) {
  return {
    event_id: eventId,
    type: "sample",
    data: {
      external_run_id: externalRunId,
      external_sample_id: externalSampleId,
      status: "completed",
      s_format: 1,
      s_common: 0.8,
      s_soft: 0.7,
      s_pref: 0.6,
      reward: 0.75,
      total_duration_ms: 1000,
    },
  };
}
function constraintEvent(externalRunId: string, sid: string, eventId: string) {
  return {
    event_id: eventId,
    type: "constraint",
    data: {
      external_run_id: externalRunId,
      external_sample_id: sid,
      constraint_id: "c1",
      name: "has title",
      tier: "hard_gate",
      status: "pass",
      passed: true,
      score: 1,
      reason: "ok",
      duration_ms: 50,
    },
  };
}

beforeAll(async () => {
  app = createApp();
  user = await registerUser(app, "ing");
  project = await createProject(app, user);
  key = await issueKey(app, { accessToken: user.accessToken, projectId: project.id });
});

describe("#1 合法入库 + 重复幂等", () => {
  it("ingests run/sample/constraint and persists to DB", async () => {
    const runId = uid("run");
    const sid = uid("s");
    const r = await signedPost(app, {
      url: "/api/public/ingest",
      secretKey: key.secretKey,
      publicKey: key.publicKey,
      bodyObj: {
        schema_version: "1.0",
        events: [
          runEvent(runId, uid("ev")),
          sampleEvent(runId, sid, uid("ev")),
          constraintEvent(runId, sid, uid("ev")),
        ],
      },
    });
    expect(r.status).toBe(202);
    expect(r.body.accepted).toBe(3);
    expect(r.body.duplicates).toBe(0);
    expect(r.body.errors).toEqual([]);

    const run = await prisma.run.findUnique({
      where: { projectId_externalRunId: { projectId: project.id, externalRunId: runId } },
    });
    expect(run).not.toBeNull();
    expect(run!.dr).toBe(0.9);
  });

  it("duplicate event_id is idempotent (duplicates, no extra rows)", async () => {
    const eventId = uid("ev");
    const runId = uid("run");
    const first = await signedPost(app, {
      url: "/api/public/ingest",
      secretKey: key.secretKey,
      publicKey: key.publicKey,
      bodyObj: { schema_version: "1.0", events: [runEvent(runId, eventId, 0.5)] },
    });
    expect(first.body.accepted).toBe(1);

    const second = await signedPost(app, {
      url: "/api/public/ingest",
      secretKey: key.secretKey,
      publicKey: key.publicKey,
      bodyObj: { schema_version: "1.0", events: [runEvent(runId, eventId, 0.99)] }, // 同 event_id
    });
    expect(second.status).toBe(202);
    expect(second.body.accepted).toBe(0);
    expect(second.body.duplicates).toBe(1);

    // DR 保持首次值（幂等：未覆盖）
    const run = await prisma.run.findUnique({
      where: { projectId_externalRunId: { projectId: project.id, externalRunId: runId } },
    });
    expect(run!.dr).toBe(0.5);
  });
});

describe("#2 schema 非法 → SCHEMA_INVALID 且不落库", () => {
  it("rejects an event missing required metrics (per-event error, 202)", async () => {
    const badEventId = uid("ev");
    const goodRunId = uid("run");
    const r = await signedPost(app, {
      url: "/api/public/ingest",
      secretKey: key.secretKey,
      publicKey: key.publicKey,
      bodyObj: {
        schema_version: "1.0",
        events: [
          { event_id: badEventId, type: "run", data: { external_run_id: goodRunId, mode: "eval_only" } }, // 缺 metrics
          runEvent(uid("run2"), uid("ev")), // 合法
        ],
      },
    });
    expect(r.status).toBe(202);
    expect(r.body.accepted).toBe(1);
    expect(r.body.errors.length).toBe(1);
    expect(r.body.errors[0].code).toBe("SCHEMA_INVALID");
    // 非法事件不落库
    const bad = await prisma.run.findUnique({
      where: { projectId_externalRunId: { projectId: project.id, externalRunId: goodRunId } },
    });
    expect(bad).toBeNull();
  });

  it("rejects whole malformed envelope (400 SCHEMA_INVALID)", async () => {
    const r = await signedPost(app, {
      url: "/api/public/ingest",
      secretKey: key.secretKey,
      publicKey: key.publicKey,
      bodyObj: { schema_version: "1.0" }, // 缺 events
    });
    expect(r.status).toBe(400);
    expect(r.body.code).toBe("SCHEMA_INVALID");
  });

  it("rejects unsupported schema_version (400 SCHEMA_VERSION_UNSUPPORTED)", async () => {
    const r = await signedPost(app, {
      url: "/api/public/ingest",
      secretKey: key.secretKey,
      publicKey: key.publicKey,
      bodyObj: { schema_version: "2.0", events: [runEvent(uid("r"), uid("ev"))] },
    });
    expect(r.status).toBe(400);
    expect(r.body.code).toBe("SCHEMA_VERSION_UNSUPPORTED");
  });
});

describe("#4 跨项目 project_id → PROJECT_FORBIDDEN", () => {
  it("rejects ingest with foreign project_id (403)", async () => {
    const r = await signedPost(app, {
      url: "/api/public/ingest",
      secretKey: key.secretKey,
      publicKey: key.publicKey,
      bodyObj: {
        schema_version: "1.0",
        project_id: "00000000-0000-0000-0000-000000000000", // 他项目
        events: [runEvent(uid("r"), uid("ev"))],
      },
    });
    expect(r.status).toBe(403);
    expect(r.body.code).toBe("PROJECT_FORBIDDEN");
  });
});

describe("#6 超批量 → PAYLOAD_TOO_LARGE", () => {
  it("rejects batches exceeding max events (413, not silent truncate)", async () => {
    // 临时把 maxBatch 调小不可行（route 用 cfg）；直接发 >500 事件
    const events = Array.from({ length: 501 }, (_, i) => runEvent(uid("r"), uid(`ev${i}`)));
    const r = await signedPost(app, {
      url: "/api/public/ingest",
      secretKey: key.secretKey,
      publicKey: key.publicKey,
      bodyObj: { schema_version: "1.0", events },
    });
    expect(r.status).toBe(413);
    expect(r.body.code).toBe("PAYLOAD_TOO_LARGE");
  });
});

describe("依赖缺失 → DEPENDENCY_MISSING", () => {
  it("sample before run is rejected with DEPENDENCY_MISSING (retryable, not consumed)", async () => {
    const eventId = uid("ev");
    const r = await signedPost(app, {
      url: "/api/public/ingest",
      secretKey: key.secretKey,
      publicKey: key.publicKey,
      bodyObj: {
        schema_version: "1.0",
        events: [sampleEvent("run-not-yet", uid("s"), eventId)],
      },
    });
    expect(r.status).toBe(202);
    expect(r.body.accepted).toBe(0);
    expect(r.body.errors[0].code).toBe("DEPENDENCY_MISSING");
    // event_id 未被消费：重发（补 run）可成功
    const r2 = await signedPost(app, {
      url: "/api/public/ingest",
      secretKey: key.secretKey,
      publicKey: key.publicKey,
      bodyObj: {
        schema_version: "1.0",
        events: [
          runEvent("run-not-yet", uid("ev")),
          sampleEvent("run-not-yet", uid("s"), eventId), // 复用同一 event_id
        ],
      },
    });
    expect(r2.body.accepted).toBe(2); // 同 event_id 的 sample 这次成功（未被消费）
    expect(r2.body.duplicates).toBe(0);
  });
});

describe("制品 presigned url + artifact 事件", () => {
  it("issues a presigned PUT, accepts upload, then artifact event links", async () => {
    const externalRunId = uid("run");
    // 先建 run（artifact 事件依赖 run 存在）
    await signedPost(app, {
      url: "/api/public/ingest",
      secretKey: key.secretKey,
      publicKey: key.publicKey,
      bodyObj: { schema_version: "1.0", events: [runEvent(externalRunId, uid("ev"))] },
    });

    // 申请 presigned
    const urlReq = await signedPost(app, {
      url: "/api/public/artifacts/url",
      secretKey: key.secretKey,
      publicKey: key.publicKey,
      bodyObj: {
        external_run_id: externalRunId,
        kind: "output",
        name: "report.md",
        content_type: "text/markdown",
      },
    });
    expect(urlReq.status).toBe(200);
    const objectKey = urlReq.body.object_key as string;
    expect(objectKey).toBe(
      buildObjectKey({ projectId: project.id, runId: externalRunId, kind: "output", name: "report.md" })
    );

    // PUT 上传
    const body = "# report";
    const up = await fetch(urlReq.body.upload_url, {
      method: "PUT",
      body,
      headers: { "Content-Type": "text/markdown" },
      redirect: "manual",
    });
    expect(up.status).toBe(200);

    // artifact 事件引用该 object_key
    const r = await signedPost(app, {
      url: "/api/public/ingest",
      secretKey: key.secretKey,
      publicKey: key.publicKey,
      bodyObj: {
        schema_version: "1.0",
        events: [
          {
            event_id: uid("ev"),
            type: "artifact",
            data: {
              external_run_id: externalRunId,
              kind: "output",
              object_key: objectKey,
              content_type: "text/markdown",
              size_bytes: Buffer.byteLength(body),
              original_name: "report.md",
            },
          },
        ],
      },
    });
    expect(r.status).toBe(202);
    expect(r.body.accepted).toBe(1);

    const art = await prisma.artifact.findFirst({
      where: { runId: (await prisma.run.findUnique({
        where: { projectId_externalRunId: { projectId: project.id, externalRunId: externalRunId } },
      }))!.id, objectKey },
    });
    expect(art).not.toBeNull();
  });

  it("artifact event for a non-uploaded object → DEPENDENCY_MISSING", async () => {
    const externalRunId = uid("run");
    await signedPost(app, {
      url: "/api/public/ingest",
      secretKey: key.secretKey,
      publicKey: key.publicKey,
      bodyObj: { schema_version: "1.0", events: [runEvent(externalRunId, uid("ev"))] },
    });
    const r = await signedPost(app, {
      url: "/api/public/ingest",
      secretKey: key.secretKey,
      publicKey: key.publicKey,
      bodyObj: {
        schema_version: "1.0",
        events: [
          {
            event_id: uid("ev"),
            type: "artifact",
            data: {
              external_run_id: externalRunId,
              kind: "screenshot",
              object_key: `projects/${project.id}/runs/${externalRunId}/artifacts/screenshot/missing.png`,
              content_type: "image/png",
              size_bytes: 1,
            },
          },
        ],
      },
    });
    expect(r.status).toBe(202);
    expect(r.body.errors[0].code).toBe("DEPENDENCY_MISSING");
  });
});

describe("#5 限流（独立 app，小配额令牌桶）", () => {
  it("returns 429 + Retry-After once quota exhausted", async () => {
    const limApp = express();
    limApp.use(
      express.json({
        verify: (req, _res, buf) => {
          (req as express.Request).rawBody = buf;
        },
      })
    );
    limApp.post(
      "/api/public/ingest",
      requireApiKey,
      rateLimiter({ capacity: 2, ratePerSec: 0.0001 }),
      (_req, res) => res.status(202).json({ ok: true })
    );
    limApp.use(errorHandler);

    const fire = () =>
      signedPost(limApp, {
        url: "/api/public/ingest",
        secretKey: key.secretKey,
        publicKey: key.publicKey,
        bodyObj: { schema_version: "1.0", events: [] },
      });

    const r1 = await fire();
    const r2 = await fire();
    const r3 = await fire(); // 第 3 次 → 超限
    expect([r1.status, r2.status]).toEqual([202, 202]);
    expect(r3.status).toBe(429);
    expect(r3.body.code).toBe("RATE_LIMITED");
    expect(r3.headers["retry-after"]).toBeDefined();
  });
});

describe("回归：tier=hard_score + project_id=null（防 7e 集成缺陷）", () => {
  // Bug 1：评估器 ConstraintTier 有第 4 档 hard_score，schema 枚举须含之。
  // Bug 2：未设 AGENT_EVAL_PROJECT 时客户端发 project_id:null，浅层信封校验须放行。
  it("accepts a constraint with tier=hard_score", async () => {
    const runId = uid("run");
    const sid = uid("s");
    const r = await signedPost(app, {
      url: "/api/public/ingest",
      secretKey: key.secretKey,
      publicKey: key.publicKey,
      bodyObj: {
        schema_version: "1.0",
        events: [
          runEvent(runId, uid("ev")),
          sampleEvent(runId, sid, uid("ev")),
          {
            event_id: uid("ev"),
            type: "constraint",
            data: {
              external_run_id: runId,
              external_sample_id: sid,
              constraint_id: "commonsense.math_formula",
              name: "数学公式",
              tier: "hard_score", // ← 第 4 档，曾经被 schema 拒
              status: "fail",
              passed: false,
              score: 0,
              reason: "公式错误",
              duration_ms: 10,
            },
          },
        ],
      },
    });
    expect(r.status).toBe(202);
    expect(r.body.accepted).toBe(3);
    expect(r.body.errors).toEqual([]);
  });

  it("accepts envelope with project_id=null (key-bound project)", async () => {
    const r = await signedPost(app, {
      url: "/api/public/ingest",
      secretKey: key.secretKey,
      publicKey: key.publicKey,
      bodyObj: {
        schema_version: "1.0",
        project_id: null, // ← 未指定项目，曾经被浅层校验拒
        batch_id: null,
        events: [runEvent(uid("run"), uid("ev"))],
      },
    });
    expect(r.status).toBe(202);
    expect(r.body.accepted).toBe(1);
    expect(r.body.errors).toEqual([]);
  });

  it("still rejects an unknown tier (enum guard intact)", async () => {
    const r = await signedPost(app, {
      url: "/api/public/ingest",
      secretKey: key.secretKey,
      publicKey: key.publicKey,
      bodyObj: {
        schema_version: "1.0",
        events: [
          {
            event_id: uid("ev"),
            type: "constraint",
            data: {
              external_run_id: uid("run"),
              external_sample_id: uid("s"),
              constraint_id: "x",
              name: "t",
              tier: "bogus_tier", // ← 不在枚举内，须拒绝
              status: "pass",
              passed: true,
              score: 1,
              reason: "r",
              duration_ms: 1,
            },
          },
        ],
      },
    });
    expect(r.status).toBe(202); // 部分接受：合法事件 0
    expect(r.body.accepted).toBe(0);
    expect(r.body.errors.length).toBe(1);
    expect(r.body.errors[0].code).toBe("SCHEMA_INVALID");
  });
});

