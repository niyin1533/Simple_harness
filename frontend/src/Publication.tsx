/** @input Published grants and configuration APIs. @output Persistent grant editor, channels and key management.
 * @position Agent publication management. @doc-sync Update INDEX.md on changes. */
import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Checkbox,
  Collapse,
  Drawer,
  Input,
  Popconfirm,
  Space,
  Spin,
  Switch,
  Table,
  Tabs,
  Tag,
  Typography,
} from "antd";
import { api } from "./api";
import "./publication.css";
export { PublishedApp } from "./PublishedApp";

export function PublicationButton({ agent }: { agent: any }) {
  const [open, setOpen] = useState(false);
  const { data = [] } = useQuery({
    queryKey: ["publications"],
    queryFn: () => api("/publications"),
  });
  const published = data.find((a: any) => a.agent_id === agent.id);
  return (
    <>
      <Space wrap>
        <Tag color={published?.enabled ? "blue" : "default"}>
          {!published
            ? "未发布"
            : !published.enabled
              ? "已停用发布"
              : published.changed
                ? "有未发布修改"
                : `已发布 v${published.number}`}
        </Tag>
        {published?.dependency_error && <Tag color="red">依赖异常</Tag>}
        <Button size="small" onClick={() => setOpen(true)}>
          发布管理
        </Button>
      </Space>
      {open && (
        <PublishDrawer
          agent={agent}
          published={published}
          close={() => setOpen(false)}
        />
      )}
    </>
  );
}
const defaultGrant = (c: any) =>
  c.ui_uri === "ui://cesium-map/mcp-app.html" ? { ui_compatibility: true } : {};
