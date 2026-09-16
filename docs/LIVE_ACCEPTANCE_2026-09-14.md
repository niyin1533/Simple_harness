# 真实服务联调报告（2026-09-14）

## 结论

当前版本不能认定为完整迁移验收通过。真实 DeepSeek 对话、上下文压缩、Microsoft Learn MCP 适配层、ZIP 投影等功能可用；发现两个确定故障：新建智能体接口 500、地图 MCP App 视图因 CSP 拦截依赖而渲染失败。

本轮仅新增诊断脚本、证据与报告，没有修改业务实现，没有修改 Fanwu。没有通过直接写数据库创建智能体来绕过接口错误。被阻塞的链路不计通过。

## 基础设施隔离

| 项目 | Agent Harness | 原 Fanwu |
|---|---|---|
| MySQL 容器 | agent-harness-db，mysql:8.4 | fanwu-mysql-test，mysql:8.0 |
| MySQL 地址 | 127.0.0.1:13310 | 127.0.0.1:3307 |
| 数据库 | agent_harness | smart_algo_test（本机 center 配置） |
| Redis | 当前没有使用，也没有复用旧 Redis | fw-redis，6379；配置 database=1 |
| 文件存储 | D:\nrts\agent\data | 原项目另有 fanwu-minio，9000/9001；Agent 不依赖它 |
| 任务队列/租约/事件 | MySQL + Python Worker | 不参与新平台执行 |

新 MySQL 持久卷名为 `agent-harness-db`，挂到容器 `/var/lib/mysql`，Docker 报告的卷源路径是 `/var/lib/docker/volumes/agent-harness-db/_data`。这是 Docker Linux 环境中的路径，不是 Windows D 盘上的目录。可在 Docker Desktop 的 Volumes 查看，也可执行 `docker volume inspect agent-harness-db`。

没有新 Redis 容器是当前设计如此，不是漏启动了 Redis。这里只能说应用、数据库、持久卷和文件目录分开，并不是独立机器或操作系统级安全隔离；仍使用同一台宿主机与 Docker Engine。

## 实测矩阵

| 功能 | 结果 | 实测证据与边界 |
|---|---|---|
| 登录与现有 DeepSeek 接入 | 通过 | 使用用户已有“deepseek基座”，连接测试返回“连接成功”；未更改密钥/模型配置 |
| 模型直聊与任务持久化 | 通过 | 计算 120×2+80×3+200，真实任务 SUCCEEDED，回答 680，保存任务/消息/事件 |
| 连续会话与上下文压缩 | 通过 | 4 轮对话后压缩，生成 checkpoint；第 5 轮仍回答 CTX-927；保留 10 条原始消息 |
| Prompt / Skill / Knowledge 创建 | 通过（资源层） | 三类资源均经真实 REST API 创建；未验证绑定后的模型行为 |
| 新建智能体 | **失败** | 两次不同新建请求均 HTTP 500；MySQL 1048，Column 'name' cannot be null |
| Microsoft Learn 工具发现 | 通过 | 真实发现 microsoft_docs_search、microsoft_docs_fetch、microsoft_code_sample_search |
| Microsoft Learn 三种工具执行 | 通过（适配层） | 通过项目自身 Python MCP 适配器分别真实调用，返回 Azure Blob 文档搜索、文档正文和 Python 代码样例；非 LLM 自主调用链路 |
| 指定 ZIP 预检与安装 | 通过 | 使用 fanwu-mcp-app-map-extension-1.0.0.zip；生成 map-assistant Skill 与 official-mcp-app-map MCP，初始均停用 |
| 插件启用与地图工具发现 | 通过 | 发现 show-map、geocode；geocode 本轮仅发现，未执行 |
| 地图 show-map 调用 | 通过（适配层） | 使用天安门附近明确经纬度边界，isError=false，返回实际地图定位结果 |
| 地图 HTML 与独立视图接口 | 通过（接口层） | 读取 ui://cesium-map/mcp-app.html，长度 225940 字符；取得 isolated-display 视图 |
| 地图浏览器渲染 | **失败** | Edge 无头浏览器打开平台生成视图，HTTP 200 但无 canvas、截图空白；iframe 报 Failed to load CesiumJS from CDN，控制台明确 CSP 拦截 |
| 记忆管理 | 通过（资源层） | 全局记忆创建、修改、停用、清理；智能体跨会话检索尚未验证 |
| 普通用户隔离 | 通过（抽样） | 新普通用户读取管理员任务为 404，创建模型为 403；看不到管理员会话与记忆；非全面安全审计 |
| 后端已有测试 | 通过 | pytest backend/tests -q：26 passed；含 mock 与数据库测试，不等价于真实模型全链路通过 |
| 前端单元测试 | 通过 | npm test：3 passed |
| 前端生产构建 | 通过、有警告 | npm run build 成功；主 JS 约 1.48 MB，触发 chunk >500 KB 提示 |

