/**
 * Sprint 7f Query API 测试（§九）：
 *  造数据（摄取 run/sample/constraint）→ 登录拿 JWT → dashboard/runs/trends/run/sample。
 *  + 跨租户隔离（他组织用户 → 404）。
 */

import request from "supertest"
import { createApp } from "../src/server"
import { registerUser, login, createProject, issueKey, bearerPost } from "./helpers"

let app: ReturnType<typeof createApp>
let owner: Awaited<ReturnType<typeof registerUser>>
let project: Awaited<ReturnType<typeof createProject>>
let key: Awaited<ReturnType<typeof issueKey>>
let accessToken: string
let runId: string // DB run id
let sampleDbId: string

function uid(p: string) {
  return `${p}_${Date.now()}_${Math.floor(Math.random() * 1e6)}`
}

function runEvent(extRunId: string, eventId: string, dr = 0.9, createdAt?: string) {
  return {
    event_id: eventId,
    type: "run",
    data: {
      external_run_id: extRunId,
      mode: "eval_only",
      status: "completed",
      metrics: { DR: dr, CPR: 0.7, avg_reward: 0.6, condR: 0.65, avg_time_ms: 1200 },
      total_samples: 1,
      ...(createdAt ? { created_at: createdAt } : {}),
    },
  }
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
  }
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
  }
}

const auth = (tok: string) => ({ Authorization: `Bearer ${tok}` })

beforeAll(async () => {
  app = createApp()
  owner = await registerUser(app, "q")
  project = await createProject(app, owner)
  key = await issueKey(app, { accessToken: owner.accessToken, projectId: project.id })

  const sess = await login(app, owner.email)
  accessToken = sess.access_token

  // 摄取两条 run（趋势需要 ≥1），含 sample + constraint；
  // created_at 显式错开（毫秒精度下同值会退化成 id 决胜，全量并行时易撞）
  const extRun1 = uid("run")
  const extRun2 = uid("run")
  const extSample = uid("s")
  const t1 = new Date(Date.now() - 2000).toISOString()
  const t2 = new Date(Date.now() - 1000).toISOString()
  for (const [er, ts] of [
    [extRun1, t1],
    [extRun2, t2],
  ] as const) {
    await bearerPost(app, {
      url: "/api/public/ingest",
      token: key.token,
      bodyObj: {
        schema_version: "1.0",
        events: [
          runEvent(er, uid("ev"), er === extRun1 ? 0.9 : 0.8, ts),
          sampleEvent(er, extSample, uid("ev")),
          constraintEvent(er, extSample, uid("ev")),
        ],
      },
    })
  }

  // 取一条 run 的 DB id + sample DB id
  const runsRes = await request(app)
    .get(`/api/v1/projects/${project.id}/runs`)
    .set(auth(accessToken))
  runId = runsRes.body.items[0].id
  const sample = await request(app).get(`/api/v1/runs/${runId}`).set(auth(accessToken))
  sampleDbId = sample.body.run.samples[0].id
})

