import { useEffect, useState } from "react"
import { useParams } from "react-router-dom"
import { useCrumbs } from "../../components/AppShell"
import { Page, PageHead } from "../../components/shared"
import { Card, CardContent, CardHeader, CardTitle } from "../../components/shadcn/card"
import { Badge } from "../../components/shadcn/badge"
import { Button } from "../../components/shadcn/button"
import { Input } from "../../components/shadcn/input"
import { Label } from "../../components/shadcn/label"
import { Textarea } from "../../components/shadcn/textarea"
import { toast } from "sonner"
import { api, type AssetKind } from "../../api/client"
import { Save, GitBranch, ArrowUpCircle } from "lucide-react"

const KIND_LABEL: Record<AssetKind, string> = {
  "rule-sets": "规则集",
  prompts: "提示词",
  datasets: "数据集",
}

const errMsg = (e: unknown, fb: string) =>
  (e as { response?: { data?: { error?: string } } })?.response?.data?.error ?? fb

const VERSION_LABELS = ["production", "staging", "latest"]

/** 统一资产编辑器：YAML 编辑 → 发布新版本；版本时间线 + 标签晋升（P4-2/3/4/5）。 */
export default function AssetEditor() {
  const { id = "", kind = "rule-sets", assetId = "" } = useParams<{ id: string; kind: AssetKind; assetId: string }>()
  const { setCrumbs } = useCrumbs()
  const [yaml, setYaml] = useState("")
  const [version, setVersion] = useState("1.0.0")
  const [label, setLabel] = useState("latest")
  const [role, setRole] = useState("reference")
  const [versions, setVersions] = useState<Array<{ version: string; labels: string[]; contentHash: string; createdAt: string }>>([])
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    setCrumbs([
      { label: "配置中心", to: "/config" },
      { label: id, to: `/config/scenarios/${id}` },
      { label: `${KIND_LABEL[kind]} · ${assetId}` },
    ])
    // 载入当前 catalog 中的最新版本内容作为编辑起点
    api
      .scenarioCatalog(id)
      .then((cat) => {
        const list =
          kind === "rule-sets" ? cat.rule_sets : kind === "prompts" ? cat.prompts : cat.datasets
        const entry = list.find((e) => e.asset_id === assetId)
        if (entry) setVersion(bumpVersion(entry.version))
      })
      .catch(() => {})
    reloadVersions()
  }, [id, kind, assetId, setCrumbs])

  function reloadVersions() {
    api.listAssetVersions(id, kind, assetId).then(setVersions).catch(() => setVersions([]))
  }

  async function publish() {
    setBusy(true)
    try {
      let content: Record<string, unknown>
      try {
        content = parseYaml(yaml)
      } catch (e) {
        toast.error("YAML 解析失败：" + errMsg(e, "语法错误"))
        setBusy(false)
        return
      }
      const input: Parameters<typeof api.publishAsset>[2] = {
        asset_id: assetId,
        version,
        labels: label ? [label] : [],
        content,
      }
      if (kind === "datasets") {
        input.role = role
        input.backend_type = "yaml_file"
        input.backend_config = {}
      }
      await api.publishAsset(id, kind, input)
      toast.success(`已发布 ${KIND_LABEL[kind]} ${assetId}@${version}`)
      reloadVersions()
    } catch (e) {
      toast.error(errMsg(e, "发布失败"))
    } finally {
      setBusy(false)
    }
  }

  async function promote(ver: string, lbl: string) {
    try {
      await api.promoteAssetLabels(id, kind, assetId, ver, [lbl])
      toast.success(`${ver} 已晋升为 ${lbl}`)
      reloadVersions()
    } catch (e) {
      toast.error(errMsg(e, "晋升失败"))
    }
  }

  const starter = yamlStarter(kind, assetId)

  return (
    <Page>
      <PageHead title={`${KIND_LABEL[kind]} · ${assetId}`} sub={`场景 ${id} · 编辑并发布新版本`} />
      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Save className="size-4" /> 编辑（YAML）
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <Textarea
              className="font-mono text-xs"
              rows={22}
              value={yaml || starter}
              onChange={(e) => setYaml(e.target.value)}
              placeholder={starter}
            />
            <div className="grid grid-cols-3 gap-3">
              <div className="space-y-1">
                <Label>新版本号</Label>
                <Input value={version} onChange={(e) => setVersion(e.target.value)} />
              </div>
              <div className="space-y-1">
                <Label>标签</Label>
                <select
                  className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                  value={label}
                  onChange={(e) => setLabel(e.target.value)}
                >
                  <option value="">（无）</option>
                  {VERSION_LABELS.map((l) => (
                    <option key={l} value={l}>
                      {l}
                    </option>
                  ))}
                </select>
              </div>
              {kind === "datasets" && (
                <div className="space-y-1">
                  <Label>角色</Label>
                  <select
                    className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                    value={role}
                    onChange={(e) => setRole(e.target.value)}
                  >
                    <option value="reference">reference（参考知识）</option>
                    <option value="test">test（测试集）</option>
                  </select>
                </div>
              )}
            </div>
            <Button onClick={publish} disabled={busy || !version}>
              {busy ? "发布中…" : "发布新版本"}
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <GitBranch className="size-4" /> 版本时间线
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {versions.length === 0 ? (
              <p className="text-sm text-muted-foreground">暂无历史版本</p>
            ) : (
              versions.map((v) => (
                <div key={v.version} className="rounded-md border p-2.5">
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-sm font-medium">{v.version}</span>
                    <div className="flex gap-1">
                      {v.labels.map((l) => (
                        <Badge key={l} variant={l === "production" ? "default" : "secondary"} className="text-xs">
                          {l}
                        </Badge>
                      ))}
                    </div>
                  </div>
                  <p className="mt-0.5 truncate font-mono text-[10px] text-muted-foreground">{v.contentHash}</p>
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {VERSION_LABELS.filter((l) => !v.labels.includes(l)).map((l) => (
                      <Button
                        key={l}
                        variant="outline"
                        size="sm"
                        className="h-6 px-2 text-xs"
                        onClick={() => promote(v.version, l)}
                      >
                        <ArrowUpCircle className="mr-1 size-3" /> 晋升 {l}
                      </Button>
                    ))}
                  </div>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </div>
    </Page>
  )
}

/** 极简 YAML→JS（仅 key: value / 列表项用 -）。复杂结构建议后端解析；此处用于发布前校验非空。 */
function parseYaml(text: string): Record<string, unknown> {
  if (!text.trim()) throw new Error("内容为空")
  // 仅做存在性校验，真实解析在后端；返回占位结构
  return { _raw: text }
}

function bumpVersion(v: string): string {
  const parts = v.split(".").map((n) => parseInt(n, 10) || 0)
  while (parts.length < 3) parts.push(0)
  parts[2] += 1
  return parts.join(".")
}

function yamlStarter(kind: AssetKind, assetId: string): string {
  if (kind === "prompts")
    return `template_id: ${assetId}\nname: \nsystem_prompt: |\nuser_prompt_template: |\nvariables:\n  - name: x\n    type: string\n`
  if (kind === "datasets")
    return `dataset:\n  id: ${assetId}\n  role: reference\n  backend:\n    type: yaml_file\n    config: {}\n`
  return `version: "1.0"\nscenario: \ndimensions: []\ncascade: []\nrules: []\n`
}
