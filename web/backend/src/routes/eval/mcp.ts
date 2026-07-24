/**
 * MCP 接入路由（/api/v1/mcp）—— 第三方对接第三种模式（docs/arch/12 §3.7 v4.0）。
 *
 * 任意 MCP 兼容客户端（Claude Code / Cursor / Windsurf 等）经 MCP 协议提交评测、
 * 查询状态、看速览。与 HTTP 同一把 API Key（requireApiKey 前置注入 req.tenant）、
 * 同一套业务（复用 createEvalJobService / readRuleSetsCatalog / objectStorage）。
 *
 * 传输：官方 TS SDK 的 StreamableHTTPServerTransport（远程第三方接入用 HTTP/SSE）。
 * 会话：stateful，每个会话建独立 McpServer，闭包捕获 initialize 请求的 tenant
 * （同一客户端用同一把 Key，租户一致；requireApiKey 仍逐请求校验）。
 */

import { randomUUID } from "crypto"
import { Router } from "express"
import { z } from "zod"
// MCP SDK（ESM-first，tsconfig paths 映射 d.ts；运行时经 package exports 解析 cjs）
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js"
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js"
import { getObjectStorage } from "../../infra/objectStorage"
import { readRuleSetsCatalog } from "../../infra/ruleSetsCatalog"
import { getLogger } from "../../infra/logger"
import { PlatformError } from "../../middleware/errorHandler"
import type { Tenant } from "../../repositories/base.repository"
import { createEvalJobService } from "../../services/evalJob.service"

const router = Router()
const logger = getLogger()

// MCP submit 工具内 base64 解码上限（解码后字节）。超出 → 引导走 request_input_upload
// （presigned PUT 直传）。受全局 express.json 8mb 限制约束，故取 5MB 解码安全余量。
const MCP_BASE64_MAX_BYTES = 5 * 1024 * 1024

interface Session {
  transport: StreamableHTTPServerTransport
  server: McpServer
}
const sessions = new Map<string, Session>()

// ---- MCP 工具结果封装 ----
type McpToolResult = {
  content: { type: "text"; text: string }[]
  isError?: boolean
}
function mcpOk(data: unknown): McpToolResult {
  return { content: [{ type: "text", text: JSON.stringify(data) }] }
}
function mcpError(e: unknown): McpToolResult {
  const err = e as { code?: string; message?: string }
  const code = err.code || "INTERNAL"
  return {
    isError: true,
    content: [{ type: "text", text: JSON.stringify({ code, error: err.message || "internal error" }) }],
  }
}
function notFound(msg: string): McpToolResult {
  return mcpError(new PlatformError(msg, { status: 404, code: "JOB_NOT_FOUND" }))
}

/**
 * 为指定 tenant 构建一个 McpServer（注册 6 工具，闭包捕获 tenant）。
 * 工具与 HTTP 接口一一对应，复用既有 service / infra。
 */
