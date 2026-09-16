/** @input Shared catalogs and deployment API. @output Resource and model-tool administration. @position Configuration UI. @doc-sync Update INDEX.md on changes. */
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  App,
  Alert,
  Button,
  Card,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  Upload,
  Popconfirm,
} from "antd";
import { PlusOutlined, UploadOutlined } from "@ant-design/icons";
import { api, list, Resource, Json, labels } from "./api";
import { useUser } from "./App";
import { Users } from "./Governance";
const names: Record<string, string> = {
  model: "模型",
  knowledge: "知识库",
  prompt: "提示词",
  skill: "技能",
  tool: "已注册工具",
  mcp: "MCP 服务",
  plugin: "插件",
  template: "推理模板",
};
const examples: Record<string, Json> = {
  model: {
    provider: "openai-compatible",
    endpoint: "https://api.deepseek.com/v1",
    model: "deepseek-chat",
    context_window: 32768,
    max_output_tokens: 2048,
    temperature: 0.2,
  },
  tool: {
    source: "http",
    endpoint: "http://127.0.0.1:9000",
    path: "/detect",
    input_schema: {
      type: "object",
      properties: { image_path: { type: "string" } },
      required: ["image_path"],
    },
    operation_class: "MUTATE_SCOPED",
    idempotent: false,
  },
  mcp: {
    transport: "stdio",
    command: "npx",
    args: ["-y", "@modelcontextprotocol/server-filesystem", "D:/work"],
    env: {},
  },
  template: { runtime: "custom", python: "", script: "" },
};
export function Configuration() {
  const user = useUser();
  return (
    <>
      <div className="page-title">
        <div>
          <span className="eyebrow">CONFIGURATION</span>
          <h1>连接模型，扩展能力</h1>
          <p>共享资源由管理员维护，上传权重即可申请独立工具部署。</p>
        </div>
      </div>
      <Tabs
        defaultActiveKey="model"
        items={[
          ...Object.entries(names)
            .filter(
              ([k]) => user.admin || !["mcp", "plugin", "template"].includes(k),
            )
            .map(([key, label]) => ({
              key,
              label,
              children: <Catalog kind={key} />,
            })),
          {
            key: "deployments",
            label: "权重与部署",
            children: <Deployments />,
          },
          ...(user.admin
            ? [{ key: "users", label: "用户", children: <Users /> }]
            : []),
        ]}
      />
    </>
  );
}
function Catalog({ kind }: { kind: string }) {
  const user = useUser(),
    cache = useQueryClient(),
    { message, modal } = App.useApp();
  const [edit, setEdit] = useState<Resource | null | undefined>(),
    [form] = Form.useForm();
  const [saving, setSaving] = useState(false);
  const { data = [], isLoading } = useQuery({
    queryKey: ["catalog", kind],
    queryFn: () => list(kind),
  });
  const refresh = () => cache.invalidateQueries();
  const open = (r: Resource | null) => {
    form.resetFields();
    form.setFieldsValue({
      ...r,
      name: r?.name || "",
      content: r?.content || "",
      enabled: r?.enabled ?? true,
      config_text: JSON.stringify(r?.config || examples[kind] || {}, null, 2),
      api_key: undefined,
    });
    setEdit(r);
  };
  const action = async (path: string, body: Json = {}) => {
    try {
      const result = await api(path, "POST", body);
      refresh();
      modal.info({
        title: "操作结果",
        width: 720,
        content: <pre>{JSON.stringify(result, null, 2)}</pre>,
      });
    } catch (e) {
      message.error(String(e));
    }
  };
  const save = async () => {
    setSaving(true);
    try {
      const v = await form.validateFields();
      await api(
        "/resources/" + kind + (edit ? "/" + edit.id : ""),
        edit ? "PUT" : "POST",
        {
          name: v.name,
          description: v.description || "",
          content: v.content || "",
          enabled: v.enabled,
          api_key: v.api_key || undefined,
          config: JSON.parse(v.config_text || "{}"),
          version: edit?.version,
        },
      );
      setEdit(undefined);
      refresh();
      message.success("资源已保存");
    } catch (e) {
      message.error(String(e));
    } finally {
      setSaving(false);
    }
  };
  return (
    <Card>
      <div className="section-toolbar">
        <div>
          <h3>{names[kind]}资源</h3>
          <span className="muted">
            {kind === "knowledge"
              ? "知识内容以文本注入上下文；不包含原平台训练与标注流程。"
              : "这些资源由平台统一管理，智能体通过绑定使用。"}
          </span>
        </div>
        {user.admin && (
          <Space>
            {kind === "plugin" ? (
              <Upload
                showUploadList={false}
                accept=".zip"
                beforeUpload={(file) => {
                  const fd = new FormData();
                  fd.append("file", file);
                  api("/extensions/preflight", "POST", fd)
                    .then(
                      (result) =>
                        void modal.confirm({
                          title: "安装此插件？默认禁用，不执行安装钩子。",
                          width: 640,
                          content: <pre>{JSON.stringify(result, null, 2)}</pre>,
                          onOk: async () => {
                            await api("/extensions/install", "POST", fd);
                            refresh();
                          },
                        }),
                    )
                    .catch((e) => message.error(String(e)));
                  return false;
                }}
              >
                <Button icon={<UploadOutlined />}>导入 ZIP</Button>
              </Upload>
            ) : (
              <Button
                type="primary"
                icon={<PlusOutlined />}
                onClick={() => open(null)}
              >
                添加{names[kind]}
              </Button>
            )}
            {kind === "mcp" && (
              <Button
                onClick={() => {
                  let raw = "";
                  modal.confirm({
                    title: "导入 mcpServers JSON",
                    width: 680,
                    content: (
                      <Input.TextArea
                        rows={12}
                        onChange={(e) => (raw = e.target.value)}
                      />
                    ),
                    onOk: async () => {
                      await api("/mcp/import", "POST", JSON.parse(raw));
                      refresh();
                    },
                  });
                }}
              >
                批量导入
              </Button>
            )}
          </Space>
        )}
      </div>
      <Table
        rowKey="id"
        loading={isLoading}
        dataSource={data}
        columns={[
          {
            title: "名称",
            dataIndex: "name",
            render: (v, r) => (
              <>
                <strong>{v}</strong>
                <div className="muted">{r.description}</div>
              </>
            ),
          },
          {
            title: "状态",
            dataIndex: "enabled",
            render: (v) => (
              <Tag color={v ? "green" : "default"}>
                {v ? "已启用" : "已停用"}
              </Tag>
            ),
          },
          { title: "版本", dataIndex: "version", width: 80 },
          {
            title: "操作",
            width: 330,
            render: (_, r) => (
              <Space wrap>
                {user.admin ? (
                  <>
                    {kind !== "plugin" && (
                      <Button size="small" onClick={() => open(r)}>
                        编辑
                      </Button>
                    )}
                    {kind === "model" && (
                      <Button
                        size="small"
                        onClick={() => action("/models/" + r.id + "/test")}
                      >
                        测试
                      </Button>
                    )}
                    {kind === "mcp" && (
                      <Button
                        size="small"
                        onClick={() => action("/mcp/" + r.id + "/discover")}
                      >
                        发现工具
                      </Button>
                    )}
                    {["mcp", "plugin"].includes(kind) && (
                      <Button
                        size="small"
                        onClick={() =>
                          action("/extensions/" + r.id + "/status", {
                            enabled: !r.enabled,
                          })
                        }
                      >
                        {r.enabled ? "禁用" : "启用"}
                      </Button>
                    )}
                    <Popconfirm
                      title="确认删除资源及其扩展子资源？已有任务快照不变。"
                      onConfirm={async () => {
                        try {
                          await api(
                            "/resources/" + kind + "/" + r.id,
                            "DELETE",
                          );
                          refresh();
                        } catch (e) {
                          message.error(String(e));
                        }
                      }}
                    >
                      <Button size="small" danger>
                        删除
                      </Button>
                    </Popconfirm>
                  </>
                ) : (
                  <Button
                    size="small"
                    onClick={() =>
                      modal.info({
                        title: r.name,
                        width: 700,
                        content: (
                          <pre>
                            {r.content || JSON.stringify(r.config, null, 2)}
                          </pre>
                        ),
                      })
                    }
                  >
                    查看
                  </Button>
                )}
              </Space>
            ),
          },
        ]}
      />
      <Modal
        open={edit !== undefined}
        title={(edit ? "编辑" : "添加") + names[kind]}
        width={760}
        onCancel={() => setEdit(undefined)}
        onOk={save}
        confirmLoading={saving}
      >
        <Form form={form} layout="vertical">
          <div className="form-grid">
            <Form.Item name="name" label="名称" rules={[{ required: true }]}>
              <Input />
            </Form.Item>
            <Form.Item name="enabled" label="启用" valuePropName="checked">
              <Switch />
            </Form.Item>
          </div>
          <Form.Item name="description" label="说明">
            <Input />
          </Form.Item>
          {["knowledge", "prompt", "skill"].includes(kind) && (
            <>
              <Upload
                accept=".md,.txt"
                showUploadList={false}
                beforeUpload={(file) => {
                  file
                    .text()
                    .then((content) => form.setFieldValue("content", content));
                  return false;
                }}
              >
                <Button>读取文本文件</Button>
              </Upload>
              <Form.Item
                name="content"
                label="内容"
                rules={[{ required: true }]}
              >
                <Input.TextArea rows={14} />
              </Form.Item>
            </>
          )}
          {!["knowledge", "prompt", "skill"].includes(kind) && (
            <>
              <Alert
                type="info"
                message={
                  kind === "template"
                    ? "Python 解释器与脚本路径均为服务器绝对路径。自定义脚本须遵循推理运行协议；脚本上传后可从上传记录取得路径。"
                    : kind === "mcp"
                      ? '支持直接填写 transport/url（或 command/args），也兼容只含一个服务的完整 mcpServers JSON；多个服务请使用页面上的“导入 mcpServers JSON”。支持 stdio 和 Streamable HTTP，敏感 env / headers 使用 ${secret:NAME} 引用。'
                      : "高级配置采用 JSON，保留完整参数能力。密钥单独加密保存，不放在 JSON 中。"
                }
                showIcon
              />
              <Form.Item
                name="config_text"
                label="配置 JSON"
                rules={[
                  {
                    validator: (_, v) => {
                      try {
                        JSON.parse(v);
                        return Promise.resolve();
                      } catch {
                        return Promise.reject("请输入有效 JSON");
                      }
                    },
                  },
                ]}
              >
                <Input.TextArea className="code-input" rows={15} />
              </Form.Item>
              {kind !== "mcp" && (
                <Form.Item name="api_key" label="API 密钥（留空保留原值）">
                  <Input.Password autoComplete="new-password" />
                </Form.Item>
              )}
            </>
          )}
        </Form>
      </Modal>
    </Card>
  );
}
function Deployments() {
  const user = useUser(),
    cache = useQueryClient(),
    { message, modal } = App.useApp();
  const [open, setOpen] = useState(false),
    [form] = Form.useForm();
  const { data = [] } = useQuery<Json[]>({
    queryKey: ["deployments"],
    queryFn: () => api("/deployments"),
    refetchInterval: 3000,
  });
  const { data: artifacts = [] } = useQuery<Json[]>({
    queryKey: ["artifacts"],
    queryFn: () => api("/artifacts"),
  });
  const { data: templates = [] } = useQuery({
    queryKey: ["templates"],
    queryFn: () => list("template"),
  });
  const { data: models = [] } = useQuery({
    queryKey: ["models"],
    queryFn: () => list("model"),
  });
  const refresh = () => cache.invalidateQueries();
  const act = async (id: string, action: string, body: Json = {}) => {
    try {
      const result = await api(
        "/deployments/" + id + "/" + action,
        "POST",
        body,
      );
      refresh();
      if (["test", "register", "skill"].includes(action))
        modal.info({
          title: "操作结果",
          width: 760,
          content: (
            <>
              <pre>{JSON.stringify(result, null, 2)}</pre>
              {result.artifact_id && (
                <a
                  href={"/api/v1/artifacts/" + result.artifact_id + "/file"}
                  target="_blank"
                  rel="noreferrer"
                >
                  下载生成结果
                </a>
              )}
              {action === "skill" && (
                <Button
                  onClick={async () => {
                    await api("/resources/skill", "POST", {
                      name: "部署工具技能",
                      content: result.content,
                    });
                    refresh();
                    message.success("已保存为技能，请绑定到智能体");
                  }}
                >
                  保存为技能
                </Button>
              )}
            </>
          ),
        });
    } catch (e) {
      message.error(String(e));
    }
  };
  const upload = (kind: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    api("/uploads/" + kind, "POST", fd)
      .then(() => {
        refresh();
        message.success("上传完成");
      })
      .catch((e) => message.error(String(e)));
    return false;
  };
  return (
    <>
      <Card>
        <div className="section-toolbar">
          <div>
            <h3>模型权重 → 推理部署 → 工具 → 技能</h3>
            <p className="muted">
              无需标注、训练项目。上传已有权重，选择预设脚本运行。
            </p>
          </div>
          <Space>
            <Upload
              showUploadList={false}
              beforeUpload={(file) => upload("weight", file)}
            >
              <Button icon={<UploadOutlined />}>上传权重</Button>
            </Upload>
            {user.admin && (
              <Upload
                accept=".py"
                showUploadList={false}
                beforeUpload={(file) => upload("script", file)}
              >
                <Button>上传脚本</Button>
              </Upload>
            )}
            <Button
              type="primary"
              onClick={() => {
                form.resetFields();
                setOpen(true);
              }}
            >
              新建部署
            </Button>
          </Space>
        </div>
        <Alert
          type="warning"
          showIcon
          message="权重和 Python 脚本可能执行代码，仅接受可信来源。普通用户的部署需管理员审核。GPU 依赖请安装在独立推理环境。"
        />
        <Table
          rowKey="id"
          dataSource={data}
          columns={[
            { title: "部署", dataIndex: "name" },
            {
              title: "状态",
              dataIndex: "status",
              render: (s, r) => (
                <>
                  <Tag>{labels[s] || s}</Tag>
                  {r.error && <div className="error-text">{r.error}</div>}
                </>
              ),
            },
            {
              title: "操作",
              render: (_, r) => (
                <Space wrap>
                  {r.status === "PENDING" && user.admin && (
                    <Button size="small" onClick={() => act(r.id, "approve")}>
                      审核启动
                    </Button>
                  )}
                  {["STOPPED", "FAILED"].includes(r.status) && (
                    <Button size="small" onClick={() => act(r.id, "start")}>
                      启动
                    </Button>
                  )}
                  {["RUNNING", "STARTING", "QUEUED"].includes(r.status) && (
                    <Button size="small" onClick={() => act(r.id, "stop")}>
                      停止
                    </Button>
                  )}
                  <Button
                    size="small"
                    onClick={async () => {
                      try {
                        const log = await api("/deployments/" + r.id + "/logs");
                        modal.info({
                          title: "部署日志",
                          width: 800,
                          content: <pre>{log.content || "暂无日志"}</pre>,
                        });
                      } catch (e) {
                        message.error(String(e));
                      }
                    }}
                  >
                    日志
                  </Button>
                  {r.status === "RUNNING" && (
                    <>
                      <Button
                        size="small"
                        onClick={() => {
                          let path = "/detect",
                            args = "{}",
                            artifact = "";
                          modal.confirm({
                            title: "接口试运行",
                            width: 640,
                            content: (
                              <Space
                                direction="vertical"
                                style={{ width: "100%" }}
                              >
                                <Input
                                  defaultValue={path}
                                  onChange={(e) => (path = e.target.value)}
                                />
                                <Select
                                  style={{ width: "100%" }}
                                  allowClear
                                  placeholder="可选：使用已上传图片"
                                  options={artifacts
                                    .filter((a) => a.kind === "attachment")
                                    .map((a) => ({
                                      label: a.name,
                                      value: a.id,
                                    }))}
                                  onChange={(v) => (artifact = v)}
                                />
                                <Upload
                                  showUploadList={false}
                                  beforeUpload={(file) =>
                                    upload("attachment", file)
                                  }
                                >
                                  <Button>上传测试素材</Button>
                                </Upload>
                                <Input.TextArea
                                  rows={8}
                                  defaultValue={args}
                                  onChange={(e) => (args = e.target.value)}
                                />
                              </Space>
                            ),
                            onOk: () =>
                              act(r.id, "test", {
                                path,
                                arguments: JSON.parse(args),
                                artifact_id: artifact || undefined,
                              }),
                          });
                        }}
                      >
                        试运行
                      </Button>
                      {user.admin && (
                        <>
                          <Button
                            size="small"
                            onClick={() => {
                              let path = "/detect";
                              modal.confirm({
                                title: "从 OpenAPI 注册工具",
                                content: (
                                  <Input
                                    defaultValue={path}
                                    onChange={(e) => (path = e.target.value)}
                                  />
                                ),
                                onOk: () => act(r.id, "register", { path }),
                              });
                            }}
                          >
                            注册工具
                          </Button>
                          <Button
                            size="small"
                            onClick={() => {
                              let model = "";
                              modal.confirm({
                                title: "选择模型生成 Skill",
                                content: (
                                  <Select
                                    style={{ width: "100%" }}
                                    options={models.map((m) => ({
                                      label: m.name,
                                      value: m.id,
                                    }))}
                                    onChange={(v) => (model = v)}
                                  />
                                ),
                                onOk: () =>
                                  act(r.id, "skill", { model_id: model }),
                              });
                            }}
                          >
                            生成技能
                          </Button>
                        </>
                      )}
                    </>
                  )}
                </Space>
              ),
            },
          ]}
        />
      </Card>
      <Card className="spaced" title="我的上传记录">
        <Table
          rowKey="id"
          dataSource={artifacts}
          columns={[
            { title: "文件", dataIndex: "name" },
            { title: "类型", dataIndex: "kind" },
            { title: "服务器路径", dataIndex: "path", ellipsis: true },
            {
              title: "大小",
              dataIndex: "size",
              render: (v) => (v / 1048576).toFixed(2) + " MB",
            },
          ]}
        />
      </Card>
      <Modal
        open={open}
        title="新建推理部署"
        onCancel={() => setOpen(false)}
        onOk={async () => {
          try {
            const v = await form.validateFields();
            await api("/deployments", "POST", v);
            setOpen(false);
            refresh();
          } catch (e) {
            message.error(String(e));
          }
        }}
      >
        <Form form={form} layout="vertical" initialValues={{ device: "cpu" }}>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item
            name="template_id"
            label="推理模板"
            rules={[{ required: true }]}
          >
            <Select
              options={templates
                .filter((t) => t.enabled)
                .map((t) => ({ label: t.name, value: t.id }))}
            />
          </Form.Item>
          <Form.Item
            name="weight_id"
            label="权重文件（语音 / 图片 API 模板可不选）"
          >
            <Select
              allowClear
              options={artifacts
                .filter((a) => a.kind === "weight")
                .map((a) => ({ label: a.name, value: a.id }))}
            />
          </Form.Item>
          <Form.Item name="device" label="设备">
            <Input placeholder="cpu 或 0" />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
