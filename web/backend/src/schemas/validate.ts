/**
 * 事件 schema 校验（§7.3）。
 *
 * 两阶段：
 *  - validateEnvelope：**浅层**信封校验（schema_version / events 为非空数组 ≤ 上限 / 每事件含 event_id·type·data）。
 *    不深度校验事件 data —— 由逐事件 validateEvent 负责，使「单事件非法」只计入 errors[] 而非整批 400。
 *  - validateEvent：按 type 走对应分支的深度校验（必填/枚举/数值范围）。
 *
 * 该 schema 文件（ingest.event.v1.json，全量校验）亦是评估器 ResultSink（7e）的契约，
 * 评估器发送前用全量 schema 自校验；平台做浅层 + 逐事件，两层防御（NF-O-13 防漂移）。
 */

import Ajv from "ajv";
import addFormats from "ajv-formats";
import batchSchema from "./ingest.event.v1.json";

const SCHEMA_ID = "https://agent-eval/schemas/ingest.event.v1.json";

const ajv = new Ajv({ allErrors: true, strict: false });
addFormats(ajv);
ajv.addSchema(batchSchema as unknown as Record<string, unknown>);

// 浅层信封 schema（自包含，不引用事件的深度 $defs）
const envelopeShallow = {
  type: "object",
  required: ["schema_version", "events"],
  properties: {
    schema_version: { type: "string" },
    batch_id: { type: ["string", "null"] },
    project_id: { type: ["string", "null"] },
    events: {
      type: "array",
      minItems: 1,
      maxItems: 500,
      items: {
        type: "object",
        required: ["event_id", "type", "data"],
        properties: {
          event_id: { type: "string", minLength: 1 },
          type: { type: "string", enum: ["run", "sample", "constraint", "artifact"] },
          data: { type: "object" },
        },
      },
    },
  },
};

const envelopeValidator = ajv.compile(envelopeShallow);
const eventValidator = ajv.getSchema(`${SCHEMA_ID}#/$defs/event`)!;

export const SUPPORTED_SCHEMA_VERSION = "1.0";

export interface SchemaProblem {
  path: string;
  message: string;
}

/** 信封浅层校验（结构/schema_version 存在/events 形态）。 */
export function validateEnvelope(body: unknown): { ok: boolean; problems: SchemaProblem[] } {
  const ok = envelopeValidator(body);
  if (ok) return { ok: true, problems: [] };
  return { ok: false, problems: formatErrors(envelopeValidator.errors) };
}

/** 单事件深度校验（按 type 走对应分支）。 */
export function validateEvent(ev: unknown): { ok: boolean; problems: SchemaProblem[] } {
  const ok = eventValidator(ev);
  if (ok) return { ok: true, problems: [] };
  return { ok: false, problems: formatErrors(eventValidator.errors) };
}

function formatErrors(
  errs: { instancePath?: string; schemaPath?: string; message?: string }[] | null | undefined
): SchemaProblem[] {
  if (!errs) return [];
  return errs.map((e) => ({
    path: e.instancePath || e.schemaPath || "/",
    message: e.message || "invalid",
  }));
}