function PublishDrawer({ agent, published, close }: any) {
  const cache = useQueryClient(),
    { message, modal } = App.useApp();
  const [web, setWeb] = useState(published?.web_enabled || false),
    [service, setService] = useState(published?.api_enabled ?? true);
  const [grants, setGrants] = useState<Record<string, any>>({}),
    [notes, setNotes] = useState(""),
    [ack, setAck] = useState(false),
    [busy, setBusy] = useState(false),
    [keyName, setKeyName] = useState("");
  const initialized = useRef(false);
  const {
    data: check,
    error,
    isFetching,
  } = useQuery({
    queryKey: ["publish-check", agent.id],
    queryFn: () => api("/publications/check/" + agent.id),
    retry: false,
    gcTime: 0,
    refetchOnMount: "always",
  });
  const { data: versions = [] } = useQuery({
    queryKey: ["published-versions", published?.id],
    queryFn: () => api(`/publications/${published.id}/versions`),
    enabled: !!published,
  });
  const { data: keys = [] } = useQuery({
    queryKey: ["published-keys", published?.id],
    queryFn: () => api(`/publications/${published.id}/keys`),
    enabled: !!published,
  });
  useEffect(() => {
    if (
      !check ||
      isFetching ||
      initialized.current ||
      (published && !("saved_grants" in check))
    )
      return;
    const saved = check.saved_grants;
    setGrants(
      Object.fromEntries(
        check.capabilities
          .filter(
            (c: any) =>
              c.allowed &&
              (saved != null
                ? Object.prototype.hasOwnProperty.call(saved, c.id)
                : c.risk !== "HIGH"),
          )
          .map((c: any) => [
            c.id,
            { ...defaultGrant(c), ...(saved?.[c.id] || {}) },
          ]),
      ),
    );
    initialized.current = true;
  }, [check, isFetching]);
  const eligible = (check?.capabilities || []).filter(
      (c: any) => c.allowed && c.risk !== "HIGH",
    ),
    selected = eligible.filter((c: any) => c.id in grants).length;
  const toggleAll = (checked: boolean) =>
    setGrants((previous) => {
      const next = { ...previous };
      for (const c of eligible) {
        if (checked) next[c.id] = next[c.id] || defaultGrant(c);
        else delete next[c.id];
      }
      return next;
    });
  async function action(fn: () => Promise<any>) {
    setBusy(true);
    try {
      await fn();
      await cache.invalidateQueries();
      message.success("操作成功");
    } catch (e) {
      message.error(String(e));
    } finally {
      setBusy(false);
    }
  }
  const webUrl = published
    ? `${location.origin}/published/agents/${published.site_code}`
    : "";
  const channels = (
    <div className="publish-channels">
      <label>
        <Switch checked={web} onChange={setWeb} aria-label="开放 Web 应用" />
        <span>
          Web 应用<small>通过链接直接聊天，无需平台账号</small>
        </span>
      </label>
      <label>
        <Switch
          checked={service}
          onChange={setService}
          aria-label="开放 API 接入"
        />
        <span>
          API 接入<small>供外部程序使用密钥调用</small>
        </span>
      </label>
    </div>
  );
  return (
    <Drawer
      title={`发布 · ${agent.name}`}
      open
      onClose={close}
      width={800}
      styles={{ body: { overflowX: "hidden" } }}
    >
      <Alert
        type="info"
        showIcon
        message="编辑草稿不影响线上；旧会话保持原版本，新会话使用当前版本。"
        style={{ marginBottom: 20 }}
      />
      <Tabs
        items={[
          {
            key: "publish",
            label: "发布版本",
            children: (
              <Space
                direction="vertical"
                className="publish-stack"
                size="middle"
              >
                {error && <Alert type="error" message={String(error)} />}
                {published && check && !("saved_grants" in check) && (
                  <Alert
                    type="warning"
                    message="请先重启后端服务，以读取已发布的授权。当前不会用默认值覆盖原授权。"
                  />
                )}
                {!initialized.current && !error && <Spin />}
                {!published && channels}
                <div>
                  <h3>工具授权</h3>
                  <p className="publish-hint">
                    首次默认全选权限允许的非 HIGH
                    工具；已发布应用恢复上次授权。文件与网络范围限制仍然生效。
                  </p>
                </div>
                <div className="publish-tool-box">
                  <div className="publish-tool-toolbar">
                    <Checkbox
                      checked={
                        !!eligible.length && selected === eligible.length
                      }
                      indeterminate={selected > 0 && selected < eligible.length}
                      onChange={(e) => toggleAll(e.target.checked)}
                    >
                      全选非 HIGH 工具
                    </Checkbox>
                    <span>
                      {selected} / {eligible.length} 项
                    </span>
                  </div>
                  <div
                    className="publish-tool-scroll"
                    tabIndex={0}
                    aria-label="可发布工具列表"
                  >
                    {check?.capabilities.map((c: any) => (
                      <div className="publish-tool" key={c.id}>
                        <div className="publish-tool-heading">
                          <Checkbox
                            disabled={!c.allowed}
                            checked={c.id in grants}
                            onChange={(e) =>
                              setGrants((previous) => {
                                const next = { ...previous };
                                if (e.target.checked)
                                  next[c.id] = defaultGrant(c);
                                else delete next[c.id];
                                return next;
                              })
                            }
                          >
                            {c.name}
                          </Checkbox>
                          <Tag
                            color={
                              c.risk === "HIGH"
                                ? "red"
                                : c.risk === "WRITE"
                                  ? "orange"
                                  : "blue"
                            }
                          >
                            {c.risk}
                          </Tag>
                        </div>
                        {!c.allowed && (
                          <small>
                            当前智能体权限预设禁止，不能通过发布授权绕过
                          </small>
                        )}
                        {c.id in grants &&
                          (c.id === "builtin.http.fetch" ||
                            c.url_parameters?.length > 0) && (
                            <Input
                              defaultValue={(grants[c.id].hosts || []).join(
                                ", ",
                              )}
                              aria-label={`${c.name}允许的域名`}
                              placeholder="必须填写允许的精确域名:端口，逗号分隔，不允许通配"
                              onChange={(e) =>
                                setGrants({
                                  ...grants,
                                  [c.id]: {
                                    ...grants[c.id],
                                    hosts: e.target.value
                                      .split(",")
                                      .map((x) => x.trim().toLowerCase())
                                      .filter(Boolean),
                                  },
                                })
                              }
                            />
                          )}
                        {c.id in grants && c.id === "builtin.process.exec" && (
                          <Input.TextArea
                            defaultValue={JSON.stringify(
                              grants[c.id].commands || [],
                            )}
                            placeholder={
                              '精确命令 JSON：[{"executable":"git","args":["status"]}]'
                            }
                            onChange={(e) => {
                              try {
                                setGrants({
                                  ...grants,
                                  [c.id]: {
                                    commands: JSON.parse(e.target.value),
                                  },
                                });
                              } catch {
                                setGrants({
                                  ...grants,
                                  [c.id]: { commands: [] },
                                });
                              }
                            }}
                          />
                        )}
                        {c.ui_uri && c.id in grants && (
                          <div className="publish-compat">
                            <Checkbox
                              checked={grants[c.id].ui_compatibility === true}
                              onChange={(e) =>
                                setGrants({
                                  ...grants,
                                  [c.id]: {
                                    ...grants[c.id],
                                    ui_compatibility: e.target.checked,
                                  },
                                })
                              }
                            >
                              允许可信交互卡片兼容模式
                            </Checkbox>
                            <small>
                              Cesium
                              地图需要开启。发布后自动使用独立显示域和受限网络，访客无需操作。
                            </small>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
                <Alert
                  type="warning"
                  showIcon
                  message="勾选即允许外部用户调用，包括所选写入工具。HIGH 不参与全选，匿名 Web 始终禁止 HIGH。"
                />
                <Input.TextArea
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="发布说明（可选）"
                  maxLength={2000}
                />
                {check?.warnings.map((w: string) => (
                  <div className="publish-hint" key={w}>
                    {w}
                  </div>
                ))}
                <Checkbox
                  checked={ack}
                  onChange={(e) => setAck(e.target.checked)}
                >
                  我已完成后台调试，确认依赖和所选授权可对外开放
                </Checkbox>
                <Button
                  type="primary"
                  loading={busy}
                  disabled={!initialized.current || !ack}
                  onClick={() =>
                    action(async () => {
                      await api("/publications", "POST", {
                        agent_id: agent.id,
                        web_enabled: web,
                        api_enabled: service,
                        grants,
                        notes,
                        acknowledge_warnings: ack,
                      });
                      setAck(false);
                    })
                  }
                >
                  发布新版本
                </Button>
              </Space>
            ),
          },
          {
            key: "access",
            label: "应用链接与密钥",
            disabled: !published,
            children: published && (
              <Space
                direction="vertical"
                size="large"
                className="publish-stack"
              >
                <Card title="分享 Web 应用" size="small">
                  <Typography.Paragraph
                    copyable
                    style={{ overflowWrap: "anywhere" }}
                  >
                    {webUrl}
                  </Typography.Paragraph>
                  <Button
                    type="primary"
                    href={webUrl}
                    target="_blank"
                    disabled={!published.enabled || !published.web_enabled}
                  >
                    打开 Web 应用
                  </Button>
                  {(!published.enabled || !published.web_enabled) && (
                    <p className="publish-hint">
                      当前未开放，请到“发布设置”开启。
                    </p>
                  )}
                </Card>
                <Card title="API 密钥 · 仅外部程序接入时需要" size="small">
                  <p className="publish-hint">
                    只使用 Web
                    链接聊天，不需要创建密钥。密钥长期有效，不用时吊销即可；名称只是帮助你区分用途的备注。
                  </p>
                  <Space.Compact block>
                    <Input
                      value={keyName}
                      onChange={(e) => setKeyName(e.target.value)}
                      placeholder="密钥备注（可选，例如：官网客服）"
                      maxLength={100}
                    />
                    <Button
                      loading={busy}
                      onClick={() =>
                        action(async () => {
                          const r = await api(
                            `/publications/${published.id}/keys`,
                            "POST",
                            {
                              name:
                                keyName.trim() || `应用密钥 ${keys.length + 1}`,
                              expires: null,
                            },
                          );
                          setKeyName("");
                          modal.info({
                            title: "请立即保存，仅显示一次",
                            width: 600,
                            content: (
                              <Typography.Paragraph
                                copyable
                                style={{ overflowWrap: "anywhere" }}
                              >
                                {r.key}
                              </Typography.Paragraph>
                            ),
                          });
                        })
                      }
                    >
                      创建密钥
                    </Button>
                  </Space.Compact>
                  <Table
                    style={{ marginTop: 16 }}
                    size="small"
                    rowKey="id"
                    dataSource={keys}
                    pagination={false}
                    columns={[
                      { title: "备注", dataIndex: "name" },
                      {
                        title: "密钥",
                        render: (_, k: any) => `${k.prefix}…${k.last_four}`,
                      },
                      {
                        title: "状态",
                        render: (_, k: any) =>
                          !k.active
                            ? "已吊销"
                            : k.expires && k.expires < Date.now()
                              ? "已过期"
                              : k.expires
                                ? "有截止日期（历史密钥）"
                                : "长期有效",
                      },
                      {
                        title: "操作",
                        render: (_, k: any) =>
                          k.active && (
                            <Popconfirm
                              title="吊销后，使用此密钥的外部程序将无法访问，确定继续？"
                              onConfirm={() =>
                                action(() =>
                                  api(
                                    `/publications/${published.id}/keys/${k.id}`,
                                    "DELETE",
                                  ),
                                )
                              }
                            >
                              <Button danger size="small">
                                吊销
                              </Button>
                            </Popconfirm>
                          ),
                      },
                    ]}
                  />
                </Card>
                <Collapse
                  items={[
                    {
                      key: "developer",
                      label: "开发者接入 · API 地址与调用说明",
                      children: (
                        <>
                          <p>
                            这是程序提交聊天请求的接口，不是聊天网页。普通访客无需使用。
                          </p>
                          <Typography.Paragraph
                            copyable
                            style={{ overflowWrap: "anywhere" }}
                          >
                            {location.origin}/service-api/v1/chat-messages
                          </Typography.Paragraph>
                          <p>
                            POST 请求，使用 Authorization: Bearer app-…，提交
                            query、稳定 user，以及 response_mode（async /
                            streaming）。密钥仅能访问本应用。
                          </p>
                        </>
                      ),
                    },
                  ]}
                />
              </Space>
            ),
          },
          {
            key: "settings",
            label: "发布设置",
            disabled: !published,
            children: published && (
              <Space
                direction="vertical"
                size="large"
                className="publish-stack"
              >
                <Card title="开放渠道" size="small">
                  {channels}
                  <p className="publish-hint">
                    只改变入口是否开放，不修改智能体版本或工具授权。
                  </p>
                  <Button
                    type="primary"
                    loading={busy}
                    onClick={() =>
                      action(() =>
                        api(`/publications/${published.id}`, "PATCH", {
                          enabled: published.enabled,
                          web_enabled: web,
                          api_enabled: service,
                          rpm: published.rpm,
                          concurrency: published.concurrency,
                        }),
                      )
                    }
                  >
                    保存开放设置
                  </Button>
                </Card>
                <Card title="应用状态" size="small">
                  <p>
                    {published.enabled
                      ? "应用已上线。下线后 Web 和 API 不再接受新消息，已运行任务可以完成，历史记录保留。"
                      : "应用已下线。重新上线后，按上述渠道设置恢复访问。"}
                  </p>
                  <Popconfirm
                    title={
                      published.enabled
                        ? "确认下线应用？Web 和 API 都将停止接收新消息。"
                        : "确认重新上线？"
                    }
                    onConfirm={() =>
                      action(() =>
                        api(`/publications/${published.id}`, "PATCH", {
                          ...published,
                          enabled: !published.enabled,
                        }),
                      )
                    }
                  >
                    <Button danger={published.enabled} loading={busy}>
                      {published.enabled ? "下线应用" : "重新上线"}
                    </Button>
                  </Popconfirm>
                </Card>
              </Space>
            ),
          },
          {
            key: "versions",
            label: "历史版本",
            disabled: !published,
            children: (
              <Table
                rowKey="id"
                dataSource={versions}
                columns={[
                  {
                    title: "版本",
                    dataIndex: "number",
                    render: (v) => `v${v}`,
                  },
                  { title: "说明", dataIndex: "notes" },
                  {
                    title: "操作",
                    render: (_, v: any) =>
                      v.id === published?.current_version ? (
                        <Tag color="blue">当前版本</Tag>
                      ) : (
                        <Popconfirm
                          title={`切换至 v${v.number}？仅影响新会话。`}
                          onConfirm={() =>
                            action(() =>
                              api(
                                `/publications/${published.id}/versions/${v.id}/activate`,
                                "POST",
                              ),
                            )
                          }
                        >
                          <Button size="small" loading={busy}>
                            切换版本
                          </Button>
                        </Popconfirm>
                      ),
                  },
                ]}
              />
            ),
          },
        ]}
      />
    </Drawer>
  );
}
