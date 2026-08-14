# CRCA-003 — 建立 OpenAI-compatible 模型兼容性门禁

## Priority

P0

## Milestone

M0 — Walking Skeleton & Risk Gates

## Background

CodeRCA 的 Diagnosis Run 依赖操作者选择的云端模型，但 Agent Core 不应绑定具体供应商、厂商 SDK 或某一个可选 API feature。MiniMax-M3 与 ModelScope/GLM-5.2 的兼容性实验表明，普通 Chat Completions 和 JSON 输出可用，并不意味着 Endpoint 能正确执行 OpenAI native strict JSON Schema。

系统真正需要保证的是：每次结构化模型交互都经过确定性本地 JSON 解析和 Pydantic 校验，只有成功后的对象才能进入 Agent State。Provider 原生 strict JSON Schema 是优先增强，而不是通用最低要求。

## Goal

实现单一通用 OpenAI-compatible ModelProvider、两种显式 Structured Output Mode 和 Model Compatibility Gate，在主体 Agent 开发前判断当前 Model Configuration 能否产生通过 CodeRCA 本地严格校验的结构化结果。

## Scope

- 通过 `CODERCA_MODEL_BASE_URL`、`CODERCA_MODEL_ID`、`CODERCA_MODEL_API_KEY`、`CODERCA_MODEL_STRUCTURED_OUTPUT_MODE` 和可选 `CODERCA_MODEL_REQUEST_EXTENSIONS` 读取单一 Model Configuration。
- Request Extensions 必须是显式 JSON object，在 HTTP 边界附加且不得覆盖 CodeRCA 控制的核心请求字段。
- Structured Output Mode 只允许 `native_json_schema` 和 `json_text`，不按 Provider 或 Model 名称推断。
- 固定非流式与 `temperature=0`；native mode 发送 strict JSON Schema，json-text mode 不发送 `response_format`。
- 所有结构化输出直接执行 `json.loads` 和本地 Pydantic 校验，成功前不得进入 Agent State。
- 提供一次 preflight 与四个一次性探针：阶段 Schema、合法工具参数、Evidence 更新和小型 Python 补丁。
- 生成记录 mode 且不包含 API Key、Authorization Header 或敏感响应正文的 Model Compatibility Report。
- 自动化测试使用 FakeModelProvider 和伪 HTTP 服务验证同一 Provider 抽象。

## Out of Scope

- Function/Tool Calling structured output、Provider 自动探测或按品牌硬编码。
- Markdown fence、`<think>`、JSON 子串清理，字段猜测或 fuzzy repair。
- retry framework；CRCA-003 对非法 JSON 与 Schema mismatch 立即失败。
- 任意未校验 `extra_body`、Provider plugin/customizer framework、原生厂商 SDK、多真实后端、模型路由、自动选择、负载均衡或回退。
- 完整 Agent State Machine、诊断 Tool Runtime、RAG 或 Evaluation Harness。
- 本地模型下载、加载、量化、CUDA 或显存管理。
- 模型排行榜、性能 Benchmark、重复稳定性实验或正式诊断 Prompt 优化。
- 让兼容性报告授权、阻止或自动配置 Diagnosis Run。

## Technical Approach

ModelProvider 只依赖 OpenAI-compatible Chat Completions。Base URL 规范化后追加 `/chat/completions`，请求使用 Bearer Token，且一次进程只面向一个 Model Configuration。

`native_json_schema` 在请求中加入阶段 JSON Schema 与 `strict=true`；`json_text` 不发送 `response_format`，而在 system prompt 中要求只返回符合阶段 Schema 的原始 JSON。两条路径之后共享完全相同的本地边界：提取字符串形式的 `message.content`，直接 `json.loads`，再执行 Pydantic validation。现有 `invalid_json`、`invalid_response` 与 `schema_mismatch` 足以表达失败。

Generic Provider 不删除 reasoning 标签，也不按品牌关闭 reasoning。如果 `<think>` 或任何自然语言进入 `message.content`，`json_text` 明确失败。操作者可以显式提供少量 Endpoint Request Extensions；Provider 先构造标准 payload，拒绝其中的 `model`、`messages`、`stream`、`temperature` 和 `response_format` 后再合并，且不包含任何品牌判断。

Model Compatibility Gate 在配置 mode 下最多发起一次 preflight 和四个相同探针，总请求数不超过五次。失败 fail-fast，产生非零退出码和脱敏报告；Diagnosis Run 不读取历史报告，也不以其作为授权条件。

