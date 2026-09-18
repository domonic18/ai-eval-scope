/**
 * 场景默认指标定义 hook（模块级缓存，多页面共享一次 fetch）。
 *
 * 指标定义统一来自后端 GET /scenarios/:id/defaults（单一源落库，由 import 脚本写入）。
 *
 * docs/plan/08 批次 C：run 展示（Dashboard/列表/明细）已改吃后端行级下发
 * metricDefinitions（锚定各 run 自带快照），本 hook 仅剩两类消费方——
 * RunDetail 的无快照兜底、DebugPage 的「当前登记预览」。
 */
import { useEffect, useState } from "react"
import { api } from "../api/client"
import type { MetricDef } from "../types"

const _cache = new Map<string, MetricDef[]>()

/** 按场景 id 拉取默认指标定义（命中模块缓存即返回缓存值，不重复请求）。 */
function fetchScenarioDefaults(scenarioId: string): Promise<MetricDef[]> {
  if (_cache.has(scenarioId)) return Promise.resolve(_cache.get(scenarioId)!)
  return api.scenarioDefaults(scenarioId).then((d) => {
    _cache.set(scenarioId, d)
    return d
  })
}

/** 单场景指标定义（scenarioId 未定/空时不拉取；拉取失败清空——宁可回退运行快照，不留上一次的脏定义）。 */
export function useScenarioDefaults(scenarioId: string | null | undefined): MetricDef[] {
  const [defs, setDefs] = useState<MetricDef[]>(
    scenarioId ? (_cache.get(scenarioId) ?? []) : [],
  )
  useEffect(() => {
    if (!scenarioId) {
      setDefs([])
      return
    }
    fetchScenarioDefaults(scenarioId)
      .then(setDefs)
      .catch(() => setDefs([])) // 404（场景未注册）等失败 → 清空，调用方回退运行快照 defs
  }, [scenarioId])
  return defs
}
