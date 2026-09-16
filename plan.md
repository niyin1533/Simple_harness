# 迁移实现与验收记录

更新时间：2026-09-07。记录当前实现，不承诺未实现能力。

## 2026-09-08 启动修复

- 确认前次开发实例残留占用 5173/8010/8011，重复启动失败；已停止确认属于该实例的进程，未修改数据库。
- 启动器增加端口/Node/Vite 预检、带服务名前缀的控制台和 UTF-8 文件日志、服务退出码与就绪检测。
- Windows 直接通过 Node 启动 Vite，使用严格端口；GBK 控制台无法显示的字符安全替换，文件日志保留原文。
- 支持 `--check` 与 `--smoke-test`；启动后仅清理本次进程树，不终止预先存在的服务。
- 本机实际启动、健康检查和自动清理通过，新增 4 项启动器回归测试通过。

## 范围

2026-09-16 MCP 输入兼容修复：“添加 MCP 服务”兼容单项 `mcpServers` 包装，并归一化存储为服务配置；多项包装明确引导批量导入，保留 transport、协议和敏感字段校验。此前把包装 JSON 误读为缺失顶层 URL，导致错误提示与实际输入不符。

2026-09-15 修复复核：已修复智能体创建自动 flush、MCP App 兼容缺失、待审批暂停恢复、未确认记忆召回、部署绕过审核五类问题，并补齐 MCP 嵌套连接异常处理与只读重连。地图兼容需用户显式确认，默认仍保持 opaque origin。详细验证与剩余边界见 [本轮报告](docs/MIGRATION_FIX_2026-09-15.md)。

独立 React + Python + MySQL 单智能体平台，新数据库不迁移历史。平台资源共享，会话、任务、记忆、附件和计划按用户隔离。管理员维护资源/智能体/脚本/扩展，普通用户可上传权重并申请部署。排除标注训练、两类画布、并行工具、子代理和智能体服务发布。

## 实现状态

| 工作包 | 位置 | 验证 |
|---|---|---|
| 独立账户与数据库 | security.py、db.py、cli.py、migrations | MySQL 初始化/迁移检查 |
| 资源和四步配置 | main.py、Agents.tsx、Configuration.tsx | 接口/前端构建、页面检查 |
| 私有会话与任务 | runtime.py、Chat.tsx | 浏览器实际 HTTP 链路，模型为夹具 |
| 串行工具与审批 | capabilities.py、runtime.py | 策略、路径、单次审批、失败落库、UNKNOWN 和预算保护 |
| 记忆和上下文 | governance.py、Governance.tsx | 私有读写与权限；语义效果待真实模型 |
| 权重/脚本部署 | deployments.py、tool-runtimes/server.py | 进程夹具启动/健康/OpenAPI/调用/停止 |
| MCP/插件 | extensions.py | stdio、HTTP、HTML 资源、ZIP 校验 |
| MCP Apps | app_host.py | 隔离显示实现，全兼容尚未完成 |
| 定时任务 | scheduling.py、worker.py | 五种周期实现，时间边界单测 |
| UI 与文档 | frontend/src、ARCHITECTURE、INDEX | 浅色高对比度，format-doc 同步 |

## 原项目映射

| Fanwu 边界 | Python/React 替代 |
|---|---|
| AgentWorkspaceServiceImpl | Resource、AgentVersion、REST、四步表单 |
| AgentRunServiceImpl | Run / Event / ToolCall / Approval、独立 Worker |
| AgentCapabilityRuntime | 能力清单、权限策略、文件/命令/HTTP 适配器 |
| AgentMemoryServiceImpl / AgentContextService | Memory / Preference / Checkpoint |
| AgentDeploymentServiceImpl / mytest | Artifact / Deployment / --config 推理协议 |
| AgentExtensionServiceImpl / AgentMcpClient | ZIP 投影、官方 Python MCP SDK |
| 训练权重导入 | 用户上传权重、管理员审核部署 |

参考 deepseek-harness 的显式执行边界与 openakita 的 Python 适配思路，没有整体复制框架，也不引用 Fanwu 训练目录。

## 测试记录

- `pytest -q`：22 项通过，含真实 MySQL、MCP 传输和推理进程生命周期。
- `alembic check`：无待迁移模型差异。
- `npm run build`：通过。
- `npm test`：3 项前端 API/CSRF/错误处理测试通过。
- `npm run test:e2e`：2 个浏览器场景通过，覆盖登录、五个页面、记忆、模型直聊、持久事件以及 MCP UI 握手与跨 origin 隔离。
- `ruff check --select F` 和 format-doc 全量一致性检查通过。
- 已检查登录、聊天、配置中心、任务详情截图；深色正文、浅色背景，placeholder 已加深。

