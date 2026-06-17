import { useState } from "react";
import { Card, Form, Input, Button, Tabs, Typography, App as AntApp } from "antd";
import { useNavigate } from "react-router-dom";
import { api, saveSession } from "../api/client";

export default function Login({ redirect }: { redirect: string }) {
  const nav = useNavigate();
  const { message } = AntApp.useApp();
  const [loading, setLoading] = useState(false);

  async function doLogin(email: string, password: string) {
    setLoading(true);
    try {
      const data = await api.login(email, password);
      saveSession(data);
      message.success("登录成功");
      nav(redirect);
    } catch (e) {
      message.error("登录失败：" + ((e as Error).message ?? "凭据错误"));
    } finally {
      setLoading(false);
    }
  }

  async function doRegister(email: string, password: string, name: string) {
    setLoading(true);
    try {
      const data = await api.register(email, password, name);
      saveSession(data);
      message.success("注册成功");
      nav(redirect);
    } catch (e) {
      message.error("注册失败：" + ((e as Error).message ?? ""));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ display: "flex", height: "100vh", alignItems: "center", justifyContent: "center", background: "#f0f2f5" }}>
      <Card style={{ width: 400 }}>
        <Typography.Title level={3} style={{ textAlign: "center", marginBottom: 24 }}>
          Agent Eval 可观测平台
        </Typography.Title>
        <Tabs
          centered
          items={[
            {
              key: "login",
              label: "登录",
              children: (
                <Form
                  onFinish={(v) => doLogin(v.email, v.password)}
                  layout="vertical"
                >
                  <Form.Item name="email" label="邮箱" rules={[{ required: true }]}>
                    <Input type="email" placeholder="you@example.com" />
                  </Form.Item>
                  <Form.Item name="password" label="密码" rules={[{ required: true }]}>
                    <Input.Password />
                  </Form.Item>
                  <Button type="primary" htmlType="submit" block loading={loading}>
                    登录
                  </Button>
                </Form>
              ),
            },
            {
              key: "register",
              label: "注册",
              children: (
                <Form
                  onFinish={(v) => doRegister(v.email, v.password, v.name)}
                  layout="vertical"
                >
                  <Form.Item name="name" label="姓名">
                    <Input />
                  </Form.Item>
                  <Form.Item name="email" label="邮箱" rules={[{ required: true }]}>
                    <Input type="email" />
                  </Form.Item>
                  <Form.Item name="password" label="密码（≥8 位）" rules={[{ required: true, min: 8 }]}>
                    <Input.Password />
                  </Form.Item>
                  <Button type="primary" htmlType="submit" block loading={loading}>
                    注册并创建组织
                  </Button>
                </Form>
              ),
            },
          ]}
        />
      </Card>
    </div>
  );
}
