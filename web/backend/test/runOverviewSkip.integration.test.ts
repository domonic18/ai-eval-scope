/**
 * 运行速览 skip 语义测试：skipped 约束（passed=false + status=skip，如
 * 「任务未声明 expected.answer，跳过」）不进 overview failures——详情页已按
 * 灰色中性展示，汇总页「发现的问题」不应把 skip 当失败（展示策略一致）。
 */

import request from "supertest"
import { createApp } from "../src/server"
import { registerUser, createProject, issueKey, bearerPost, login } from "./helpers"

function uid(p: string) {
  return `${p}_${Date.now()}_${Math.floor(Math.random() * 1e6)}`
}

const SKIP_REASON = "任务未声明 expected.answer，跳过"

describe("GET /api/v1/runs/:id/overview — skip 不进 failures", () => {
  it("fail 约束进 failures，skip 约束被排除；样本级 skip 计数仍统计", async () => {
    const app = createApp()
    const owner = await registerUser(app, "ov-skip")
    const project = await createProject(app, owner)
    const key = await issueKey(app, { accessToken: owner.accessToken, projectId: project.id })
    const sess = await login(app, owner.email)

    const extRun = uid("run")
    const extSample = uid("s")
    const constraint = (eventId: string, name: string, status: string, passed: boolean, reason: string) => ({
      event_id: eventId,
      type: "constraint" as const,
      data: {
        external_run_id: extRun,
        external_sample_id: extSample,
        constraint_id: `c-${name}`,
        name,
        tier: "hard_score",
        status,
        passed,
        score: passed ? 1 : 0,
        reason,
        duration_ms: 10,
      },
    })

    await bearerPost(app, {
      url: "/api/public/ingest",
      token: key.token,
      bodyObj: {
        schema_version: "1.0",
        events: [
          {
            event_id: uid("ev"),
            type: "run",
            data: {
              external_run_id: extRun,
              mode: "eval_only",
              status: "completed",
              metrics: { reward: 0.6 },
              total_samples: 1,
            },
          },
          {
            event_id: uid("ev"),
            type: "sample",
            data: {
              external_run_id: extRun,
              external_sample_id: extSample,
              status: "completed",
              reward: 0.6,
            },
          },
          constraint(uid("ev"), "精确答案比对", "fail", false, "答案不一致：期望 3，实际 4"),
          constraint(uid("ev"), "精确答案提取", "skip", false, SKIP_REASON),
        ],
      },
    })

    const runsRes = await request(app)
      .get(`/api/v1/projects/${project.id}/runs`)
      .set("Authorization", `Bearer ${sess.access_token}`)
    const runId = runsRes.body.items[0].id

    const ov = await request(app)
      .get(`/api/v1/runs/${runId}/overview`)
      .set("Authorization", `Bearer ${sess.access_token}`)
    expect(ov.status).toBe(200)

    const failures = ov.body.overview.items[0].failures
    expect(failures).toHaveLength(1)
    expect(failures[0].name).toBe("精确答案比对")
    expect(JSON.stringify(failures)).not.toContain(SKIP_REASON)
  })
})
