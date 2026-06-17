/**
 * 制品 presigned 上传（/api/public/artifacts/url，HMAC 鉴权）。
 *
 * 客户端发送 {external_run_id, kind, name, content_type, size_bytes?, md5?}，
 * 平台以 Key 所属项目 + external_run_id 构造对象 key（租户隔离前缀）并签发 presigned PUT。
 * 客户端 PUT 上传后，再以 artifact 事件回填引用（object_key 一致）。
 */

import { Router, type RequestHandler } from "express";
import { requireApiKey } from "../../middleware/apiKeyAuth";
import { getObjectStorage, buildObjectKey } from "../../infra/objectStorage";
import { getConfig } from "../../config";
import { PlatformError } from "../../middleware/errorHandler";

const router = Router();

const wrap =
  (fn: RequestHandler): RequestHandler =>
  (req, res, next) =>
    Promise.resolve(fn(req, res, next)).catch(next);

router.post(
  "/url",
  requireApiKey,
  wrap(async (req, res) => {
    const projectId = req.tenant!.projectId!;
    const cfg = getConfig();
    const b = (req.body || {}) as {
      external_run_id?: string;
      kind?: string;
      name?: string;
      content_type?: string;
      md5?: string;
    };

    if (!b.external_run_id || !b.kind || !b.name || !b.content_type) {
      throw new PlatformError(
        "external_run_id, kind, name, content_type required",
        { status: 400, code: "SCHEMA_INVALID" }
      );
    }

    // key 用 external_run_id 作路径段（制品在 ingest 之前上传，平台 run UUID 尚未生成）
    const key = buildObjectKey({
      projectId,
      runId: b.external_run_id,
      kind: b.kind,
      name: b.name,
    });

    const presigned = await getObjectStorage().presignPut({
      key,
      contentType: b.content_type,
      md5: b.md5,
      ttlSec: cfg.presignTtlSec,
    });

    res.status(200).json({
      object_key: key,
      upload_url: presigned.url,
      headers: presigned.headers,
      expires_at: presigned.expiresAt,
    });
  })
);

export default router;
