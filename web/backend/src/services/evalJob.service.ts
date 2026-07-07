/**
 * 评测任务提交 / 查询服务（docs/arch/14）。
 *
 * 提交流程：物化输入 → 上传对象存储 → 签发 presigned GET → 写 eval_jobs(queued)
 *           → SCF Invoke Event 触发 executor（生产）。
 *
 * SCF 未启用时仅入队，由 executor worker 模式轮询（本地开发）。
 * executor 不持对象存储凭据：经 presigned GET URL 下载输入。
 */

import crypto from "crypto"
import { getConfig } from "../config"
import { getObjectStorage } from "../infra/objectStorage"
import {
  materializeInline,
  materializeUpload,
  type MaterializedInput,
} from "../infra/inputMaterialize"
import { invokeScf, type ScfInvokePayload } from "../infra/scf"
import { PlatformError } from "../middleware/errorHandler"
import { EvalJobRepository } from "../repositories/evalJob.repository"
import type { Tenant } from "../repositories/base.repository"

export interface SubmitInput {
  // multipart 文件
  filename?: string
  fileBytes?: Buffer
  // 内联 JSON
  inlineFilename?: string
  inlineText?: string
  // 元数据
  ruleSetId: string
  taskId?: string
  taskTitle?: string
  taskSubject?: string
}

export interface SubmitResult {
  job_id: string
  status: "queued"
  project_id: string
  poll_url: string
  scf_request_id?: string
}

function extOf(filename: string, scope: "single" | "unit"): string {
  const dot = filename.lastIndexOf(".")
  if (dot >= 0) return filename.slice(dot)
  return scope === "unit" ? ".zip" : ".md"
}

function buildObjectKey(projectId: string, jobId: string, mat: MaterializedInput): string {
  return `projects/${projectId}/eval/jobs/${jobId}/input${extOf(mat.filename, mat.scope)}`
}

export function createEvalJobService(tenant: Tenant) {
  const repo = new EvalJobRepository(tenant)
  const storage = getObjectStorage()

  async function submit(input: SubmitInput): Promise<SubmitResult> {
    if (!tenant.projectId || !tenant.orgId || !tenant.apiKeyId) {
      throw new PlatformError("missing tenant context (project/org/apiKey)", {
        status: 403,
        code: "FORBIDDEN",
      })
    }
    const projectId = tenant.projectId
    const jobId = crypto.randomUUID()

    // 物化输入 + scope 探测
    const mat = input.fileBytes
      ? materializeUpload(input.filename || "input", input.fileBytes)
      : materializeInline(input.inlineFilename || "input.md", input.inlineText || "")

    // 上传对象存储 + 签发短期 presigned GET（executor 下载用，不持凭据）
    const objectKey = buildObjectKey(projectId, jobId, mat)
    await storage.put({ key: objectKey, body: mat.bytes, contentType: "application/octet-stream" })
    const presigned = await storage.presignGet({ key: objectKey })

    // 写 eval_jobs（queued）
    await repo.create({
      jobId,
      projectId,
      orgId: tenant.orgId,
      apiKeyId: tenant.apiKeyId,
      inputKind: mat.inputKind,
      scope: mat.scope,
      inputObjectKey: objectKey,
      inputPresignedUrl: presigned.url,
      ruleSetId: input.ruleSetId,
      taskId: input.taskId ?? null,
      taskTitle: input.taskTitle ?? null,
      taskSubject: input.taskSubject ?? null,
    })

    // 触发 executor（生产 SCF；本地 TENCENT_SCF_ENABLED=false 时仅入队，由 worker 轮询）
    const cfg = getConfig()
    let scfRequestId: string | undefined
    if (cfg.scfEnabled) {
      const payload: ScfInvokePayload = {
        job_id: jobId,
        rule_set_id: input.ruleSetId,
        input_kind: mat.inputKind,
        scope: mat.scope,
        input_object_key: objectKey,
        input_presigned_url: presigned.url,
        task_id: input.taskId,
        task_title: input.taskTitle,
        task_subject: input.taskSubject,
      }
      const resp = await invokeScf(payload)
      scfRequestId = resp.RequestId
      if (scfRequestId) {
        await repo.updateScfRequestId(jobId, scfRequestId).catch(() => {
          /* best-effort：链路追踪字段，失败不影响提交 */
        })
      }
    }

    return {
      job_id: jobId,
      status: "queued",
      project_id: projectId,
      poll_url: `/api/v1/jobs/${jobId}`,
      scf_request_id: scfRequestId,
    }
  }

  async function get(jobId: string) {
    return repo.findById(jobId)
  }

  return { submit, get }
}