describe("Query API", () => {
  it("GET /orgs/:org/projects dashboard returns latestRun + runCount", async () => {
    const r = await request(app).get(`/api/v1/orgs/${owner.org.id}/projects`).set(auth(accessToken))
    expect(r.status).toBe(200)
    const p = r.body.projects.find((x: { id: string }) => x.id === project.id)
    expect(p).toBeDefined()
    expect(p.runCount).toBeGreaterThanOrEqual(2)
    expect(p.latestRun).not.toBeNull()
    expect((p.latestRun.metrics as Record<string, number>)?.DR).toBeGreaterThanOrEqual(0.8)
  })

  it("GET /projects/:id/runs lists runs (paginated)", async () => {
    const r = await request(app).get(`/api/v1/projects/${project.id}/runs`).set(auth(accessToken))
    expect(r.status).toBe(200)
    expect(r.body.total).toBeGreaterThanOrEqual(2)
    expect(Array.isArray(r.body.items)).toBe(true)
    expect(r.body.items[0].metrics).toBeDefined()
  })

  it("GET /projects/:id/trends returns ordered points", async () => {
    const r = await request(app)
      .get(`/api/v1/projects/${project.id}/trends?limit=10`)
      .set(auth(accessToken))
    expect(r.status).toBe(200)
    expect(Array.isArray(r.body)).toBe(true)
    expect(r.body.length).toBeGreaterThanOrEqual(2)
    // 按 created_at ASC
    expect(r.body[0].created_at <= r.body[1].created_at).toBe(true)
    expect(r.body[0]).toHaveProperty("metrics")
  })

  it("GET /projects/:id/trends?limit=1 keeps newest（窗口=最新 N；旧实现取最老）", async () => {
    const r = await request(app)
      .get(`/api/v1/projects/${project.id}/trends?limit=1`)
      .set(auth(accessToken))
    expect(r.status).toBe(200)
    expect(r.body.length).toBe(1)
    // 最老 run1(DR=0.9) 被淘汰——旧 ASC LIMIT 实现将取到 0.9
    expect(Number(r.body[0].metrics?.DR)).toBe(0.8)
  })

  it("GET /runs/:id returns run with samples", async () => {
    const r = await request(app).get(`/api/v1/runs/${runId}`).set(auth(accessToken))
    expect(r.status).toBe(200)
    expect(r.body.run.id).toBe(runId)
    expect(Array.isArray(r.body.run.samples)).toBe(true)
    expect(r.body.run.samples.length).toBeGreaterThanOrEqual(1)
  })

  it("GET /runs/:id/samples/:sid returns constraints + artifacts", async () => {
    const r = await request(app)
      .get(`/api/v1/runs/${runId}/samples/${sampleDbId}`)
      .set(auth(accessToken))
    expect(r.status).toBe(200)
    expect(r.body.sample.id).toBe(sampleDbId)
    expect(Array.isArray(r.body.sample.constraintResults)).toBe(true)
    expect(r.body.sample.constraintResults.length).toBeGreaterThanOrEqual(1)
    expect(r.body.sample.constraintResults[0].passed).toBe(true)
  })

  it("cross-tenant: another org user cannot read runs (404)", async () => {
    const other = await registerUser(app, "qother")
    const r = await request(app).get(`/api/v1/runs/${runId}`).set(auth(other.accessToken))
    expect(r.status).toBe(404)
  })

  it("cross-tenant: another org user cannot list project runs (404)", async () => {
    const other = await registerUser(app, "qother2")
    const r = await request(app)
      .get(`/api/v1/projects/${project.id}/runs`)
      .set(auth(other.accessToken))
    expect(r.status).toBe(404)
  })
})

