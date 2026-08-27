/**
 * task-sets / sut-configs 资产接入测试（arch/13 §四：考卷与 SUT 接入内嵌于场景包）。
 * POST /scenarios/:id/{task-sets,sut-configs}、content/versions/labels、catalog 聚合。
 * 语义：task-set assetId=文件 stem、content=完整考卷；sut-config assetId=sut.name、content=仅 sut: 子树。
 */

import { describe, it, expect, afterEach } from "vitest"
import request from "supertest"
import { createApp } from "../src/server"
import { registerUser } from "./helpers"
import { getPrisma } from "../src/infra/prisma"

const prisma = getPrisma()
const SCENARIO_ID = `test-ts-sut-${Date.now()}`
const USER_EMAIL: string[] = []
const ORG_SLUGS: string[] = []

afterEach(async () => {
  await prisma.taskSetAsset.deleteMany({ where: { scenarioId: SCENARIO_ID } }).catch(() => {})
  await prisma.sutConfigAsset.deleteMany({ where: { scenarioId: SCENARIO_ID } }).catch(() => {})
  await prisma.scenario.deleteMany({ where: { id: SCENARIO_ID } }).catch(() => {})
  for (const slug of ORG_SLUGS) await prisma.organization.deleteMany({ where: { slug } }).catch(() => {})
  for (const email of USER_EMAIL) await prisma.user.deleteMany({ where: { email } }).catch(() => {})
  ORG_SLUGS.length = 0
  USER_EMAIL.length = 0
})

async function adminToken(app: ReturnType<typeof createApp>, tag: string) {
  const u = await registerUser(app, tag)
  USER_EMAIL.push(u.email)
  ORG_SLUGS.push(u.org.slug)
  await prisma.user.update({ where: { email: u.email }, data: { role: "admin" } })
  return u.accessToken
}

const TASK_SET = {
  id: "exam_general_001",
  name: "通用考卷",
  description: "测试用考卷",
  tasks: [
    {
      id: "identity_001",
      input: { instruction: "请介绍一下你自己", intent: "identity_self_description" },
      expected: { must_mention: ["角色定位"] },
      constraints: { max_turns: 2 },
    },
  ],
}

const SUT_SUBTREE = {
  name: "sut-a",
  channel: "agent_protocol",
  base_url: "https://sut-a.example.com",
  protocol_flavor: "commands",
  exec_mode: "wait",
  timeout: 300,
  auth: { type: "api_login", credential_ref: "SUT_A" },
}

