/**
 * 规则集静态 catalog 读取（构建期由 scripts/gen_rule_sets.py 生成）。
 *
 * catalog 落 web/backend/assets/rule-sets.json；Phase 3 起动态目录（DB RuleSetAsset）为权威，
 * 此静态文件仅作能力声明（capabilities/scopes）补充，读取失败时返回 []（best-effort）。
 */

import fs from "fs"
import path from "path"

let _cache: unknown[] | undefined

/**
 * 读取静态 catalog（进程级缓存；best-effort）。
 *
 * 路径随运行形态不同：编译后 __dirname=dist/src/infra → ../../../assets/（web/backend 根）；
 * 源码运行（tsx/vitest）__dirname=src/infra → ../../assets/。逐个尝试，命中即缓存，全 miss 返回 []。
 */
export function readRuleSetsCatalog(): unknown[] {
  if (_cache !== undefined) return _cache
  const candidates = [
    path.resolve(__dirname, "../../../assets/rule-sets.json"), // dist/src/infra → web/backend
    path.resolve(__dirname, "../../assets/rule-sets.json"), // src/infra → web/backend
  ]
  for (const p of candidates) {
    if (fs.existsSync(p)) {
      _cache = JSON.parse(fs.readFileSync(p, "utf-8")) as unknown[]
      return _cache
    }
  }
  _cache = [] // 静态文件缺失（如源码运行未生成）→ 空数组，动态目录仍可用
  return _cache
}

