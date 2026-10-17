# CRCA-004 — 形成单个初始 Active Hypothesis

## Priority

P0

## Milestone

M1 — Evidence-Driven Diagnosis

## Background

CodeRCA 的核心招聘信号不是自由对话式 ReAct，而是由程序维护生命周期和不变量、模型负责有限诊断决策。初始阶段只有 Task 与 CI Failure，过早形成并冻结多个候选会把弱猜测固化为搜索空间。

## Goal

让 Diagnosis Run 经过合法生命周期只形成 H1，并建立 single-active、append-only H1～H3 History、受限 Schema correction 与 decision-specific reconstructed context 的基础。

## Scope

- 实现 Preparing、Forming Hypothesis、Diagnosing 和失败时 Finalizing 的最小状态路径。
- 定义只返回一个 Proposal 的 `FormHypothesisDecision`，ID 由程序分配。
- 首次只形成 H1；同一时刻最多一个 Active Hypothesis。
- 建立 H1～H3 append-only History、rejected no-revival、no-H4 和 Reformulation 前置约束。
- 建立 H1、Experiment、Evidence、Hypothesis Assessment、Reformulation 和 Validation 的确定性 Context View 基础。
- 从 Task Manifest 安全解析 CI artifact，并只把 bounded excerpt 放入 Working Context。
- Schema 首次失败允许一次明确纠错，第二次失败产生 Schema Failure。

## Out of Scope

- 真实 Tool Runtime、Tool 执行和 model-driven diagnosis loop。
- Evidence Interpretation、Hypothesis Assessment 和 H2/H3 的应用层自动 Reformulation。
- 补丁、Validation、RAG 和 Evaluation Harness。

## Technical Approach

使用轻量显式状态机控制生命周期。Hypothesis 包含程序分配的稳定 ID、位置、机制、falsification criterion、可选 Evidence basis 和状态。状态机维护 append-only History 与预算；模型不能生成 ID、覆盖历史或写状态。`ContextBuilder` 根据 Decision Type 从结构化状态投影 Working Context，Raw Model Response 与 Tool Result 只保存在 Run Artifact 中。

## Implementation Steps

1. 将复数形成合同改为单个 Proposal，并由程序分配 H1。
2. 实现 single-active、H1～H3 History、no revival/no H4 与形成前置条件。
3. 实现确定性的 decision-specific ContextBuilder 基础。
4. 安全解析 Manifest 相对 CI artifact，拒绝目录逃逸并限制片段长度。
5. 保留一次 Schema correction 与 Schema Failure 路径。
6. 更新 CLI、事件、报告和模型响应 Artifact 的 singular 语义。

## Acceptance Criteria

- [x] 合法初始运行只形成一个 H1，ID 由程序分配。
- [x] 有 Active Hypothesis 时不能形成下一个；H1 ended 后才能形成 H2。
- [x] History 只允许 H1、H2、H3 顺序追加，不允许 H4、覆盖或复活 rejected H。
- [x] H2/H3 Proposal 必须携带推动 Reformulation 的 Evidence basis。
- [x] Context View 按 Decision 选择相关状态，不包含完整 Conversation History 或全部 Model Response。
- [x] 大 Observation 只以 bounded excerpt 与 Artifact ref 进入 Context。
- [x] CI artifact 从 Task 目录内安全解析，路径逃逸被拒绝。
- [x] 首次结构失败允许一次纠错；再次失败产生 Schema Failure。
- [x] CLI 和事件流可观察 H1、当前阶段和失败分类。

## Testing Strategy

- 表驱动验证合法和非法生命周期转换。
- 验证 single-active、reject-before-H2、rejected no-revival、H2/H3 顺序和 no-H4。
- 分别验证 H1、Experiment、Evidence、Hypothesis Assessment、Reformulation 和 Validation Context View。
- 验证 Context 不回放完整历史，并对大 Observation 使用 bounded excerpt。
- 验证 CI artifact 内容而非路径字符串进入 H1 Context。
- 用 FakeModelProvider 覆盖首次成功、一次纠错成功和二次失败。

## Dependencies

- CRCA-001 — 建立 Manifest-to-Run 纵向骨架
- CRCA-003 — 建立 OpenAI-compatible 模型兼容性门禁

## Risks

- ContextBuilder 过早发展为通用 Memory Framework；本 Ticket 只允许固定 Decision View 与确定性选择规则。
- 为证明未来 Loop 而提前实现 Tool Runtime；本 Ticket 只冻结合同和状态不变量。

## Estimated Effort

1 engineer-day

## Related Spec Sections

- User Stories 5–7, 16–17, 21–22, 25–26, 35–39, 53–54
- Implementation Decisions 6–14, 24–25
- Testing Decisions 1, 7–12

## Related ADRs

- ADR-0014 — 单 Active Hypothesis 与按决策重建上下文
- ADR-0008 — 两周 MVP 按 Diagnosis Run 目录保存记录
- ADR-0013 — 本地 Schema 校验与显式 Structured Output Mode
