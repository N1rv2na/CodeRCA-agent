# CRCA-001 — 建立 Manifest-to-Run 纵向骨架

## Priority

P0

## Milestone

M0 — Walking Skeleton & Risk Gates

## Background

CodeRCA 需要一个由 CLI 和后续 Evaluation Harness 共用的最高测试缝。若入口、Diagnosis Run 和产物合同在早期没有贯通，后续状态机、工具和评测容易形成彼此独立的横向模块。

## Goal

让本地操作者提交最小合法 Task Manifest 后，通过 Diagnosis Application Service 创建一次可审计的 Diagnosis Run，并得到终态摘要与运行产物。

## Scope

- 定义最小版本化 Task Manifest 及其校验入口。
- 建立 CLI、Diagnosis Application Service、FakeModelProvider 和运行目录之间的纵向调用路径。
- 写入 Manifest 快照、JSONL 事件和最小 JSON Root Cause Report。
- CLI 显示 Run ID、生命周期摘要、停止原因和运行目录。
- 建立项目打包、测试入口和默认无 API Key、网络或 GPU 的测试环境。

## Out of Scope

- 完整诊断状态机和受约束 ReAct。
- 五个真实工具、RAG、Docker 和补丁 Validation。
- 真实云端模型 API。
- GitHub Issue、Web API、数据库或后台执行。

## Technical Approach

以 Diagnosis Application Service 作为唯一应用级入口。CLI 只负责输入输出适配；FakeModelProvider 返回确定性的最小合法响应；运行记录遵循每个 Diagnosis Run 一个目录的持久化边界。首个纵向测试从 Task Manifest 输入一直观察到终态报告和运行文件，而不是直接测试内部组件。

## Implementation Steps

1. 固定最小 Task Manifest Schema、版本字段与错误表达。
2. 定义 Diagnosis Application Service 的请求与结果合同。
3. 实现 FakeModelProvider 驱动的最小终态路径。
4. 建立 Diagnosis Run 目录、事件流、报告和 Manifest 快照写入。
5. 接入非交互式 CLI，并显示关键结果引用。
6. 增加从 CLI/应用服务到运行产物的自动化纵向测试。

## Acceptance Criteria

- [ ] 合法的最小 Task Manifest 能通过 CLI 创建唯一 Diagnosis Run。
- [ ] CLI 与测试均通过同一个 Diagnosis Application Service 启动运行。
- [ ] 运行结束后存在 Manifest 快照、合法 JSONL 事件和最小 JSON 报告。
- [ ] CLI 输出 Run ID、终态、停止原因和运行目录。
- [ ] 非法 Manifest 在创建 Diagnosis Run 前失败，并给出结构化错误。
- [ ] 默认自动化测试不需要 API Key、GPU、网络、Docker 或真实模型 API。

## Testing Strategy

- 用合法和非法 Manifest fixture 进行 Schema 合同测试。
- 通过应用服务执行 FakeModelProvider 纵向测试，验证公开结果与运行产物。
- 对 CLI 做薄适配器测试，确保其不复制应用编排逻辑。
- 解析每行 JSONL 和最终 JSON，验证格式而非内部调用顺序。

## Dependencies

None — can start immediately.

## Risks

- 过早把临时文件布局当成稳定存储 API；仅承诺 ADR-0008 中的产物类别。
- Walking Skeleton 被扩展成完整状态机；本 Ticket 只建立测试缝和端到端形状。

## Estimated Effort

0.5 engineer-day

## Related Spec Sections

- Solution
- User Stories 1–5, 17–18, 33–34, 43
- Implementation Decisions 2–5, 36–38
- Testing Decisions 1–6, 21

## Related ADRs

- ADR-0008 — 两周 MVP 按 Diagnosis Run 目录保存记录
- ADR-0012 — 使用可配置的 OpenAI-compatible 云端模型 Provider
