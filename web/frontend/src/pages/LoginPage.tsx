/**
 * 登录页（shadcn/Tailwind 重写）— 密码 / SSO Tab。
 * SSO：GET /sso/config 显隐；POST /sso/login 跳转；回调 ?sso=success&code → /sso/exchange。
 */
import { useEffect, useRef, useState } from "react"
import { useLocation, useNavigate } from "react-router-dom"
import { api, saveSession } from "../api/client"
import { loadSession } from "../store/auth"
import { Button } from "@/components/shadcn/button"
import { Input } from "@/components/shadcn/input"
import { Label } from "@/components/shadcn/label"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/shadcn/tabs"
import { useToast } from "../hooks/useToast"
import { APP_VERSION } from "../version"
import { ArrowRight, KeyRound, Lock, Mail } from "lucide-react"

export default function LoginPage() {
  const nav = useNavigate()
  const loc = useLocation()
  const toast = useToast()
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [loading, setLoading] = useState(false)
  const [ssoEnabled, setSsoEnabled] = useState(false)
  const exchangedRef = useRef(false)

  const redirect = (loc.state as { from?: string } | null)?.from || "/dashboard"

  useEffect(() => {
    if (loadSession()) {
      nav("/dashboard", { replace: true })
      return
    }
    api.ssoConfig().then((d) => setSsoEnabled(d.enabled)).catch(() => setSsoEnabled(false))
  }, [nav])

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
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-background p-4">
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.07]"
        style={{
          background:
            "radial-gradient(ellipse 80% 50% at 50% 0%, var(--primary), transparent)",
        }}
      />
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.05]"
        style={{
          background:
            "radial-gradient(ellipse 60% 40% at 100% 100%, var(--chart-2), transparent)",
        }}
      />
      <div className="relative z-10 w-full max-w-sm space-y-6">
        <div className="text-center">
          <a href="/" className="mb-5 inline-flex items-center gap-3 text-[17px] font-medium">
            <span className="flex size-8 items-center justify-center">
              <img src="/logo.svg" alt="EvalScope" className="h-full w-full" />
            </span>
            <span className="text-foreground">
              Eval<b>Scope</b>
            </span>
            <span className="ml-1 rounded border border-border bg-secondary px-1.5 py-0.5 font-mono text-[11px] font-medium tracking-tight text-muted-foreground">
              v{APP_VERSION}
            </span>
          </a>
          <h1 className="text-2xl font-semibold tracking-tight">欢迎回来</h1>
          <p className="mt-1 text-sm text-muted-foreground">登录以访问你的评估控制台</p>
        </div>

        <div className="rounded-xl border bg-card p-8 text-card-foreground shadow-sm">
          <Tabs defaultValue="password">
            <TabsList className="grid w-full grid-cols-2 bg-muted/50 p-1">
              <TabsTrigger
                value="password"
                className="rounded-md data-[state=active]:bg-primary data-[state=active]:text-primary-foreground data-[state=inactive]:bg-transparent data-[state=inactive]:text-muted-foreground"
              >
                密码登录
              </TabsTrigger>
              <TabsTrigger
                value="sso"
                className="rounded-md data-[state=active]:bg-primary data-[state=active]:text-primary-foreground data-[state=inactive]:bg-transparent data-[state=inactive]:text-muted-foreground"
              >
                SSO 登录
              </TabsTrigger>
            </TabsList>
            <TabsContent value="password" className="mt-6">
              <form onSubmit={submit} className="space-y-5">
                <div className="space-y-2">
                  <Label htmlFor="email" className="text-base font-medium text-foreground">
                    邮箱
                  </Label>
                  <div className="relative">
                    <Mail className="pointer-events-none absolute left-3.5 top-1/2 size-5 -translate-y-1/2 text-muted-foreground" />
                    <Input
                      id="email"
                      type="email"
                      autoComplete="username"
                      required
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      placeholder="you@company.com"
                      className="h-11 pl-10 text-base"
                    />
                  </div>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="password" className="text-base font-medium text-foreground">
                    密码
                  </Label>
                  <div className="relative">
                    <Lock className="pointer-events-none absolute left-3.5 top-1/2 size-5 -translate-y-1/2 text-muted-foreground" />
                    <Input
                      id="password"
                      type="password"
                      autoComplete="current-password"
                      required
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder="输入密码"
                      className="h-11 pl-10 text-base"
                    />
                  </div>
                </div>
                <Button type="submit" className="h-11 w-full text-base" disabled={loading}>
                  {loading ? "处理中…" : "登录"}
                </Button>
              </form>
            </TabsContent>
            <TabsContent value="sso" className="mt-6 text-center">
              {ssoEnabled ? (
                <div className="space-y-4">
                  <div className="mx-auto flex size-12 items-center justify-center rounded-full bg-primary/10 text-primary">
                    <KeyRound className="size-6" />
                  </div>
                  <div>
                    <h3 className="font-medium">企业身份认证</h3>
                    <p className="mt-1 text-sm text-muted-foreground">
                      通过光华平台统一身份认证登录
                      <br />
                      无需额外账号密码
                    </p>
                  </div>
                  <Button className="w-full" disabled={loading} onClick={handleSso}>
                    <KeyRound className="size-4" />
                    {loading ? "正在跳转…" : "企业账号登录"}
                    {!loading && <ArrowRight className="size-4" />}
                  </Button>
                  <p className="text-xs text-muted-foreground">需要企业管理员开通权限</p>
                </div>
              ) : (
                <div className="space-y-2 py-4">
                  <div className="mx-auto flex size-12 items-center justify-center rounded-full bg-muted text-muted-foreground">
                    <KeyRound className="size-6" />
                  </div>
                  <p className="font-medium">SSO 登录未启用</p>
                  <p className="text-sm text-muted-foreground">请联系管理员配置企业身份认证</p>
                </div>
              )}
            </TabsContent>
          </Tabs>
        </div>

        <div className="text-center text-sm text-muted-foreground">
          还没有账号？
          <button className="ml-1 text-primary hover:underline" onClick={() => nav("/register")}>
            立即注册
          </button>
        </div>
        <div className="text-center">
          <button
            className="mt-3 inline-flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
            onClick={() => nav("/")}
          >
            ← 返回首页
          </button>
        </div>
      </div>
    </div>
  )
}
