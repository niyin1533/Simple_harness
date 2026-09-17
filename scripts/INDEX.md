<!-- FORMAT-DOC: Update when files in this folder change -->

# scripts

本目录职责：监督启动四个开发进程，仅停止自身子进程；提供按需真实服务联调与浏览器诊断。

## Files

| File | Role | Responsibilities |
|---|---|---|
| dev.py | CLI | 端口/依赖预检、四服务就绪检测、带前缀控制台与文件日志；仅清理自身进程树；支持 --check / --smoke-test |
| live_acceptance.py | Test | 使用现有 DeepSeek、公网 MCP 和指定 ZIP 分阶段联调，保存任务/文件证据，仅停用自身测试资源 |
| live_browser.mjs | Test | 使用 Edge 无头浏览器验证真实 MCP App 视图，保存截图与渲染错误 |
| live_ui.mjs | Test | 真实 React 四步创建与任务详情地图兼容操作，停用自身新建智能体 |
| verify_sep16.py | Test | 真实统一记忆治理、后台地图任务及用户 YOLO 权重部署验收；仅清理测试记忆 |
| verify_sep16_browser.mjs | Test | 真实地图票据的浏览器截图、画布与瓦片验收 |
| verify_cleanup_ui.mjs | Test | 无损浏览器回归：弹窗宽度、加载反馈、删除按钮悬停/键盘/触屏及任务批量清理 |
| verify_publication_ui.mjs | Test | 无损授权回显/全选、长期密钥、公开侧栏删除/隐私、桌面移动截图与可选真实地图嵌入验收 |
| verify_publication_map.py | Test | 只读复用成功地图结果，读取真实 MCP HTML 并生成短期兼容票据；不改发布授权或版本 |
