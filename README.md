# Agent Harness

可自托管的智能体工作台，使用 **React + TypeScript、Python / FastAPI、MySQL** 构建。连接模型、组合工具、调试任务，再将单个智能体发布为 Web 应用或 Service API。

项目专注于智能体运行与工具化，不包含标注、训练或多智能体工作流。来源于 Fanwu 智能体模块的独立重构，运行时无需原项目。

## 功能

- **智能体与聊天**：模型/知识/提示词/技能绑定，私有会话、附件与上下文压缩。
- **可观察执行**：有界串行 Agent Loop、任务事件/SSE、审批、暂停/继续/取消及历史清理。
- **工具与扩展**：文件和命令工具、HTTP 工具、MCP stdio / Streamable HTTP、声明式插件导入、隔离交互卡片。
- **记忆与计划**：私有跨会话记忆、治理去重、可选 Embedding、一次性和周期计划任务。
- **权重工具化**：上传已有权重，通过独立推理环境部署、注册 OpenAPI 工具并生成技能。
- **单智能体发布**：不可变版本与回滚、独立 Web 聊天、API Key、外部用户隔离、预授权、限流与审计。

## 快速开始（Windows / PowerShell）

需要 Python 3.12、Node.js 22、Docker Engine / Docker Desktop（含 Compose）。以下命令在**克隆后的项目根目录**执行。不要在已有数据库的机器上重复创建占用相同端口的数据库。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
npm.cmd ci --prefix frontend
Copy-Item .env.example .env
docker compose up -d --wait mysql redis
Push-Location backend
..\.venv\Scripts\python.exe -m app.cli init
Pop-Location
.\.venv\Scripts\python.exe scripts\dev.py
```

打开 **http://127.0.0.1:5173**，使用 `admin` 和初始化时输入的密码登录。密码至少 10 个字符，没有通用默认密码。`init` 执行迁移并创建内置模板，不覆盖已有账号密码。

若需随机密码，在初始化命令末尾加 `--generate-password`；新账号凭据保存至 `data/initial-admin.txt`。安全保存后可删除该文件，**不要删除 `data/master.key`**。

示例数据库密码仅供本机开发。对外部署前必须修改密码和安全配置；修改已有数据卷的 Compose 密码变量不会自动修改数据库账户密码。不要覆盖已有 `.env`。

### 第一次使用

1. 配置中心 → 模型：添加模型接口并测试连接。
2. 按需添加知识、提示词、技能或 MCP 工具。
3. 创建智能体，绑定资源，设置专用工作目录、权限与运行预算。
4. 开始对话，在任务中心检查执行事件和审批。
5. 分享时进入发布管理，核对工具授权并主动开启 Web 渠道，参见[发布指南](docs/PUBLICATION.md)。

Ollama Embedding 可填写 `http://localhost:11434` 或 `http://localhost:11434/v1`，模型名称须与本机已安装名称一致，例如 `bge-m3:latest`。

### 日常启动

```powershell
docker compose up -d mysql redis
.\.venv\Scripts\python.exe scripts\dev.py
```

在启动终端按 Ctrl+C 停止本次启动的服务。启动器不会结束已有进程；端口占用时回到原终端停止旧实例。推理部署请在页面中检查/停止。不要执行 `docker compose down -v`，它会删除数据卷。

## 组件与端口

| 组件 | 默认本机端口 | 说明 |
|---|---|---|
| Web | 5173 | 开发前端及 API 代理 |
| FastAPI | 8010 | 控制台、公开应用与 Service API |
| MCP UI host | 8011 | 独立 origin 交互卡片 |
| MySQL | 13310 | 持久业务数据 |
| Redis | 16379 | 公开新任务限流，不可用时拒绝公开新任务 |
| Worker | 无 | 执行、调度、推理进程管理 |

## 文档与目录

- [架构](ARCHITECTURE.md)
- [运维与推理接入](docs/OPERATIONS.md)
- [发布与 Service API](docs/PUBLICATION.md)
- [贡献与测试](CONTRIBUTING.md)
- [安全说明](SECURITY.md)
- [GitHub 发布步骤](docs/RELEASING.md)
- [第三方说明](THIRD_PARTY_NOTICES.md)

```text
backend/         FastAPI、Worker、数据库迁移与测试
frontend/        React 工作台与公开聊天页
tool-runtimes/   独立推理服务模板
scripts/         开发启动器与验证脚本
docs/            使用与维护文档
data/            本机数据和密钥（不提交）
```

## 当前边界

- Windows 是当前主要验证环境；Linux、不同 GPU/CUDA 组合需另行验证。
- 当前为串行单智能体，不含并行工具、子代理或工作流画布。
- SSE 提供实时任务事件和完整最终回答，不是模型逐 token 输出。
- 知识内容直接进入上下文，不是完整的文档向量 RAG 系统。
- MCP Apps 提供隔离和可信地图兼容模式，不承诺兼容任意扩展，不支持页面任意调用业务工具。
- 权重、脚本、命令及 stdio MCP 可能执行本机代码。权限策略不是操作系统沙箱，面向不可信用户需要额外隔离；不提供开箱即用的生产安全保证。

## 许可证

许可证待维护者确认；添加根目录 `LICENSE` 后再正式开放分发授权。第三方组件保留各自许可证，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
