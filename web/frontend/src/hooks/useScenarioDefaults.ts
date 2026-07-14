/**
 * 场景默认指标定义 hook（模块级缓存，多页面共享一次 fetch）。
 *
 * 取代前端硬编码的 COURSEWARE_DEFAULT_METRIC_DEFS——指标定义统一来自后端
 * GET /scenarios/:id/defaults（单一源落库，由 import 脚本写入）。
 */
import { useEffect, useState } from "react"
import { api } from "../api/client"
import type { MetricDef } from "../types"

const _cache = new Map<string, MetricDef[]>()

export function useScenarioDefaults(scenarioId = "courseware"): MetricDef[] {
  const [defs, setDefs] = useState<MetricDef[]>(_cache.get(scenarioId) ?? [])
  useEffect(() => {
    if (_cache.has(scenarioId)) {
      setDefs(_cache.get(scenarioId)!)
      return
    }
    api
      .scenarioDefaults(scenarioId)
      .then((d) => {
        _cache.set(scenarioId, d)
        setDefs(d)
      })
      .catch(() => {})
  }, [scenarioId])
  return defs
}
