# 运行与推理协议

## 进程和数据

| 组件 | 开发端口 | 职责 |
|---|---|---|
| React/Vite | 5173 | UI、/api 代理 |
| FastAPI | 8010 | 身份、资源、任务、SSE、附件 |
| MCP UI host | 8011 | 无业务 API 的独立 origin 展示 |
| MySQL | 13310 | 独立 agent_harness 数据库 |
| Worker | 无 | 数据库租约、串行执行、计划、推理部署 |

`data/master.key` 用于资源和 Embedding 密钥加密，丢失无法解密，应与数据库分开备份。`data/uploads` 按用户存文件，`data/deployments` 存配置、日志、输出。不要向 LLM 提供平台凭据。

暂停/取消不撤销已完成的文件操作或第三方调用。Worker 失去租约后不重放执行中的工具，标记 UNKNOWN / NEEDS_REVIEW；人工检查后取消旧任务并发起新任务。数据库备份不包括文件系统副作用。

## 权重与脚本

管理员创建独立推理虚拟环境，在模板 JSON 的 `python` 填解释器绝对路径。YOLO 安装 `tool-runtimes/requirements-yolo.txt`，Torch/CUDA 版本按驱动选择。YOLOv5 另需固定版本独立仓库，填写 `yolov5_repo`；不引用 Fanwu 的 ai_o。MiniMax 无需权重，在模板独立密钥字段填 API key，通过子进程环境传递，不写入 deployment.json。

普通用户上传权重并新建部署，管理员审核，健康后从 OpenAPI 注册工具。按需编辑工具的风险类别、超时和参数 Schema。

自定义脚本调用协议：

```text
<python> <script.py> --config <absolute-deployment.json>
```

配置包含 `instance_id`、`host`、`port`、`weights_path`、`deployment_dir`、`device`、`runtime`、`input_roots`。脚本必须：

- 只监听分配的 127.0.0.1 端口。
- `GET /health` 返回 `{"status":"ok","instance_id":"配置中的 ID"}`。
- `GET /openapi.json` 提供标准 OpenAPI，工具使用 JSON POST。
- 返回 JSON，显式 `ok` 和失败时 `error`；输出保存到 `deployment_dir/outputs`。
- 使用 `annotated_image_path`、`image_path` 或 `audio_path` 返回输出，Harness 校验后发布受认证下载。

内置 `/detect` 输入 `image_path`、`confidence`、`iou`、`image_size`；MiniMax 路径为 `/tts/synthesize`、`/images/generate`。注册工具默认非幂等、工作区写入类别，因此需要确认。进程的系统权限不由 API Schema 隔离。

## MCP/ZIP

MCP 支持 `command/args/env` 或 `transport: "streamable-http"`、`url/headers`。敏感字段用 `${secret:ENV_NAME}`，由服务器管理员设置。stdio 继承最小环境，而非全部平台密钥。

ZIP 接受 `.codex-plugin/plugin.json`、`.claude-plugin/plugin.json` 或 `plugin.json`，以及 `.mcp.json` 和 `skills/*/SKILL.md`。限制 20MB、256 文件、单文件 2MB、解压合计 20MB；拒绝路径穿越、符号链接、可执行脚本。默认禁用，不执行钩子、不自动下载依赖。

MCP Apps 只能读取已启用工具声明的 URI；显示票据 5 分钟有效，HTML 在无同源权限的子 iframe 中执行，CSP 不允许域名通配符。尚未支持直接工具调用、OAuth、同源存储等兼容模式。

## Linux 与生产

Python API/Worker 可在同机 Linux 部署，通过 MySQL 协调，推理仍是本机进程。前端 `npm ci`、`npm run build` 后由反向代理提供 dist 和 /api；SSE 关闭代理缓冲。

分别监督 API、Worker、UI host；设置真实 `AGENT_ORIGINS`、`AGENT_SECURE_COOKIE=true`、专用 `AGENT_APP_ORIGIN`。建议 UI 使用独立站点域、不共享业务 cookie 域。数据库仅向内网开放，修改开发密码。

生产前仍需登录限流、完整审计/容量保留策略、备份恢复演练、真实供应商/GPU 验收。执行命令和权重的 OS 账户应低权限。允许不可信用户必须使用独立容器/虚拟机；命令白名单不是沙箱，不要让不可信脚本以能读取 master.key 的账户运行。

迁移执行 `python -m alembic upgrade head`。迁移文件已冻结，破坏性 downgrade 被拒绝；回退需要已验证备份。
