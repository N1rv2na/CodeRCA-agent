# ADR-0011：两周 MVP 使用单一 Gemini 云端模型 API

- 状态：Accepted
- 日期：2026-08-13
- 取代：ADR-0009

## 背景

ADR-0009 基于“没有云端 API 预算”和“开发机只有 RTX 4060 Ti 8 GB”的前提，要求 MVP 连接外部本地模型服务。后续验证表明，项目已经具备可用的 Gemini API 凭证，而本地小模型的选择、部署、显存占用和结构输出稳定性会继续占用两周 MVP 的关键开发时间。

CodeRCA 的招聘信号是 Agent 工作流、Tool Runtime、Context Engineering、代码 RAG 和 Evaluation，而不是本地模型部署。项目需要一个质量足够、接口固定且能够尽早验证的真实模型边界，同时必须明确云端调用带来的网络、配额、凭证和源代码隐私风险。

2026-08-13 的手工兼容性探针已经验证 `gemini-3.6-flash` 能在冻结参数下连续三次完成以下四类输出：阶段 Schema、合法工具参数、Contradicting Evidence 更新和可应用的小型 Python 补丁。这些结果只证明候选模型通过最小能力门禁，不构成模型 Benchmark 或稳定性统计结论。

## 决策

CodeRCA MVP 只实现一个真实 `ModelProvider`：通过 HTTPS 调用 Google Gemini Developer API 的 OpenAI-compatible Chat Completions 接口，固定模型标识为 `gemini-3.6-flash`，固定基础地址为 `https://generativelanguage.googleapis.com/v1beta/openai/`。不实现本地模型后端、其他云端提供商、多模型路由、自动模型选择或运行期降级。

`GEMINI_API_KEY` 只从宿主进程环境变量读取。凭证不得进入 Prompt、Task Manifest、Diagnosis Run 产物、日志、SQLite、Git、任何 Tool 参数或 Docker 容器。真实云端调用只允许处理冻结的公开基准仓库；私有仓库、雇主代码和其他敏感源代码不属于 MVP 支持范围。

Provider 使用阶段级结构化 JSON 输出，不让模型直接绕过 Tool Runtime。若 Gemini 响应包含 `extra_content.google.thought_signature`，适配器将其作为不透明的提供商元数据原样保留，并在继续同一提供商交互时按协议回传；Agent 核心不得解释、改写或把它转换为 Evidence、Observation 或私有思维链。

真实运行前执行显式 preflight 和四类能力探针。Provider 必须区分缺少凭证、认证失败、权限或配额失败、限流、模型不可用、网络或超时以及非法响应。默认自动化测试继续使用 `FakeModelProvider`，不读取 API Key、不联网，也不消费 Gemini 配额。

诊断模型在云端运行。CodeRCA 不加载模型，不管理量化、CUDA、显存或本地诊断 GPU；代码 embedding 仍在索引阶段预计算，reranker 仍在 CPU 上处理小候选集。

## 备选方案

- 继续使用单一本地模型服务：避免源代码离开本机，但会把模型选择、部署和 8 GB 显存适配留在交付关键路径。
- 同时支持本地模型与 Gemini：增加适配、配置、测试和故障定位成本，不符合两周 MVP 的单后端边界。
- 使用 Gemini 原生 SDK：可直接暴露更多提供商能力，但会扩大第一版适配面；OpenAI-compatible HTTP 接口已经满足当前阶段 Schema 和响应合同。
- 使用动态模型别名或自动回退：可以提高可用性，但会降低运行配置的可复现性，并引入额外的成本与行为差异。

## 后果

- 正面：移除本地模型部署、量化和 GPU 适配风险，使开发时间回到 Agent 核心闭环。
- 正面：冻结单一真实后端、模型标识和协议，ModelProvider 仍可通过 Fake 实现进行确定性测试。
- 负面：真实 Diagnosis Run 依赖网络、Gemini 服务可用性、API 配额和提供商行为。
- 负面：云端请求会离开本机，因此 MVP 只能对公开基准代码执行真实调用，不能声称支持私有代码诊断。
- 中性：RTX 4060 Ti 不再是诊断模型的运行要求；本地检索组件仍按既有固定管线执行。
- 中性：若模型、协议或数据边界需要改变，必须新增 ADR，而不是在 Provider 中静默加入回退。
