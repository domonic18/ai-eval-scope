/**
 * 验证标准 #1：/health 返回 db / object_storage 均 ok + schema_version。
 * 依赖：docker compose 起的 postgres + minio（test/setup.ts 指向）。
 */

import request from "supertest";
import { createApp } from "../src/server";

describe("GET /health", () => {
  let app: ReturnType<typeof createApp>;
  beforeAll(() => {
    app = createApp();
  });

  it("returns 200 with db + object_storage ok and schema_version 1.0", async () => {
    const res = await request(app).get("/health");
    expect(res.status).toBe(200);
    expect(res.body.status).toBe("ok");
    expect(res.body.schema_version).toBe("1.0");
    expect(res.body.components.db.ok).toBe(true);
    expect(res.body.components.db.latency_ms).toBeGreaterThanOrEqual(0);
    expect(res.body.components.object_storage.ok).toBe(true);
  });

  it("also responds on /api/health (platform health alias)", async () => {
    const res = await request(app).get("/api/health");
    expect(res.status).toBe(200);
    expect(res.body.components.db.ok).toBe(true);
  });
});
