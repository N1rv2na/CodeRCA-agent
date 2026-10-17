# CRCA-005 — 通过 Diff 与代码 Evidence 检验并 Reformulate Hypothesis

## Priority

P0

## Milestone

M1 — Evidence-Driven Diagnosis

## Background

只有 H1 仍可能是一次模型猜测。CodeRCA 必须证明每次工具调用服务于当前 Active Hypothesis，Observation 能转换为可追溯 Evidence，并且错误 H1 可以结束后基于累积诊断知识 Reformulate H2/H3。

## Goal

让 Agent 围绕 Task 1 使用 `inspect_diff` 和 `read_code` 执行 falsification-first 诊断循环，产出可追溯 Evidence、append-only Hypothesis History 和确定停止原因的只读 Root Cause Report。

## Scope

- 建立统一 Tool Spec 注册、校验、执行、错误和审计入口。
- 实现只读的 `inspect_diff` 与 `read_code`。
- 实现 Select Experiment、Update Evidence 和 Assess Hypothesis 阶段 Schema。
- 强制 Experiment 绑定当前 Active Hypothesis、目的、预期 Observation 和 falsification relevance。
- 程序验证 Evidence provenance、Observation reference 和 Hypothesis 归属。
- 根据结构化 Assessment 继续检验、support、reject 或结束为 inconclusive。
- 当前 H rejected/inconclusive 且预算剩余时，使用相关 Evidence/Observation Context Reformulate H2/H3。
- 实现八次 Tool Budget、H3 exhausted 和合法停止原因。
- 生成不含补丁 Validation 的 Root Cause Report。

## Out of Scope

- `search_code`、`run_tests` 和 `apply_patch` 的真实实现。
- Docker Experiment、RAG 和补丁搜索。
- Evidence Score、Candidate Ranking、概率或 LLM confidence。

## Technical Approach

状态机控制 Diagnosing、Executing Tool、Updating Evidence、Forming Hypothesis 和 Finalizing。模型一次只选择一个 falsification-oriented Experiment，并在 Observation 后输出 qualitative Evidence 与 Assessment；程序检查当前 Active Hypothesis、真实 Observation 引用、Evidence 方向、Budget 和状态前置条件。Reformulation Context 包含旧 H 的终态、否定或结束它的 Evidence、相关代码/diff Observation 和剩余预算，不重放完整历史。

## Implementation Steps

1. 固定 Tool Spec、调用上下文、结果和统一错误合同。
2. 实现工具注册入口以及 `inspect_diff`、`read_code`。
3. 实现 Select Experiment、Update Evidence 和 Assess Hypothesis Schema。
4. 实现 Active Hypothesis 绑定、权限、结果上限和审计事件。
5. 实现 program-owned Assessment 映射和 Evidence 引用检查。
6. 实现 H2/H3 bounded Reformulation 与 budget-exhausted stop。
7. 扩展 Root Cause Report，呈现 History、最终 Hypothesis、正反 Evidence 和停止原因。
8. 用 Task 1 fixture 建立只读诊断纵向测试。

## Acceptance Criteria

- [ ] `inspect_diff` 和 `read_code` 通过同一 Tool Runtime 与 Tool Spec 执行。
- [ ] Tool Call 只能绑定当前 Active Hypothesis；rejected H 不能再次接收 Tool Call。
- [ ] Experiment 缺少目的、预期 Observation 或 falsification relevance 时在执行前失败。
- [ ] Observation 与 Evidence 均引用真实 Tool Result；Evidence 不含数值 Score。
- [ ] falsified Assessment 必须引用当前 H 的 Contradicting Evidence，程序才将其转换为 rejected。
- [ ] H1 rejected/inconclusive 后可形成 H2；Active H1 存在时不能形成 H2。
- [ ] H2/H3 Context 包含旧 H 的结束 Evidence 与相关 Observation，且新机制不能只是原文重复。
- [ ] H3 结束或第九次 Tool Call 产生确定性停止，不允许 H4。
- [ ] Task 1 的只读运行输出最终 Root Symbol、机制、History 和 Evidence refs。
- [ ] 路径穿越、仓库外读取、非法参数、超时和执行失败正确分类且默认不重试。

## Testing Strategy

- 对 Tool Runtime 执行参数、权限、超时、错误、截断和审计做合同测试。
- 对两个只读工具使用冻结仓库 fixture 做集成测试。
- 用 Supporting、Contradicting 和 Inconclusive Evidence 测试 Assessment 前置条件。
- 用 FakeModelProvider 执行 H1 continue、H1 reject→H2、H3 exhausted 和 supported 路径。
- 验证 Reformulation Context 的选定知识与 Raw Artifact 边界。

## Dependencies

- CRCA-002 — 冻结 Django 基准仓库并构造 Task 1
- CRCA-004 — 形成单个初始 Active Hypothesis

## Risks

- 模型把一般代码相关性误判为 falsification；Schema 必须要求 falsification relevance 与 Evidence explanation。
- Reformulation 只是换句话重复旧机制；程序做 ID/Budget/历史约束，Trajectory Evaluation 与人工核查机制差异。
- Tool Runtime 与 Agent Loop 同时开发造成调试面过大；先以两个只读工具贯通统一合同。

## Estimated Effort

1.5 engineer-days

## Related Spec Sections

- User Stories 6–12, 16–18, 21–25, 38–46, 58, 66–69
- Implementation Decisions 7–25, 38–41
- Testing Decisions 7–15, 21–24

## Related ADRs

- ADR-0014 — 单 Active Hypothesis 与按决策重建上下文
- ADR-0002 — 使用结构化工具运行时且不实现 MCP
- ADR-0008 — 两周 MVP 按 Diagnosis Run 目录保存记录
