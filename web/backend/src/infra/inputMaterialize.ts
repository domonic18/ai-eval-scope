/**
 * 输入物化（Web 侧）—— 仅做 scope 探测与大小校验。
 *
 * 解压在 executor 消费侧（input_loader）；Web 不解压，只上传原始字节 + 推导 scope 元数据。
 * zip-slip 防护、中文文件名编码修正等都在 executor 解压时处理。
 */

import { PlatformError } from "../middleware/errorHandler"

export type Scope = "single" | "unit"
export type InputKind = "upload" | "inline"

export interface MaterializedInput {
  bytes: Buffer
  filename: string
  scope: Scope
  inputKind: InputKind
}

const MAX_UPLOAD_BYTES = 50 * 1024 * 1024

/** zip 魔数探测（PK）。 */
export function isZip(bytes: Buffer): boolean {
  return bytes.length >= 2 && bytes[0] === 0x50 && bytes[1] === 0x4b
}

/** multipart 文件 → scope 探测（zip→unit，否则 single）。 */
export function materializeUpload(
  filename: string,
  bytes: Buffer,
  maxBytes: number = MAX_UPLOAD_BYTES,
): MaterializedInput {
  if (!bytes || bytes.length === 0) {
    throw new PlatformError("file body is empty", { status: 400, code: "INPUT_INVALID" })
  }
  if (bytes.length > maxBytes) {
    throw new PlatformError(`upload exceeds max size ${maxBytes} bytes`, {
      status: 413,
      code: "PAYLOAD_TOO_LARGE",
    })
  }
  return {
    bytes,
    filename,
    scope: isZip(bytes) ? "unit" : "single",
    inputKind: "upload",
  }
}

/** 内联 JSON → 单页。 */
export function materializeInline(filename: string, text: string): MaterializedInput {
  const bytes = Buffer.from(text, "utf-8")
  if (bytes.length > MAX_UPLOAD_BYTES) {
    throw new PlatformError(`inline content exceeds max size ${MAX_UPLOAD_BYTES} bytes`, {
      status: 413,
      code: "PAYLOAD_TOO_LARGE",
    })
  }
  return { bytes, filename, scope: "single", inputKind: "inline" }
}
