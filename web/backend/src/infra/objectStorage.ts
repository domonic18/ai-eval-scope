/**
 * 对象存储抽象（§五）。
 *
 * - ObjectStorage 接口：presignPut / presignGet / put / get / head。
 * - S3Storage 实现：基于 @aws-sdk/client-s3 + s3-request-presigner，
 *   兼容 MinIO / AWS S3 / 腾讯云 COS（均走 S3 协议，差别仅在 endpoint/签名版本）。
 * - 工厂 createObjectStorage(cfg)：按 PLATFORM_OBJECT_STORAGE 返回实现。
 *
 * Key 布局（§5.2，前缀含 project_id 以支持租户隔离校验）：
 *   projects/{project_id}/runs/{run_id}/artifacts/{kind}/{name}
 */

import crypto from "crypto";
import {
  S3Client,
  PutObjectCommand,
  GetObjectCommand,
  HeadObjectCommand,
  HeadBucketCommand,
  CreateBucketCommand,
} from "@aws-sdk/client-s3";
import { getSignedUrl } from "@aws-sdk/s3-request-presigner";
import { getConfig, type PlatformConfig } from "../config";

export interface PresignPutResult {
  url: string;
  method: "PUT";
  headers: Record<string, string>;
  expiresAt: number;
}
export interface PresignGetResult {
  url: string;
  expiresAt: number;
}
export interface PutResult {
  md5: string;
  size: number;
}
export interface HeadResult {
  size: number;
  contentType: string;
  etag?: string;
}

/** 构造制品 key（租户隔离前缀）。 */
export function buildObjectKey(p: {
  projectId: string;
  runId: string;
  kind: string;
  name: string;
}): string {
  return `projects/${p.projectId}/runs/${p.runId}/artifacts/${p.kind}/${p.name}`;
}

