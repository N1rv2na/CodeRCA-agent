# CRCA-003 — 建立 OpenAI-compatible 模型兼容性门禁

## Priority

P0

## Milestone

M0 — Walking Skeleton & Risk Gates

## Background

CodeRCA 的 Diagnosis Run 依赖操作者选择的云端模型，但 Agent 核心不应绑定任何具体提供商或厂商 SDK。不同 OpenAI-compatible 端点对 strict JSON Schema、错误响应和补丁输出的支持仍可能存在差异；若到开发末期才发现不兼容，状态机和 Prompt 都可能被迫返工。

## Goal

实现单一通用的 OpenAI-compatible ModelProvider 和显式 Model Compatibility Gate，在主体 Agent 开发前判断当前 Model Configuration 是否满足 CodeRCA 所需的最小协议与能力合同。

## Scope

- 通过 `CODERCA_MODEL_BASE_URL`、`CODERCA_MODEL_ID` 和 `CODERCA_MODEL_API_KEY` 读取单一 Model Configuration。
- 定义 OpenAI-compatible Chat Completions 请求、响应、超时和错误合同。
- 固定非流式、`temperature=0`、strict JSON Schema 和本地 Pydantic 校验。
- 提供一次 preflight 与四个一次性探针：阶段 Schema、合法工具参数、Evidence 更新和小型 Python 补丁。
- 生成不包含 API Key、Authorization Header 或敏感响应正文的 Model Compatibility Report。
- 自动化测试使用 FakeModelProvider 和伪 HTTP 服务验证同一 Provider 抽象。

## Out of Scope

- 本地模型下载、加载、量化、CUDA 或显存管理。
- 原生厂商 SDK、服务发现、多真实后端、模型路由、自动选择、负载均衡或回退。
- 模型排行榜、性能 Benchmark、重复稳定性实验或正式诊断 Prompt 优化。
- 让兼容性报告授权、阻止或自动配置 Diagnosis Run。

## Technical Approach

ModelProvider 只依赖 OpenAI-compatible Chat Completions 协议。`CODERCA_MODEL_BASE_URL` 规范化后追加 `/chat/completions`，请求使用 Bearer Token，且每次只面向一个模型。结构化响应必须同时通过服务端 strict JSON Schema 约束和本地 Pydantic 校验，不通过模糊正则恢复。

Model Compatibility Gate 是操作者显式运行的建议性检查：最多发起一次 preflight 和四个探针，每类只执行一次，总请求数不超过五次。失败产生非零退出码和脱敏报告，但 Diagnosis Run 不读取历史门禁报告，也不以其作为授权条件。

## Implementation Steps

1. 定义 Model Configuration、Provider 请求响应和通用失败分类。
2. 实现 base URL 规范化、Bearer 鉴权、请求超时和 Chat Completions 调用。
3. 为阶段输出接入 strict JSON Schema 请求和本地 Pydantic 校验。
4. 实现一次 preflight 与四个一次性能力探针。
5. 写入脱敏 Model Compatibility Report，并为不兼容结果返回非零退出码。
6. 增加 FakeModelProvider、伪 HTTP 服务和 CLI 合同测试。

## Acceptance Criteria

- [ ] Provider 只从三个规定环境变量读取单一端点、模型 ID 和 API Key；缺失配置产生可操作的结构化错误。
- [ ] 请求发往规范化 base URL 的 `/chat/completions`，使用 Bearer Token、非流式、`temperature=0`、`response_format.type=json_schema` 和 `json_schema.strict=true`。
- [ ] 响应必须通过本地 Pydantic Schema 校验；超时、网络失败、HTTP 错误、非法 JSON、缺失字段和 Schema 不匹配具有通用失败分类。
- [ ] 显式门禁最多执行一次 preflight 与四个一次性探针，总请求数不超过五次。
- [ ] 四个探针分别验收阶段对象、合法工具参数、Evidence 更新和可应用的小型 Python patch。
- [ ] Model Compatibility Report 记录脱敏端点、模型 ID、请求配置、探针结果和错误分类，但不包含 API Key、Authorization Header 或敏感响应正文。
- [ ] 门禁失败返回非零退出码，但不会创建或修改 Diagnosis Run 授权状态。
- [ ] 默认自动化测试使用 FakeModelProvider 或伪 HTTP 服务，不读取真实 API Key、不访问网络且不需要 GPU。

## Testing Strategy

- 用伪 HTTP 服务覆盖成功、超时、网络失败、非 JSON、错误状态码、缺失字段和 Schema 不匹配。
- 断言请求 URL、Bearer Header、模型 ID、非流式、`temperature=0` 和 strict JSON Schema 参数。
- 用请求计数器验证一次 preflight、四个探针和五次总调用上限。
- 使用不可应用 patch 和非法工具参数 fixture 验证相应探针失败。
- 检查报告和日志脱敏，并验证失败不会建立 Diagnosis Run 门禁状态。
- 将真实端点检查保留为操作者显式运行的本地命令，不纳入默认 CI。

## Dependencies

- CRCA-001 — 建立 Manifest-to-Run 纵向骨架

## Risks

- 提供商宣称 OpenAI-compatible 但 strict JSON Schema 行为不同；用门禁显式暴露差异，不在 Agent 核心加入厂商分支。
- 单次探针不能证明长期稳定性；报告只声明当次兼容结果，不表达成功概率或 Benchmark 结论。
- 错误处理泄漏凭证；测试所有错误与报告路径的脱敏行为。

## Estimated Effort

1 engineer-day

## Related Spec Sections

- User Stories 17, 35–36, 47–50, 73, 76
- Implementation Decisions 8–9, 26–28, 33
- Testing Decisions 5–6, 11, 19
- Further Notes — Model Compatibility Gate

## Related ADRs

- ADR-0012 — 使用可配置的 OpenAI-compatible 云端模型 Provider
