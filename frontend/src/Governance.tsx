/** @input Private memory, schedule and admin user APIs. @output Governance pages with bounded review layout and asynchronous loading feedback. @position Settings UI. @doc-sync Update INDEX.md on changes. */
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  App,
  Alert,
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  Popconfirm,
} from "antd";
import { api, list, Json, date } from "./api";
const memoryTypes = [
  { value: "fact", label: "事实" }, { value: "preference", label: "偏好" },
  { value: "rule", label: "规则" }, { value: "experience", label: "经验" },
  { value: "error", label: "错误教训" }, { value: "context", label: "上下文" },
];
export function Memories() {
  const [reviewing, setReviewing] = useState(false);
  const [reindexing, setReindexing] = useState(false);
  const cache = useQueryClient(),
    { message, modal } = App.useApp();
  const [edit, setEdit] = useState<Json | null | undefined>(),
    [form] = Form.useForm(),
    [prefs] = Form.useForm();
  const { data = [] } = useQuery<Json[]>({
    queryKey: ["memories"],
    queryFn: () => api("/memories"),
  });
  const { data: agents = [] } = useQuery({
    queryKey: ["agents-options"],
    queryFn: () => list("agent"),
  });
  const { data: models = [] } = useQuery({
    queryKey: ["models-options"],
    queryFn: () => list("model"),
  });
  const { data: preference } = useQuery({
    queryKey: ["preferences"],
    queryFn: () => api("/preferences"),
  });
  const refresh = () => cache.invalidateQueries();
  const change = async (id: string, body: Json) => {
    try {
      await api("/memories/" + id, "PUT", body);
      refresh();
    } catch (e) {
      message.error(String(e));
    }
  };
  return (
    <>
      <div className="page-title">
        <div>
          <span className="eyebrow">MEMORY</span>
          <h1>保留有用的，整理过时的</h1>
          <p>记忆只属于当前用户。治理建议需要确认后才会应用。</p>
        </div>
        <Button
          type="primary"
          onClick={() => {
            form.resetFields();
            setEdit(null);
          }}
        >
          添加记忆
        </Button>
      </div>
      <Tabs
        items={[
          {
            key: "entries",
            label: "记忆条目",
            children: (
              <Card>
                <Space className="spaced-bottom">
                  <Button
                    loading={reviewing}
                    disabled={reindexing}
                    onClick={async () => {
                      setReviewing(true);
                      try {
                        const result = await api("/memories/review", "POST");
                        modal.info({
                          title: "治理建议 · 逐条确认",
                          width: 750,
                          className: "memory-review-modal",
                          content: (
                            <div className="memory-review-list">
                              {!result.suggestions?.length && <p>未发现需要处理的重复或冲突。</p>}
                              {(result.suggestions || []).map((s: Json) => (
                                <Card key={s.id} size="small">
                                  <strong>{s.reason}</strong>
                                  <p>{s.content}</p>
                                  <Button
                                    onClick={() =>
                                      change(s.id, s.action === "disable" ? { enabled: false } : {
                                        content: s.content,
                                        type: s.type,
                                        confirmed: true,
                                      })
                                    }
                                  >
                                    {s.action === "disable" ? "停用重复记忆" : "应用此建议"}
                                  </Button>
                                </Card>
                              ))}
                            </div>
                          ),
                        });
                      } catch (e) {
                        message.error(String(e));
                      } finally {
                        setReviewing(false);
                      }
                    }}
                  >
                    {reviewing ? "正在分析…" : "分析重复与冲突"}
                  </Button>
                  <Button
                    loading={reindexing}
                    disabled={reviewing}
                    onClick={async () => {
                      setReindexing(true);
                      try {
                        const r = await api("/memories/reindex", "POST");
                        message.success("已重建 " + r.count + " 条记忆索引");
                        refresh();
                      } catch (e) {
                        message.error(String(e));
                      } finally {
                        setReindexing(false);
                      }
                    }}
                  >
                    {reindexing ? "正在重建…" : "重建向量索引"}
                  </Button>
                </Space>
                <Table
                  rowKey="id"
                  dataSource={data}
                  columns={[
                    { title: "内容", dataIndex: "content" },
                    { title: "分类", render: (_, r) => memoryTypes.find(t => t.value === r.meta?.type)?.label || "未分类（历史记录）" },
                    {
                      title: "范围",
                      render: (_, r) =>
                        r.agent_id
                          ? agents.find((a) => a.id === r.agent_id)?.name ||
                            "智能体"
                          : "用户通用",
                    },
                    {
                      title: "确认",
                      dataIndex: "confirmed",
                      render: (v) => (
                        <Tag color={v ? "green" : "gold"}>
                          {v ? "已确认" : "待审核"}
                        </Tag>
                      ),
                    },
                    {
                      title: "启用",
                      render: (_, r) => (
                        <Switch
                          checked={r.enabled}
                          onChange={(enabled) => change(r.id, { enabled })}
                        />
                      ),
                    },
                    {
                      title: "操作",
                      render: (_, r) => (
                        <Space>
                          <Button
                            size="small"
                            onClick={() => {
                              form.setFieldsValue({ ...r, type: r.meta?.type || "fact" });
                              setEdit(r);
                            }}
                          >
                            编辑
                          </Button>
                          {!r.confirmed && (
                            <Button
                              size="small"
                              onClick={() => change(r.id, { confirmed: true })}
                            >
                              确认
                            </Button>
                          )}
                          <Popconfirm
                            title="删除此记忆？"
                            onConfirm={async () => {
                              await api("/memories/" + r.id, "DELETE");
                              refresh();
                            }}
                          >
                            <Button size="small" danger>
                              删除
                            </Button>
                          </Popconfirm>
                        </Space>
                      ),
                    },
                  ]}
                />
              </Card>
            ),
          },
          {
            key: "settings",
            label: "召回与治理设置",
            children: preference && (
              <Card className="settings-card">
                <Alert
                  type="info"
                  showIcon
                  message="未配置 Embedding 时使用文本相关性召回。自动治理默认关闭，开启后通过校验的长期记忆直接生效，治理失败进入待审核。"
                />
                <Form
                  key={JSON.stringify(preference)}
                  form={prefs}
                  layout="vertical"
                  initialValues={{ embedding_provider: "auto", ...preference.config }}
                  onFinish={async (v) => {
                    try {
                      const { api_key, ...config } = v;
                      await api("/preferences", "PUT", {
                        config,
                        api_key: api_key || undefined,
                      });
                      refresh();
                      message.success("设置已保存");
                    } catch (e) {
                      message.error(String(e));
                    }
                  }}
                >
                  <Form.Item name="governance_model_id" label="治理模型">
                    <Select
                      allowClear
                      options={models.map((m) => ({
                        label: m.name,
                        value: m.id,
                      }))}
                    />
                  </Form.Item>
                  <Form.Item
                    name="auto_extract"
                    label="对话后自动提取"
                    valuePropName="checked"
                  >
                    <Switch />
                  </Form.Item>
                  <Form.Item name="retrieval_limit" label="最多召回条数">
                    <InputNumber min={1} max={20} />
                  </Form.Item>
                  <Form.Item name="embedding_provider" label="Embedding 接口类型">
                    <Select options={[
                      { value: "auto", label: "自动（兼容已有配置）" },
                      { value: "ollama", label: "Ollama 原生" },
                      { value: "openai-compatible", label: "OpenAI 兼容" },
                    ]} />
                  </Form.Item>
                  <Form.Item
                    name="embedding_endpoint"
                    label="Embedding API 地址"
                    extra="Ollama 原生：http://localhost:11434；OpenAI 兼容：http://localhost:11434/v1。召回接口异常时降级为文本相关性，不中断聊天。"
                  >
                    <Input placeholder="https://…/v1" />
                  </Form.Item>
                  <Form.Item name="embedding_model" label="Embedding 模型">
                    <Input />
                  </Form.Item>
                  <Form.Item name="api_key" label="Embedding 密钥（空白保留）">
                    <Input.Password />
                  </Form.Item>
                  <Button type="primary" htmlType="submit">
                    保存设置
                  </Button>
                </Form>
              </Card>
            ),
          },
        ]}
      />
      <Modal
        open={edit !== undefined}
        title={edit ? "编辑记忆" : "添加记忆"}
        onCancel={() => setEdit(undefined)}
        onOk={async () => {
          try {
            const v = await form.validateFields();
            await api(
              "/memories" + (edit ? "/" + edit.id : ""),
              edit ? "PUT" : "POST",
              { ...v, operation: "save", confirmed: true },
            );
            setEdit(undefined);
            refresh();
          } catch (e) {
            message.error(String(e));
          }
        }}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="type" label="分类" initialValue="fact">
            <Select options={memoryTypes} />
          </Form.Item>
          <Form.Item name="agent_id" label="范围">
            <Select
              allowClear
              disabled={!!edit}
              placeholder="用户通用"
              options={agents.map((a) => ({ label: a.name, value: a.id }))}
            />
          </Form.Item>
          <Form.Item
            name="content"
            label="记忆内容"
            rules={[{ required: true }]}
          >
            <Input.TextArea rows={6} maxLength={4000} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
export function Schedules() {
  const cache = useQueryClient(),
    { message } = App.useApp();
  const [edit, setEdit] = useState<Json | null | undefined>(),
    [form] = Form.useForm();
  const { data = [] } = useQuery<Json[]>({
    queryKey: ["schedules"],
    queryFn: () => api("/schedules"),
    refetchInterval: 5000,
  });
  const { data: agents = [] } = useQuery({
    queryKey: ["agents-options"],
    queryFn: () => list("agent"),
  });
  const type = Form.useWatch(["config", "type"], form);
  const refresh = () => cache.invalidateQueries();
  return (
    <>
      <div className="page-title">
        <div>
          <span className="eyebrow">SCHEDULES</span>
          <h1>让任务按时发生</h1>
          <p>每个任务独立会话；同一计划不重叠执行，停机期间过期任务不补跑。</p>
        </div>
        <Button
          type="primary"
          onClick={() => {
            form.resetFields();
            form.setFieldsValue({
              config: {
                type: "daily",
                timezone: "Asia/Shanghai",
                time: "09:00",
              },
            });
            setEdit(null);
          }}
        >
          创建计划
        </Button>
      </div>
      <Card>
        <Table
          rowKey="id"
          dataSource={data}
          columns={[
            { title: "名称", dataIndex: "name" },
            { title: "任务", dataIndex: "task", ellipsis: true },
            {
              title: "下次执行",
              dataIndex: "next_at",
              render: (v) => (v ? date(v) : "—"),
            },
            {
              title: "启用",
              render: (_, r) => (
                <Switch
                  checked={r.enabled}
                  onChange={async (enabled) => {
                    try {
                      await api("/schedules/" + r.id, "PUT", { enabled });
                      refresh();
                    } catch (e) {
                      message.error(String(e));
                    }
                  }}
                />
              ),
            },
            {
              title: "操作",
              render: (_, r) => (
                <Space>
                  <Button
                    size="small"
                    onClick={() => {
                      form.setFieldsValue(r);
                      setEdit(r);
                    }}
                  >
                    编辑
                  </Button>
                  <Button
                    size="small"
                    onClick={async () => {
                      try {
                        await api("/schedules/" + r.id + "/run", "POST");
                        message.success("已提交，前往任务查看");
                        refresh();
                      } catch (e) {
                        message.error(String(e));
                      }
                    }}
                  >
                    立即执行
                  </Button>
                  <Popconfirm
                    title="删除计划？"
                    onConfirm={async () => {
                      await api("/schedules/" + r.id, "DELETE");
                      refresh();
                    }}
                  >
                    <Button size="small" danger>
                      删除
                    </Button>
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
      </Card>
      <Modal
        open={edit !== undefined}
        title="定时任务"
        onCancel={() => setEdit(undefined)}
        onOk={async () => {
          try {
            const v = await form.validateFields();
            await api(
              "/schedules" + (edit ? "/" + edit.id : ""),
              edit ? "PUT" : "POST",
              v,
            );
            setEdit(undefined);
            refresh();
          } catch (e) {
            message.error(String(e));
          }
        }}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="计划名称" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item
            name="agent_id"
            label="智能体"
            rules={[{ required: true }]}
          >
            <Select
              options={agents
                .filter((a) => a.enabled)
                .map((a) => ({ label: a.name, value: a.id }))}
            />
          </Form.Item>
          <Form.Item name="task" label="任务内容" rules={[{ required: true }]}>
            <Input.TextArea rows={3} />
          </Form.Item>
          <div className="form-grid">
            <Form.Item name={["config", "type"]} label="周期">
              <Select
                options={["once", "daily", "weekly", "monthly", "cron"].map(
                  (value, i) => ({
                    value,
                    label: ["一次", "每天", "每周", "每月", "Cron"][i],
                  }),
                )}
              />
            </Form.Item>
            <Form.Item name={["config", "timezone"]} label="时区">
              <Input />
            </Form.Item>
          </div>
          {type === "once" ? (
            <Form.Item
              name={["config", "at"]}
              label="执行时间（ISO，例如 2026-10-01T09:00:00+08:00）"
            >
              <Input />
            </Form.Item>
          ) : type === "cron" ? (
            <Form.Item
              name={["config", "expression"]}
              label="Cron（分 时 日 月 周）"
            >
              <Input placeholder="0 9 * * 1-5" />
            </Form.Item>
          ) : (
            <Form.Item name={["config", "time"]} label="时间 HH:mm">
              <Input />
            </Form.Item>
          )}
          {type === "weekly" && (
            <Form.Item
              name={["config", "weekday"]}
              label="星期（0=周一，6=周日）"
            >
              <InputNumber min={0} max={6} />
            </Form.Item>
          )}
          {type === "monthly" && (
            <Form.Item name={["config", "day"]} label="每月几号">
              <InputNumber min={1} max={31} />
            </Form.Item>
          )}
        </Form>
      </Modal>
    </>
  );
}
export function Users() {
  const cache = useQueryClient(),
    { message } = App.useApp();
  const [open, setOpen] = useState(false),
    [form] = Form.useForm();
  const { data = [] } = useQuery<Json[]>({
    queryKey: ["users"],
    queryFn: () => api("/users"),
  });
  return (
    <Card>
      <Button type="primary" onClick={() => setOpen(true)}>
        添加用户
      </Button>
      <Table
        rowKey="id"
        dataSource={data}
        columns={[
          { title: "用户名", dataIndex: "username" },
          {
            title: "管理员",
            render: (_, r) => (
              <Switch
                checked={r.admin}
                onChange={async (admin) => {
                  try {
                    await api("/users/" + r.id, "PUT", { admin });
                    cache.invalidateQueries({ queryKey: ["users"] });
                  } catch (e) {
                    message.error(String(e));
                  }
                }}
              />
            ),
          },
          {
            title: "启用",
            render: (_, r) => (
              <Switch
                checked={r.active}
                onChange={async (active) => {
                  try {
                    await api("/users/" + r.id, "PUT", { active });
                    cache.invalidateQueries({ queryKey: ["users"] });
                  } catch (e) {
                    message.error(String(e));
                  }
                }}
              />
            ),
          },
        ]}
      />
      <Modal
        open={open}
        title="添加用户"
        onCancel={() => setOpen(false)}
        onOk={async () => {
          try {
            await api("/users", "POST", await form.validateFields());
            setOpen(false);
            form.resetFields();
            cache.invalidateQueries({ queryKey: ["users"] });
          } catch (e) {
            message.error(String(e));
          }
        }}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="username"
            label="用户名"
            rules={[{ required: true }]}
          >
            <Input autoComplete="off" />
          </Form.Item>
          <Form.Item
            name="password"
            label="密码"
            rules={[{ required: true, min: 10 }]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item name="admin" label="管理员" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
