/**
 * 规则集静态 catalog 读取（构建期由 scripts/gen_rule_sets.py 生成）。
 *
 * catalog 落 web/backend/assets/rule-sets.json；eval /debug 路由共用此读取器（docs/arch/09 §7.7）。
 */

import fs from "fs"
import path from "path"

let _cache: unknown[] | undefined

/** 读取规则集 catalog（进程级缓存；首读后缓存）。
 *
 * 路径：编译后 __dirname = dist/src/infra → ../../../ 为 web/backend 根（WORKDIR），
 * 即 web/backend/assets/rule-sets.json；该文件由 Dockerfile
 * `COPY web/backend/assets ./assets` 提供到镜像。
 */
export function readRuleSetsCatalog(): unknown[] {
  if (_cache === undefined) {
    _cache = JSON.parse(
      fs.readFileSync(path.resolve(__dirname, "../../../assets/rule-sets.json"), "utf-8"),
    ) as unknown[]
  }
  return _cache
}
