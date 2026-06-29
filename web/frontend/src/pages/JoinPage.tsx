/**
 * 加入团队页（/join）— 发现团队 + 申请加入 + 我的申请状态。
 * 纯团队中心模型：新用户登录后无团队，在此申请加入，owner 审批通过后成为成员。
 */

import { useEffect, useState } from "react"
import { api } from "../api/client"
import { Badge, Button, Empty, useToast } from "../components/ui"

interface Team {
  id: string
  name: string
  slug: string
  isMember: boolean
  requestStatus: string | null
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
    <div style={{ maxWidth: 720, margin: "0 auto", padding: "32px 24px" }}>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 22, fontWeight: 650, marginBottom: 6 }}>加入团队</h1>
        <p style={{ color: "var(--text-secondary)", fontSize: 14 }}>
          选择一个团队申请加入，owner 审批通过后即可查看和创建该团队下的项目。
        </p>
      </div>

      {loading ? (
        <div style={{ color: "var(--text-tertiary)", fontSize: 13 }}>加载中…</div>
      ) : teams.length === 0 ? (
        <Empty title="还没有团队">
          <span style={{ color: "var(--text-tertiary)", fontSize: 13 }}>
            联系同事创建团队，或在侧栏「创建团队」自建一个。
          </span>
        </Empty>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {teams.map((t) => (
            <div
              key={t.id}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "14px 16px",
                background: "var(--bg-elevated)",
                border: "1px solid var(--border)",
                borderRadius: "var(--r-lg)",
              }}
            >
              <div style={{ overflow: "hidden" }}>
                <div style={{ fontWeight: 600, fontSize: 15 }}>{t.name}</div>
                <div style={{ fontSize: 12, color: "var(--text-tertiary)" }}>{t.slug}</div>
              </div>
              <div>
                {t.isMember ? (
                  <Badge>已加入</Badge>
                ) : t.requestStatus === "pending" ? (
                  <Badge>审批中</Badge>
                ) : t.requestStatus === "approved" ? (
                  <Badge>已通过</Badge>
                ) : t.requestStatus === "rejected" ? (
                  <Badge>已拒绝</Badge>
                ) : (
                  <Button variant="primary" onClick={() => apply(t.id)}>
                    申请加入
                  </Button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
