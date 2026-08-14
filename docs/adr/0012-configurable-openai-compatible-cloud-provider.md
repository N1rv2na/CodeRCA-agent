# ADR-0012：使用单个可配置的 OpenAI-compatible 云端模型

- 状态：Superseded by ADR-0013
- 日期：2026-08-14
- 取代：ADR-0009、ADR-0011

## 背景

ADR-0009 把真实诊断绑定到本地模型服务，ADR-0011 又把同一边界绑定到 Gemini。Gemini 免费层的实际请求配额表明，供应商选择会随配额、价格和可用性改变；把供应商、模型标识、凭证名称和错误语义写入 Agent 核心，会让一次运行配置变化演变为架构返工。

CodeRCA 仍需要一个质量足够的云端模型完成真实 Agent 闭环，但 MVP 不需要多模型路由、自动回退或厂商原生 SDK。稳定边界应是 CodeRCA 所需的结构化交互合同，而不是某个供应商品牌。

## 决策

CodeRCA 只实现一个真实 `OpenAICompatibleModelProvider`，通过 OpenAI-compatible Chat Completions HTTPS 接口连接操作者配置的单个云端模型。一次进程和一次 Diagnosis Run 只使用一个 Model Configuration，不自动选择、切换或降级。

宿主环境使用固定变量 `CODERCA_MODEL_BASE_URL`、`CODERCA_MODEL_ID` 和 `CODERCA_MODEL_API_KEY`。Provider 规范化 Base URL 后调用 `/chat/completions`，使用 Bearer Authentication、非流式响应、`temperature=0` 和严格 `response_format.type=json_schema`。模型返回的 JSON 必须再次通过对应阶段的 Pydantic Contract；CodeRCA 不提取 Markdown JSON、不猜测字段，也不模糊修复非法结构。

API Key 不得进入 Prompt、Task Manifest、Run Manifest、Diagnosis Run 产物、日志、Git、Tool 参数或 Docker。真实云端调用只处理冻结的公开基准仓库及有界上下文，不支持私有仓库、雇主代码或其他敏感源码。供应商扩展字段只能作为不透明元数据保存，不得进入 Hypothesis、Evidence、Observation 或 Root Cause Report。

操作者可以显式运行 Model Compatibility Gate。门禁执行一次 preflight，以及阶段 Schema、合法 Tool 参数、Contradicting Evidence 更新和可应用 Python patch 四个单次探针，最多产生五次真实请求。Model Compatibility Report 只记录脱敏配置、探针结果、失败分类和原始响应引用；它不授权或阻止 Diagnosis Run，也不宣称模型具有统计稳定性或诊断正确性。

默认自动化测试继续使用 `FakeModelProvider`，不读取 API Key、不联网，也不消费云端配额。CodeRCA 不加载诊断模型，不管理量化、CUDA 或显存；embedding 和 reranker 的既有本地计算边界不变。

## 备选方案

- 固定单一云端供应商：实现最直接，但再次把配额和供应商变化传播到核心代码与文档。
- 同时实现多个厂商适配器：可以覆盖原生能力，但增加配置、测试、错误处理和维护矩阵。
- 恢复本地模型：避免源码离开本机，但重新引入模型选择、部署和有限显存适配风险。
- 增加自动路由或回退：提升可用性，但破坏单一可复现 Model Configuration，并扩大两周 MVP 范围。

## 后果

- 正面：供应商和模型成为运行配置，不再成为 Agent Core 的固定依赖。
- 正面：严格 `json_schema` 和本地 Contract 保持阶段输出边界清晰。
- 正面：操作者可以在不修改架构的情况下选择满足合同的云端模型。
- 负面：并非所有 OpenAI-compatible Endpoint 都支持严格 `json_schema`；不满足者不能通过门禁。
- 负面：云端调用仍受网络、配额、价格和公开源码数据边界约束。
- 中性：门禁是显式工程检查，不是运行时授权或模型质量 Evaluation。
