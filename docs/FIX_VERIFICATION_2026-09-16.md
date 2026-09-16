# 2026-09-16 三项问题修复与验收

## 地图

新日志确认初始化成功后出现 ConnectError；上次仅初始化重试未覆盖后续 POST 的连接建立。HTTPX transport 现对连接错误重试两次（请求尚未发送），不重放读超时或已执行工具。AnyIO BrokenResourceError/EndOfStream 纳入网络故障分类，资源读取可重连，避免裸 500。

真实后台 Worker、模型决策、审批及工具调用连续三次通过。任务：79403c70-a923-44f2-b000-50c357067ce1、f46b0c01-7f48-4045-ba1b-2e0dc9228467、48c05db2-81f1-442c-93f1-143920143c43。最后一条任务结果创建地图票据；Edge 实际渲染画布，67 个瓦片请求成功，无页面脚本异常，截图目视确认北京天安门附近地图。

## 记忆

对照原 AgentMemoryServiceImpl 的 governUserMemory/buildGovernancePrompt/validateOperations/applyOperations：统一显式与自动治理；只读取用户原始消息和已有可见记忆；operations JSON + 一次校验纠正重试；六类记忆、0.70 置信度门槛、entity/attribute 稳定槽；MySQL 用户行锁串行化治理，事务更新；失败或识别到联系方式/身份证信息进入待审核。显式工具成功后不再重复自动提取。

新增可空 meta 列，无删除或重写旧数据。历史记录显示未分类，可通过编辑或治理建议确认分类。已有重复项未自动删除，分析建议支持手动停用。召回采用向量/关键词混合、重要性与时效排序，最多条数和 2000 token 文本预算；实际使用仍由回答模型决定。

结构化治理启用 JSON 输出，并对官方 DeepSeek 请求显式禁用思考模式；空白/不完整/无效决策进行一次纠正重试，不将 reasoning_content 冒充答案。

真实 DeepSeek 验证：新增姓名、异步重复消息、修改称呼每步均只留下一个记忆条目；现有用户“重复与冲突”审查成功返回建议，未应用。专用测试用户及其记忆已清理。

边界：不保证所有自然语言的语义去重准确；模型对槽命名和事实仍可能判断错误。隐私识别是有限规则，不是完备隐私分类器。治理上下文最多 200 条，长期大规模记忆还需独立压力与召回评测。

## 权重部署

错误原因是内置模板回退到后端 Python，缺少 ultralytics。现默认使用项目内独立 `.venv-yolo`，自定义解释器优先，并启动前检查依赖。实际已安装依赖并启动用户的 yolo11s.pt CPU 部署；使用 Ultralytics 自带 bus.jpg 经上传 API 和部署测试 API 完成真实检测，返回 bus/person 检测框与标注图。未改动 Fanwu 环境，未验证 CUDA/YOLOv5。

## 证据

- `data/fix-verification-20260916/`：memory.json、map-run-*.json、browser.json、map.png、inference.json、deployment.json。
- 54 项后端测试通过；前端生产构建通过（已有大包警告）。
- 本轮部署依赖安装在 `.venv-yolo`，MySQL 已升级至迁移 0003。
