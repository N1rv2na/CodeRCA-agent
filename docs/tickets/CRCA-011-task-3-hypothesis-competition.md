# CRCA-011 — 使用 Task 3 验证 Hypothesis 竞争机制

## Priority

P1

## Milestone

M3 — Retrieval & Generalization Evidence

## Background

Task 1 和 Task 2 可以证明诊断闭环与 RAG，但未必证明 Agent 会根据新 Observation 改变候选排序。Task 3 用至少两个合理候选和一个有区分力的测试 Experiment，展示反证如何排除错误 Hypothesis。

## Goal

在核心 Prompt、Schema 和工具策略冻结后，以一个未用于调试核心流程的故障任务证明候选竞争、Contradicting Evidence 和动态排序真实发生。

## Scope

- 在同一冻结仓库与镜像中构造 Task 3。
- 保证初始信息支持至少两个合理且可区分的 Hypothesis。
- 设计一个注册测试 Experiment，其 Observation 能反驳至少一个错误候选。
- 冻结 Manifest、Ground Truth 和期望的关键轨迹性质。
- 使用通过门禁检查的已配置 OpenAI-compatible 云端模型执行端到端 Diagnosis Run。
- 记录排序变化、反证来源、Top-1 补丁和 Validation。

## Out of Scope

- 动态新增或复活 Hypothesis。
- 多次重复运行、稳定性统计、LLM Judge 或大规模泛化评测。
- 为通过 Task 3 重新设计核心 Prompt、Schema 或工具策略。

## Technical Approach

Task 3 只能在核心行为基本冻结后加入，避免把 Agent 针对该任务手工调成固定流水线。Ground Truth 不要求私有思维链，而是定义可观察轨迹：至少两个初始候选、一个声明预期的测试 Experiment、真实 Observation、针对错误候选的 Contradicting Evidence，以及由程序计算的排序变化。

## Implementation Steps

1. 确认核心 Prompt、阶段 Schema 和工具策略冻结点。
2. 构造两个合理候选共享失败表象的业务逻辑回归。
3. 注册能够区分候选的最小测试命令。
4. 编写 Manifest、独立 Ground Truth 和轨迹期望。
5. 用 FakeModelProvider 验证评测 fixture 能识别正确与违规轨迹。
6. 使用已配置的真实云端模型执行并人工检查最终因果链。

## Acceptance Criteria

- [ ] Task 3 在同一仓库和镜像中稳定复现，并与 Agent 可见答案隔离。
- [ ] 初始状态包含至少两个合理 Root Cause Candidate，且程序不在运行中新增候选。
- [ ] 至少一个 `run_tests` Experiment 预先声明所属 Hypothesis、目的和预期 Observation。
- [ ] 实际 Observation 对错误候选产生 `-4` Contradicting Evidence。
- [ ] 错误候选因程序计算的 Evidence Score 降级或 rejected，运行轨迹可审计排序变化。
- [ ] 只有最终 Top-1 进入补丁与 Validation。
- [ ] Task 3 加入后不针对该任务修改已冻结的核心 Prompt、Schema 或工具策略。

## Testing Strategy

- 对 Manifest、Ground Truth、复现性和输入隔离执行任务合同测试。
- 用合法轨迹和缺少目的、预期、Observation 引用或反证的轨迹测试验收器。
- 用 FakeModelProvider 确定性地产生候选竞争和排序变化。
- 显式运行真实模型，并人工核查候选合理性与因果机制。

## Dependencies

- CRCA-006 — 在最小 Docker 边界中运行测试 Experiment
- CRCA-007 — 完成一次 Top-1 补丁 Validation 闭环
- CRCA-010 — 使用 Task 2 验证 RAG 诊断路径

## Risks

- Task 3 设计本身耗时或变成 Prompt 调参；若第七天闭环落后，按 Spec 删除本 Ticket。
- 两个候选并不真正合理；Ground Truth 必须说明各自为何与初始证据相容。
- 测试结果只支持正确候选但没有反驳错误候选；验收要求明确的 Contradicting Evidence。

## Estimated Effort

0.5 engineer-day

## Related Spec Sections

- User Stories 6, 8–12, 23, 40–42, 55–57, 60–62, 66–70
- Implementation Decisions 10–17, 32, 40–42, 44
- Testing Decisions 8–10, 23–27

## Related ADRs

- ADR-0001 — 使用自研显式诊断状态机
- ADR-0008 — 两周 MVP 按 Diagnosis Run 目录保存记录
- ADR-0010 — 两周 MVP 采用最小 Docker 执行边界
