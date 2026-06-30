/** 加入团队页（/join）— 发现团队 + 申请加入 + 我的申请状态。 */
import { useEffect, useState } from "react"
import { api } from "../api/client"
import { Button } from "@/components/shadcn/button"
import { useToast } from "../components/toast"
import { PageHead } from "../components/shared"

interface Team {
  id: string
  name: string
  slug: string
  isMember: boolean
  requestStatus: string | null
}

const STATUS_LABEL: Record<string, string> = {
  pending: "审批中",
  approved: "已通过",
  rejected: "已拒绝",
}
const STATUS_CLS: Record<string, string> = {
  pending: "border-yellow-500/40 text-yellow-400",
  approved: "border-emerald-500/40 text-emerald-400",
  rejected: "border-red-500/40 text-red-400",
}

export default function JoinPage() {
  const [teams, setTeams] = useState<Team[]>([])
  const [loading, setLoading] = useState(false)
  const toast = useToast()

  async function load() {
    setLoading(true)
    try {
      setTeams(await api.teams())
    } catch {
      setTeams([])
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => {
    load()
  }, [])

  async function apply(orgId: string) {
    try {
      await api.requestJoin(orgId)
      toast.success("申请已提交，等待团队 owner 审批")
      await load()
    } catch (e) {
      const ex = e as { response?: { data?: { error?: string } }; message?: string }
      toast.error(ex.response?.data?.error || ex.message || "申请失败")
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-6">
      <PageHead
        title="加入团队"
        sub="选择一个团队申请加入，owner 审批通过后即可查看和创建该团队下的项目。"
      />
      {loading ? (
        <div className="text-sm text-muted-foreground">加载中…</div>
      ) : teams.length === 0 ? (
        <div className="rounded-lg border bg-card p-8 text-center text-sm text-muted-foreground">
          还没有团队。联系同事创建团队，或在侧栏「创建团队」自建一个。
        </div>
      ) : (
        <div className="space-y-3">
          {teams.map((t) => (
            <div
              key={t.id}
              className="flex items-center justify-between rounded-lg border bg-card p-4 text-card-foreground"
            >
              <div className="min-w-0">
                <div className="font-medium">{t.name}</div>
                <div className="text-xs text-muted-foreground">{t.slug}</div>
              </div>
              {t.isMember ? (
                <span className="inline-flex items-center rounded-md border border-emerald-500/40 px-2 py-0.5 text-xs font-medium text-emerald-400">
                  已加入
                </span>
              ) : t.requestStatus ? (
                <span
                  className={`inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium ${STATUS_CLS[t.requestStatus]}`}
                >
                  {STATUS_LABEL[t.requestStatus] ?? t.requestStatus}
                </span>
              ) : (
                <Button size="sm" onClick={() => apply(t.id)}>
                  申请加入
                </Button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
