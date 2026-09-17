/** @input Visitor-bound conversation, SSE and MCP view APIs. @output Responsive sci-fi public chat and isolated interactive cards.
 * @position Public application, independent of console login. @doc-sync Update INDEX.md on changes. */
import { useEffect, useRef, useState } from "react";
import {
  Alert,
  Button,
  ConfigProvider,
  Dropdown,
  Input,
  Modal,
  Popconfirm,
  Spin,
  Tooltip,
  theme,
} from "antd";
import {
  ArrowUpOutlined,
  DeleteOutlined,
  MenuOutlined,
  MessageOutlined,
  MoreOutlined,
  PlusOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  ThunderboltFilled,
} from "@ant-design/icons";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import "./publication.css";

const terminal = [
  "SUCCEEDED",
  "FAILED",
  "CANCELLED",
  "BLOCKED",
  "PAUSED",
  "NEEDS_REVIEW",
];
export function PublishedApp() {
  const site = location.pathname.split("/").filter(Boolean).pop() || "",
    base = `/public-api/v1/apps/${encodeURIComponent(site)}`;
  const [info, setInfo] = useState<any>(),
    [error, setError] = useState(""),
    [conversations, setConversations] = useState<any[]>([]);
  const [conversation, setConversation] = useState<string>(),
    [messages, setMessages] = useState<any[]>([]),
    [query, setQuery] = useState("");
  const [run, setRun] = useState<string>(),
    [busy, setBusy] = useState(false),
    [status, setStatus] = useState(""),
    [views, setViews] = useState<any[]>([]);
  const [sidebar, setSidebar] = useState(false),
    [loadingHistory, setLoadingHistory] = useState(false),
    [deleting, setDeleting] = useState<string>();
  const [privacyOpen, setPrivacyOpen] = useState(false),
    [clearing, setClearing] = useState(false);
  const bottom = useRef<HTMLDivElement>(null),
    epoch = useRef(0),
    csrf = useRef("");
  csrf.current = info?.csrf || "";
  async function request(path: string, method = "GET", body?: any) {
    const response = await fetch(base + path, {
      method,
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-Visitor-CSRF": csrf.current,
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await response.json();
    if (!response.ok)
      throw new Error(data.message || data.detail || "应用暂不可用");
    return data;
  }
  async function refresh() {
    setConversations(await request("/conversations"));
  }
  function newConversation() {
    epoch.current++;
    setConversation(undefined);
    setMessages([]);
    setViews([]);
    setError("");
    setSidebar(false);
  }
  async function openConversation(id: string) {
    const generation = ++epoch.current;
    setConversation(id);
    setLoadingHistory(true);
    setSidebar(false);
    setViews([]);
    setError("");
    try {
      const [history, cards] = await Promise.all([
        request(`/conversations/${id}/messages`),
        request(`/conversations/${id}/views`),
      ]);
      if (generation === epoch.current) {
        setMessages(history);
        setViews(cards);
      }
    } catch (e) {
      if (generation === epoch.current) setError(String(e));
    } finally {
      if (generation === epoch.current) setLoadingHistory(false);
    }
  }
  async function remove(id: string) {
    setDeleting(id);
    try {
      await request(`/conversations/${id}`, "DELETE");
      if (conversation === id) newConversation();
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setDeleting(undefined);
    }
  }
  useEffect(() => {
    request("")
      .then(setInfo)
      .catch((e) => setError(String(e)));
  }, []);
  useEffect(() => {
    if (info) refresh().catch((e) => setError(String(e)));
  }, [info]);
  useEffect(() => {
    bottom.current?.scrollIntoView({
      behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "instant"
        : "smooth",
      block: "end",
    });
  }, [messages, views, busy]);
  useEffect(() => {
    if (!run) return;
    let alive = true;
    const source = new EventSource(base + `/runs/${run}/events`);
    source.addEventListener("run_started", () =>
      setStatus("正在思考，构建回答…"),
    );
    source.addEventListener("tool_started", () => setStatus("正在调用工具…"));
    source.addEventListener("tool_completed", (event: any) => {
      const r = JSON.parse(event.data);
      setStatus(
        r.ok ? "工具已完成，正在整理结果…" : "工具未成功，正在处理结果…",
      );
      if (r.ui)
        setViews((previous) =>
          previous.some((v) => v.call_id === r.call_id)
            ? previous
            : [
                ...previous,
                { run_id: run, call_id: r.call_id, name: "交互结果" },
              ],
        );
    });
    source.addEventListener("message_completed", (event: any) => {
      const r = JSON.parse(event.data);
      setMessages((m) =>
        m.some((x) => x.role === "assistant" && x.run_id === run)
          ? m
          : [...m, { role: "assistant", content: r.answer, run_id: run }],
      );
    });
    source.addEventListener("run_failed", (event: any) =>
      setError(JSON.parse(event.data).message || "任务未完成"),
    );
    source.addEventListener("done", () => {
      source.close();
      setRun(undefined);
      setBusy(false);
      setStatus("");
      refresh().catch(() => {});
    });
    source.onerror = () => {
      setStatus("连接中断，正在恢复…");
      request(`/runs/${run}`)
        .then(async (r) => {
          if (!alive) return;
          if (terminal.includes(r.status)) {
            source.close();
            const [history, cards] = await Promise.all([
              request(
                `/conversations/${r.conversation_id || conversation}/messages`,
              ),
              request(
                `/conversations/${r.conversation_id || conversation}/views`,
              ),
            ]);
            if (alive) {
              setMessages(history);
              setViews(cards);
              setRun(undefined);
              setBusy(false);
              setStatus("");
              refresh().catch(() => {});
            }
          }
        })
        .catch((e) => {
          if (alive) {
            source.close();
            setRun(undefined);
            setBusy(false);
            setError(String(e));
          }
        });
    };
    return () => {
      alive = false;
      source.close();
    };
  }, [run]);
  async function send() {
    if (!query.trim() || busy || loadingHistory) return;
    setBusy(true);
    setError("");
    setStatus("请求已提交，正在排队…");
    try {
      const r = await request("/chat-messages", "POST", {
        query,
        conversation_id: conversation,
        response_mode: "async",
      });
      setMessages((m) => [
        ...m,
        { role: "user", content: query, run_id: r.run_id },
      ]);
      setQuery("");
      setConversation(r.conversation_id);
      setRun(r.run_id);
      refresh().catch(() => {});
    } catch (e) {
      setError(String(e));
      setBusy(false);
      setStatus("");
    }
  }
  return (
    <ConfigProvider
      theme={{
        algorithm: theme.darkAlgorithm,
        token: {
          colorPrimary: "#65e5d1",
          colorBgContainer: "#121e31",
          colorText: "#f0f5ff",
          colorTextSecondary: "#b6c6dc",
          colorTextPlaceholder: "#93a6c0",
          colorBorder: "#354761",
          borderRadius: 12,
        },
      }}
    >
      <div className="public-universe">
        <div className="public-aurora" aria-hidden="true" />
        <div className="public-grid" aria-hidden="true" />
        {!info ? (
          <div className="public-loading">
            {error ? (
              <Alert
                type="warning"
                message="应用未开放或暂不可用"
                description={error}
              />
            ) : (
              <Spin size="large" />
            )}
          </div>
        ) : (
          <>
            {sidebar && (
              <button
                className="public-backdrop"
                aria-label="关闭会话列表"
                onClick={() => setSidebar(false)}
              />
            )}
            <aside className={`public-sidebar ${sidebar ? "is-open" : ""}`}>
              <div className="public-brand">
                <div className="public-logo">
                  <ThunderboltFilled />
                </div>
                <div>
                  AGENT<span>INTELLIGENCE STUDIO</span>
                </div>
              </div>
              <Button
                className="public-new"
                icon={<PlusOutlined />}
                block
                disabled={busy || loadingHistory}
                onClick={newConversation}
              >
                新建会话
              </Button>
              <div className="public-section-label">
                你的会话{" "}
                <span>{conversations.length.toString().padStart(2, "0")}</span>
              </div>
              <nav className="public-history" aria-label="历史会话">
                {!conversations.length && (
                  <p className="public-empty-history">新的想法，从这里开始。</p>
                )}
                {conversations.map((c) => (
                  <div
                    className={`public-history-row ${conversation === c.id ? "is-active" : ""}`}
                    key={c.id}
                  >
                    <button
                      className="public-history-select"
                      disabled={busy || loadingHistory}
                      onClick={() => openConversation(c.id)}
                      title={c.title}
                    >
                      <MessageOutlined />
                      <span>{c.title}</span>
                    </button>
                    <Popconfirm
                      title="删除此会话？"
                      description="对话内容将删除，后台执行审计仍保留。"
                      onConfirm={() => remove(c.id)}
                    >
                      <Tooltip title="删除会话">
                        <Button
                          className="public-history-delete"
                          type="text"
                          size="small"
                          icon={<DeleteOutlined />}
                          aria-label={`删除会话：${c.title}`}
                          disabled={busy}
                          loading={deleting === c.id}
                        />
                      </Tooltip>
                    </Popconfirm>
                  </div>
                ))}
              </nav>
              <div className="public-sidebar-footer">
                <div className="public-private">
                  <SafetyCertificateOutlined />
                  <span>
                    独立访客空间<small>会话与记忆仅属于当前访客</small>
                  </span>
                </div>
                <Dropdown
                  trigger={["click"]}
                  menu={{
                    items: [{ key: "privacy", label: "隐私与数据" }],
                    onClick: () => setPrivacyOpen(true),
                  }}
                >
                  <Button
                    type="text"
                    icon={<MoreOutlined />}
                    aria-label="隐私与数据菜单"
                  />
                </Dropdown>
              </div>
            </aside>
            <main className="public-stage">
              <header className="public-header">
                <div className="public-heading">
                  <Button
                    className="public-mobile-menu"
                    type="text"
                    icon={<MenuOutlined />}
                    aria-label="打开会话列表"
                    onClick={() => setSidebar(true)}
                  />
                  <div>
                    <span className="public-eyebrow">
                      CONNECTED INTELLIGENCE
                    </span>
                    <h1>{info.name}</h1>
                  </div>
                </div>
                <div className="public-status">
                  <i />
                  {busy ? "执行中" : "运行就绪"}{" "}
                  <span>
                    v
                    {conversations.find((c) => c.id === conversation)
                      ?.version || info.version}
                  </span>
                </div>
              </header>
              <div
                className="public-transcript"
                aria-live="polite"
                aria-busy={busy || loadingHistory}
              >
                {error && (
                  <Alert
                    closable
                    onClose={() => setError("")}
                    type="error"
                    message={error}
                  />
                )}
                {loadingHistory ? (
                  <div className="public-loading-history">
                    <Spin /> 正在读取会话…
                  </div>
                ) : (
                  <>
                    {!messages.length && (
                      <section className="public-welcome">
                        <div className="public-orbit" aria-hidden="true">
                          <div />
                          <div />
                          <div />
                          <ThunderboltFilled />
                        </div>
                        <span className="public-eyebrow">
                          A NEW POSSIBILITY
                        </span>
                        <h2>
                          让想法，<em>即刻发生。</em>
                        </h2>
                        <p>
                          {info.description ||
                            "从一个问题开始。连接知识、调用工具，把灵感变成可见的结果。"}
                        </p>
                        <div className="public-welcome-tags">
                          <span>✧ 智能对话</span>
                          <span>⌘ 工具协作</span>
                          <span>◈ 独立记忆</span>
                        </div>
                      </section>
                    )}
                    {messages.map((m, i) => (
                      <section
                        className={`public-message ${m.role === "user" ? "from-user" : "from-agent"}`}
                        key={`${m.run_id || i}-${m.role}`}
                      >
                        <div className="public-message-label">
                          <span>{m.role === "user" ? "YOU" : "AGENT"}</span>
                          {m.role === "user" ? "你" : info.name}
                        </div>
                        <div className="public-message-body">
                          <Markdown remarkPlugins={[remarkGfm]}>
                            {m.content}
                          </Markdown>
                        </div>
                        {m.role === "assistant" &&
                          views
                            .filter((v) => v.run_id === m.run_id)
                            .map((v) => (
                              <InteractiveView
                                key={v.call_id}
                                view={v}
                                request={request}
                              />
                            ))}
                      </section>
                    ))}
                    {views
                      .filter(
                        (v) =>
                          !messages.some(
                            (m) =>
                              m.role === "assistant" && m.run_id === v.run_id,
                          ),
                      )
                      .map((v) => (
                        <InteractiveView
                          key={v.call_id}
                          view={v}
                          request={request}
                        />
                      ))}
                  </>
                )}
                {busy && (
                  <div className="public-thinking">
                    <span />
                    <span />
                    <span />
                    <p>{status}</p>
                  </div>
                )}
                <div ref={bottom} />
              </div>
              <footer className="public-composer-area">
                <div className="public-composer">
                  <Input.TextArea
                    value={query}
                    disabled={busy || loadingHistory}
                    onChange={(e) => setQuery(e.target.value)}
                    autoSize={{ minRows: 2, maxRows: 6 }}
                    placeholder="描述你的想法，让智能开始工作…"
                    aria-label="消息输入框"
                    onKeyDown={(e) => {
                      if (
                        e.key === "Enter" &&
                        !e.shiftKey &&
                        !e.nativeEvent.isComposing
                      ) {
                        e.preventDefault();
                        send();
                      }
                    }}
                  />
                  <div className="public-composer-bottom">
                    <span>
                      <i />
                      {busy ? "AGENT WORKING" : "READY FOR YOUR NEXT IDEA"}
                    </span>
                    {busy ? (
                      <Button
                        disabled={!run}
                        onClick={() =>
                          request(`/runs/${run}/stop`, "POST").catch((e) =>
                            setError(String(e)),
                          )
                        }
                      >
                        停止生成
                      </Button>
                    ) : (
                      <Button
                        type="primary"
                        icon={<ArrowUpOutlined />}
                        disabled={!query.trim() || loadingHistory}
                        onClick={send}
                      >
                        发送
                      </Button>
                    )}
                  </div>
                </div>
                <small>
                  Enter 发送 · Shift + Enter 换行{" "}
                  <span>POWERED BY AGENT HARNESS</span>
                </small>
              </footer>
            </main>
          </>
        )}
        <Modal
          title="隐私与数据"
          open={privacyOpen}
          onCancel={() => setPrivacyOpen(false)}
          okText="清除所有访客数据"
          okButtonProps={{ danger: true }}
          confirmLoading={clearing}
          onOk={async () => {
            setClearing(true);
            try {
              await request("/visitor", "DELETE");
              location.reload();
            } catch (e) {
              setError(String(e));
              setPrivacyOpen(false);
            } finally {
              setClearing(false);
            }
          }}
        >
          <p>
            将清除当前访客的全部会话及跨会话记忆，并停止在途任务。此操作无法撤销。
          </p>
          <p>
            发布者后台的任务审计仍会保留。只需删除一条会话时，请使用左侧会话卡片的删除按钮。
          </p>
        </Modal>
      </div>
    </ConfigProvider>
  );
}

function InteractiveView({
  view,
  request,
}: {
  view: any;
  request: (path: string, method?: string) => Promise<any>;
}) {
  const [ticket, setTicket] = useState<any>(),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(true),
    [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError("");
    request(`/runs/${view.run_id}/views/${view.call_id}`, "POST")
      .then((r) => {
        if (alive) setTicket(r);
      })
      .catch((e) => {
        if (alive) setError(String(e));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [view.run_id, view.call_id, attempt]);
  const blocked =
    ticket?.compatibility_required && !ticket?.compatibility_allowed;
  return (
    <div className="public-interactive">
      <div className="public-interactive-title">
        <span>◈ {view.name || "交互结果"}</span>
        <div>
          {ticket?.mode === "isolated-compatibility" && (
            <small>兼容模式 · 隔离运行</small>
          )}
          <Button
            size="small"
            type="text"
            icon={<ReloadOutlined />}
            loading={loading}
            onClick={() => setAttempt((a) => a + 1)}
          >
            重新加载
          </Button>
        </div>
      </div>
      {loading ? (
        <div className="public-view-loading">
          <Spin /> 正在连接交互视图…
        </div>
      ) : error ? (
        <Alert
          type="error"
          message="交互视图暂时无法加载"
          description={error}
        />
      ) : blocked ? (
        <Alert
          type="warning"
          message="此会话绑定的发布版本未授权地图兼容模式"
          description="请发布者在工具授权中开启可信交互卡片兼容模式并发布新版本，再新建会话。访客不能自行修改安全授权。"
        />
      ) : (
        ticket && (
          <iframe
            title="工具交互卡片"
            src={ticket.url}
            sandbox={
              ticket.mode === "isolated-compatibility"
                ? "allow-scripts allow-forms allow-same-origin"
                : "allow-scripts"
            }
            referrerPolicy="no-referrer"
          />
        )
      )}
    </div>
  );
}
