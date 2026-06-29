/**
 * 登录页 — 复刻 SquadSight 视觉（居中卡片 + 密码/SSO Tab），docs/arch/12 §5。
 * Tab=密码登录 / SSO 登录；注册另走 /register。
 * SSO 流程：GET /sso/config 决定 Tab 显隐；点登录 POST /sso/login 跳光华；
 *          回调 /login?sso=success&code=xxx → POST /sso/exchange → saveSession。
 */

import { useEffect, useRef, useState } from "react"
import { useLocation, useNavigate } from "react-router-dom"
import { api, saveSession } from "../api/client"
import { loadSession } from "../store/auth"
import { Button, Field, Input, InputIconWrap, Logo, useToast } from "../components/ui"
import { IconArrowRight, IconKey, IconLock, IconMail } from "../components/icons"

type Mode = "password" | "sso"

export default function LoginPage() {
  const nav = useNavigate()
  const loc = useLocation()
  const toast = useToast()
  const [mode, setMode] = useState<Mode>("password")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [loading, setLoading] = useState(false)
  const [ssoEnabled, setSsoEnabled] = useState(false)
  const exchangedRef = useRef(false)

  const redirect = (loc.state as { from?: string } | null)?.from || "/dashboard"

  // 已登录直接进看板；否则拉 SSO 配置决定是否显示 SSO Tab
  useEffect(() => {
    if (loadSession()) {
      nav("/dashboard", { replace: true })
      return
    }
    api
      .ssoConfig()
      .then((d) => setSsoEnabled(d.enabled))
      .catch(() => setSsoEnabled(false))
  }, [nav])

  // SSO 回调：?sso=success&code=xxx（换 token）/ ?sso=error&reason=...（失败提示）
  useEffect(() => {
    const params = new URLSearchParams(loc.search)
    const sso = params.get("sso")
    const code = params.get("code")
    if (sso === "success" && code && !exchangedRef.current) {
      exchangedRef.current = true
      window.history.replaceState({}, "", "/login")
      api
        .ssoExchange(code)
        .then((data) => {
          saveSession(data)
          toast.success("登录成功")
          nav(redirect, { replace: true })
        })
        .catch(() => toast.error("SSO 登录失败：交换码无效或已过期"))
    } else if (sso === "error") {
      window.history.replaceState({}, "", "/login")
      toast.error(decodeURIComponent(params.get("reason") || "SSO 登录失败"))
    }
  }, [loc.search, nav, redirect, toast])

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    try {
      const data = await api.login(email, password)
      saveSession(data)
      toast.success("登录成功")
      nav(redirect)
    } catch (err) {
      const ex = err as { response?: { data?: { error?: string } }; message?: string }
      toast.error(ex.response?.data?.error || ex.message || "邮箱或密码错误")
    } finally {
      setLoading(false)
    }
  }

  async function handleSso() {
    setLoading(true)
    try {
      const { redirect_url } = await api.ssoLogin()
      if (redirect_url) window.location.href = redirect_url
    } catch {
      toast.error("SSO 发起失败，请稍后重试")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth-page">
      <div className="ambient" />
      <div className="auth">
        <div className="auth-head">
          <Logo to="/" fontSize={17} />
          <h1>欢迎回来</h1>
          <p>登录以访问你的评估控制台</p>
        </div>

        <div className="auth-card">
          <div className="auth-tabs">
            <button
              type="button"
              className={mode === "password" ? "active" : ""}
              onClick={() => setMode("password")}
            >
              密码登录
            </button>
            <button
              type="button"
              className={mode === "sso" ? "active" : ""}
              onClick={() => setMode("sso")}
            >
              SSO 登录
            </button>
          </div>

          {mode === "password" ? (
            <form onSubmit={submit}>
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
              <Field label="密码">
                <InputIconWrap icon={<IconLock size={16} />}>
                  <Input
                    type="password"
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="输入密码"
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
                {loading ? "处理中…" : "登录"}
              </Button>
            </form>
          ) : (
            <div className="sso-panel">
              {ssoEnabled ? (
                <>
                  <div className="sso-icon">
                    <IconKey size={24} />
                  </div>
                  <h3>企业身份认证</h3>
                  <p>
                    通过光华平台统一身份认证登录
                    <br />
                    无需额外账号密码
                  </p>
                  <Button
                    variant="primary"
                    size="lg"
                    disabled={loading}
                    onClick={handleSso}
                    style={{ width: "100%", justifyContent: "center", gap: 8 }}
                  >
                    <IconKey size={16} />
                    {loading ? "正在跳转…" : "企业账号登录"}
                    {!loading && <IconArrowRight size={14} />}
                  </Button>
                  <p className="sso-hint">需要企业管理员开通权限</p>
                </>
              ) : (
                <>
                  <div className="sso-icon sso-icon-off">
                    <IconKey size={22} />
                  </div>
                  <p className="sso-off-title">SSO 登录未启用</p>
                  <p className="sso-off-desc">请联系管理员配置企业身份认证</p>
                </>
              )}
            </div>
          )}
        </div>

        <div className="auth-foot">
          还没有账号？
          <a onClick={() => nav("/register")}>立即注册</a>
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
