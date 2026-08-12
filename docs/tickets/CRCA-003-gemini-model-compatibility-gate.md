# CRCA-003 — 建立 Gemini 模型兼容性门禁

## Parent

- #1 — Implement CodeRCA Two-Week MVP

## Priority

P0

## Milestone

M0 — Walking Skeleton & Risk Gates

## Background

CodeRCA MVP 已冻结为只调用 Gemini Developer API 的 `gemini-3.6-flash`。如果到开发末期才发现凭证、协议、结构化输出或补丁能力不满足 Agent 合同，状态机、Prompt 和真实 Evaluation 都可能被迫返工。云端调用还引入了认证、配额、限流、网络和源码隐私边界，必须在主体 Agent 开发前显式验证。

## Goal

用一个固定的 Gemini ModelProvider、preflight 和最小能力探针，在主体 Agent 开发前冻结可用配置，并让不兼容或越过数据边界的真实运行明确失败。

## Scope

- 定义 Gemini OpenAI-compatible HTTPS 请求、响应、超时和错误合同。
- 固定基础地址、`gemini-3.6-flash` 模型标识和关键生成参数。
- 提供 Diagnosis Run 启动前的凭证、服务与模型可用性检查。
- 建立四类小探针：阶段 Schema、合法工具参数、Evidence 更新和小型 Python 补丁。
- 记录模型标识、关键生成参数、原始响应引用和探针结果，同时保证凭证不落盘。
- 将 Gemini 扩展响应字段作为不透明 Provider 元数据处理。
- 自动化测试使用 FakeModelProvider 验证同一 Provider 抽象。

## Out of Scope

- 本地模型、其他云端提供商、多真实模型适配、自动路由或运行期降级。
- 模型下载、加载、量化、CUDA 或显存管理。
- API Key 申请、计费管理、配额购买或通用 Secret Manager。
- 性能 Benchmark、模型排行榜、正式诊断 Prompt 优化和三项 Agent Evaluation。

## Technical Approach

在现有 ModelProvider 抽象后实现唯一的 `GeminiModelProvider`，通过 `https://generativelanguage.googleapis.com/v1beta/openai/` 调用 `gemini-3.6-flash`。Provider 只从宿主环境变量读取 `GEMINI_API_KEY`，并通过阶段 Schema 对响应做显式校验；不通过模糊解析修复非法响应。

preflight 先验证配置和最小请求，再运行四类冻结探针。真实探针只允许使用公开、非敏感 fixture，并且必须显式启动。若响应包含 `extra_content.google.thought_signature`，Provider 原样保留并在继续同一提供商交互时按协议回传；Agent 核心不解释该字段，也不把它转成 Evidence 或私有思维链。

## Implementation Steps

1. 冻结 Gemini Provider 配置、HTTPS 请求响应和失败分类。
2. 实现 `GEMINI_API_KEY`、服务连通性、模型标识和请求超时的 preflight。
3. 编写四类最小能力探针及其结构化验收规则。
4. 为冻结参数提供显式真实探针入口，并保存脱敏后的结果与原始响应引用。
5. 增加 FakeModelProvider 与 GeminiModelProvider 的共享合同测试和模拟 HTTP 测试。
6. 验证 API Key 不会进入 Prompt、Task Manifest、运行产物、日志、Tool 参数或 Docker 环境。
7. 记录失败诊断信息以及需要通过新 ADR 重新选择模型的边界。

## Acceptance Criteria

- [ ] 真实 Provider 只通过固定 Gemini OpenAI-compatible HTTPS 接口调用 `gemini-3.6-flash`，不包含本地或第二云端模型后端。
- [ ] `GEMINI_API_KEY` 只从宿主环境读取，且不会出现在 Prompt、Task Manifest、运行产物、日志、Tool 参数、Git 或 Docker 容器中。
- [ ] preflight 能区分缺少凭证、认证失败、权限或配额失败、限流、模型不可用、网络或超时以及非法响应。
- [ ] 冻结模型与参数能连续三次分别输出合法阶段对象、工具参数、Contradicting Evidence 更新和可应用的小型 Python patch。
- [ ] 探针保存模型标识、生成配置、原始响应引用和校验结果，但不保存 API Key。
- [ ] `thought_signature` 等 Gemini 扩展字段只作为不透明 Provider 元数据保留，不进入 Evidence、Observation 或报告因果字段。
- [ ] preflight 或探针不通过会明确失败，不进入正式 Diagnosis Run，也不会静默切换模型。
- [ ] 默认自动化测试使用 FakeModelProvider，不需要 API Key、GPU 或网络。

## Testing Strategy

- 用模拟 HTTP transport 覆盖成功、缺少凭证、认证、权限、配额、限流、超时、网络错误、非 JSON、错误状态码和错误模型场景。
- 对 FakeModelProvider 和 GeminiModelProvider 执行共享合同测试。
- 将真实 Gemini 探针标记为显式检查，避免进入默认 CI 或意外消费配额。
- 使用不可应用 patch 和非法工具参数 fixture 验证门禁确实拒绝。
- 用哨兵 API Key 检查 Prompt、日志、运行目录、Tool 调用和 Docker 环境均没有凭证泄漏。
- 用带 `thought_signature` 的响应 fixture 验证元数据原样保留且不污染领域对象。

## Dependencies

- #2 (CRCA-001) — 建立 Manifest-to-Run 纵向骨架

## Risks

- Gemini 模型或兼容接口行为变化；固定模型标识和请求参数，并用 preflight 与探针在真实运行前失败。
- 免费配额、限流或网络波动造成基础设施失败；显式分类并保存脱敏诊断信息，不把它误判为 RCA 失败。
- 为容忍非法响应而破坏阶段 Schema；门禁失败时阻断运行，不扩大模糊解析范围。
- 公开基准之外的源代码被发送到云端；真实入口只接受冻结公开任务，并测试凭证与数据边界。

## Estimated Effort

1 engineer-day

## Related Spec Sections

- User Stories 17, 25, 34–35, 47–50, 73, 76
- Implementation Decisions 8–9, 26–28, 33
- Testing Decisions 5–6, 11, 19, 21
- Further Notes — 模型能力探针

## Related ADRs

- ADR-0011 — 两周 MVP 使用单一 Gemini 云端模型 API，取代 ADR-0009
