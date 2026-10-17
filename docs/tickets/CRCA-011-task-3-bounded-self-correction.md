# CRCA-011 — 使用 Task 3 验证 Bounded Self-Correction

## Priority

P1

## Milestone

M3 — Retrieval & Generalization Evidence

## Background

Task 1 和 Task 2 可以证明诊断闭环与 RAG，但未必证明 Agent 能纠正错误的初始诊断方向。Task 3 用一个对初始信息合理但错误的 H1，以及一个具有区分力的测试 Experiment，展示 Contradicting Evidence 如何结束 H1 并驱动 H2 Reformulation。

## Goal

在核心 Prompt、Schema 和工具策略冻结后，以一个未用于调试核心流程的故障任务证明 falsification、reject-before-reformulate、诊断知识复用和 bounded self-correction 真实发生。

## Scope

- 在同一冻结仓库与镜像中构造 Task 3。
- 保证初始信息可以产生一个合理但错误、可证伪的 H1。
- 设计一个注册测试 Experiment，其 Observation 能反驳 H1。
- 冻结 Manifest、Ground Truth 和关键 Trajectory 期望。
- 使用真实模型执行端到端 Diagnosis Run。
- 记录 H1 rejection、由真实 Evidence ID 组成的 H2 Evidence Basis、最终 Hypothesis、补丁和 Validation。

## Out of Scope

- 多 Active Hypothesis、Candidate Ranking、Evidence Score 或 rejected H revival。
- 多次重复运行、稳定性统计、LLM Judge 或大规模泛化评测。
- 为通过 Task 3 重新设计核心 Prompt、Schema 或工具策略。

## Technical Approach

Task 3 在核心行为冻结后加入，避免把 Agent 针对任务手工调成固定流水线。Ground Truth 不要求私有思维链，而是定义可观察 Trajectory：空 Evidence Basis 的 H1、声明 falsification relevance 的测试 Experiment、真实 Observation、针对 H1 的 Contradicting Evidence、H1 rejected、通过独立 Reformulation 合同引用该 Evidence ID 的 H2，以及最终 supported Hypothesis。H2 Context 必须来自结构化 State 与选定 Observation，不重放完整 Conversation History。

## Implementation Steps

1. 确认核心 Prompt、阶段 Schema 和工具策略冻结点。
2. 构造初始表象支持错误 H1、但 Experiment 可证伪的业务逻辑回归。
3. 注册能够否定 H1 的最小测试命令。
4. 编写 Manifest、独立 Ground Truth 和 Trajectory 期望。
5. 用 FakeModelProvider 验证合法 self-correction 与违规轨迹检测。
6. 使用真实模型执行并人工检查最终因果链。

## Acceptance Criteria

- [ ] Task 3 在同一仓库和镜像中稳定复现，并与 Agent 可见答案隔离。
- [ ] 初始运行只形成 H1，且 H1 对初始输入合理但与真实 Root Cause 不同。
- [ ] `run_tests` Experiment 绑定 H1，并预先声明目的、预期 Observation 和 falsification relevance。
- [ ] 实际 Observation 产生引用真实 Artifact 的 Contradicting Evidence。
- [ ] 程序先把 H1 转为 rejected，再允许形成 H2。
- [ ] H2 的 `evidence_basis` 只包含程序验证的 Contradicting Evidence ID，并且机制与 H1 有实质区别。
- [ ] 最终只有 supported Hypothesis 进入补丁与 Validation。
- [ ] Task 3 加入后不针对该任务修改已冻结的核心 Prompt、Schema 或工具策略。

## Testing Strategy

- 对 Manifest、Ground Truth、复现性和输入隔离执行任务合同测试。
- 用合法轨迹以及 parallel active H、H1 自由文本 Basis、H2 missing/unknown/duplicate Evidence ID、H revival、H4 等违规轨迹测试验收器。
- 用 FakeModelProvider 确定性地产生 H1 reject→H2 supported 路径。
- 显式运行真实模型，并人工核查 H1 合理性、H2 差异和因果机制。

## Dependencies

- CRCA-006 — 在最小 Docker 边界中运行测试 Experiment
- CRCA-007 — 完成 Supported Hypothesis 补丁 Validation 闭环
- CRCA-010 — 使用 Task 2 验证 RAG 诊断路径

## Risks

- H1 明显荒谬，无法证明 self-correction；Ground Truth 必须说明 H1 为什么与初始 Evidence 相容。
- Observation 只支持 H2 而没有否定 H1；验收要求明确 Contradicting Evidence。
- Task 3 演变为 Prompt 调参；若时间不足，按 Spec 删除该任务而不是削弱不变量。

## Estimated Effort

0.5 engineer-day

## Related Spec Sections

- User Stories 8–12, 23, 38–42, 55–57, 60–62, 66–70
- Implementation Decisions 10–17, 24–25, 40–42, 44
- Testing Decisions 8–12, 23–27

## Related ADRs

- ADR-0014 — 单 Active Hypothesis 与按决策重建上下文
- ADR-0008 — 两周 MVP 按 Diagnosis Run 目录保存记录
- ADR-0010 — 两周 MVP 采用最小 Docker 执行边界
