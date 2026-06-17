/**
 * 数据访问层基类（§6.4 隔离实现）。
 *
 * 隔离是数据层的强制行为：所有「评估数据/项目资源」查询必须带 org_id/project_id 过滤，
 * 由 tenant 上下文注入；repository 构造时绑定 tenant，作用域查询缺 tenant 直接抛错。
 *
 * 业务层（services）不直接访问 PrismaClient，只能经由 repository。
 */

import { PrismaClient } from "@prisma/client";
import { getPrisma } from "../infra/prisma";
import { PlatformError } from "../middleware/errorHandler";

/** 租户上下文（由 auth/apiKeyAuth/tenantGuard 注入到 req.tenant，再传给 repository）。 */
export interface Tenant {
  kind?: "user" | "apikey";
  userId?: string;
  orgId?: string;
  projectId?: string;
  role?: string;
  apiKeyId?: string;
  scopes?: string[];
}

export abstract class BaseRepository {
  protected readonly prisma: PrismaClient;
  protected readonly tenant: Tenant;

  constructor(tenant?: Tenant) {
    this.prisma = getPrisma();
    this.tenant = tenant || {};
  }

  /** 断言租户含 orgId（组织/项目级操作前置）。 */
  protected requireOrg(): string {
    if (!this.tenant.orgId) {
      throw new PlatformError("missing org context", { status: 403, code: "FORBIDDEN" });
    }
    return this.tenant.orgId;
  }

  /** 断言租户含 projectId（项目级操作前置）。 */
  protected requireProject(): string {
    if (!this.tenant.projectId) {
      throw new PlatformError("missing project context", { status: 403, code: "FORBIDDEN" });
    }
    return this.tenant.projectId;
  }
}
