/**
 * 发布场景包版本对话框（从 ScenarioConfig 抽出，控制主文件行数）。
 * 前端把整段 manifest YAML 文本存入 content.manifest_yaml，由后端解析。
 */
import { useState } from "react"
import { toast } from "sonner"
import { Package } from "lucide-react"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "../../components/shadcn/dialog"
import { Input } from "../../components/shadcn/input"
import { Label } from "../../components/shadcn/label"
import { Textarea } from "../../components/shadcn/textarea"
import { Button } from "../../components/shadcn/button"
import { api } from "../../api/client"
import { errMsg, VERSION_LABELS } from "./editor/types"

export function PublishPackageDialog({
  open,
  onOpenChange,
  scenarioId,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  scenarioId: string
}) {
  const [assetId, setAssetId] = useState("")
  const [version, setVersion] = useState("1.0.0")
  const [label, setLabel] = useState<string>("production")
  const [name, setName] = useState("")
  const [yaml, setYaml] = useState("package:\n  id: \n  scenario: \n  version: 1.0.0\n")
  const [busy, setBusy] = useState(false)

  async function submit() {
    setBusy(true)
    try {
      const content: Record<string, unknown> = { manifest_yaml: yaml }
      await api.publishPackage(scenarioId, {
        asset_id: assetId,
        version,
        labels: label ? [label] : [],
        name: name || undefined,
        content,
      })
      toast.success("包版本已发布")
      onOpenChange(false)
    } catch (e) {
      toast.error(errMsg(e, "发布失败"))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Package className="size-4" /> 发布场景包版本
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>包 ID (asset_id)</Label>
              <Input value={assetId} onChange={(e) => setAssetId(e.target.value)} placeholder="如 quality" />
            </div>
            <div className="space-y-1">
              <Label>版本</Label>
              <Input value={version} onChange={(e) => setVersion(e.target.value)} />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
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
            <div className="space-y-1">
              <Label>展示名</Label>
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="可选" />
            </div>
          </div>
          <div className="space-y-1">
            <Label>清单 (agent_eval.yaml)</Label>
            <Textarea
              className="font-mono text-xs"
              rows={8}
              value={yaml}
              onChange={(e) => setYaml(e.target.value)}
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button onClick={submit} disabled={busy || !assetId || !version}>
            {busy ? "发布中…" : "发布"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
