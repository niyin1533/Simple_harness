# 安全说明

本项目能执行文件操作、命令、推理脚本和 stdio MCP。白名单和审批不等于操作系统沙箱；不要让不可信脚本在能读取平台密钥的账户下运行。公网部署需要低权限账户、容器/虚拟机隔离及网关防护。

## 敏感数据

不要提交 `.env`、API Key、Cookie、私钥、初始密码、整个 `data/`、数据库导出、模型权重或包含真实用户内容的截图。

`.gitignore` 不会清除历史提交。如果秘密已经提交，先吊销/轮换，再清理历史；仅删除当前文件不足以消除泄露。公开前审查历史、远程 URL 和提交者邮箱。

## 部署检查

- 更换开发数据库密码，MySQL/Redis 不直接暴露公网。
- 使用 HTTPS、真实 `AGENT_ORIGINS` / `AGENT_APP_ORIGIN` 和 `AGENT_SECURE_COOKIE=true`。
- MCP UI 使用独立 origin；公开工具使用专用工作区和最小权限。
- 备份数据库、上传文件和 `master.key` 并演练恢复。不要直接替换主密钥，否则可能使加密资源、应用密钥和访客签名失效。
- 核对发布 WRITE 授权，地图兼容仅用于可信资源。
- 生产前补充登录限流、日志保留、监控、容量管理和依赖漏洞检查。

## 报告漏洞

不要在公开 Issue 粘贴利用细节或秘密。维护者启用 GitHub Private vulnerability reporting 后使用 Security → Report a vulnerability；若未启用，先通过不含漏洞细节的 Issue 请求私密联系渠道。
