/** @input Auth and page modules. @output Authenticated workspace shell. @position Application UI. @doc-sync Update INDEX.md on changes. */
import { useState, useEffect, createContext, useContext } from "react";
import {
  NavLink,
  Routes,
  Route,
  Navigate,
  useLocation,
} from "react-router-dom";
import {
  Button,
  Form,
  Input,
  Alert,
  Spin,
  App as AntApp,
  Avatar,
  Dropdown,
} from "antd";
import {
  MessageOutlined,
  RobotOutlined,
  UnorderedListOutlined,
  ClockCircleOutlined,
  DatabaseOutlined,
  SettingOutlined,
  LogoutOutlined,
  ThunderboltFilled,
} from "@ant-design/icons";
import { useQueryClient } from "@tanstack/react-query";
import { api, setCsrf } from "./api";
import { Chat, Tasks } from "./Chat";
import { Agents } from "./Agents";
import { Configuration } from "./Configuration";
import { Memories, Schedules, Users } from "./Governance";
import { PublishedApp } from "./Publication";
export const UserContext = createContext({
  id: "",
  username: "",
  admin: false,
});
export const useUser = () => useContext(UserContext);
export default function App() {
  const location = useLocation();
  if (location.pathname.startsWith("/published/agents/"))
    return <PublishedApp />;
  return <ConsoleApp />;
}
function ConsoleApp() {
  const cache = useQueryClient();
  const [user, setUser] = useState<any>(null),
    [loading, setLoading] = useState(true),
    [error, setError] = useState("");
  const { message } = AntApp.useApp();
  const location = useLocation();
  useEffect(() => {
    api("/auth/me")
      .then((r) => {
        setUser(r.user);
        setCsrf(r.csrf);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);
  if (loading)
    return (
      <div className="loading">
        <Spin size="large" />
      </div>
    );
  if (!user)
    return (
      <div className="login-page">
        <section className="login-story">
          <div className="brand">
            <ThunderboltFilled /> Agent Harness
          </div>
          <h1>
            让想法，
            <br />
            成为行动。
          </h1>
          <p>连接模型与工具，构建属于你的智能体工作空间。</p>
          <div className="story-note">模型 · 工具 · 记忆 · 执行</div>
        </section>
        <section className="login-form">
          <span className="eyebrow">YOUR AGENT WORKSPACE</span>
          <h2>欢迎回来</h2>
          <p>登录后继续你的工作</p>
          {error && <Alert type="error" message={error} />}
          <Form
            layout="vertical"
            onFinish={async (v) => {
              try {
                const r = await api("/auth/login", "POST", v);
                setCsrf(r.csrf);
                setUser(r.user);
              } catch (e) {
                setError(String(e));
              }
            }}
          >
            <Form.Item
              name="username"
              label="用户名"
              rules={[{ required: true }]}
            >
              <Input autoComplete="username" placeholder="输入用户名" />
            </Form.Item>
            <Form.Item
              name="password"
              label="密码"
              rules={[{ required: true }]}
            >
              <Input.Password
                autoComplete="current-password"
                placeholder="输入密码"
              />
            </Form.Item>
            <Button type="primary" htmlType="submit" block size="large">
              登录工作台
            </Button>
          </Form>
          <small>账户由平台管理员创建</small>
        </section>
      </div>
    );
  const navigation = [
    ["/chat", <MessageOutlined />, "聊天"],
    ["/agents", <RobotOutlined />, "智能体"],
    ["/tasks", <UnorderedListOutlined />, "任务中心"],
    ["/schedules", <ClockCircleOutlined />, "定时任务"],
    ["/memories", <DatabaseOutlined />, "记忆"],
    ["/configuration", <SettingOutlined />, "配置中心"],
  ] as const;
  const title =
    navigation.find((n) => location.pathname.startsWith(n[0]))?.[2] ||
    "用户管理";
  return (
    <UserContext.Provider value={user}>
      <div className="shell">
        <aside className="sidebar">
          <div className="brand">
            <span className="brand-icon">
              <ThunderboltFilled />
            </span>
            <div>
              Agent Harness<small>智能体工作台</small>
            </div>
          </div>
          <div className="nav-label">工作空间</div>
          <nav>
            {navigation.map(([path, icon, label]) => (
              <NavLink key={path} to={path}>
                {icon}
                <span>{label}</span>
              </NavLink>
            ))}
          </nav>
          <div className="sidebar-bottom">
            <div className="system-status">
              <span /> 独立 Harness 运行时
            </div>
            <Dropdown
              menu={{
                items: [
                  ...(user.admin
                    ? [
                        {
                          key: "users",
                          label: <NavLink to="/users">用户管理</NavLink>,
                        },
                      ]
                    : []),
                  {
                    key: "logout",
                    label: "退出登录",
                    icon: <LogoutOutlined />,
                    onClick: async () => {
                      try {
                        await api("/auth/logout", "POST");
                        cache.clear();
                        setUser(null);
                      } catch (e) {
                        message.error(String(e));
                      }
                    },
                  },
                ],
              }}
            >
              <button className="user-menu">
                <Avatar style={{ background: "#e8edff", color: "#3157d5" }}>
                  {user.username[0].toUpperCase()}
                </Avatar>
                <span>
                  {user.username}
                  <small>{user.admin ? "管理员" : "成员"}</small>
                </span>
                <span>⌄</span>
              </button>
            </Dropdown>
          </div>
        </aside>
        <main className="main">
          <header className="topbar">
            <span>
              工作空间 <span className="muted">/</span> {title}
            </span>
            <span className="topbar-note">专注思考，交给智能体执行</span>
          </header>
          <div className="page">
            <Routes>
              <Route path="/chat" element={<Chat />} />
              <Route path="/agents" element={<Agents />} />
              <Route path="/tasks" element={<Tasks />} />
              <Route path="/schedules" element={<Schedules />} />
              <Route path="/memories" element={<Memories />} />
              <Route path="/configuration" element={<Configuration />} />
              <Route
                path="/users"
                element={user.admin ? <Users /> : <Navigate to="/chat" />}
              />
              <Route path="*" element={<Navigate to="/chat" replace />} />
            </Routes>
          </div>
        </main>
      </div>
    </UserContext.Provider>
  );
}