## Implementation Steps

1. 定义 Structured Output Mode 与受控 Request Extensions，并把它们加入 Model Configuration 的显式环境配置。
2. 为 native 与 json-text mode 构造不同请求，但复用响应解析和 Pydantic 校验。
3. 保留五个 probe、fail-fast、Artifact 脱敏与 CLI 退出码合同，并在报告中记录 mode。
4. 增加两种 mode 的请求、严格失败、本地校验、Gate parity 与 CLI 回归测试。
5. 同步领域词汇、设计、Specification 与 ADR。

## Acceptance Criteria

- [ ] Provider 从规定环境变量读取单一 Endpoint、Model ID、API Key、Structured Output Mode 和可选 Request Extensions；空扩展视为 `{}`，非法 JSON 或非 object 值产生 `configuration_error`。
- [ ] Request Extensions 在标准 payload 后合并，能够为 `json_text` 附加 `reasoning_split` 等显式 JSON 参数；`model`、`messages`、`stream`、`temperature` 和 `response_format` 冲突立即产生 `configuration_error`。
- [ ] 两种 mode 都请求规范化 `/chat/completions`，使用 Bearer Token、非流式和 `temperature=0`。
- [ ] `native_json_schema` 请求包含 `response_format.type=json_schema`、阶段 Schema 与 `strict=true`，并继续执行本地 Pydantic 校验。
- [ ] `json_text` 请求不包含 `response_format`；纯 JSON 可通过，Markdown fence、`<think>` 加 JSON、自然语言加 JSON 和 Schema mismatch 均明确失败。
- [ ] 两种 mode 都在 JSON 解析与 Pydantic validation 成功前阻止输出进入 Agent State，不做 fuzzy extraction 或 repair，单次失败不自动 retry。
- [ ] 两种 mode 运行相同的一次 preflight 与四个能力探针，总请求数不超过五次，并保持 fail-fast。
- [ ] Model Compatibility Report Schema 升级为版本 `2`，记录 `structured_output_mode`、脱敏 Endpoint、Model ID、请求配置、探针结果、原始响应引用和错误分类，但不包含 secret。
- [ ] Gate 失败返回非零退出码，不创建或修改 Diagnosis Run 授权状态；默认测试不读取真实 API Key、不访问外部网络且不需要 GPU。

## Testing Strategy

- 断言 native 请求包含 strict JSON Schema，json-text 请求完全省略 `response_format`。
- 对两种 mode 使用有效响应和 Schema mismatch，证明本地 Pydantic validation 始终执行。
- 对 json-text mode 测试纯 JSON、fenced JSON、reasoning 标签、自然语言前缀，并断言没有第二次请求。
- 测试空、合法、非法、非 object 和受保护键 Request Extensions，以及无 Provider/Model 名称推断的 payload 合并。
- 对两种 mode 使用同一 FakeModelProvider probe fixture，验证五个 probe、调用顺序、fail-fast 与报告 mode。
- 用伪 HTTP 服务覆盖成功、超时、网络失败、非 JSON、错误状态码、缺失字段和 Schema mismatch。
- 检查报告、Artifact、错误和 CLI 输出的脱敏与退出码；真实 Endpoint 检查只由操作者显式运行。

## Dependencies

- CRCA-001 — 建立 Manifest-to-Run 纵向骨架

## Risks

- `json_text` 比 native strict JSON Schema 更容易产生格式错误；当前通过 Gate 暴露，不在此 Ticket 增加 retry。
- Endpoint 把 reasoning 写入 `message.content` 会导致 json-text mode 失败；generic Provider 不做品牌修复。
- 单次 probe 不能证明长期稳定性；报告只声明当次配置与 mode 的兼容结果。
- 错误处理泄漏凭证；所有模式都必须经过相同脱敏路径。
- Request Extension 值可能含 Endpoint 私有配置；兼容性报告不持久化这些值，响应中回显的字符串值在写入 Artifact 前脱敏。

## Estimated Effort

1 engineer-day

## Related Spec Sections

- User Stories 17, 35–36, 47–50, 73, 76
- Implementation Decisions 8–9, 26–28, 33
- Testing Decisions 5–6, 11, 19
- Further Notes — Model Compatibility Gate

## Related ADRs

- ADR-0013 — 本地 Schema 校验与显式 Structured Output Mode
