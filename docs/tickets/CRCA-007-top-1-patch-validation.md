# CRCA-007 — 完成一次 Top-1 补丁 Validation 闭环

## Priority

P0

## Milestone

M2 — Experiment & Patch Validation

## Background

根因报告如果不能连接到可执行修复验证，仍然容易停留在合理文本层面。MVP 的最简完整价值是：定位 Top-1 Root Cause、提出一个补丁，并在隔离工作区中执行一次真实 Validation。

## Goal

使用真实本地模型对 Task 1 完成从 Task Manifest 到 Top-1 补丁 Validation 和最终 Root Cause Report 的端到端 Diagnosis Run。

## Scope

- 实现补丁生成阶段 Schema 和 `apply_patch` Tool Spec。
- 只允许排名第一的 Root Cause Candidate 进入补丁阶段。
- 校验补丁可应用性、允许路径和禁止修改类型。
- 在临时 Docker 工作区应用一个候选补丁。
- 运行注册测试与轻量静态检查，记录一次 Public Validation。
- Validation 后直接 Finalizing，不进行第二轮补丁搜索。
- 完成 Task 1 的真实本地模型端到端验收。

## Out of Scope

- Top-2/Top-3 补丁、多轮自动修补和 Hidden Validation。
- 修改真实仓库、推送分支或创建 Pull Request。
- 自动语义防投机或生产级补丁安全审查。

## Technical Approach

在诊断停止后由程序冻结 Top-1 Candidate，再请求模型生成一个结构化补丁。`apply_patch` 只能修改 Manifest 允许的业务源码，拒绝测试、依赖锁、任务定义和 Evaluation 数据。补丁只应用于临时工作区；一次注册 Validation 无论通过或失败都写入 Evidence 和最终报告，随后终止运行。

## Implementation Steps

1. 定义 Top-1 冻结、补丁生成和 Validation 阶段转移。
2. 固定补丁阶段 Schema 与一次纠错行为。
3. 实现 `apply_patch` 的路径、文件类型、可应用性和审计检查。
4. 在临时工作区应用补丁并运行注册测试与轻量静态检查。
5. 扩展 Root Cause Report 和运行产物以包含补丁及 Validation。
6. 增加 FakeModelProvider 完整闭环测试。
7. 使用通过门禁的真实本地模型运行 Task 1 并保存验收记录。

## Acceptance Criteria

- [ ] 只有 Evidence Score 排名第一的 Candidate 能进入补丁生成与 Validation。
- [ ] 一次 Diagnosis Run 最多生成并应用一个候选补丁。
- [ ] 对测试、依赖锁、任务定义、Evaluation 数据或仓库外路径的修改被拒绝。
- [ ] 补丁只修改临时工作区，Faulty Commit 的原始工作副本保持不变。
- [ ] 注册测试和轻量静态检查均被记录为 Public Validation 结果。
- [ ] Validation 通过或失败后都直接生成最终报告，不启动第二轮补丁搜索。
- [ ] Task 1 能以真实本地模型完成全链路运行，并保存模型响应、工具输出、补丁、Validation、事件和报告。

## Testing Strategy

- 用可应用、语法错误、越界和修改禁止文件的 patch fixture 做合同测试。
- 通过 FakeModelProvider 执行 Manifest、Hypothesis、Evidence、补丁、Validation 和报告的完整纵向路径。
- 验证失败 Validation 仍生成报告且不会重新进入 Diagnosing。
- 将 Task 1 真实模型验收作为显式本地测试，记录 Run Manifest 与运行目录。

## Dependencies

- CRCA-003 — 建立本地模型兼容性门禁
- CRCA-005 — 使用 Diff 与代码证据完成诊断循环
- CRCA-006 — 在最小 Docker 边界中运行测试 Experiment

## Risks

- 本地小模型补丁输出不稳定；通过小型阶段 Schema、一次纠错和早期探针限制风险。
- 模型通过改测试投机；程序在应用前强制禁止修改测试与任务基础设施。
- 端到端错误难定位；所有阶段保留结构化事件和原始产物引用。

## Estimated Effort

1 engineer-day

## Related Spec Sections

- User Stories 13–18, 29, 43, 64, 70
- Implementation Decisions 8–9, 17, 21–23, 35–39, 45
- Testing Decisions 5, 10–15, 19–22

## Related ADRs

- ADR-0001 — 使用自研显式诊断状态机
- ADR-0002 — 使用结构化工具运行时且不实现 MCP
- ADR-0008 — 两周 MVP 按 Diagnosis Run 目录保存记录
- ADR-0009 — 两周 MVP 只连接一个外部本地模型服务
- ADR-0010 — 两周 MVP 采用最小 Docker 执行边界

