# CRCA-005 — 使用 Diff 与代码证据完成诊断循环

## Priority

P0

## Milestone

M1 — Evidence-Driven Diagnosis

## Background

只有 Hypothesis 列表仍可能是一次模型猜测。CodeRCA 必须证明每次工具调用都服务于待验证假设，Observation 能转化为可追溯的 Supporting Evidence 或 Contradicting Evidence，并由程序更新候选排序。

## Goal

让 Agent 围绕 Task 1 使用 `inspect_diff` 和 `read_code` 执行受约束诊断循环，产出具有证据链、候选排序和停止原因的只读 Root Cause Report。

## Scope

- 建立统一 Tool Spec 注册、校验、执行、错误和审计入口。
- 实现只读的 `inspect_diff` 与 `read_code`。
- 实现选择 Experiment、执行工具、记录 Observation 和更新 Evidence 的阶段 Schema。
- 强制工具调用绑定活跃 Hypothesis、目的和预期 Observation。
- 实现固定 Evidence Score、反证扣分、同分规则和候选排序。
- 实现八次工具预算、候选耗尽和合法停止原因。
- 生成不含补丁 Validation 的 Root Cause Report。

## Out of Scope

- `search_code`、`run_tests` 和 `apply_patch` 的真实实现。
- Docker Experiment、RAG 和补丁搜索。
- 将 Evidence Score 表述为概率或自动因果文本评分。

## Technical Approach

状态机控制 Diagnosing、Executing Tool、Updating Evidence 和 Finalizing，诊断循环内部采用受约束 ReAct。Tool Runtime 对每次调用先执行统一 Schema、权限和预算检查，再记录结构化事件。程序根据 Evidence 来源、方向和强度计算排序，模型不能提供自信概率或直接改写分数。

固定评分如下：

- Experiment Observation：Supporting `+4`，Contradicting `-4`。
- 直接代码、堆栈或断言证据：Supporting `+3`，Contradicting `-3`。
- Git diff 关联：Supporting `+2`，Contradicting `-2`。
- 检索相似性：Supporting `+1`，Contradicting `-1`。
- 同分保持初始 Hypothesis 顺序；分数只用于排序，不是概率。

## Implementation Steps

1. 固定 Tool Spec、调用上下文、结果和统一错误合同。
2. 实现工具注册入口以及 `inspect_diff`、`read_code`。
3. 实现 Experiment 选择与 Observation/Evidence 更新 Schema。
4. 实现工具调用的 Hypothesis 绑定、权限、结果上限和审计事件。
5. 实现 Evidence Score、排序、拒绝候选和预算停止规则。
6. 扩展 Root Cause Report，呈现候选、Root Symbol、机制、正反 Evidence 和停止原因。
7. 用 Task 1 fixture 建立只读诊断纵向测试。

## Acceptance Criteria

- [ ] `inspect_diff` 和 `read_code` 通过同一 Tool Runtime 与 Tool Spec 执行。
- [ ] 没有合法 Hypothesis、目的或预期 Observation 的调用在执行前被拒绝。
- [ ] Observation 与 Evidence 均引用真实工具结果，Supporting 与 Contradicting 分开记录。
- [ ] 固定评分、反证扣分和同分保持初始顺序均由确定性测试证明。
- [ ] Root Cause Candidate 排序只由程序计算，报告不把 Evidence Score 标为概率。
- [ ] 第九次工具调用被拒绝，运行以合法预算停止原因结束。
- [ ] Task 1 的只读运行能输出包含 Root Symbol、机制和证据引用的 Root Cause Report。
- [ ] 路径穿越、仓库外读取、非法参数、超时和执行失败被正确分类且默认不重试。

## Testing Strategy

- 对 Tool Runtime 执行参数、权限、超时、错误、截断和审计的合同测试。
- 对两个只读工具使用冻结仓库 fixture 进行集成测试。
- 对 Evidence Score 使用正反证据组合和同分候选进行表驱动测试。
- 用 FakeModelProvider 执行 Task 1 只读纵向路径，验证状态、事件、报告和停止行为。
- 测试公开事件和报告，不断言私有调用顺序或 Prompt 文本。

## Dependencies

- CRCA-002 — 冻结 Django 基准仓库并构造 Task 1
- CRCA-004 — 形成受约束的初始诊断假设

## Risks

- Tool Runtime 与 Agent 循环同时开发造成调试面过大；先以两个只读工具贯通统一合同。
- Evidence 分类被模型任意操纵；程序校验来源、方向和允许强度。
- 评分规则造成虚假精确性；所有输出明确其仅为候选排序规则。

## Estimated Effort

1.5 engineer-days

## Related Spec Sections

- User Stories 6–12, 16–18, 21–25, 40–46, 58, 66–69
- Implementation Decisions 7–25, 38–39
- Testing Decisions 7–15, 21–22, 24

## Related ADRs

- ADR-0001 — 使用自研显式诊断状态机
- ADR-0002 — 使用结构化工具运行时且不实现 MCP
- ADR-0008 — 两周 MVP 按 Diagnosis Run 目录保存记录

