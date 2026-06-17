/**
 * 审计服务（§6.5）。敏感操作（建 Key、归档项目、邀请/移除成员）经此落库。
 * 写入为 best-effort：审计失败不应阻断业务请求，仅记 warn。
 */

import { AuditRepository, type AuditEntry } from "../repositories/audit.repository";
import { getLogger } from "../infra/logger";

const repo = new AuditRepository();

async function log(entry: AuditEntry): Promise<void> {
  try {
    await repo.log(entry);
  } catch (err) {
    getLogger().warn({ action: entry.action, error: (err as Error).message }, "audit_log_failed");
  }
}

export const AuditService = { log };
export { repo as auditRepo };