describe("GET /projects/:id/latest-run（快照语义 §9.6）", () => {
  it("empty project → run null + 空指标定义", async () => {
    const p2 = await createProject(app, owner)
    const r = await request(app).get(`/api/v1/projects/${p2.id}/latest-run`).set(auth(accessToken))
    expect(r.status).toBe(200)
    expect(r.body.run).toBeNull()
    expect(r.body.metricDefinitions).toEqual([])
  })

  it("returns newest of two runs（非最老窗口）+ 未带场景时 defs 为空", async () => {
    const r = await request(app)
      .get(`/api/v1/projects/${project.id}/latest-run`)
      .set(auth(accessToken))
    expect(r.status).toBe(200)
    expect(r.body.run).not.toBeNull()
    // beforeAll 摄取 run1(DR=0.9) → run2(DR=0.8)，快照取最新
    expect(r.body.run.metrics?.DR).toBe(0.8)
    // run 事件未带 scenario_id → defs 空数组，杜绝交叉配对
    expect(r.body.metricDefinitions).toEqual([])
  })

  it("run 与其场景 metricDefinitions 服务端配对原子下发", async () => {
    // 独立项目：run 带 scenario_id + run_config_snapshot（auto-ingest 补缺注册场景 defaults）
    const proj = await createProject(app, owner)
    const k = await issueKey(app, { accessToken: owner.accessToken, projectId: proj.id })
    const scen = `snap_scn_${Date.now()}`
    const defs = [{ id: "reward", name: "Reward", threshold: 0.8, unit: "0-1" }]
    const res = await bearerPost(app, {
      url: "/api/public/ingest",
      token: k.token,
      bodyObj: {
        schema_version: "1.0",
        events: [
          {
            event_id: uid("ev"),
            type: "run",
            data: {
              external_run_id: uid("snaprun"),
              mode: "eval_only",
              status: "completed",
              metrics: { reward: 0.88 },
              total_samples: 0,
              scenario_id: scen,
              run_config_snapshot: {
                scenario_id: scen,
                snapshot_hash: "sha256:test-snapshot",
                package: { id: "pkg", version: "1.0.0" },
                metric_definitions: defs,
              },
            },
          },
        ],
      },
    })
    expect(res.status).toBe(202)

    const r = await request(app)
      .get(`/api/v1/projects/${proj.id}/latest-run`)
      .set(auth(accessToken))
    expect(r.status).toBe(200)
    expect(r.body.run.scenarioId).toBe(scen)
    expect(r.body.run.metrics?.reward).toBe(0.88)
    expect(r.body.metricDefinitions).toEqual(defs)
  })

  it("跨包代际：defs 锚定该 run 自带快照，而非场景旧代 defaults（edu 事故回归，docs/plan/08）", async () => {
    // 复现线上事故：run A（旧代 edu:*）先摄取 → auto-ingest 以其快照注册场景 defaults；
    // run B（新代 kb:*）后摄取 → latest-run 的 defs 必须取 run B 快照（kb:*），而非旧代 defaults
    const proj = await createProject(app, owner)
    const k = await issueKey(app, { accessToken: owner.accessToken, projectId: proj.id })
    const scen = `anchor_scn_${Date.now()}`
    const ingestRun = async (extRunId: string, prefix: string, ts: string) =>
      bearerPost(app, {
        url: "/api/public/ingest",
        token: k.token,
        bodyObj: {
          schema_version: "1.0",
          events: [
            {
              event_id: uid("ev"),
              type: "run",
              data: {
                external_run_id: extRunId,
                mode: "eval_only",
                status: "completed",
                created_at: ts,
                metrics: { [`${prefix}:reward`]: 0.9 },
                total_samples: 0,
                scenario_id: scen,
                run_config_snapshot: {
                  scenario_id: scen,
                  snapshot_hash: `sha256:${extRunId}`,
                  package: { id: "pkg", version: "1.0.0" },
                  metric_definitions: [
                    { id: `${prefix}:reward`, name: "综合得分", threshold: 0.8, unit: "score" },
                  ],
                },
              },
            },
          ],
        },
      })
    const t1 = new Date(Date.now() - 2000).toISOString()
    const t2 = new Date(Date.now() - 1000).toISOString()
    expect((await ingestRun(uid("old"), "edu", t1)).status).toBe(202)
    expect((await ingestRun(uid("new"), "kb", t2)).status).toBe(202)

    const r = await request(app)
      .get(`/api/v1/projects/${proj.id}/latest-run`)
      .set(auth(accessToken))
    expect(r.status).toBe(200)
    expect(r.body.run.metrics?.["kb:reward"]).toBe(0.9)
    expect(r.body.metricDefinitions).toEqual([
      { id: "kb:reward", name: "综合得分", threshold: 0.8, unit: "score" },
    ])
  })

  it("快照缺失的 run：defs 回退场景 defaults（极老 run 兜底）", async () => {
    // run A 带快照（注册场景 defaults）→ run B 同场景无快照且更新 → latest-run 取 run B + defaults defs
    const proj = await createProject(app, owner)
    const k = await issueKey(app, { accessToken: owner.accessToken, projectId: proj.id })
    const scen = `fallback_scn_${Date.now()}`
    const defs = [{ id: "edu:reward", name: "综合得分", threshold: 0.7, unit: "score" }]
    const base = {
      mode: "eval_only",
      status: "completed",
      metrics: { "edu:reward": 0.8 },
      total_samples: 0,
      scenario_id: scen,
    }
    expect(
      (
        await bearerPost(app, {
          url: "/api/public/ingest",
          token: k.token,
          bodyObj: {
            schema_version: "1.0",
            events: [
              {
                event_id: uid("ev"),
                type: "run",
                data: {
                  ...base,
                  external_run_id: uid("withsnap"),
                  created_at: new Date(Date.now() - 2000).toISOString(),
                  run_config_snapshot: {
                    scenario_id: scen,
                    snapshot_hash: "sha256:fb",
                    package: { id: "pkg", version: "1.0.0" },
                    metric_definitions: defs,
                  },
                },
              },
            ],
          },
        })
      ).status,
    ).toBe(202)
    expect(
      (
        await bearerPost(app, {
          url: "/api/public/ingest",
          token: k.token,
          bodyObj: {
            schema_version: "1.0",
            events: [
              {
                event_id: uid("ev"),
                type: "run",
                data: {
                  ...base,
                  external_run_id: uid("nosnap"),
                  created_at: new Date(Date.now() - 1000).toISOString(),
                },
              },
            ],
          },
        })
      ).status,
    ).toBe(202)

    const r = await request(app)
      .get(`/api/v1/projects/${proj.id}/latest-run`)
      .set(auth(accessToken))
    expect(r.status).toBe(200)
    expect(r.body.run.metrics?.["edu:reward"]).toBe(0.8)
    expect(r.body.metricDefinitions).toEqual(defs)
  })

  it("cross-tenant: another org user gets 404", async () => {
    const other = await registerUser(app, "qlatest")
    const r = await request(app)
      .get(`/api/v1/projects/${project.id}/latest-run`)
      .set(auth(other.accessToken))
    expect(r.status).toBe(404)
  })
})