/** 从 object_key 解析 projectId（用于下载签发前的租户校验 §6.4）。 */
export function projectIdFromKey(key: string): string | null {
  const m = String(key).match(/^projects\/([^/]+)\//);
  return m ? m[1] : null;
}

export interface S3StorageOpts {
  endpoint: string;
  region: string;
  bucket: string;
  forcePathStyle: boolean;
  accessKey: string;
  secretKey: string;
  kind: "s3" | "cos" | "minio";
  defaultTtlSec?: number;
}

export class S3Storage {
  readonly bucket: string;
  readonly kind: "s3" | "cos" | "minio";
  readonly defaultTtlSec: number;
  private bucketEnsured = false;
  readonly client: S3Client;

  constructor(opts: S3StorageOpts) {
    this.bucket = opts.bucket;
    this.kind = opts.kind;
    this.defaultTtlSec = opts.defaultTtlSec || 900;
    this.client = new S3Client({
      region: opts.region,
      endpoint: opts.endpoint,
      forcePathStyle: opts.forcePathStyle,
      credentials: {
        accessKeyId: opts.accessKey,
        secretAccessKey: opts.secretKey,
      },
    });
  }

  /** 懒建桶（本地 MinIO 首次启动用，幂等）。 */
  async ensureBucket(): Promise<void> {
    if (this.bucketEnsured) return;
    try {
      await this.client.send(new CreateBucketCommand({ Bucket: this.bucket }));
    } catch (err) {
      const e = err as { name?: string; $metadata?: { httpStatusCode?: number } };
      const name = e.name ?? "";
      if (name !== "BucketAlreadyOwnedByYou" && name !== "BucketAlreadyExists") {
        if (!(e.$metadata && e.$metadata.httpStatusCode === 409)) {
          throw err;
        }
      }
    }
    this.bucketEnsured = true;
  }

  /** 签发上传 URL（§5.3 两段式上传 step-1）。 */
  async presignPut(p: {
    key: string;
    contentType: string;
    md5?: string;
    ttlSec?: number;
  }): Promise<PresignPutResult> {
    await this.ensureBucket();
    const ttl = Math.min(p.ttlSec || this.defaultTtlSec, 900);
    const input: PutObjectCommand["input"] = {
      Bucket: this.bucket,
      Key: p.key,
      ContentType: p.contentType,
    };
    const headers: Record<string, string> = { "Content-Type": p.contentType };
    const md5B64 = toBase64Md5(p.md5);
    if (md5B64) {
      input.ContentMD5 = md5B64;
      headers["Content-MD5"] = md5B64;
    }
    const url = await getSignedUrl(this.client, new PutObjectCommand(input), {
      expiresIn: ttl,
    });
    return { url, method: "PUT", headers, expiresAt: epochNow() + ttl };
  }

  /** 签发下载 URL（短时效 ≤15min，§十三）。 */
  async presignGet(p: { key: string; ttlSec?: number }): Promise<PresignGetResult> {
    const ttl = Math.min(p.ttlSec || this.defaultTtlSec, 900);
    const url = await getSignedUrl(
      this.client,
      new GetObjectCommand({ Bucket: this.bucket, Key: p.key }),
      { expiresIn: ttl }
    );
    return { url, expiresAt: epochNow() + ttl };
  }

  /** 服务端兜底直传（小文件/测试）。 */
  async put(p: { key: string; body: Buffer; contentType: string }): Promise<PutResult> {
    await this.ensureBucket();
    const buf = Buffer.isBuffer(p.body) ? p.body : Buffer.from(p.body);
    await this.client.send(
      new PutObjectCommand({
        Bucket: this.bucket,
        Key: p.key,
        Body: buf,
        ContentType: p.contentType,
        ContentMD5: bufToBase64Md5(buf),
      })
    );
    return { md5: bufToHexMd5(buf), size: buf.length };
  }

  /** 下载对象为 Buffer。 */
  async get(p: { key: string }): Promise<Buffer> {
    const resp = await this.client.send(
      new GetObjectCommand({ Bucket: this.bucket, Key: p.key })
    );
    return streamToBuffer(resp.Body);
  }

  /** HEAD 对象；不存在返回 null。 */
  async head(p: { key: string }): Promise<HeadResult | null> {
    try {
      const resp = await this.client.send(
        new HeadObjectCommand({ Bucket: this.bucket, Key: p.key })
      );
      return {
        size: resp.ContentLength != null ? Number(resp.ContentLength) : 0,
        contentType: resp.ContentType || "application/octet-stream",
        etag: resp.ETag || undefined,
      };
    } catch (err) {
      const e = err as { $metadata?: { httpStatusCode?: number }; name?: string };
      const status = e.$metadata && e.$metadata.httpStatusCode;
      if (status === 404 || e.name === "NotFound") return null;
      throw err;
    }
  }

  /** /health 连通性探测：HEAD bucket（轻量、校验凭证与桶可达）。 */
  async ping(): Promise<{ ok: boolean; bucket?: string; error?: string }> {
    try {
      await this.ensureBucket();
      await this.client.send(new HeadBucketCommand({ Bucket: this.bucket }));
      return { ok: true, bucket: this.bucket };
    } catch (err) {
      return { ok: false, error: (err as Error).message };
    }
  }
}

/* ── helpers ── */
function epochNow(): number {
  return Math.floor(Date.now() / 1000);
}
function bufToHexMd5(buf: Buffer): string {
  return crypto.createHash("md5").update(buf).digest("hex");
}
function bufToBase64Md5(buf: Buffer): string {
  return crypto.createHash("md5").update(buf).digest("base64");
}
/** 接受 hex 或 base64 的 md5，统一转 base64（Content-MD5 要求 base64）。 */
function toBase64Md5(md5?: string): string | undefined {
  if (!md5) return undefined;
  if (/^[A-Za-z0-9+/=]+$/.test(md5) && md5.length % 4 === 0 && md5.length > 16) {
    return md5; // 看起来像 base64
  }
  try {
    return Buffer.from(md5, "hex").toString("base64");
  } catch {
    return undefined;
  }
}
async function streamToBuffer(stream: unknown): Promise<Buffer> {
  const chunks: Buffer[] = [];
  if (!stream || typeof (stream as AsyncIterable<Buffer>)[Symbol.asyncIterator] !== "function") {
    throw new Error("unsupported stream body");
  }
  for await (const chunk of stream as AsyncIterable<Buffer>) chunks.push(chunk);
  return Buffer.concat(chunks);
}

/** 工厂：按配置返回对象存储实现。 */
export function createObjectStorage(cfg?: PlatformConfig): S3Storage {
  const config = cfg || getConfig();
  const kind = config.objectStorage;
  if (!["minio", "s3", "cos"].includes(kind)) {
    throw new Error(`unsupported PLATFORM_OBJECT_STORAGE: ${kind}`);
  }
  return new S3Storage({
    endpoint: config.s3Endpoint,
    region: config.s3Region,
    bucket: config.s3Bucket,
    forcePathStyle: config.s3PathStyle,
    accessKey: config.s3AccessKey,
    secretKey: config.s3SecretKey,
    kind,
    defaultTtlSec: config.presignTtlSec,
  });
}

let _storage: S3Storage | null = null;

/** 进程级单例。 */
export function getObjectStorage(): S3Storage {
  if (!_storage) _storage = createObjectStorage();
  return _storage;
}
