# Agent Harness

从 Fanwu 智能体部分独立重构的 Web 平台：React + Python/FastAPI + MySQL。没有标注、训练任务或原 Java 服务依赖。

## 当前可用

- 共享模型、文本知识、提示词、Skill、HTTP 工具、MCP、插件与推理模板。
- 四步智能体配置、基础模型直聊、私有会话、附件和历史。
- 有界串行 Agent Loop、任务快照、持久事件/SSE、暂停/继续/取消、单次审批和未知执行保护。
- 权重/脚本上传、部署审核、推理进程、OpenAPI 工具注册、试运行、Skill 生成。
- 私有记忆、可选 Embedding、自动提取、人工治理与上下文压缩。
- 一次、每日、每周、每月和 Cron 计划任务。
- MCP stdio / Streamable HTTP、安全 ZIP 声明投影、隔离 HTML 展示。
- 单智能体不可变发布、独立 Web / Service API、外部记忆隔离、预授权和限流，见 [发布指南](docs/PUBLICATION.md)。

## 当前机器启动

已安装 `.venv` 与前端依赖。独立 MySQL 容器是 `agent-harness-db`，端口 `13310`；没有使用或修改 Fanwu 的 `3307` 数据库。

```powershell
cd D:\nrts\agent
docker start agent-harness-db
docker compose up -d redis
.\.venv\Scripts\python.exe scripts\dev.py
```

访问 **http://127.0.0.1:5173**。管理员是 `admin`，随机初始密码保存在 `data/initial-admin.txt`，不写入代码。请安全保存后删除该凭据文件，并保护 `data/master.key`。

启动前确认 5173、8010、8011 未被另一组本项目进程占用。启动器不会主动结束其他进程。Ctrl+C 停止它创建的进程；独立推理部署从页面停止。

启动器现在先检查端口和 Node/Vite，完成 API（含数据库）、UI host 和前端就绪检测后才显示 `Ready`。日志同时带服务名前缀显示在终端，并保存在 `data/logs/dev-时间-PID/`。服务退出会明确显示名称、退出码与日志位置。Windows 前端直接通过 Node 启动 Vite，并强制使用 5173，不会静默换端口。

```powershell
# 只检查端口与依赖，不启动服务
.\.venv\Scripts\python.exe scripts\dev.py --check
# 实际启动并检查就绪，随后自动停止本次创建的服务
.\.venv\Scripts\python.exe scripts\dev.py --smoke-test
```

若提示 `Ports already occupied`，先尝试访问现有实例；需要重启时，在原启动窗口按 Ctrl+C。启动器不会自动杀掉占用端口的进程。`--check` 不检查 MySQL；数据库连通性在实际启动的健康检查中验证。

## 从空环境安装

使用 Python 3.12、Node.js 20+ 和 MySQL 8。仅对本项目执行：

```powershell
cd D:\nrts\agent
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
cd frontend
npm ci
cd ..
docker compose up -d mysql
cd backend
..\.venv\Scripts\python.exe -m app.cli init
cd ..
.\.venv\Scripts\python.exe scripts\dev.py
```

`init` 输入管理员密码、执行迁移并创建内置模板，不重置已有账户。`--generate-password` 可为新管理员生成凭据文件。当前机器已有独立数据库容器，不要再同时运行 compose 抢占端口。生产通过 `.env` 配置强密码、HTTPS 和 origin，不使用开发密码。

## 第一次使用

1. 配置中心 → 模型：添加 OpenAI-compatible 或 Ollama 模型；密钥填独立字段，执行连接测试。
2. 添加需要的知识、提示词、Skill。知识内容直接注入上下文，不是文档向量检索系统。
3. 智能体 → 创建：绑定模型/资源，设置记忆、工作目录、权限和预算。
4. 开始聊天，通过任务中心查看工具参数、事件和审批。
5. 小模型先上传权重，管理员配置独立推理环境；部署、测试、注册工具，再绑定到智能体。

## 验证

### YOLO 推理环境

内置 YOLO 模板默认使用 `D:\nrts\agent\.venv-yolo`，不复用平台后端或 Fanwu 环境。首次部署前执行：

```powershell
cd D:\nrts\agent
.\.venv\Scripts\python.exe -m venv .venv-yolo
.\.venv-yolo\Scripts\python.exe -m pip install -r tool-runtimes\requirements-yolo.txt
```

模板显式配置的 Python 路径优先。CPU 已验证；CUDA 需按硬件安装匹配的 PyTorch。缺包会在启动前给出解释器和依赖提示。

### 回归命令

```powershell
cd D:\nrts\agent\backend
..\.venv\Scripts\python.exe -m pytest -q
..\.venv\Scripts\python.exe -m alembic check
cd ..\frontend
npm run build
```

MySQL 测试创建随机 UUID 记录并清理；运行时请暂停 Worker，防止它领取测试任务。MCP 测试使用短生命周期子进程与本地 18992 端口。

浏览器测试需要 API、Worker、前端和 `python -m uvicorn tests.fixture_model:app --host 127.0.0.1 --port 18991`。在 frontend 执行 `npm run test:e2e`，使用本机 Edge；完成后在 backend 执行 `python -m tests.cleanup_e2e` 清理标记数据。测试模型是确定性夹具，不代表真实模型效果。

## 验收边界

这是可运行实现，不能描述为已通过生产验收或全部细节无差异复刻。

- 已验证：后端单元/MySQL/MCP/部署测试、前端构建、浏览器登录/记忆/聊天事件链路。
- 2026-09-16 已真实验证：DeepSeek 治理、BGE-M3、地图后台任务和浏览器渲染、用户 YOLO11s 权重 CPU 检测。详见 `docs/FIX_VERIFICATION_2026-09-16.md`。
- 尚需真实验证：YOLOv5 权重、CUDA、MiniMax 付费调用和 Linux 部署。
- MCP Apps 默认使用隔离展示；可信 Cesium 地图可在任务详情点击“地图兼容模式”显式确认，使用独立显示域内的同源存储、本地 Cesium/Worker 与声明域网络，支持重置视图。仍未开放页面直接调用业务工具、OAuth 或任意扩展的全量兼容。不是 Python 技术栈的必然限制。
- SSE 提供任务事件流，模型回答暂时是完整响应，不是逐 token 文本流。
- 面向可信内网。命令白名单/路径检查不等于 OS 沙箱；Python/Node 子进程拥有对应操作系统账户权限，不应运行不可信脚本或权重。

详见 [ARCHITECTURE.md](ARCHITECTURE.md)、[plan.md](plan.md)、[docs/OPERATIONS.md](docs/OPERATIONS.md)。
