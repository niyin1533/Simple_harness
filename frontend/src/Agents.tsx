/** @input Shared resources. @output Four-step agent authoring. @position Agent management UI. @doc-sync Update INDEX.md on changes. */
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  App,
  Button,
  Card,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Steps,
  Switch,
  Tag,
  Space,
  Popconfirm,
  Alert,
  Descriptions,
} from "antd";
import {
  PlusOutlined,
  RobotOutlined,
  ArrowRightOutlined,
  EditOutlined,
} from "@ant-design/icons";
import { api, list, Resource } from "./api";
import { useUser } from "./App";
export function Agents() {
  const { data = [] } = useQuery({
    queryKey: ["agent"],
    queryFn: () => list("agent"),
  });
  const [editing, setEditing] = useState<Resource | null | undefined>();
  const navigate = useNavigate();
  const user = useUser();
  const cache = useQueryClient();
  const { message } = App.useApp();
  return (
    <>
      <div className="page-title">
        <div>
          <span className="eyebrow">AGENTS</span>
          <h1>你的智能体团队</h1>
          <p>为不同任务配置模型、工具与记忆，随时开始协作。</p>
        </div>
        {user.admin && (
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setEditing(null)}
          >
            创建智能体
          </Button>
        )}
      </div>
      {!data.length ? (
        <div className="empty-card">
          <Empty description="还没有智能体，从一个清晰的任务开始" />
          {user.admin && (
            <Button type="primary" onClick={() => setEditing(null)}>
              创建第一个智能体
            </Button>
          )}
        </div>
      ) : (
        <div className="agent-grid">
          {data.map((agent) => (
            <Card key={agent.id} className="agent-card">
              <div className="agent-card-top">
                <div className="agent-avatar">
                  <RobotOutlined />
                </div>
                <Tag color={agent.enabled ? "green" : "default"}>
                  {agent.enabled ? "已启用" : "已停用"}
                </Tag>
              </div>
              <h2>{agent.name}</h2>
              <p>{agent.description || "一个专注于完成任务的智能体"}</p>
              <div className="agent-meta">
                <Tag>{agent.config.tool_ids?.length || 0} 个工具</Tag>
                <Tag>
                  {agent.config.memory_enabled ? "已开启记忆" : "独立对话"}
                </Tag>
                <Tag>v{agent.version}</Tag>
              </div>
              <div className="card-footer">
                <Button
                  type="text"
                  icon={<ArrowRightOutlined />}
                  disabled={!agent.enabled}
                  onClick={() => navigate("/chat?agent=" + agent.id)}
                >
                  开始对话
                </Button>
                {user.admin && (
                  <Space>
                    <Button
                      type="text"
                      aria-label="编辑智能体"
                      icon={<EditOutlined />}
                      onClick={() => setEditing(agent)}
                    />
                    <Popconfirm
                      title="删除此智能体？已有任务保留快照。"
                      onConfirm={async () => {
                        try {
                          await api("/resources/agent/" + agent.id, "DELETE");
                          cache.invalidateQueries({ queryKey: ["agent"] });
                        } catch (e) {
                          message.error(String(e));
                        }
                      }}
                    >
                      <Button type="text" danger>
                        删除
                      </Button>
                    </Popconfirm>
                  </Space>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}
      {editing !== undefined && (
        <Wizard initial={editing} close={() => setEditing(undefined)} />
      )}
    </>
  );
}
function Wizard({
  initial,
  close,
}: {
  initial: Resource | null;
  close: () => void;
}) {
  const [form] = Form.useForm();
  const [step, setStep] = useState(0),
    [saving, setSaving] = useState(false);
  const { message, modal } = App.useApp();
  const cache = useQueryClient();
  const { data: resources = {} } = useQuery({
    queryKey: ["wizard-resources"],
    queryFn: async () =>
      Object.fromEntries(
        await Promise.all(
          ["model", "knowledge", "skill", "tool", "prompt"].map(async (k) => [
            k,
            await list(k),
          ]),
        ),
      ),
  });
  const defaults = {
    model_id: "",
    system_prompt:
      "你是一个严谨、有帮助的智能体。根据用户目标调用工具，依据真实结果回答。",
    knowledge_ids: [],
    skill_ids: [],
    tool_ids: [],
    prompt_ids: [],
    memory_enabled: false,
    memory_scopes: ["user", "agent"],
    loop_enabled: true,
    permission_preset: "workspace-write",
    workspace_path: "",
    limits: {
      max_steps: 12,
      max_tool_calls: 20,
      max_run_seconds: 600,
      max_consecutive_failures: 3,
      model_retries: 2,
      tool_retries: 1,
    },
  };
  const options = (kind: string) =>
    (resources[kind] || [])
      .filter((r: Resource) => r.enabled)
      .map((r: Resource) => ({ label: r.name, value: r.id }));
  const dismiss = () => {
    if (form.isFieldsTouched())
      modal.confirm({ title: "放弃未保存的配置？", onOk: close });
    else close();
  };
  const next = async () => {
    try {
      await form.validateFields(
        step === 0 ? ["name", "system_prompt"] : step === 1 ? ["model_id"] : [],
      );
      setStep(step + 1);
    } catch {}
  };
  const save = async () => {
    setSaving(true);
    try {
      const v = await form.validateFields();
      const { name, description, ...config } = v;
      await api(
        "/resources/agent" + (initial ? "/" + initial.id : ""),
        initial ? "PUT" : "POST",
        {
          name,
          description: description || "",
          config,
          enabled: initial?.enabled ?? true,
          version: initial?.version,
        },
      );
      cache.invalidateQueries({ queryKey: ["agent"] });
      message.success("智能体已保存");
      close();
    } catch (e) {
      message.error(String(e));
    } finally {
      setSaving(false);
    }
  };
  return (
    <Modal
      open
      title={initial ? "编辑智能体" : "创建智能体"}
      width={860}
      onCancel={dismiss}
      footer={
        <Space>
          <Button onClick={dismiss}>取消</Button>
          {step > 0 && (
            <Button onClick={() => setStep(step - 1)}>上一步</Button>
          )}
          {step < 3 ? (
            <Button type="primary" onClick={next}>
              下一步
            </Button>
          ) : (
            <Button type="primary" loading={saving} onClick={save}>
              保存智能体
            </Button>
          )}
        </Space>
      }
    >
      <Steps
        className="wizard-steps"
        current={step}
        items={["基础信息", "模型与能力", "记忆", "运行策略"].map((title) => ({
          title,
        }))}
      />
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          ...defaults,
          ...initial?.config,
          name: initial?.name,
          description: initial?.description,
        }}
      >
        <div hidden={step !== 0}>
          <Form.Item
            name="name"
            label="智能体名称"
            rules={[{ required: true, message: "请输入名称" }]}
          >
            <Input placeholder="例如：代码分析助手" />
          </Form.Item>
          <Form.Item name="description" label="说明">
            <Input.TextArea rows={2} placeholder="告诉用户这个智能体擅长什么" />
          </Form.Item>
          <Form.Item
            name="system_prompt"
            label="系统提示词"
            rules={[{ required: true }]}
          >
            <Input.TextArea rows={7} />
          </Form.Item>
        </div>
        <div hidden={step !== 1}>
          <Form.Item
            name="model_id"
            label="基础模型"
            rules={[{ required: true, message: "请选择基础模型" }]}
          >
            <Select options={options("model")} placeholder="选择已配置的模型" />
          </Form.Item>
          {[
            ["knowledge_ids", "知识库", "knowledge"],
            ["prompt_ids", "提示词模板", "prompt"],
            ["skill_ids", "技能", "skill"],
            ["tool_ids", "业务工具 / MCP 工具", "tool"],
          ].map(([name, label, kind]) => (
            <Form.Item key={name} name={name} label={label}>
              <Select
                mode="multiple"
                options={options(kind)}
                placeholder="按需选择"
              />
            </Form.Item>
          ))}
          <Alert
            type="info"
            showIcon
            message="基础文件工具、任务状态与上下文能力由 Harness 自动提供。"
          />
        </div>
        <div hidden={step !== 2}>
          <h3>让智能体记住有用的信息</h3>
          <p className="muted">长期记忆按当前用户隔离，不会与其他用户共享。</p>
          <Form.Item
            name="memory_enabled"
            label="跨会话记忆"
            valuePropName="checked"
          >
            <Switch />
          </Form.Item>
          <Form.Item name="memory_scopes" label="召回范围">
            <Select
              mode="multiple"
              options={[
                { value: "user", label: "用户通用记忆" },
                { value: "agent", label: "当前智能体记忆" },
              ]}
            />
          </Form.Item>
        </div>
        <div hidden={step !== 3}>
          <Form.Item name="permission_preset" label="权限预设">
            <Select
              options={[
                { value: "read-only", label: "只读" },
                { value: "workspace-write", label: "工作区可写 · 写入需确认" },
                {
                  value: "danger-full-access",
                  label: "管理员全权限 · 高影响操作需确认",
                },
              ]}
            />
          </Form.Item>
          <Form.Item name="workspace_path" label="服务器工作目录">
            <Input placeholder="例如 D:\work 或 /srv/work；留空时文件和命令工具不可用" />
          </Form.Item>
          <Form.Item
            name="loop_enabled"
            label="启用工具执行循环"
            valuePropName="checked"
          >
            <Switch />
          </Form.Item>
          <div className="form-grid">
            {[
              ["max_steps", "最大步骤", 1, 50],
              ["max_tool_calls", "工具调用上限", 1, 100],
              ["max_run_seconds", "运行时限（秒）", 30, 3600],
              ["max_consecutive_failures", "连续失败上限", 1, 5],
              ["model_retries", "模型重试", 0, 3],
              ["tool_retries", "幂等工具重试", 0, 2],
            ].map(([name, label, min, max]) => (
              <Form.Item
                key={name}
                name={["limits", name as string]}
                label={label}
              >
                <InputNumber
                  min={Number(min)}
                  max={Number(max)}
                  style={{ width: "100%" }}
                />
              </Form.Item>
            ))}
          </div>
          <Form.Item noStyle shouldUpdate>
            {() => (
              <Descriptions
                size="small"
                column={2}
                title="配置摘要"
                items={[
                  {
                    key: "name",
                    label: "名称",
                    children: form.getFieldValue("name"),
                  },
                  {
                    key: "tools",
                    label: "业务工具",
                    children: (form.getFieldValue("tool_ids") || []).length,
                  },
                  {
                    key: "memory",
                    label: "记忆",
                    children: form.getFieldValue("memory_enabled")
                      ? "开启"
                      : "关闭",
                  },
                ]}
              />
            )}
          </Form.Item>
        </div>
      </Form>
    </Modal>
  );
}