describe("task-sets / sut-configs asset publish", () => {
  it("publishes both kinds (201) → catalog 聚合（task_count/channel）→ content 读取（sut 无壳）", async () => {
    const app = createApp()
    const tok = await adminToken(app, "ts-ok")

    const ts = await request(app)
      .post(`/api/v1/scenarios/${SCENARIO_ID}/task-sets`)
      .set("Authorization", `Bearer ${tok}`)
      .send({ asset_id: "default", version: "1.0.0", content: TASK_SET })
    expect(ts.status).toBe(201)
    expect(ts.body.asset).toEqual({ assetId: "default", version: "1.0.0" })

    const sut = await request(app)
      .post(`/api/v1/scenarios/${SCENARIO_ID}/sut-configs`)
      .set("Authorization", `Bearer ${tok}`)
      .send({ asset_id: "sut-a", version: "1.0.0", content: SUT_SUBTREE })
    expect(sut.status).toBe(201)

    const cat = await request(app).get(`/api/v1/scenarios/${SCENARIO_ID}/catalog`)
    expect(cat.status).toBe(200)
    const tsEntry = cat.body.task_sets.find((t: { asset_id: string }) => t.asset_id === "default")
    expect(tsEntry).toBeTruthy()
    expect(tsEntry.task_count).toBe(1)
    expect(tsEntry.name).toBe("通用考卷")
    const sutEntry = cat.body.sut_configs.find((s: { asset_id: string }) => s.asset_id === "sut-a")
    expect(sutEntry).toBeTruthy()
    expect(sutEntry.channel).toBe("agent_protocol")

    // content：task-set 返回完整考卷；sut-config 返回子树（顶层即 name，无 sut: 壳）
    const tsContent = await request(app).get(`/api/v1/scenarios/${SCENARIO_ID}/task-sets/default/content`)
    expect(tsContent.status).toBe(200)
    expect(tsContent.body.content.tasks).toHaveLength(1)

    const sutContent = await request(app).get(`/api/v1/scenarios/${SCENARIO_ID}/sut-configs/sut-a/content`)
    expect(sutContent.status).toBe(200)
    expect(sutContent.body.content.name).toBe("sut-a")
    expect(sutContent.body.content.sut).toBeUndefined()
  })

  it("400：tasks 非数组 / sut.name 与 asset_id 不一致 / 缺 asset_id", async () => {
    const app = createApp()
    const tok = await adminToken(app, "ts-bad")

    const badTasks = await request(app)
      .post(`/api/v1/scenarios/${SCENARIO_ID}/task-sets`)
      .set("Authorization", `Bearer ${tok}`)
      .send({ asset_id: "default", version: "1.0.0", content: { name: "空考卷" } })
    expect(badTasks.status).toBe(400)

    const nameMismatch = await request(app)
      .post(`/api/v1/scenarios/${SCENARIO_ID}/sut-configs`)
      .set("Authorization", `Bearer ${tok}`)
      .send({ asset_id: "sut-b", version: "1.0.0", content: { ...SUT_SUBTREE, name: "sut-a" } })
    expect(nameMismatch.status).toBe(400)
    expect(JSON.stringify(nameMismatch.body)).toContain("一致")

    const noName = await request(app)
      .post(`/api/v1/scenarios/${SCENARIO_ID}/sut-configs`)
      .set("Authorization", `Bearer ${tok}`)
      .send({ asset_id: "sut-c", version: "1.0.0", content: { channel: "agent_protocol" } })
    expect(noName.status).toBe(400)

    const missing = await request(app)
      .post(`/api/v1/scenarios/${SCENARIO_ID}/task-sets`)
      .set("Authorization", `Bearer ${tok}`)
      .send({ version: "1.0.0" })
    expect(missing.status).toBe(400)
  })

  it("409：同 (asset_id, version) 重发被拒（不可变），原行 labels 不被覆盖", async () => {
    const app = createApp()
    const tok = await adminToken(app, "ts-imm")
    const url = `/api/v1/scenarios/${SCENARIO_ID}/sut-configs`
    const first = await request(app)
      .post(url)
      .set("Authorization", `Bearer ${tok}`)
      .send({ asset_id: "sut-a", version: "1.0.0", labels: ["production"], content: SUT_SUBTREE })
    expect(first.status).toBe(201)
    const again = await request(app)
      .post(url)
      .set("Authorization", `Bearer ${tok}`)
      .send({ asset_id: "sut-a", version: "1.0.0", content: { ...SUT_SUBTREE, timeout: 60 } })
    expect(again.status).toBe(409)
    const row = await prisma.sutConfigAsset.findUnique({
      where: { scenarioId_assetId_version: { scenarioId: SCENARIO_ID, assetId: "sut-a", version: "1.0.0" } },
    })
    expect(row?.labels).toContain("production")
    expect((row?.content as Record<string, unknown>).timeout).toBe(300) // 原内容未被覆盖
  })

  it("403：非 admin 发布被拒", async () => {
    const app = createApp()
    const nonAdmin = await registerUser(app, "ts-no")
    USER_EMAIL.push(nonAdmin.email)
    ORG_SLUGS.push(nonAdmin.org.slug)
    const forbidden = await request(app)
      .post(`/api/v1/scenarios/${SCENARIO_ID}/task-sets`)
      .set("Authorization", `Bearer ${nonAdmin.accessToken}`)
      .send({ asset_id: "default", version: "1.0.0", content: TASK_SET })
    expect(forbidden.status).toBe(403)
  })

  it("versions 历史 + 标签互斥晋升（production 全局唯一）", async () => {
    const app = createApp()
    const tok = await adminToken(app, "ts-ver")
    for (const [ver, content] of [
      ["1.0.0", TASK_SET],
      ["1.1.0", { ...TASK_SET, tasks: [...TASK_SET.tasks, { ...TASK_SET.tasks[0], id: "t2" }] }],
    ] as const) {
      const r = await request(app)
        .post(`/api/v1/scenarios/${SCENARIO_ID}/task-sets`)
        .set("Authorization", `Bearer ${tok}`)
        .send({ asset_id: "default", version: ver, content })
      expect(r.status).toBe(201)
    }

    const versions = await request(app).get(`/api/v1/scenarios/${SCENARIO_ID}/task-sets/default/versions`)
    expect(versions.status).toBe(200)
    expect(versions.body.versions).toHaveLength(2)

    const promote = (ver: string, labels: string[]) =>
      request(app)
        .post(`/api/v1/scenarios/${SCENARIO_ID}/task-sets/default/versions/${ver}/labels`)
        .set("Authorization", `Bearer ${tok}`)
        .send({ labels })
    expect((await promote("1.0.0", ["production"])).status).toBe(200)
    expect((await promote("1.1.0", ["production"])).status).toBe(200)

    const v1 = await prisma.taskSetAsset.findUnique({
      where: { scenarioId_assetId_version: { scenarioId: SCENARIO_ID, assetId: "default", version: "1.0.0" } },
    })
    expect(v1?.labels).not.toContain("production") // 已被摘除
  })

  it("catalog 版本选择：production 优先于 latest（sut-configs）", async () => {
    const app = createApp()
    const tok = await adminToken(app, "ts-pick")
    const url = `/api/v1/scenarios/${SCENARIO_ID}/sut-configs`
    await request(app)
      .post(url)
      .set("Authorization", `Bearer ${tok}`)
      .send({ asset_id: "sut-a", version: "1.0.0", content: SUT_SUBTREE }) // 发布即 latest
    await request(app)
      .post(url)
      .set("Authorization", `Bearer ${tok}`)
      .send({ asset_id: "sut-a", version: "1.1.0", labels: ["production"], content: SUT_SUBTREE })

    const cat = await request(app).get(`/api/v1/scenarios/${SCENARIO_ID}/catalog`)
    const entry = cat.body.sut_configs.find((s: { asset_id: string }) => s.asset_id === "sut-a")
    expect(entry.version).toBe("1.1.0")
  })

  it("404：未知 kind 的 content/versions/publish 全部拒绝", async () => {
    const app = createApp()
    expect(
      (await request(app).get(`/api/v1/scenarios/${SCENARIO_ID}/foo/x/content`)).status,
    ).toBe(404)
    expect(
      (await request(app).get(`/api/v1/scenarios/${SCENARIO_ID}/foo/x/versions`)).status,
    ).toBe(404)
    const tok = await adminToken(app, "ts-404")
    const r = await request(app)
      .post(`/api/v1/scenarios/${SCENARIO_ID}/foo`)
      .set("Authorization", `Bearer ${tok}`)
      .send({ asset_id: "x", version: "1.0.0" })
    expect(r.status).toBe(404)
  })
})
