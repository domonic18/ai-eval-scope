import { Layout, Menu, Typography } from "antd";
import { Link, Route, Routes, useLocation } from "react-router-dom";
import ProjectList from "./pages/ProjectList";
import ProjectDetail from "./pages/ProjectDetail";
import RunDetail from "./pages/RunDetail";
import TaskDetail from "./pages/TaskDetail";

const { Header, Content, Footer } = Layout;

function AppLayout() {
  const location = useLocation();
  const selectedKey = location.pathname === "/" ? "/" : location.pathname.split("/")[1] || "/";

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Header style={{ background: "#001529", padding: "0 24px" }}>
        <div style={{ display: "flex", alignItems: "center", height: "100%" }}>
          <Typography.Title level={4} style={{ color: "#fff", margin: 0, marginRight: 48 }}>
            Agent Eval
          </Typography.Title>
          <Menu
            theme="dark"
            mode="horizontal"
            selectedKeys={[selectedKey]}
            items={[
              { key: "/", label: <Link to="/">项目看板</Link> },
            ]}
            style={{ flex: 1, minWidth: 0 }}
          />
        </div>
      </Header>
      <Content style={{ padding: "24px", background: "#f0f2f5" }}>
        <div className="page-container">
          <Routes>
            <Route path="/" element={<ProjectList />} />
            <Route path="/project/:id" element={<ProjectDetail />} />
            <Route path="/run/:id" element={<RunDetail />} />
            <Route path="/run/:id/task/:taskId" element={<TaskDetail />} />
          </Routes>
        </div>
      </Content>
      <Footer style={{ textAlign: "center" }}>
        Agent Eval Web Portal ©{new Date().getFullYear()}
      </Footer>
    </Layout>
  );
}

export default function App() {
  return (
    <AppLayout />
  );
}