function buildServer(tenant: Tenant): McpServer {
  const server = new McpServer({ name: "evalscope", version: "1.0.0" })
  const svc = () => createEvalJobService(tenant)

  // 1. list_rule_sets —— GET /api/v1/rule-sets
  server.registerTool(
    "list_rule_sets",
    { description: "列出可用的评测规则集目录（含所需能力）" },
    async () => {
      try {
        return mcpOk({ rule_sets: readRuleSetsCatalog() })
      } catch (e) {
        return mcpError(e)
      }
    },
  )

  // 2. eval_health —— GET /api/v1/health
  server.registerTool(
    "eval_health",
    { description: "eval 子系统健康检查" },
    async () => mcpOk({ status: "ok", subsystem: "eval" }),
  )

  // 3. get_eval_job —— GET /api/v1/jobs/:id
  server.registerTool(
    "get_eval_job",
    {
      description: "查询评测任务状态与指标",
      inputSchema: { job_id: z.string().describe("任务 id") },
    },
    async (args) => {
      try {
        const job = await svc().get(args.job_id)
        return job ? mcpOk(job) : notFound("job not found")
      } catch (e) {
        return mcpError(e)
      }
    },
  )

  // 4. get_eval_job_overview —— GET /api/v1/jobs/:id/overview
  server.registerTool(
    "get_eval_job_overview",
    {
      description: "评测速览：过没过 / 多少分 + 各评测项失败原因（深度详情走 iframe）",
      inputSchema: { job_id: z.string().describe("任务 id") },
    },
    async (args) => {
      try {
        const ov = await svc().overview(args.job_id)
        return ov ? mcpOk(ov) : notFound("job not found")
      } catch (e) {
        return mcpError(e)
      }
    },
  )

  // 5. request_input_upload —— 大文件专用：presigned PUT 直传对象存储
  server.registerTool(
    "request_input_upload",
    {
      description:
        "大文件上传：签发 presigned PUT URL，客户端直传对象存储后，把返回的 object_key 传给 submit_eval_job（避免 MCP 传大 base64）。文件名决定评估粒度：.zip → 单元评估（多文件目录树），.html/.md 等 → 单页评估。",
      inputSchema: {
        filename: z.string().describe("文件名（决定扩展名与评估粒度：unit.zip / lesson.html / notes.md）"),
        content_type: z.string().optional().describe("可选 MIME，默认 application/octet-stream"),
      },
    },
    async (args) => {
      try {
        if (!tenant.projectId) {
          return mcpError(new PlatformError("missing tenant context", { status: 403, code: "FORBIDDEN" }))
        }
        const ext = (args.filename.match(/\.[^.]+$/) || [".md"])[0]
        const objectKey = `projects/${tenant.projectId}/eval/jobs/uploads/${randomUUID()}/input${ext}`
        const storage = getObjectStorage()
        const presigned = await storage.presignPut({
          key: objectKey,
          contentType: args.content_type || "application/octet-stream",
        })
        return mcpOk({
          upload_url: presigned.url,
          object_key: objectKey,
          expires_at: presigned.expiresAt,
          hint: "PUT 二进制到 upload_url 后，调 submit_eval_job 传 input_object_key",
        })
      } catch (e) {
        return mcpError(e)
      }
    },
  )

  // 6. submit_eval_job —— POST /api/v1/jobs（三种承载方式分层）
  server.registerTool(
    "submit_eval_job",
    {
      description:
        "提交评测任务（异步）。入参三选一：content(inline 文本) / file(base64 小二进制 ≤5MB) / input_object_key(大文件，先用 request_input_upload 直传)。文件名决定评估粒度：.zip 为单元评估（多文件目录树），.html/.md 等为单页评估；声明为 .zip 但内容不是合法 zip 会被拒绝。",
      inputSchema: {
        content: z
          .object({ filename: z.string(), text: z.string() })
          .optional()
          .describe("inline 文本内容（小体量 HTML/Markdown）"),
        file: z
          .object({ filename: z.string(), base64: z.string() })
          .optional()
          .describe("base64 小二进制（解码后 ≤5MB）；.zip → 单元评估，.html/.md → 单页评估"),
        input_object_key: z
          .string()
          .optional()
          .describe("大文件：request_input_upload 返回的 object_key；key 以 .zip 结尾会按单元评估解压"),
        rule_set_id: z.string().optional(),
        package_ref: z.string().optional(),
        task_id: z.string().optional(),
        task_title: z.string().optional(),
        task_subject: z.string().optional(),
      },
    },
    async (args) => {
      try {
        const ruleSetId = args.rule_set_id || "coursework-quality"
        const common = {
          ruleSetId,
          packageRef: args.package_ref,
          taskId: args.task_id,
          taskTitle: args.task_title,
          taskSubject: args.task_subject,
        }
        if (args.input_object_key) {
          return mcpOk(await svc().submit({ ...common, inputObjectKey: args.input_object_key }))
        }
        if (args.file) {
          const bytes = Buffer.from(args.file.base64, "base64")
          if (bytes.length > MCP_BASE64_MAX_BYTES) {
            return mcpError(
              new PlatformError(
                `base64 文件过大(${bytes.length} > ${MCP_BASE64_MAX_BYTES})，请改用 request_input_upload 直传`,
                { status: 413, code: "PAYLOAD_TOO_LARGE" },
              ),
            )
          }
          return mcpOk(await svc().submit({ ...common, filename: args.file.filename, fileBytes: bytes }))
        }
        if (args.content) {
          return mcpOk(
            await svc().submit({
              ...common,
              inlineFilename: args.content.filename,
              inlineText: args.content.text,
            }),
          )
        }
        return mcpError(
          new PlatformError("必须提供 content / file / input_object_key 之一", {
            status: 400,
            code: "INPUT_INVALID",
          }),
        )
      } catch (e) {
        return mcpError(e)
      }
    },
  )

  return server
}

// ---- Express 路由：把 MCP 协议请求交给会话的 transport ----

router.post("/", async (req, res) => {
  try {
    const sessionId = req.header("mcp-session-id")
    let session = sessionId ? sessions.get(sessionId) : undefined
    if (!session) {
      // initialize（无会话）→ 建新会话，闭包捕获 req.tenant（由 requireApiKey 注入）
      const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: () => randomUUID() })
      const server = buildServer(req.tenant!)
      transport.onclose = () => {
        const sid = transport.sessionId
        if (sid) {
          sessions.delete(sid)
        }
        server.close().catch(() => {})
      }
      await server.connect(transport)
      session = { transport, server }
      await session.transport.handleRequest(req, res, req.body)
      // sessionId 在 handleRequest 后才生成，注册进 map 供后续请求复用
      if (session.transport.sessionId) {
        sessions.set(session.transport.sessionId, session)
      }
    } else {
      await session.transport.handleRequest(req, res, req.body)
    }
  } catch (e) {
    logger.error({ error: (e as Error).message }, "mcp_post_failed")
    if (!res.headersSent) {
      res.status(500).json({ error: "mcp handler failed", code: "INTERNAL" })
    }
  }
})

router.get("/", async (req, res) => {
  const sessionId = req.header("mcp-session-id")
  const session = sessionId ? sessions.get(sessionId) : undefined
  if (!session) {
    res.status(406).json({ error: "session required for GET (SSE)", code: "MCP_SESSION_REQUIRED" })
    return
  }
  try {
    await session.transport.handleRequest(req, res)
  } catch (e) {
    logger.error({ error: (e as Error).message }, "mcp_get_failed")
  }
})

router.delete("/", async (req, res) => {
  const sessionId = req.header("mcp-session-id")
  const session = sessionId ? sessions.get(sessionId) : undefined
  if (!session) {
    res.status(404).json({ error: "session not found", code: "MCP_SESSION_NOT_FOUND" })
    return
  }
  try {
    await session.transport.handleRequest(req, res)
  } finally {
    sessions.delete(sessionId!)
    await session.server.close().catch(() => {})
  }
})

export default router