## 未完成验收与差异

1. MCP Apps 只提供显示/初始化/输入/结果通知；页面工具调用被拒绝，不能宣称全量兼容。
2. 模型返回为完整响应，尚未逐 token 输出；任务 SSE 已实现。
3. 尚无用户实际权重、CUDA、LLM/Embedding/MiniMax 密钥的实物验收，夹具测试不证明推理效果。
4. 仅 Windows 实测，Linux 部署说明不等于 Linux 验收通过。
5. 无 OS 级沙箱，不支持不可信多租户的强隔离承诺。
6. 尚需断电、多 Worker 压力测试与第三方插件兼容矩阵验证。

这些差异不是 React/Python/MySQL 本身无法实现，不能作为永久功能删减默默接受。
# 2026-09-16 模型决策与 Ollama Embedding 修复

- Agent Loop 实际启用 JSON 输出模式，校验决策字段，格式错误携带纠正提示重试，记录 MODEL_ATTEMPT_FAILED；不重放已完成工具。
- 用户格式要求放入 answer 字符串；纯空白输出视为失败，不伪造答复。
- Embedding 支持 Ollama `/api/embed` 与 OpenAI 兼容 `/v1/embeddings`，保留旧配置；界面新增接口类型。
- 无候选记忆跳过向量请求，召回接口异常记录警告并降级文本；显式记忆写入仍报告向量错误。
- 回归：48 项后端测试通过、前端构建通过；真实 bge-m3 两种接口均返回 1024 维；真实 DeepSeek 使用失败任务已有工具结果生成 JSON 最终回答及官方链接。未重放原任务或修改其结果。
# 2026-09-16 地图 MCP 传输恢复

- 用户地图失败记录仅保留通用传输错误，无法追溯历史底层异常；现场同服务连续三次 show-map 成功，非稳定配置/参数错误。
- 对照原项目持久 HTTP 会话：迁移版每操作重新初始化，增加了握手失败暴露。补齐初始化阶段最多三次安全重连；进入操作阶段不重放工具。
- 日志记录失败阶段、次数和底层异常类型，不记录敏感 URL、请求头或密钥。
- 50 项后端测试通过；修改后真实 show-map 成功，地图 HTML 资源读取成功（225940 字符）。本次未重新验收浏览器地图渲染。
# 2026-09-16 三项反馈闭环

- 修复握手后 HTTP 连接失败的安全重试和 SDK 断流分类；真实后台地图任务连续三次成功，浏览器实际地图/瓦片验证通过。
- 按原版统一显式/异步记忆治理，补齐分类、0.70 置信度、稳定槽与事务更新、失败待审核、混合召回及预算；已有重复项提供人工停用建议，不静默删除。
- 内置 YOLO 默认独立 `.venv-yolo`，增加依赖预检；用户 yolo11s.pt 已完成 CPU 启动和真实图片检测。
- 数据库迁移 0003 已执行，54 项后端测试及前端构建通过；详细证据和边界见 `docs/FIX_VERIFICATION_2026-09-16.md`。此前关于尚未真实验证 YOLO、仅简化记忆治理的记录为历史状态，以本条为准。
# 2026-09-16 界面反馈与历史记录清理

- 治理建议长文本自动换行，限制弹窗内容高度；分析及向量重建显示加载状态并防止重复提交。
- 会话列表提供带确认的红叉快捷删除，不切换会话；现有任务审计保留。
- 任务中心提供单条/批量删除。只允许自己的 SUCCEEDED/FAILED/CANCELLED/BLOCKED 任务，事务内清理事件、调用和审批，并清空计划的末次任务引用；聊天内容与产物文件保留，不可撤销。
- 55 项后端测试、前端构建通过；模拟浏览器在 1280px/600px 验证弹窗不溢出、加载反馈和删除流程。未删除任何真实用户历史数据。
# 2026-09-16 会话删除视觉优化

- 常显红叉改为 15px 线框垃圾桶、32px 点击区域；桌面仅悬停/键盘焦点时显示灰色，指向按钮时红色浅红底。
- 触屏常显灰色按钮；预留固定文字空间避免覆盖或抖动，保留确认与不可恢复提示，不修改删除逻辑。
