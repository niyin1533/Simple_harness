<!-- FORMAT-DOC: Update when files in this folder change -->

# backend/tests

本目录职责：按明确夹具标记清理测试记录；独立推理协议测试服务，不执行实际 ML等，文件职责如下。

## Files

| File | Role | Responsibilities |
|---|---|---|
| cleanup_e2e.py | Test | 按明确夹具标记清理测试记录 |
| fixture_inference.py | Fixture | 独立推理协议测试服务，不执行实际 ML |
| fixture_mcp.py | Fixture | stdio/HTTP MCP echo、HTML 资源与 UI 握手夹具 |
| fixture_model.py | Fixture | 测试专用确定性模型接口 |
| test_adapters.py | Test | MCP 初始化重连、发出后不重放、传输和部署进程生命周期回归 |
| test_contracts.py | Test | 策略、文件、ZIP、调度、JSON 与单项 mcpServers 兼容/错误边界 |
| test_dev_launcher.py | Test | 端口冲突、Node 直接启动、服务退出提示和 GBK 控制台日志回归 |
| test_mysql_runtime.py | Test | MySQL 任务、审批、预算与用户隔离 |
| test_provider_protocols.py | Test | JSON 模式、Ollama/兼容向量协议、空候选与故障降级回归 |
| test_memory_governance.py | Test | 稳定槽去重更新、用户隔离、治理重试/待审核与部署依赖预检 |
| test_run_delete.py | Test | 任务删除归属/状态校验、批量原子性、关联记录清理与聊天保留 |
| test_publication.py | Test | 发布授权回显、版本/准入/幂等/隔离、历史视图归属及兼容不可越权；测试任务不被在线 Worker 领取 |
| test_migration_regressions.py | Test | 真实智能体创建/版本接口、待审批恢复、声明域 CSP 与显式兼容回归 |
