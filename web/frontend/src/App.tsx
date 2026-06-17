import { useEffect, useState } from "react";
import { Layout, Menu, Select, Space, Typography, Button, Drawer, List, Tag, Input, App as AntApp, Popconfirm } from "antd";
import { Outlet, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { LogoutOutlined, DashboardOutlined, TeamOutlined, PlusOutlined } from "@ant-design/icons";
import { api } from "./api/client";
import { clearSession, getActiveOrg, loadSession, setActiveOrg } from "./store/auth";
import type { Membership } from "./types";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import ProjectDetail from "./pages/ProjectDetail";
import RunDetail from "./pages/RunDetail";
import SampleDetail from "./pages/SampleDetail";

const { Header, Sider, Content } = Layout;

interface MemberRow {
  userId: string;
  role: string;
  email: string;
  name: string | null;
  joinedAt: string;
}

function MembersDrawer({ orgId, open, onClose }: { orgId: string | null; open: boolean; onClose: () => void }) {
  const { message } = AntApp.useApp();
  const [members, setMembers] = useState<MemberRow[]>([]);
  const [inviteEmail, setInviteEmail] = useState("");
  const [loading, setLoading] = useState(false);

  async function load() {
    if (!orgId) return;
    setLoading(true);
    try {
      setMembers(await api.listMembers(orgId));
    } catch {
      setMembers([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (open) load();
  }, [open, orgId]);

  async function doInvite() {
    if (!orgId || !inviteEmail.trim()) return;
    try {
      await api.inviteMember(orgId, inviteEmail.trim(), "member");
      message.success("已邀请（对方须已注册）");
      setInviteEmail("");
      load();
    } catch (e) {
      message.error("邀请失败：" + ((e as Error).message ?? "用户不存在或已是成员"));
    }
  }

  async function doRemove(userId: string) {
    if (!orgId) return;
    try {
      await api.removeMember(orgId, userId);
      message.success("已移除");
      load();
    } catch (e) {
      message.error("移除失败：" + ((e as Error).message ?? ""));
    }
  }

  return (
    <Drawer title="组织成员" open={open} onClose={onClose} width={420}>
      <Space.Compact style={{ width: "100%", marginBottom: 16 }}>
        <Input placeholder="邀请成员邮箱（须已注册）" value={inviteEmail} onChange={(e) => setInviteEmail(e.target.value)} onPressEnter={doInvite} />
        <Button type="primary" icon={<PlusOutlined />} onClick={doInvite}>
          邀请
        </Button>
      </Space.Compact>
      <List
        loading={loading}
        dataSource={members}
        renderItem={(m) => (
          <List.Item
            actions={
              m.role === "owner"
                ? undefined
                : [
                    <Popconfirm key="rm" title={`移除 ${m.email}？`} onConfirm={() => doRemove(m.userId)}>
                      <Button danger size="small">移除</Button>
                    </Popconfirm>,
                  ]
            }
          >
            <List.Item.Meta
              title={
                <Space>
                  {m.email} {m.role === "owner" ? <Tag color="gold">owner</Tag> : <Tag>member</Tag>}
                </Space>
              }
              description={m.name || "—"}
            />
          </List.Item>
        )}
      />
    </Drawer>
  );
}

function Shell() {
  const [memberships, setMemberships] = useState<Membership[]>([]);
  const [activeOrg, setActive] = useState<string | null>(null);
  const [membersOpen, setMembersOpen] = useState(false);
  const nav = useNavigate();
  const loc = useLocation();
  const session = loadSession();

  useEffect(() => {
    api.me().then((data) => {
      setMemberships(data.memberships);
      setActive(getActiveOrg(data.memberships));
    });
  }, []);

  const items = [{ key: "/", icon: <DashboardOutlined />, label: "项目看板" }];

  return (
    <Layout className="app-shell">
      <Sider collapsible collapsed={false} theme="light">
        <div style={{ padding: "16px 24px", fontWeight: 600 }}>Agent Eval</div>
        <Menu mode="inline" selectedKeys={[loc.pathname]} items={items} onClick={({ key }) => nav(key)} />
      </Sider>
      <Layout>
        <Header
          style={{
            background: "#fff",
            padding: "0 24px",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <Space>
            <Typography.Text>组织：</Typography.Text>
            <Select
              style={{ width: 220 }}
              value={activeOrg ?? undefined}
              options={memberships.map((m) => ({ value: m.orgId, label: m.org.name }))}
              onChange={(v) => {
                setActive(v);
                setActiveOrg(v);
                nav("/");
              }}
            />
            <Button icon={<TeamOutlined />} onClick={() => setMembersOpen(true)}>
              成员
            </Button>
          </Space>
          <Space>
            <Typography.Text type="secondary">{session?.user.email}</Typography.Text>
            <Button
              icon={<LogoutOutlined />}
              onClick={() => {
                clearSession();
                nav("/login");
              }}
            >
              登出
            </Button>
          </Space>
        </Header>
        <Content className="app-content">
          <Outlet context={{ activeOrg }} key={activeOrg ?? "none"} />
        </Content>
      </Layout>
      <MembersDrawer orgId={activeOrg} open={membersOpen} onClose={() => setMembersOpen(false)} />
    </Layout>
  );
}

function RequireAuth({ children }: { children: React.ReactNode }) {
  const session = loadSession();
  const loc = useLocation();
  if (!session) {
    return <Login redirect={loc.pathname} />;
  }
  return <>{children}</>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login redirect="/" />} />
      <Route
        element={
          <RequireAuth>
            <Shell />
          </RequireAuth>
        }
      >
        <Route path="/" element={<Dashboard />} />
        <Route path="/project/:id" element={<ProjectDetail />} />
        <Route path="/run/:id" element={<RunDetail />} />
        <Route path="/run/:id/sample/:sid" element={<SampleDetail />} />
      </Route>
    </Routes>
  );
}
