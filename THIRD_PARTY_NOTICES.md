# 第三方组件说明

本文件不替代上游许可证，也不是完整的许可证合规审计。

- `backend/vendor/cesium/`：随仓库分发的 CesiumJS 1.129 静态资源，用于地图显示。保留目录中的 `LICENSE.md` 和源文件声明，不要当作普通缓存删除。
- React、Ant Design、Vite、FastAPI、MCP Python SDK 等通过 npm / pip 安装，版本见 lockfile 和 requirements，许可以上游随包文件为准。
- Ultralytics、YOLOv5、PyTorch 和用户权重属于独立/可选组件，本项目许可证不覆盖它们；分发或提供服务前另行核对相关代码和权重许可。
- 地图瓦片、模型/MCP/API 服务受各自条款约束，保留地图署名；外部数据不自动成为本项目授权内容。

项目由 Fanwu 智能体模块独立重构，设计曾参考 DeepSeek Harness、OpenAkita。发布者应确认有权公开自有代码，并核对任何实际复制的代码、素材及上游许可；设计参考不代表这些项目为本项目背书。
