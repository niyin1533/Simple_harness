# 迁移差异核查与修复（2026-09-15）

## 结论与范围

不止原先两项。本轮确认并修复了五类功能/状态缺陷，另补齐了一类已实际触发的 MCP 连接异常处理缺陷。React/Python/MySQL 并不妨碍实现原逻辑；问题来自迁移时的实现遗漏和新运行时边界处理。

仅修改 `D:\nrts\agent`。原 Fanwu 只读对照；Redis 未添加，仍使用独立 MySQL 队列。这里的结论是“本轮已确认问题已修复”，不是证明全平台没有其他缺陷。

## 根因、原实现对照、修复

| 问题 | 原项目对照 / 根因 | 本次处理 |
|---|---|---|
| 新建智能体 500 | AgentWorkspaceServiceImpl.toAgentItem 先构造完整名称/模型/配置再 upsert；Python 在 name 赋值前查询模型触发 SQLAlchemy autoflush，违反 MySQL 非空约束 | 查询校验提前；增加真实 MySQL 创建、更新和过期版本冲突测试 |
| 地图视图不显示 | McpAppFrame.vue 原有声明域、通配子域、显式兼容模式、本地 Cesium、Worker 修正和视图恢复；迁移版外层 CSP 拦截 CDN，且漏掉上述兼容链路 | 同步内外 CSP，支持声明的 HTTPS 通配子域；恢复显式确认兼容、独立本地 Cesium、模块 Worker 路径归一化、相机定位和重置 |
| 等待审批的任务暂停后恢复失败 | 原 AgentRunServiceImpl 的恢复执行仍由审批观察器处理未决审批；迁移版直接排队后遇到 PENDING 即报“审批未通过” | 恢复时检测未决审批，保持 WAITING_APPROVAL；批准后才排队，等待时间不消耗执行预算 |
| 未确认记忆进入上下文 | 原 AgentMemoryMapper.selectRetrievalCandidates 只读 active；迁移版只检查 enabled，漏查 confirmed | 同时要求 enabled 与 confirmed；待确认/停用内容不能注入 |
| 普通用户绕过部署审核 | 独立平台增加普通用户申请部署；原部署执行边界没有等价地落实在新状态机中。PENDING→stop→STOPPED→start 可绕过仅按 PENDING 判断的审核 | 服务端保存 approved，客户端提交不能自行授予；普通用户启动始终检查批准标记，管理员批准/启动才授权 |
| MCP 连接异常成为不明 500 | 实际出现 TLS ConnectError；Python MCP SDK/AnyIO 封装为 ExceptionGroup，原 Java AgentMcpClient 的连接诊断语义未完整迁移 | 识别嵌套连接异常，返回脱敏 502 提示；仅 tools/list、resources/read 最多重试 3 次，不在传输层自动重放 tools/call |

源码参考路径均在原项目：

- `fw-aa/fw/ruoyi-business/src/main/java/com/ruoyi/business/service/impl/AgentWorkspaceServiceImpl.java`
- `fw-aa/fw/ruoyi-business/src/main/java/com/ruoyi/business/service/impl/AgentRunServiceImpl.java`
- `fw-aa/fw/ruoyi-business/src/main/java/com/ruoyi/business/service/impl/AgentMcpClient.java`
- `fw-aa/fw/ruoyi-business/src/main/resources/mapper/business/AgentMemoryMapper.xml`
- `fw-aa-frontend/src/views/system/workspace/McpAppFrame.vue`

## 地图兼容模式的边界

在任务详情的工具结果处点击“地图兼容模式”，阅读提示并确认；之后可以“重置视图”。与原项目一样，这是对可信地图扩展的显式授权，不默认对所有 MCP HTML 放宽。

- 普通模式仍是 opaque-origin iframe；已有默认隔离/握手浏览器测试通过。
- 兼容模式允许显示域内同源 iframe、受限动态脚本与 Worker；显示域仍独立于业务前端/API。
- 不开放页面 tools/call，不暴露业务 API 凭据；网络受 CSP 声明域限制。
- 从原项目独立复制 Cesium **1.129** 发布资源至 `backend/vendor/cesium`，保留 LICENSE.md；运行时不读取 Fanwu。
- 地图瓦片沿用原兼容模式的 OpenStreetMap.de 来源，需要外网。CDN/瓦片服务不可达仍可能导致失败，不能承诺离线地图。
- 浏览器会提示 allow-scripts 与 allow-same-origin 的组合可逃离其内层 sandbox；这正是兼容模式需显式确认、且必须置于独立显示 origin 的原因。不是强多租户 OS 沙箱。

## 验证结果

