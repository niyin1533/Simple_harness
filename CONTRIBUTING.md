# 贡献指南

先阅读 [README](README.md) 和 [架构](ARCHITECTURE.md)。Issue 应提供复现步骤、预期/实际行为、操作系统和脱敏日志，不上传凭据、数据库或真实聊天内容。

## 约定

- 前端 React / TypeScript，后端 Python 3.12；新增依赖同步依赖文件。
- 保持控制台和公开应用共用 Runtime，不绕过主体隔离、授权、审批或副作用保护。
- 数据库变更新增 Alembic 迁移，不修改已发布迁移。
- 修改代码同步相关文档、文件头和目录 `INDEX.md`；结构变化同步 `ARCHITECTURE.md`。
- PR 说明变更、测试和兼容影响；界面变更附脱敏截图。

## 测试

在项目根目录执行：

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe -m pytest backend/tests/test_contracts.py backend/tests/test_provider_protocols.py backend/tests/test_dev_launcher.py -q
npm.cmd test --prefix frontend
npm.cmd run build --prefix frontend
```

完整测试需要**专用测试 MySQL 和 Redis**，用 `AGENT_DATABASE_URL` / `AGENT_REDIS_URL` 指向测试实例，先执行迁移，停止连接该测试库的 Worker，再执行 `pytest backend/tests -q`。不要对生产库运行集成测试；部分测试会创建、修改或清理记录并启动本地夹具。

`frontend/e2e` 使用 Edge、运行中的测试平台和夹具模型，运行前阅读测试代码。`scripts/live_*` 和 `scripts/verify_sep16*` 是历史真实服务诊断脚本，依赖预置资源、本机凭据和外部测试材料，**不是通用安装或默认测试步骤**；需先调整测试环境，可能产生模型费用。

`scripts/verify_cleanup_ui.mjs` 和 `scripts/verify_publication_ui.mjs` 使用模拟业务接口进行浏览器回归，需要开发前端和 Edge，不能替代真实后端联调。
