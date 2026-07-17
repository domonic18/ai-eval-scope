/**
 * 旧独立资产编辑器路由 — 301 重定向到统一包编辑器（docs/arch/14配置编辑器交互设计.md §6.1）。
 *
 * /config/scenarios/:id/:kind/:assetId  →  /config/scenarios/:id/edit?select=<kind>:<assetId>
 * 保留外链兼容；全部编辑能力已收敛到 PackageEditor。
 */

import { Navigate, useParams } from "react-router-dom"
import type { AssetKind } from "../../api/client"

export default function AssetEditor() {
  const { id = "", kind = "rule-sets", assetId = "" } = useParams<{
    id: string
    kind: AssetKind
    assetId: string
  }>()
  return <Navigate to={`/config/scenarios/${id}/edit?select=${kind}:${assetId}`} replace />
}
