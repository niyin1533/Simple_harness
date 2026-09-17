<!-- FORMAT-DOC: Update when files in this folder change -->

# frontend/src

本目录职责：智能体卡片和四步配置表单；认证请求、CSRF 和公共类型等，文件职责如下。

## Files

| File | Role | Responsibilities |
|---|---|---|
| Agents.tsx | UI | 智能体卡片和四步配置表单 |
| api.ts | API | 认证请求、CSRF 和公共类型 |
| api.test.ts | Test | 认证请求和错误处理契约 |
| App.tsx | UI | 登录、身份上下文、路由和导航 |
| Publication.tsx | UI | 发布授权回显、非 HIGH 默认全选、固定滚动工具框、渠道管理及可选备注长期密钥 |
| PublishedApp.tsx | UI | 科技风公开聊天、独立会话侧栏/快捷删除、隐私菜单、SSE 与可恢复兼容交互卡片 |
| publication.css | Style | 发布工具滚动区和公开页深色光晕/轨道动效；高对比度、移动端及减少动态效果支持 |
| Chat.tsx | UI | 私有聊天、悬停/聚焦垃圾桶快捷删除、任务清理、审批及地图兼容 |
| Configuration.tsx | UI | 模型/知识/Skill/MCP/插件/模板与权重部署；说明单服务和批量 MCP 配置入口 |
| Governance.tsx | UI | 记忆治理弹窗换行与加载反馈、Embedding 配置、计划任务和用户管理 |
| main.tsx | UI | React 根节点、主题和状态提供器 |
| shell.css | Style | 固定侧栏与响应式工作台布局 |
| style.css | Style | 高对比度浅色页面、卡片、对话和表单 |
