/**
 * 注册页 — 复刻 SquadSight 视觉（居中卡片 + 密码强度），docs/arch/12 §5。
 * 字段沿用平台 email 体系（姓名/邮箱/密码/确认密码）；登录另走 /login。
 */

import { useEffect, useState } from "react"
import { useLocation, useNavigate } from "react-router-dom"
import { api, saveSession } from "../api/client"
import { loadSession } from "../store/auth"
import { Button, Field, Input, InputIconWrap, Logo, useToast } from "../components/ui"
import { IconLock, IconMail } from "../components/icons"

export default function RegisterPage() {
  const nav = useNavigate()
  const loc = useLocation()
  const toast = useToast()
  const [name, setName] = useState("")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [confirm, setConfirm] = useState("")
  const [loading, setLoading] = useState(false)

  const redirect = (loc.state as { from?: string } | null)?.from || "/dashboard"

  useEffect(() => {
    if (loadSession()) nav("/dashboard", { replace: true })
  }, [nav])

  const strength = passwordStrength(password)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (password !== confirm) {
      toast.error("两次输入的密码不一致")
      return
    }
    setLoading(true)
    try {
      const data = await api.register(email, password, name || email.split("@")[0])
      saveSession(data)
      toast.success("注册成功")
      nav(redirect)
    } catch (err) {
      const ex = err as { response?: { data?: { error?: string } }; message?: string }
      toast.error(ex.response?.data?.error || ex.message || "注册失败")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth-page">
      <div className="ambient" />
      <div className="auth" style={{ maxWidth: 420 }}>
        <div className="auth-head">
          <Logo to="/" fontSize={17} />
          <h1>创建账号</h1>
          <p>注册账号，开始创建你的评估项目</p>
        </div>

        <div className="auth-card">
          <form onSubmit={submit}>
            <Field label="姓名">
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="如：张工"
              />
            </Field>
            <Field label="邮箱">
              <InputIconWrap icon={<IconMail size={16} />}>
                <Input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@company.com"
                />
              </InputIconWrap>
            </Field>
            <Field label="密码" help="至少 8 位，包含字母与数字">
              <InputIconWrap icon={<IconLock size={16} />}>
                <Input
                  type="password"
                  required
                  minLength={8}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="至少 8 位"
                />
              </InputIconWrap>
            </Field>
            {password && (
              <div className="pw-strength">
                {[0, 1, 2].map((i) => (
                  <span key={i} className={i < strength.score ? `bar ${strength.level}` : "bar"} />
                ))}
                <span className="pw-strength-label">{strength.label}</span>
              </div>
            )}
            <Field label="确认密码">
              <InputIconWrap icon={<IconLock size={16} />}>
                <Input
                  type="password"
                  required
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  placeholder="再次输入密码"
                />
              </InputIconWrap>
            </Field>
            <Button
              type="submit"
              variant="primary"
              size="lg"
              disabled={loading}
              style={{ width: "100%", justifyContent: "center", marginTop: 4 }}
            >
              {loading ? "处理中…" : "注册并进入"}
            </Button>
          </form>
        </div>

        <div className="auth-foot">
          已有账号？
          <a onClick={() => nav("/login")}>登录</a>
        </div>
        <div style={{ textAlign: "center" }}>
          <a className="auth-back" onClick={() => nav("/")}>
            ← 返回首页
          </a>
        </div>
      </div>
    </div>
  )
}

/** 密码强度：长度≥8 / 含字母+数字 / 长度≥12或含特殊字符，三档递增。 */
function passwordStrength(pw: string): { score: number; level: string; label: string } {
  let score = 0
  if (pw.length >= 8) score += 1
  if (/[a-zA-Z]/.test(pw) && /\d/.test(pw)) score += 1
  if (pw.length >= 12 || /[^a-zA-Z0-9]/.test(pw)) score += 1
  const levels = ["weak", "medium", "strong"]
  const labels = ["弱", "一般", "强"]
  const idx = Math.max(0, score - 1)
  return { score, level: levels[idx], label: labels[idx] }
}
