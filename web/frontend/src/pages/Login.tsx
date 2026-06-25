import { useEffect, useState } from "react"
import { useLocation, useNavigate } from "react-router-dom"
import { api, saveSession } from "../api/client"
import { loadSession } from "../store/auth"
import { Button, Field, Input, InputIconWrap, Logo, Segment, useToast } from "../components/ui"
import { IconLock, IconMail } from "../components/icons"

type Mode = "login" | "register"

export default function Login() {
  const nav = useNavigate()
  const loc = useLocation()
  const toast = useToast()
  const [mode, setMode] = useState<Mode>("login")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [name, setName] = useState("")
  const [loading, setLoading] = useState(false)

  const redirect = (loc.state as { from?: string } | null)?.from || "/dashboard"

  useEffect(() => {
    if (loadSession()) nav("/dashboard", { replace: true })
  }, [nav])

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    try {
      const data =
        mode === "login"
          ? await api.login(email, password)
          : await api.register(email, password, name || email.split("@")[0])
      saveSession(data)
      toast.success(mode === "login" ? "登录成功" : "注册成功")
      nav(redirect)
    } catch (err) {
      const e = err as { response?: { data?: { error?: string } }; message?: string }
      toast.error(
        e.response?.data?.error || e.message || (mode === "login" ? "邮箱或密码错误" : "注册失败"),
      )
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
          <h1>{mode === "login" ? "欢迎回来" : "创建账号"}</h1>
          <p>
            {mode === "login" ? "登录以访问你的评估控制台" : "注册账号，开始创建你的评估项目"}
          </p>
        </div>

        <div className="auth-card">
          <div style={{ marginBottom: 22 }}>
            <Segment<Mode>
              value={mode}
              onChange={setMode}
              items={[
                { key: "login", label: "登录" },
                { key: "register", label: "注册" },
              ]}
            />
          </div>

          <form onSubmit={submit}>
            {mode === "register" && (
              <Field label="姓名">
                <Input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="如：张工"
                />
              </Field>
            )}
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
            <Field
              label="密码"
              help={mode === "register" ? "至少 8 位，包含字母与数字" : undefined}
            >
              <InputIconWrap icon={<IconLock size={16} />}>
                <Input
                  type="password"
                  required
                  minLength={mode === "register" ? 8 : undefined}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder={mode === "register" ? "至少 8 位" : "输入密码"}
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
              {loading ? "处理中…" : mode === "login" ? "登录" : "注册并进入"}
            </Button>
          </form>
        </div>

        <div className="auth-foot">
          {mode === "login" ? "还没有账号？" : "已有账号？"}
          <a onClick={() => setMode(mode === "login" ? "register" : "login")}>
            {mode === "login" ? "立即注册" : "登录"}
          </a>
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