describe("行级 defs 配对（docs/plan/08 批次 C）：listRuns / dashboard", () => {
  it("listRuns 每行 metricDefinitions 锚定各自 run 快照，重 content 不下发", async () => {
    const proj = await createProject(app, owner)
    const k = await issueKey(app, { accessToken: owner.accessToken, projectId: proj.id })
    const scen = `pair_scn_${Date.now()}`
    const ingestRun = async (extRunId: string, prefix: string, ts: string) =>
      bearerPost(app, {
        url: "/api/public/ingest",
        token: k.token,
        bodyObj: {
          schema_version: "1.0",
          events: [
            {
              event_id: uid("ev"),
              type: "run",
              data: {
                external_run_id: extRunId,
                mode: "eval_only",
                status: "completed",
                created_at: ts,
                metrics: { [`${prefix}:reward`]: 0.9 },
                total_samples: 0,
                scenario_id: scen,
                run_config_snapshot: {
                  scenario_id: scen,
                  snapshot_hash: `sha256:${extRunId}`,
                  package: { id: "pkg", version: "1.0.0" },
                  metric_definitions: [
                    { id: `${prefix}:reward`, name: "综合得分", threshold: 0.8, unit: "score" },
                  ],
                },
              },
            },
          ],
        },
      })
    const t1 = new Date(Date.now() - 2000).toISOString()
    const t2 = new Date(Date.now() - 1000).toISOString()
    expect((await ingestRun(uid("old"), "edu", t1)).status).toBe(202)
    expect((await ingestRun(uid("new"), "kb", t2)).status).toBe(202)

    const r = await request(app).get(`/api/v1/projects/${proj.id}/runs`).set(auth(accessToken))
    expect(r.status).toBe(200)
    expect(r.body.items).toHaveLength(2)
    for (const item of r.body.items as Array<Record<string, unknown>>) {
      // 解析后剥离：快照重 content 不随列表下发
      expect("runConfigSnapshot" in item).toBe(false)
    }
    const byGen = (prefix: string) =>
      (r.body.items as Array<{ metrics: Record<string, number>; metricDefinitions: unknown[] }>).find(
        (x) => x.metrics?.[`${prefix}:reward`] != null,
      )
    // 两代行各自配对（跨代不互借定义）
    expect(byGen("edu")?.metricDefinitions).toEqual([
      { id: "edu:reward", name: "综合得分", threshold: 0.8, unit: "score" },
    ])
    expect(byGen("kb")?.metricDefinitions).toEqual([
      { id: "kb:reward", name: "综合得分", threshold: 0.8, unit: "score" },
    ])

    // dashboard：latest-run（新代 kb）行级 defs 同步锚定
    const d = await request(app)
      .get(`/api/v1/orgs/${owner.org.id}/projects`)
      .set(auth(accessToken))
    expect(d.status).toBe(200)
    const p = d.body.projects.find((x: { id: string }) => x.id === proj.id)
    expect(p.latestRun).not.toBeNull()
    expect(p.latestRun.metricDefinitions).toEqual([
      { id: "kb:reward", name: "综合得分", threshold: 0.8, unit: "score" },
    ])
    expect("runConfigSnapshot" in p.latestRun).toBe(false)
  })
})
