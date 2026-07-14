import { Navigate, Route, Routes, useLocation } from "react-router-dom"
import { loadSession } from "./store/auth"
import { AppShell } from "./components/AppShell"
import { PublicShell } from "./components/PublicShell"
import Landing from "./pages/Landing"
import DocsPage from "./pages/DocsPage"
import LoginPage from "./pages/LoginPage"
import RegisterPage from "./pages/RegisterPage"
import JoinPage from "./pages/JoinPage"
import Dashboard from "./pages/Dashboard"
import ProjectDetail from "./pages/ProjectDetail"
import RunDetail from "./pages/RunDetail"
import SampleDetail from "./pages/SampleDetail"
import ComingSoon from "./pages/ComingSoon"
import DebugPage from "./pages/DebugPage"
import ConfigHub from "./pages/config/ConfigHub"
import ScenarioConfig from "./pages/config/ScenarioConfig"
import AssetEditor from "./pages/config/AssetEditor"
import AdminLayout from "./pages/admin/AdminLayout"
import AdminOverview from "./pages/admin/AdminOverview"
import AdminUsers from "./pages/admin/AdminUsers"
import AdminOrgs from "./pages/admin/AdminOrgs"
import AdminProjects from "./pages/admin/AdminProjects"
import AdminRuns from "./pages/admin/AdminRuns"
import AdminArtifacts from "./pages/admin/AdminArtifacts"
import AdminAudit from "./pages/admin/AdminAudit"

/** 根路径：已登录进看板，未登录展示产品落地页。 */
function RootRedirect() {
  return loadSession() ? <Navigate to="/dashboard" replace /> : <Landing />
}

/** 登录守卫：无 session 跳登录（记下来源）。通过则渲染 AppShell（含 Outlet）。 */
function RequireAuth() {
  const loc = useLocation()
  if (!loadSession()) {
    return <Navigate to="/login" replace state={{ from: loc.pathname }} />
  }
  return <AppShell />
}

/** 超管守卫：非 platformAdmin → 回看板（管理后台独立 shell，不嵌套 AppShell）。 */
function RequireAdmin() {
  const session = loadSession()
  if (!session) return <Navigate to="/login" replace state={{ from: "/admin" }} />
  if (!session.user?.platformAdmin) return <Navigate to="/dashboard" replace />
  return <AdminLayout />
}

/**
 * 运行/样本详情外壳选择器（docs/arch/12 §3.5 公开嵌入）：
 * 已登录 → AppShell（完整）；匿名 → PublicShell（只读，支持公开项目 iframe 嵌入）。
 * 匿名访问非公开项目时，页面内 Query 401 由 axios 拦截器跳转登录。
 */
function RunViewShell() {
  return loadSession() ? <AppShell /> : <PublicShell />
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<RootRedirect />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/docs" element={<DocsPage />} />
      <Route element={<RequireAuth />}>
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/join" element={<JoinPage />} />
        <Route path="/project/:id" element={<ProjectDetail />} />
        <Route path="/runs" element={<ComingSoon title="全部运行" />} />
        {/* 调试台：登录即可访问，不限组织 / 角色 */}
        <Route path="/debug" element={<DebugPage />} />
        {/* 配置中心：场景包配置资产可视化 + 发布（Phase 4）*/}
        <Route path="/config" element={<ConfigHub />} />
        <Route path="/config/scenarios/:id" element={<ScenarioConfig />} />
        <Route path="/config/scenarios/:id/:kind/:assetId" element={<AssetEditor />} />
      </Route>
      {/* 运行/样本详情：登录走 AppShell，匿名走 PublicShell（公开项目可 iframe 嵌入） */}
      <Route element={<RunViewShell />}>
        <Route path="/run/:id" element={<RunDetail />} />
        <Route path="/run/:id/sample/:sid" element={<SampleDetail />} />
      </Route>
      {/* 超管后台（独立 shell，platformAdmin 专属）*/}
      <Route element={<RequireAdmin />}>
        <Route path="/admin" element={<AdminOverview />} />
        <Route path="/admin/users" element={<AdminUsers />} />
        <Route path="/admin/orgs" element={<AdminOrgs />} />
        <Route path="/admin/projects" element={<AdminProjects />} />
        <Route path="/admin/runs" element={<AdminRuns />} />
        <Route path="/admin/artifacts" element={<AdminArtifacts />} />
        <Route path="/admin/audit" element={<AdminAudit />} />
      </Route>
    </Routes>
  )
}
