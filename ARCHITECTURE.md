<!-- FORMAT-DOC: Update when project structure or architecture changes -->

# Architecture

React + TypeScript 提供独立 Web 工作台，FastAPI 提供认证、资源与任务接口。
MySQL 保存用户、共享资源、版本、私有会话、任务快照、审批、事件、记忆与计划。
Python Worker 通过数据库租约领取任务；同一任务的模型决策与工具调用严格串行。
执行链路为“快照 → 策略 → 单次审批 → 工具 → 持久结果 → 下一步”。
上传权重通过独立推理进程，以健康检查、OpenAPI 和实例 ID 接入工具目录。
显式记忆与异步提取共用治理模型、稳定槽和原子操作；YOLO 默认使用项目内 `.venv-yolo`，与后端依赖隔离。
MCP 使用官方 Python SDK；ZIP 仅投影声明和 Skill，不执行安装钩子。
MCP Apps 由独立 origin 显示；默认 opaque iframe，显式确认后可用本地 Cesium/Worker 兼容模式，不授予业务 API 操作权。
不依赖 Fanwu 的 Java、RuoYi、训练、标注或原数据库，不包含画布与多代理。
单智能体发布以不可变版本进入同一 Runtime；独立 Web/API、外部主体记忆隔离、Redis 限流和 MySQL 串行准入共同保护公开调用。

## Modules

- [backend/app](backend/app/INDEX.md) — 认证、资源 API、持久 Harness、调度和适配器。
- [backend/migrations](backend/migrations/INDEX.md) — Alembic 迁移入口。
- [backend/migrations/versions](backend/migrations/versions/INDEX.md) — 冻结的数据库版本历史。
- [backend/tests](backend/tests/INDEX.md) — 单元、MySQL、MCP 与推理进程测试。
- [frontend](frontend/INDEX.md) — 构建、代理和浏览器测试配置。
- [frontend/e2e](frontend/e2e/INDEX.md) — 浏览器链路验收。
- [frontend/src](frontend/src/INDEX.md) — 页面、API 客户端和样式。
- [scripts](scripts/INDEX.md) — 本地开发进程启动与按需真实服务联调诊断。
- [tool-runtimes](tool-runtimes/INDEX.md) — YOLO、YOLOv5 和 MiniMax 独立适配器。

`backend/vendor/cesium` 是从原项目已使用的 Cesium 1.129 静态发布包独立复制的第三方运行资源（保留 LICENSE.md），由显示服务挂载 `/Cesium`；运行时不读取 Fanwu 目录。

运行方式与边界见 [README.md](README.md)、[plan.md](plan.md)、[docs/OPERATIONS.md](docs/OPERATIONS.md)。
