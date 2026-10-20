# CRCA-007 — 完成 Supported Hypothesis 补丁 Validation 闭环

## Priority

P0

## Milestone

M2 — Experiment & Patch Validation

## Background

Root Cause Report 如果不能连接到可执行修复验证，仍然容易停留在合理文本层面。MVP 的最简完整价值是：通过 Evidence 支持一个 Hypothesis、提出结构化 Patch Intent、由程序生成 Candidate Patch，并在隔离工作区执行一次真实 Validation。ADR-0018 将模型修复语义与 unified diff 序列化分离，避免正确修复因 hunk 语法错误而无法验证。

## Goal

定位合同补充（ADR-0016）：复用现有最终报告调用输出独立、可空 location；
暂定 Hypothesis.root_symbol 保留不变。最终位置须有实际代码 Evidence 覆盖，
不新增定位阶段，不因定位为空改变 Validation 的真实结果。

使用通过门禁检查的 OpenAI-compatible 云端模型，对 Task 1 完成从 Task Manifest 到 supported Hypothesis 补丁 Validation 和最终 Root Cause Report 的端到端 Diagnosis Run。

## Scope

- 实现 `PatchIntentDecision`、Exact Replacement、确定性 Patch Compiler 和 `apply_patch` Tool Spec。
- 只允许状态为 `supported` 的 Hypothesis 进入补丁阶段。
- 校验 Patch Intent 的唯一原文锚点、非重叠、非 no-op、允许路径和禁止修改类型，并生成可应用的规范 Candidate Patch。
- 在临时 Docker 工作区应用一个候选补丁。
- 运行注册测试与轻量静态检查，记录一次 Public Validation。
- Validation 后直接 Finalizing，不进行第二轮补丁搜索。
- 完成 Task 1 的真实云端模型端到端验收。

## Out of Scope

- 为 rejected/inconclusive Hypothesis 生成补丁、多补丁并行搜索、多轮自动修补和 Hidden Validation。
- 修改真实仓库、推送分支或创建 Pull Request。
- 自动语义防投机或生产级补丁安全审查。

## Technical Approach

程序只有在 Hypothesis Assessment 合法进入 `supported` 后才请求模型提交结构化 Patch Intent。模型声明一个允许目标文件和一至三个 Exact Replacement，不生成 unified diff。Patch Compiler 在 Faulty Commit 上要求 `old_text` 精确且唯一匹配、编辑不重叠并确实改变文件，再确定性生成 Candidate Patch；失败复用一次结构化纠错，成功前不创建 Patch Validation Action。`apply_patch` 只能修改 Manifest 允许的业务源码，拒绝测试、依赖锁、任务定义和 Evaluation 数据。Candidate Patch 只应用于临时工作区；一次注册 Validation 无论通过或失败都写入 Evidence 和最终报告，随后终止运行。

## Implementation Steps

1. 定义 supported Hypothesis、Patch Intent、Candidate Patch 和 Validation 阶段转移。
2. 固定 Patch Intent Schema、Exact Replacement 上限与一次纠错行为。
3. 实现唯一匹配、重叠/no-op 拒绝、规范 diff 生成和 `git apply --check` 的 Patch Compiler。
4. 实现 `apply_patch` 的路径、文件类型、可应用性和审计检查。
5. 在临时工作区应用补丁并运行注册测试与轻量静态检查。
6. 扩展 Root Cause Report 和 Run Artifact 以区分模型 Intent、Candidate Patch 及 Validation。
7. 增加 FakeModelProvider 完整闭环测试。
8. 使用通过门禁检查的真实模型运行 Task 1 并保存验收记录。

## Acceptance Criteria

- [ ] 只有 `supported` Hypothesis 能进入补丁生成与 Validation。
- [ ] 模型不直接生成 unified diff；合法 Patch Intent 只包含一个目标文件和一至三个 Exact Replacement。
- [ ] 缺失、歧义、重叠、no-op 或越界 Patch Intent 被确定性拒绝，并且纠错成功前不产生 Candidate Patch 或消耗 Validation 工具预算。
- [ ] 一次 Diagnosis Run 最多编译并应用一个 Candidate Patch。
- [ ] 对测试、依赖锁、任务定义、Evaluation 数据或仓库外路径的修改被拒绝。
- [ ] 补丁只修改临时工作区，Faulty Commit 的原始工作副本保持不变。
- [ ] 注册测试和轻量静态检查均被记录为 Public Validation 结果。
- [ ] Validation 通过或失败后都直接生成最终报告，不启动第二轮补丁搜索。
- [ ] Task 1 能以真实模型完成全链路运行，并保存模型响应、工具输出、补丁、Validation、事件和报告。

## Testing Strategy

- 用合法、缺失、歧义、重叠、no-op、越界和修改禁止文件的 Patch Intent fixture 做合同测试，并验证程序生成的 diff 可由 Git 应用。
- 通过 FakeModelProvider 执行 Manifest、Hypothesis History、Evidence、补丁、Validation 和报告的完整纵向路径。
- 验证 proposed/testing/rejected/inconclusive H 均不能进入补丁阶段。
- 验证失败 Validation 仍生成报告且不会重新进入 Diagnosing。

## Dependencies

- CRCA-003 — 建立 OpenAI-compatible 模型兼容性门禁
- CRCA-005 — 通过 Diff 与代码 Evidence 检验并 Reformulate Hypothesis
- CRCA-006 — 在最小 Docker 边界中运行测试 Experiment

## Risks

- 模型可能无法复制唯一原文锚点；通过一至三个 Exact Replacement、小型阶段 Schema、一次纠错和 Patch Intent 探针限制风险，程序不做 fuzzy repair。
- 模型通过改测试投机；程序在应用前强制禁止修改测试与任务基础设施。
- 端到端错误难定位；所有阶段保留结构化事件和原始 Artifact 引用。

## Estimated Effort

1 engineer-day

## Related Spec Sections

- User Stories 13–18, 29, 43, 64, 70
- Implementation Decisions 8–9, 17, 21–23, 35–39, 45
- Testing Decisions 5, 10–15, 19–22

## Related ADRs

- ADR-0016 — 最终定位与搜索能力独立验收
- ADR-0014 — 单 Active Hypothesis 与按决策重建上下文
- ADR-0002 — 使用结构化工具运行时且不实现 MCP
- ADR-0008 — 两周 MVP 按 Diagnosis Run 目录保存记录
- ADR-0013 — 本地 Schema 校验与显式 Structured Output Mode
- ADR-0010 — 两周 MVP 采用最小 Docker 执行边界
- ADR-0018 — 结构化 Patch Intent 与确定性补丁编译
