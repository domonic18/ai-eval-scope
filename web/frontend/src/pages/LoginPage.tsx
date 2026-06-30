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
import { useToast } from "../components/toast"
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
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <div className="w-full max-w-sm space-y-6">
        <div className="text-center">
          <div className="mb-3 inline-flex size-9 items-center justify-center rounded-lg bg-primary font-bold text-primary-foreground">
            E
          </div>
          <h1 className="text-2xl font-semibold tracking-tight">欢迎回来</h1>
          <p className="mt-1 text-sm text-muted-foreground">登录以访问你的评估控制台</p>
        </div>

        <div className="rounded-xl border bg-card p-6 text-card-foreground shadow-sm">
          <Tabs defaultValue="password">
            <TabsList className="grid w-full grid-cols-2">
              <TabsTrigger value="password">密码登录</TabsTrigger>
              <TabsTrigger value="sso">SSO 登录</TabsTrigger>
            </TabsList>
            <TabsContent value="password" className="mt-4">
              <form onSubmit={submit} className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="email">邮箱</Label>
                  <div className="relative">
                    <Mail className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                    <Input
                      id="email"
                      type="email"
                      required
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      placeholder="you@company.com"
                      className="pl-9"
                    />
                  </div>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="password">密码</Label>
                  <div className="relative">
                    <Lock className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                    <Input
                      id="password"
                      type="password"
                      required
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder="输入密码"
                      className="pl-9"
                    />
                  </div>
                </div>
                <Button type="submit" className="w-full" disabled={loading}>
                  {loading ? "处理中…" : "登录"}
                </Button>
              </form>
            </TabsContent>
            <TabsContent value="sso" className="mt-4 text-center">
              {ssoEnabled ? (
                <div className="space-y-4">
                  <div className="mx-auto flex size-12 items-center justify-center rounded-full bg-primary/10 text-primary">
                    <KeyRound className="size-6" />
                  </div>
                  <div>
                    <h3 className="font-medium">企业身份认证</h3>
                    <p className="mt-1 text-sm text-muted-foreground">通过光华平台统一身份认证登录</p>
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
      </div>
    </div>
  )
}
