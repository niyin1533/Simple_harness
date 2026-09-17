# 单智能体发布与 Service API

## 使用

管理员在“智能体 → 发布管理”中检查依赖、选择渠道、逐项授权工具并发布。
工具列表为固定高度滚动区。首次发布默认选择权限预设允许的全部非 HIGH 工具；“全选非 HIGH 工具”不会选择 HIGH 或绕过权限预设。已发布应用重新打开时读取当前版本授权，而不是重置默认值；用户编辑中的选择也不随后台查询刷新而丢失。新增工具需主动选择或再次全选。
默认选择含写入能力，发布者应核对范围；文件授权仍需专用工作区，URL 参数仍必须明确填写域名白名单，不能通过全选跳过校验。
Service API 默认开启，匿名 Web 默认关闭。编辑草稿不影响线上；旧会话固定原版本，新会话使用当前版本。版本页可切换历史版本。
匿名 Web 不允许 HIGH 工具（包括进程执行）。文件参数必须位于智能体专用工作区；命令必须精确授权 executable + args；URL 参数必须明确授权域名/端口。
MCP 兼容显示由发布者授权，访客不能自行降低沙箱限制。已识别的 Cesium 地图工具默认开启可见的“允许可信交互卡片兼容模式”，发布时固化；显式关闭的历史选择会保留。公开页自动使用该模式，显示兼容状态并支持重新加载，返回历史会话也能恢复卡片。
旧版本未授权兼容模式时显示明确提示而非无提示的黑屏。需要发布新版本，再新建会话；不会修改旧版本或让访客越权开启兼容模式。

“应用链接与密钥”提供 Web 分享链接和可选的 API 密钥。API 地址是外部程序 POST 聊天请求的入口，不是网页，收在默认折叠的“开发者接入”中；只用 Web 聊天不需要密钥。
密钥备注可不填，自动生成名称；界面不再提供失效日期，新密钥长期有效，停用时吊销。已有带截止日期的密钥维持原语义，不擅自延长。
“发布设置”集中管理 Web/API 渠道和应用下线。“保存开放设置”只保存渠道开关，不发布新版本；“下线应用”同时拒绝 Web/API 新消息。密钥明文仍只显示一次，请立即安全保存。
应用停用后不能发起新消息，但已接受的任务可以完成和查询；控制台任务中心保留来源、版本、工具及审计。
公开聊天页使用独立左侧会话列表，悬停或键盘聚焦显示删除按钮（触屏常显），无需点开会话即可确认删除。全量访客清理位于左下角“隐私与数据”菜单，二次确认后才执行。背景动效响应系统减少动态效果设置。
公开任务只允许取消，不从控制台绕过配额恢复；需要重试时从原应用发起。

## 启动 / 升级

```powershell
# 在项目根目录执行，先在原终端停止旧服务
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
docker compose up -d --wait mysql redis
.\.venv\Scripts\python.exe -m alembic -c backend\alembic.ini upgrade head
.\.venv\Scripts\python.exe scripts\dev.py
```

现有进程需要在原终端 Ctrl+C 后重新启动 API、Worker 和前端；先确认没有正在运行的用户任务。关闭启动器可能同时结束它的推理子进程，重启后在“权重与部署”检查并按需启动。
不要执行 `docker compose down -v`，它会删除数据卷。

Redis 容器 `agent-harness-redis`，本机 `127.0.0.1:16379`；Compose 卷名随项目名变化，使用 `docker volume ls` 查看。不依赖原项目服务。
默认 `AGENT_REDIS_URL=redis://127.0.0.1:16379/0`，键前缀 `agent:publication:`。
Redis 不可达时公开**新任务**返回 503，后台聊天、历史读取和已运行任务不依赖 Redis。

并发准入使用 MySQL 应用行锁 + 持久 Run 计数（排队也占额度），而非仅依赖易丢失的 Redis TTL；默认应用 5、外部用户 2。Redis Lua 原子控制每应用 30 次/分钟、匿名 Web 每 IP 10 次/分钟。公开事务使用 READ COMMITTED，避免请求等待行锁后读到旧快照造成幂等/并发竞态。
管理员接口可设置应用 rpm / concurrency，Web 页面使用默认值。IP 采用连接对端，不信任任意 X-Forwarded-For；反向代理场景会保守聚合到代理 IP，部署前应规划可信网关限流。

