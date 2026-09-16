<!-- FORMAT-DOC: Update when files in this folder change -->

# backend/app

本目录职责：Python 应用包入口；独立 origin 的 MCP HTML 显示与最小消息桥等，文件职责如下。

## Files

| File | Role | Responsibilities |
|---|---|---|
| __init__.py | Module | Python 应用包入口 |
| app_host.py | Controller | 独立 origin 的 MCP HTML 显示、声明域 CSP 与显式兼容票据；挂载本地 Cesium |
| mcp_compat.js | Adapter | 可信地图兼容模式的本地 Cesium Worker、相机与视图重置 |
| capabilities.py | Service | 工具清单、权限预设、路径检查与本地/MCP/HTTP 执行 |
| cli.py | CLI | 数据库迁移、主密钥与初始管理员创建 |
| config.py | Config | 环境变量、数据根目录和运行限制 |
| db.py | Schema | MySQL 表模型、记忆治理元数据、事务会话和公开字段投影 |
| deployments.py | Service | 独立 YOLO 环境选择、依赖预检、推理进程生命周期、OpenAPI 注册和输出发布 |
| extensions.py | Adapter | MCP 配置归一化、两种传输、初始化安全重连、失败阶段脱敏日志和 ZIP 投影；已发出的工具不自动重放 |
| governance.py | Service | 仅召回已启用且已确认的私有记忆；空候选跳过向量、接口失败降级文本并记录日志；提取与检查点 |
| memory_governance.py | Service | 显式/异步统一治理、分类/置信度校验、稳定槽更新、失败待审核及人工去重建议 |
| main.py | Controller | 身份/资源 REST、审批恢复、部署审核、任务 SSE 及归属/终态校验的单条批量清理 |
| providers.py | Adapter | OpenAI/Ollama JSON 输出、DeepSeek 结构化非思考模式与治理纠正重试；原生/兼容向量校验 |
| runtime.py | Service | 快照驱动的串行状态机、预算、单次审批、JSON 决策纠正重试和持久事件 |
| scheduling.py | Service | 时区与一次/每日/每周/每月/Cron 时间计算 |
| security.py | Security | Cookie 会话、CSRF、角色检查和密钥加密 |
| worker.py | Worker | MySQL 租约、失效恢复、计划和推理部署调度 |
