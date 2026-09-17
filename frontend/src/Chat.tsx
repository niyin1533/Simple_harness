/** @input Private sessions, durable run events, MCP views. @output Chat/task supervision, confirmed history cleanup and map compatibility. @position Conversation UI. @doc-sync Update INDEX.md on changes. */
import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import {
  App,
  Alert,
  Button,
  Card,
  Drawer,
  Empty,
  Input,
  List,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Collapse,
  Popconfirm,
  Tooltip,
  Upload,
} from "antd";
import {
  PlusOutlined,
  DeleteOutlined,
  SendOutlined,
  PaperClipOutlined,
} from "@ant-design/icons";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, list, Json, labels, date } from "./api";
const done = new Set([
  "SUCCEEDED",
  "FAILED",
  "CANCELLED",
  "PAUSED",
  "BLOCKED",
  "NEEDS_REVIEW",
  "WAITING_APPROVAL",
]);
export function Chat() {
  const [params] = useSearchParams();
  const cache = useQueryClient();
  const { message } = App.useApp();
  const [session, setSession] = useState<string>(),
    [target, setTarget] = useState(params.get("agent") || ""),
    [text, setText] = useState(""),
    [busy, setBusy] = useState(false),
    [run, setRun] = useState<string>();
  const { data: targets = [] } = useQuery({
    queryKey: ["chat-targets"],
    queryFn: async () => [...(await list("agent")), ...(await list("model"))],
  });
  const { data: sessions = [] } = useQuery<Json[]>({
    queryKey: ["sessions"],
    queryFn: () => api("/sessions"),
  });
  const { data: conversation } = useQuery({
    queryKey: ["messages", session],
    queryFn: () => api("/sessions/" + session + "/messages"),
    enabled: !!session,
    refetchInterval: session ? 2500 : false,
  });
  const { data: runs = [] } = useQuery<Json[]>({
    queryKey: ["runs"],
    queryFn: () => api("/runs"),
    refetchInterval: 3000,
  });
  const active = runs.find((r) => r.session_id === session);
  const selected = targets.find((r) => r.id === target);
  const removeSession = async (id: string) => {
    try {
      await api("/sessions/" + id, "DELETE");
      if (id === session) {
        setSession(undefined);
        setRun(undefined);
      }
      cache.removeQueries({ queryKey: ["messages", id] });
      await cache.invalidateQueries({ queryKey: ["sessions"] });
      message.success("对话已删除，任务记录仍保留");
    } catch (e) {
      message.error(String(e));
    }
  };
  const send = async () => {
    if (!text.trim() || !target) return;
    setBusy(true);
    try {
      const r = await api("/runs", "POST", {
        target_id: target,
        target_type: selected?.kind === "model" ? "model" : "agent",
        task: text,
        session_id: session,
      });
      setSession(r.session_id);
      setText("");
      cache.invalidateQueries({ queryKey: ["sessions"] });
      cache.invalidateQueries({ queryKey: ["messages"] });
      cache.invalidateQueries({ queryKey: ["runs"] });
    } catch (e) {
      message.error(String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="chat-layout">
      <aside className="session-panel">
        <Button
          block
          icon={<PlusOutlined />}
          onClick={() => {
            setSession(undefined);
            setRun(undefined);
          }}
        >
          新建对话
        </Button>
        <h4>最近对话</h4>
        <List
          dataSource={sessions}
          locale={{ emptyText: "对话将保存在这里" }}
          renderItem={(s) => (
            <List.Item
              className={s.id === session ? "selected-session" : ""}
              onClick={() => {
                setSession(s.id);
                setTarget(s.target_id);
                setRun(undefined);
              }}
            >
              <div className="session-title">
                {s.title}
                <small>{date(s.created)}</small>
              </div>
              <span onClick={(e) => e.stopPropagation()}>
                <Popconfirm
                  title="删除此对话？"
                  description="对话删除后无法恢复，任务记录仍保留。"
                  onConfirm={() => removeSession(s.id)}
                >
                  <Tooltip title="删除会话">
                    <Button
                      className="session-delete"
                      type="text"
                      icon={<DeleteOutlined />}
                      aria-label={"删除对话：" + s.title}
                    />
                  </Tooltip>
                </Popconfirm>
              </span>
            </List.Item>
          )}
        />
      </aside>
      <section className="conversation">
        <div className="conversation-toolbar">
          <Select
            showSearch
            optionFilterProp="label"
            value={target || undefined}
            placeholder="选择智能体或基础模型"
            onChange={(v) => {
              setTarget(v);
              setSession(undefined);
              setRun(undefined);
            }}
            style={{ minWidth: 260 }}
            options={targets
              .filter((r) => r.enabled)
              .map((r) => ({
                value: r.id,
                label: (r.kind === "model" ? "模型 · " : "") + r.name,
              }))}
          />
          {session && (
            <Space>
              <Button
                onClick={async () => {
                  try {
                    await api("/sessions/" + session + "/compact", "POST");
                    message.success("上下文已整理");
                  } catch (e) {
                    message.error(String(e));
                  }
                }}
              >
                压缩上下文
              </Button>
              <Popconfirm
                title="删除对话记录？任务审计仍保留。"
                onConfirm={() => removeSession(session)}
              >
                <Button type="text" danger>
                  删除
                </Button>
              </Popconfirm>
            </Space>
          )}
        </div>
        <div className="message-scroll">
          {!conversation?.messages.length ? (
            <div className="chat-welcome">
              <span className="eyebrow">YOUR AGENT WORKSPACE</span>
              <h1>复杂任务，从一次对话开始。</h1>
              <p>
                选择一个智能体，描述目标。执行过程和需要确认的操作，都清晰可见。
              </p>
              <div className="welcome-prompts">
                {[
                  "分析工作目录中的项目结构",
                  "检查数据文件并总结发现",
                  "帮我梳理一份可执行的任务清单",
                ].map((p) => (
                  <Button key={p} onClick={() => setText(p)}>
                    {p}
                  </Button>
                ))}
              </div>
            </div>
          ) : (
            conversation.messages.map((m: Json) => (
              <article key={m.id} className={"message-bubble " + m.role}>
                <div className="message-role">
                  {m.role === "user" ? "你" : "智能体"}
                </div>
                <Markdown remarkPlugins={[remarkGfm]}>{m.content}</Markdown>
                {m.meta?.used?.length > 0 && (
                  <Tag>使用了 {m.meta.used.length} 条记忆</Tag>
                )}
              </article>
            ))
          )}
          {active && (
            <div className="inline-run">
              <Tag color={active.status === "SUCCEEDED" ? "green" : "blue"}>
                {labels[active.status] || active.status}
              </Tag>
              <span>
                步骤 {active.step} · {active.agent_name}
              </span>
              <Button size="small" onClick={() => setRun(active.id)}>
                查看执行过程
              </Button>
              {active.error && <Alert type="error" message={active.error} />}
            </div>
          )}
        </div>
        <div className="composer">
          <Input.TextArea
            value={text}
            onChange={(e) => setText(e.target.value)}
            autoSize={{ minRows: 3, maxRows: 8 }}
            placeholder="描述你的目标，Shift + Enter 换行"
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
          <div className="composer-footer">
            <Upload
              showUploadList={false}
              beforeUpload={(file) => {
                const data = new FormData();
                data.append("file", file);
                api("/uploads/attachment", "POST", data)
                  .then((a) => {
                    setText(
                      (t) =>
                        t + "\n附件：" + a.name + "\n服务器路径：" + a.path,
                    );
                    message.success("附件已上传");
                  })
                  .catch((e) => message.error(String(e)));
                return false;
              }}
            >
              <Button type="text" icon={<PaperClipOutlined />}>
                附件
              </Button>
            </Upload>
            <span className="muted">文件访问受智能体工作目录限制</span>
            <Button
              type="primary"
              icon={<SendOutlined />}
              loading={busy}
              disabled={
                !text.trim() ||
                !target ||
                (!!active &&
                  !["SUCCEEDED", "FAILED", "CANCELLED"].includes(active.status))
              }
              onClick={send}
            >
              发送
            </Button>
          </div>
        </div>
      </section>
      {run && <RunDrawer id={run} close={() => setRun(undefined)} />}
    </div>
  );
}
export function Tasks() {
  const cache = useQueryClient();
  const { message } = App.useApp();
  const [checked, setChecked] = useState<React.Key[]>([]);
  const [deleting, setDeleting] = useState(false);
  const removable = (r: Json) =>
    ["SUCCEEDED", "FAILED", "CANCELLED", "BLOCKED"].includes(r.status);
  const remove = async (ids: string[]) => {
    setDeleting(true);
    try {
      await api("/runs/batch-delete", "POST", { ids });
      setChecked([]);
      if (selected && ids.includes(selected)) setSelected(undefined);
      await cache.invalidateQueries({ queryKey: ["runs"] });
      message.success("已删除 " + ids.length + " 条任务记录");
    } catch (e) {
      message.error(String(e));
    } finally {
      setDeleting(false);
    }
  };
  const [selected, setSelected] = useState<string>();
  const { data = [], isLoading } = useQuery<Json[]>({
    queryKey: ["runs"],
    queryFn: () => api("/runs"),
    refetchInterval: 2500,
  });
  return (
    <>
      <div className="page-title">
        <div>
          <span className="eyebrow">TASKS</span>
          <h1>每一步，都有迹可循</h1>
          <p>查看自己的执行记录、工具调用和待确认操作。</p>
        </div>
      </div>
      <Card>
        <Space className="spaced-bottom">
          <Popconfirm
            title={
              "永久删除所选 " +
              checked.length +
              " 条任务及执行记录？聊天内容保留，无法撤销。"
            }
            onConfirm={() => remove(checked.map(String))}
          >
            <Button danger disabled={!checked.length} loading={deleting}>
              批量删除{checked.length ? `（${checked.length}）` : ""}
            </Button>
          </Popconfirm>
          <span>仅可删除已结束任务；其他任务请先取消。</span>
        </Space>
        <Table
          rowKey="id"
          loading={isLoading}
          dataSource={data}
          rowSelection={{
            selectedRowKeys: checked,
            onChange: setChecked,
            getCheckboxProps: (r) => ({ disabled: !removable(r) || deleting }),
          }}
          columns={[
            { title: "任务", dataIndex: "task", ellipsis: true },
            { title: "智能体", dataIndex: "agent_name" },
            {
              title: "来源",
              dataIndex: "trigger",
              filters: [
                { text: "后台", value: "INTERACTIVE" },
                { text: "定时任务", value: "SCHEDULED" },
                { text: "公开 Web", value: "WEB_APP" },
                { text: "Service API", value: "SERVICE_API" },
              ],
              onFilter: (v, r) => r.trigger === v,
              render: (s) =>
                (
                  ({
                    INTERACTIVE: "后台",
                    SCHEDULED: "定时任务",
                    WEB_APP: "公开 Web",
                    SERVICE_API: "Service API",
                  }) as Record<string, string>
                )[s] || s,
            },
            {
              title: "发布版本",
              dataIndex: "published_version",
              filters: [
                ...new Set(
                  data.map((r) => r.published_version).filter(Boolean),
                ),
              ].map((v) => ({ text: `v${v}`, value: v })),
              onFilter: (v, r) => r.published_version === v,
              render: (v) => (v ? `v${v}` : "—"),
            },
            {
              title: "状态",
              dataIndex: "status",
              render: (s) => (
                <Tag
                  color={
                    s === "SUCCEEDED"
                      ? "green"
                      : s === "FAILED"
                        ? "red"
                        : "blue"
                  }
                >
                  {labels[s] || s}
                </Tag>
              ),
            },
            { title: "发起时间", dataIndex: "created", render: date },
            {
              title: "",
              render: (_, r) => (
                <Space>
                  <Button onClick={() => setSelected(r.id)}>详情</Button>
                  <Popconfirm
                    title="永久删除此任务及执行记录？聊天内容保留，无法撤销。"
                    onConfirm={() => remove([r.id])}
                  >
                    <Button danger disabled={!removable(r) || deleting}>
                      删除
                    </Button>
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
      </Card>
      {selected && (
        <RunDrawer id={selected} close={() => setSelected(undefined)} />
      )}
    </>
  );
}
export function RunDrawer({ id, close }: { id: string; close: () => void }) {
  const cache = useQueryClient(),
    { message } = App.useApp();
  const [events, setEvents] = useState<Json[]>([]);
  const { data } = useQuery({
    queryKey: ["run", id],
    queryFn: () => api("/runs/" + id),
    refetchInterval: 2000,
  });
  useEffect(() => {
    setEvents([]);
    let disposed = false;
    const stream = new EventSource("/api/v1/runs/" + id + "/stream");
    stream.addEventListener("agent-run", (event) => {
      if (disposed) return;
      const row = JSON.parse((event as MessageEvent).data);
      setEvents((old) =>
        old.some((e) => e.seq === row.seq) ? old : [...old, row],
      );
      cache.invalidateQueries({ queryKey: ["run", id] });
      cache.invalidateQueries({ queryKey: ["messages"] });
    });
    return () => {
      disposed = true;
      stream.close();
    };
  }, [id, cache]);
  const act = async (action: string) => {
    try {
      await api("/runs/" + id + "/" + action, "POST");
      cache.invalidateQueries({ queryKey: ["run", id] });
      cache.invalidateQueries({ queryKey: ["runs"] });
    } catch (e) {
      message.error(String(e));
    }
  };
  const status = data?.run.status;
  return (
    <Drawer open width={720} title="任务执行记录" onClose={close}>
      {!data ? (
        <Spin />
      ) : (
        <>
          <Space wrap>
            <Tag color="blue">{labels[status] || status}</Tag>
            <span>{data.run.agent_name}</span>
            {["RUNNING", "QUEUED", "WAITING_APPROVAL"].includes(status) && (
              <Button onClick={() => act("pause")}>暂停</Button>
            )}
            {["PAUSED", "FAILED", "BLOCKED"].includes(status) && (
              <Button onClick={() => act("resume")}>继续</Button>
            )}
            {!["SUCCEEDED", "CANCELLED"].includes(status) && (
              <Popconfirm
                title="取消此任务？已完成的操作不会撤销。"
                onConfirm={() => act("cancel")}
              >
                <Button danger>取消</Button>
              </Popconfirm>
            )}
          </Space>
          <p>{data.run.task}</p>
          {data.run.error && (
            <Alert showIcon type="error" message={data.run.error} />
          )}{" "}
          {data.approvals
            .filter(
              (a: Json) =>
                a.status === "PENDING" && status === "WAITING_APPROVAL",
            )
            .map((a: Json) => {
              const call = data.calls.find((c: Json) => c.id === a.call_id);
              return (
                <Card key={a.id} className="approval-card" title="需要你的确认">
                  <p>{call?.capability_id}</p>
                  <pre>{JSON.stringify(call?.arguments, null, 2)}</pre>
                  <Space>
                    {[true, false].map((approved) => (
                      <Button
                        key={String(approved)}
                        type={approved ? "primary" : "default"}
                        danger={!approved}
                        onClick={async () => {
                          try {
                            await api("/approvals/" + a.id, "POST", {
                              approved,
                            });
                            cache.invalidateQueries({ queryKey: ["run", id] });
                          } catch (e) {
                            message.error(String(e));
                          }
                        }}
                      >
                        {approved ? "允许这一次" : "拒绝"}
                      </Button>
                    ))}
                  </Space>
                </Card>
              );
            })}
          <h3>事件时间线</h3>
          <Collapse
            items={events.map((e) => ({
              key: e.seq,
              label: (
                <Space>
                  <Tag>{e.seq}</Tag>
                  {e.name}
                  <span className="muted">{date(e.created)}</span>
                </Space>
              ),
              children: <pre>{JSON.stringify(e.data, null, 2)}</pre>,
            }))}
          />
          {!done.has(status) && (
            <p>
              <Spin size="small" /> 等待下一条执行事件…
            </p>
          )}
          <h3>工具结果</h3>
          {data.calls.map((c: Json) => (
            <Card
              key={c.id}
              size="small"
              className="tool-result"
              title={c.capability_id}
              extra={<Tag>{labels[c.status] || c.status}</Tag>}
            >
              <pre>{JSON.stringify(c.result, null, 2)}</pre>
              {c.result?.data?.artifacts?.map((a: Json) => (
                <div key={a.id} className="spaced-bottom">
                  <a href={a.url} target="_blank" rel="noreferrer">
                    下载 {a.name}
                  </a>
                  {/\.(png|jpe?g|webp)$/i.test(a.name) && (
                    <img
                      src={a.url}
                      alt="工具生成结果"
                      style={{
                        display: "block",
                        maxWidth: "100%",
                        maxHeight: 360,
                        marginTop: 12,
                      }}
                    />
                  )}
                  {/\.(mp3|wav)$/i.test(a.name) && (
                    <audio
                      controls
                      src={a.url}
                      style={{ display: "block", width: "100%", marginTop: 12 }}
                    />
                  )}
                </div>
              ))}
              {c.result?.data?.app && (
                <McpApp
                  app={c.result.data.app}
                  result={c.result.data}
                  arguments_={c.arguments}
                />
              )}
            </Card>
          ))}
          {data.run.result && (
            <>
              <h3>最终答复</h3>
              <Markdown remarkPlugins={[remarkGfm]}>{data.run.result}</Markdown>
            </>
          )}
        </>
      )}
    </Drawer>
  );
}
function McpApp({
  app,
  result,
  arguments_,
}: {
  app: Json;
  result: Json;
  arguments_: Json;
}) {
  const { message, modal } = App.useApp();
  const [url, setUrl] = useState("");
  const [compatibility, setCompatibility] = useState(false);
  const openView = async (compatible: boolean) => {
    try {
      const r = await api("/mcp/" + app.server_id + "/view", "POST", {
        uri: app.uri,
        arguments: arguments_,
        result,
        compatibility: compatible,
      });
      setCompatibility(compatible);
      setUrl(r.url);
    } catch (e) {
      message.error(String(e));
    }
  };
  return (
    <>
      <Button onClick={() => openView(compatibility)}>
        {url ? "重置视图" : "打开交互结果"}
      </Button>
      <Button
        onClick={() =>
          modal.confirm({
            title: "启用可信扩展兼容模式？",
            content:
              "仅对可信扩展启用。允许独立显示域内的同源 iframe、Worker 和动态脚本；网络仍受声明域名限制，不开放业务 API 工具操作。Cesium 地图需要此模式。",
            okText: "启用兼容模式",
            cancelText: "取消",
            onOk: () => openView(true),
          })
        }
      >
        地图兼容模式
      </Button>
      {compatibility && <Tag color="orange">兼容模式已启用</Tag>}
      {url && (
        <iframe
          title="MCP 交互结果"
          className="mcp-app"
          src={url}
          sandbox="allow-scripts allow-forms allow-same-origin"
          referrerPolicy="no-referrer"
        />
      )}
    </>
  );
}
