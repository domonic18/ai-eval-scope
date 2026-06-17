/**
 * Sprint 7f Query API 测试（§九）：
 *  造数据（摄取 run/sample/constraint）→ 登录拿 JWT → dashboard/runs/trends/run/sample。
 *  + 跨租户隔离（他组织用户 → 404）。
 */

import request from "supertest";
import { createApp } from "../src/server";
import { registerUser, login, createProject, issueKey, signedPost } from "./helpers";

let app: ReturnType<typeof createApp>;
let owner: Awaited<ReturnType<typeof registerUser>>;
let project: Awaited<ReturnType<typeof createProject>>;
let key: Awaited<ReturnType<typeof issueKey>>;
let accessToken: string;
let runId: string; // DB run id
let sampleDbId: string;

function uid(p: string) {
  return `${p}_${Date.now()}_${Math.floor(Math.random() * 1e6)}`;
}

function runEvent(extRunId: string, eventId: string, dr = 0.9) {
  return {
    event_id: eventId,
    type: "run",
    data: {
      external_run_id: extRunId,
      mode: "eval_only",
      status: "completed",
      metrics: { DR: dr, CPR: 0.7, avg_reward: 0.6, condR: 0.65, avg_time_ms: 1200 },
      total_samples: 1,
    },
  };
}
function sampleEvent(extRunId: string, extSample: string, eventId: string) {
  return {
    event_id: eventId,
    type: "sample",
    data: {
      external_run_id: extRunId,
      external_sample_id: extSample,
      status: "completed",
      s_format: 1,
      s_common: 0.8,
      s_soft: 0.7,
      s_pref: 0.6,
      reward: 0.75,
    },
  };
}
function constraintEvent(extRunId: string, extSample: string, eventId: string) {
  return {
    event_id: eventId,
    type: "constraint",
    data: {
      external_run_id: extRunId,
      external_sample_id: extSample,
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

const auth = (tok: string) => ({ Authorization: `Bearer ${tok}` });

beforeAll(async () => {
  app = createApp();
  owner = await registerUser(app, "q");
  project = await createProject(app, owner);
  key = await issueKey(app, { accessToken: owner.accessToken, projectId: project.id });

  const sess = await login(app, owner.email);
  accessToken = sess.access_token;

  // 摄取两条 run（趋势需要 ≥1），含 sample + constraint
  const extRun1 = uid("run");
  const extRun2 = uid("run");
  const extSample = uid("s");
  for (const er of [extRun1, extRun2]) {
    await signedPost(app, {
      url: "/api/public/ingest",
      secretKey: key.secretKey,
      publicKey: key.publicKey,
      bodyObj: {
        schema_version: "1.0",
        events: [
          runEvent(er, uid("ev"), er === extRun1 ? 0.9 : 0.8),
          sampleEvent(er, extSample, uid("ev")),
          constraintEvent(er, extSample, uid("ev")),
        ],
      },
    });
  }

  // 取一条 run 的 DB id + sample DB id
  const runsRes = await request(app)
    .get(`/api/v1/projects/${project.id}/runs`)
    .set(auth(accessToken));
  runId = runsRes.body.items[0].id;
  const sample = await request(app).get(`/api/v1/runs/${runId}`).set(auth(accessToken));
  sampleDbId = sample.body.run.samples[0].id;
});

describe("Query API", () => {
  it("GET /orgs/:org/projects dashboard returns latestRun + runCount", async () => {
    const r = await request(app).get(`/api/v1/orgs/${owner.org.id}/projects`).set(auth(accessToken));
    expect(r.status).toBe(200);
    const p = r.body.projects.find((x: { id: string }) => x.id === project.id);
    expect(p).toBeDefined();
    expect(p.runCount).toBeGreaterThanOrEqual(2);
    expect(p.latestRun).not.toBeNull();
    expect(p.latestRun.dr).toBeGreaterThanOrEqual(0.8); // 最新运行（最后入库者）指标已回填
  });

  it("GET /projects/:id/runs lists runs (paginated)", async () => {
    const r = await request(app).get(`/api/v1/projects/${project.id}/runs`).set(auth(accessToken));
    expect(r.status).toBe(200);
    expect(r.body.total).toBeGreaterThanOrEqual(2);
    expect(Array.isArray(r.body.items)).toBe(true);
    expect(r.body.items[0].dr).toBeDefined();
  });

  it("GET /projects/:id/trends returns ordered points", async () => {
    const r = await request(app)
      .get(`/api/v1/projects/${project.id}/trends?limit=10`)
      .set(auth(accessToken));
    expect(r.status).toBe(200);
    expect(Array.isArray(r.body)).toBe(true);
    expect(r.body.length).toBeGreaterThanOrEqual(2);
    // 按 created_at ASC
    expect(r.body[0].created_at <= r.body[1].created_at).toBe(true);
    expect(r.body[0]).toHaveProperty("DR");
    expect(r.body[0]).toHaveProperty("CPR");
    expect(r.body[0]).toHaveProperty("Reward");
  });

  it("GET /runs/:id returns run with samples", async () => {
    const r = await request(app).get(`/api/v1/runs/${runId}`).set(auth(accessToken));
    expect(r.status).toBe(200);
    expect(r.body.run.id).toBe(runId);
    expect(Array.isArray(r.body.run.samples)).toBe(true);
    expect(r.body.run.samples.length).toBeGreaterThanOrEqual(1);
  });

  it("GET /runs/:id/samples/:sid returns constraints + artifacts", async () => {
    const r = await request(app)
      .get(`/api/v1/runs/${runId}/samples/${sampleDbId}`)
      .set(auth(accessToken));
    expect(r.status).toBe(200);
    expect(r.body.sample.id).toBe(sampleDbId);
    expect(Array.isArray(r.body.sample.constraintResults)).toBe(true);
    expect(r.body.sample.constraintResults.length).toBeGreaterThanOrEqual(1);
    expect(r.body.sample.constraintResults[0].passed).toBe(true);
  });

  it("cross-tenant: another org user cannot read runs (404)", async () => {
    const other = await registerUser(app, "qother");
    const r = await request(app).get(`/api/v1/runs/${runId}`).set(auth(other.accessToken));
    expect(r.status).toBe(404);
  });

  it("cross-tenant: another org user cannot list project runs (404)", async () => {
    const other = await registerUser(app, "qother2");
    const r = await request(app)
      .get(`/api/v1/projects/${project.id}/runs`)
      .set(auth(other.accessToken));
    expect(r.status).toBe(404);
  });
});