### 真实 DeepSeek + 当前 MySQL + 实际工具

- 新建智能体成功，并完成绑定 Knowledge/Prompt/Skill 的订单任务。
- 文件列举/读取通过；两次分别批准写入后生成 report.md、result.json。结果为 3 笔订单、6 件商品、原价 680、九折 612、规则码 RULE-927。
- 拒绝审批未写文件；等待审批时取消未写文件。
- 等待审批→暂停→恢复→仍待审批→批准→仅执行一次写入，通过。
- 只读禁止写入；`../outside.txt` 被工作目录边界拦截。模型正确报告读取失败；任务最终答复成功不代表越界工具成功。
- Microsoft Learn 三个工具均由真实 DeepSeek 智能体选择、经过审批并真实调用成功，不再只是昨日的适配层检查。
- 地图插件预检/安装、Skill/MCP 投影、发现、真实智能体 show-map 调用通过。
- 地图兼容视图已实际加载本地 Worker 与远程瓦片，截图显示天安门周边道路，而非仅判断 canvas 存在。
- 记忆跨会话召回 BLUE-WHALE-927 成功；停用后不再注入。
- 会话压缩后仍能回答 CTX-927，原始消息保留。
- 一次性定时任务自动触发，回答 SCHEDULE-927，并自动停用。
- 普通用户不能读取管理员任务/记忆或维护模型。

### 自动回归

- 后端：`pytest backend/tests -q`，**32 passed**。新增创建/版本、审批恢复、未确认记忆、部署审核绕过、MCP 连接重试与禁止重放等用例。
- 其中“未确认记忆”“停止绕过审核”用例在修复前均实际失败，修复后通过。
- 前端：`npm test`，**3 passed**。
- 默认 MCP opaque iframe：`npm run test:e2e -- --grep "MCP resource"`，**1 passed**。
- 前端生产构建成功；仍有大 bundle 警告，不影响本次功能修复，但不等于性能验收通过。
- format-doc 全目录检查通过；相关文件头、目录索引和架构说明已同步。
- Ruff 按项目要求的 Python 3.12 检查通过（`--target-version py312 --select F`）。
- 原 runtime 测试有手工设置 RUNNING 却未设置有效租约的夹具竞争；补齐测试租约，避免被实际运行的 Worker 当成失效任务回收。这是测试隔离修正，不计作产品缺陷。

### 可复查证据

- `data/live-acceptance-20260915/state.json`：真实服务分项结果。
- `data/live-acceptance-20260915/*.json`：各任务调用、审批、事件证据。
- `data/live-acceptance-20260915/map-browser.json` / `map-browser.png`：初始化、输入/结果通知、定位、Worker 和瓦片记录、实际地图截图。孤立视图的 favicon 404 不影响地图。
- `data/live-acceptance-20260915/ui-results.json` / `ui-wizard.png` / `ui-map.png`：React 四步向导及实际任务详情的浏览器复核结果，以该 JSON 的最终状态为准。
- 最终页面复核：四步向导创建通过；任务详情兼容视图 HTTP 200，canvas=1，页面脚本错误为空；已目视确认真实道路地图截图。该脚本创建的智能体已停用。
- 订单任务 `30d5f410-6e00-4936-8bca-a101d3fbf2da`；审批暂停恢复任务 `38f8708d-1309-46d1-abf5-c77c11ee68f3`；地图任务 `1dcc6c45-28db-4403-a9c1-5bd6de24b638`。

## 不能据此宣称完成的项目

本轮未用真实用户权重和预期推理结果验收 YOLO/GPU/自定义推理脚本；既有推理生命周期测试是明确的夹具，不证明模型精度。也未进行断电恢复、多 Worker 压力、所有第三方 MCP App、全量安全审计。

原计划明确排除的并行工具、子代理和服务发布，不属于本轮实现范围；逐 token 模型流、完整 MCP App 反向工具桥、原项目完整记忆语义治理等既有差异也不能因为本次修复而标记为完成。详见 plan.md 的范围和未完成验收说明。

## 使用及数据处理

已重启 Agent 自身开发服务加载代码，MySQL 与 Redis 配置不变。部署审核字段存于现有 JSON config，无需结构迁移；旧部署若缺少可信 approved 标记，普通用户重新启动时需要管理员再批准一次，不推断旧状态即为已授权。

测试资源/用户由测试脚本停用，保留任务、会话和截图证据。原模型和密钥不修改。联调测试会产生实际 DeepSeek 调用费用。

手动复查地图时，先在配置中心启用对应的地图插件（测试清理时已停用），再在任务详情选择地图兼容模式。无需 Redis。
