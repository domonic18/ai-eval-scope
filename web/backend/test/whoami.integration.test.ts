/**
 * /api/public/whoami 集成测试（docs/arch/15 §5.1，CLI auth login/status 身份探测）：
 *  - 有效 Key → 200 + { kind, key, project{name,slug}, org{name,slug} }
 *  - 错误/吊销 Key → 401 AUTH_INVALID
 *  - 无 Authorization → 401
 */

import request from "supertest"

import { createApp } from "../src/server"
import { registerUser, createProject, issueKey } from "./helpers"

import type express from "express"

let mgmt: express.Application
let accessToken: string
let project: { id: string; name: string; slug: string }
let token: string

beforeAll(async () => {
  mgmt = createApp()
  const user = await registerUser(mgmt, "whoami")
  accessToken = user.accessToken
  project = await createProject(mgmt, user, { name: "Whoami-项目", slug: "whoami-proj" })
  token = (await issueKey(mgmt, { accessToken, projectId: project.id }, "cli-test")).token
})

describe("GET /api/public/whoami", () => {
  it("200 returns apikey identity with project and org", async () => {
    const r = await request(mgmt)
      .get("/api/public/whoami")
      .set("Authorization", `Bearer ${token}`)
    expect(r.status).toBe(200)
    expect(r.body.kind).toBe("apikey")
    expect(r.body.key.name).toBe("cli-test")
    expect(r.body.key.scopes).toEqual(["ingest"])
    expect(r.body.project).toMatchObject({ id: project.id, name: project.name, slug: project.slug })
    expect(r.body.org).toMatchObject({ id: expect.any(String), name: expect.any(String) })
    expect(r.body.org.slug).toEqual(expect.any(String))
  })

  it("401 AUTH_INVALID for wrong token", async () => {
    const r = await request(mgmt)
      .get("/api/public/whoami")
      .set("Authorization", "Bearer eval-wrongtoken")
    expect(r.status).toBe(401)
    expect(r.body.code).toBe("AUTH_INVALID")
  })

  it("401 without Authorization header", async () => {
    const r = await request(mgmt).get("/api/public/whoami")
    expect(r.status).toBe(401)
  })

  it("401 after key revoked", async () => {
    const second = await issueKey(mgmt, { accessToken, projectId: project.id }, "cli-revoke")
    const revoke = await request(mgmt)
      .post(`/api/v1/projects/${project.id}/keys/${second.id}/revoke`)
      .set("Authorization", `Bearer ${accessToken}`)
    expect(revoke.status).toBe(200)

    const r = await request(mgmt)
      .get("/api/public/whoami")
      .set("Authorization", `Bearer ${second.token}`)
    expect(r.status).toBe(401)
  })
})