## Service API

根路径 `/service-api/v1`，不开放控制台 `/api/v1`。前端开发代理已转发；生产反向代理也必须转发 `/service-api`、`/public-api`，并为 `/published/agents/*` 提供 SPA 回退。

```http
POST /service-api/v1/chat-messages
Authorization: Bearer app-你的密钥
Content-Type: application/json
Idempotency-Key: 唯一业务请求号

{"query":"请介绍你的能力","user":"customer-10086","response_mode":"async"}
```

返回 HTTP 202，包含 `run_id`、`conversation_id`、`version`、`status`。
后续消息提供 `conversation_id`。不存在或不属于当前应用/用户/渠道的会话直接拒绝。

| 接口 | 用途 |
|---|---|
| GET `/runs/{id}?user=customer-10086` | 状态和最终回答 |
| GET `/runs/{id}/events?user=customer-10086` | SSE，支持 Last-Event-ID |
| POST `/runs/{id}/stop?user=customer-10086` | 停止任务（不能撤销已发生的副作用） |
| GET `/conversations/{id}/messages?user=customer-10086` | 本外部用户会话历史 |

`response_mode: streaming` 直接返回 SSE；事件为 `run_started`、`tool_started`、`tool_completed`、`message_completed`、`run_failed`、`done`，持久连续 seq。当前是**实时执行事件 + 完整最终回答**，不模拟逐字输出，`message_delta` 为将来保留。
工具事件仅有安全状态/调用 ID，MCP App 额外提供资源描述；Service API 不提供通用 MCP 资源代理。
错误结构 `{code,message,request_id,run_id}`，不会返回内部异常堆栈。API Key 信任持有它的业务服务，该服务负责校验终端用户身份，`user` 不是独立登录凭据。
幂等键在应用/外部用户范围内有效 24 小时；同键不同请求返回 409，任务清理后同键返回 410，不重复执行。

## 隔离与安全

- Web 使用签名 HttpOnly / SameSite Cookie 和访客 CSRF 校验，生产启用 HTTPS + `AGENT_SECURE_COOKIE=true` 并设置 `AGENT_ORIGINS`。
- API Key HMAC-SHA256 摘要使用 `data/master.key` 做域隔离签名；数据库只存摘要、前缀与末四位。主密钥轮换会同时使原 Key 和访客签名失效，不能直接覆盖。
- 发布快照及新公开 Run 不含资源密钥，执行时解析服务端凭据引用；模型凭据轮换无需发布。MCP 敏感 headers/env 必须 `${secret:NAME}` 引用。
- 记忆显式主体 `PLATFORM_USER` / `APP_END_USER`；历史平台主体回填，外部用户按应用/渠道/身份隔离，使用发布者的治理/向量凭据和发布时策略。
- 访客清除会先取消并等待在途执行释放，再删除会话和记忆并轮换 Cookie；审计留存。若后台失联暂未释放，返回 409，可稍后重试，不声称已清除。
- 能力 Schema、服务器配置漂移以及依赖删除/停用会拒绝新请求；知识内容保持实时，每次准入时写入该 Run 的审计快照。
- 工作目录和工具声明不是操作系统沙箱。发布者需信任所选模型、MCP 服务和脚本；公开高风险工具前仍需独立低权限运行环境。

## 快速验收

1. 发布一个仅模型问答的智能体，主动开启 Web；无痕窗口打开，能聊天，后台任务中心显示“公开 Web / v1”。
2. 创建 Key，以 async 调用，查到回答；另一个 `user` 查该 Run 应返回 404，同幂等键只返回原 Run。
3. 改系统提示词并发布 v2：旧会话仍 v1，新会话 v2；回滚后新会话 v1。
4. 勾选已调试的 Microsoft Learn 搜索工具，确认回答有真实工具进度且不会等待人工审批；地图工具勾选可信兼容模式再测试。
5. 停用发布，新消息被拒绝；吊销 Key 后该 Key 查询也失败。公开访客清除后旧会话不可访问，控制台审计仍在。

自动验证：`$env:PYTHONPATH='backend'; .\.venv\Scripts\python.exe -m pytest backend/tests -q`。
集成测试使用独立 MySQL / Redis，创建 UUID 测试数据后清理，不修改现有智能体。运行时应先暂停 Worker，避免领取测试任务。