Microsoft Learn 当前工具定义应以服务发现为准；本轮三种工具均已真实发现与调用。官方说明：[Microsoft Learn MCP developer reference](https://learn.microsoft.com/en-us/training/support/mcp-developer-reference)。

## 故障定位

### 1. 新建智能体接口 500（阻断核心入口）

- 位置：`backend/app/main.py` 的 `save_resource`，约 303–311 行。
- 先构造仅包含 id/kind/version 的 Resource 并 `db.add(row)`。
- 随后执行 `await db.get(Resource, config['model_id'])` 查询基础模型。
- SQLAlchemy 查询触发 autoflush，此时 `row.name = body.name` 尚未执行，MySQL 拒绝空名称。
- API 日志两次均明确包含 `Query-invoked autoflush` 和 `Column 'name' cannot be null`。
- 修复方向：先校验基础模型再添加新 Resource，或在添加前完成必填字段；补充经真实创建 API 的 MySQL 回归测试。现有 runtime 测试直接构造完整 Resource，未覆盖这个入口缺陷。

日志：`data/logs/dev-20260914-184439-44128/api.log`，相关错误约 93–275、282–464 行。

### 2. 地图视图 CSP 与真实资源不兼容

- 位置：`backend/app/app_host.py` 约 84 行，外层响应 CSP 的 script-src/style-src 只有 unsafe-inline，禁止地图从 cesium.com 加载必要脚本和样式。
- 即使内部 srcdoc 的策略允许 cesium.com，也不能放宽继承的外层策略，浏览器实际拒绝加载。
- 另一个静态检查发现：`backend/app/main.py` 的 domains 校验不接受插件声明的 `https://*.openstreetmap.org`、`https://*.cesium.com`，后续瓦片/资源兼容性也需要校验；本轮已经实证的直接失败原因是 Cesium 脚本/样式被 CSP 拦截。
- 修复应保持隔离 iframe、无业务凭据/权限，并精确处理声明域名、通配子域、worker 等需求；不建议简单删除 CSP 或开放所有来源。

证据：`data/live-acceptance-20260914/map-browser.json` 与 `map-browser.png`。

## 未完成验收项

由于新建智能体失败，以下计划测试被阻塞：绑定 Prompt/Skill/Knowledge 的实际执行、订单文件读写、审批通过/拒绝、等待审批时取消与暂停恢复、只读与路径越界限制、智能体调用 MCP、智能体记忆召回、定时任务的完整执行。这些功能不能据当前界面或旧测试判定可用。

本轮亦未验证真实用户权重上传后推理服务启动/工具注册/模型结果正确性、GPU 兼容性、所有 HTTP 工具、进程崩溃恢复与长期稳定性、全量前端交互。没有合适的真实权重及预期输出，不能用假权重或 mock 代替验收。

## 测试资源与证据

- 测试资源使用 `[联调0914]` 名称前缀；插件投影沿用包内名称。
- 已停用本轮创建的 Prompt/Skill/Knowledge、Microsoft Learn MCP、地图插件及其投影工具，并读取验证停用状态。
- 临时普通用户已停用；本轮测试记忆已删除（证据保留，可重建），未删除用户原有数据。
- 保留测试任务、会话、CSV 输入和 JSON/截图证据，以便复查；未更改已有 DeepSeek，未停止用户运行中的平台。
- 结果索引：`data/live-acceptance-20260914/state.json`。
- 直聊任务：`1d7da8f4-d425-44d2-a184-da4e1646e6ed`。
- 压缩后回忆任务：`d4334961-e379-4433-aeff-599e59c4a60b`。
- 本轮新增：`scripts/live_acceptance.py`、`scripts/live_browser.mjs`；按 format-doc 要求同步了文件头、脚本目录索引及架构索引说明，未改变产品架构。

下一步应先修复以上两个故障，再继续被阻塞的真实 DeepSeek 智能体验收；本轮未擅自实施修复。
