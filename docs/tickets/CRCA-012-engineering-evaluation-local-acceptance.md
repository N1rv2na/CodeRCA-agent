# CRCA-012 — 发布 Engineering Evaluation 与本地验收工作流

## Priority

P0

## Milestone

M4 — Evaluation & Delivery

## Background

求职项目需要让技术评审者复现已经声明的能力，并能区分位置命中、因果解释、补丁结果和 Agent 轨迹是否合规。三个任务不足以支持统计结论，但足以建立确定性的工程回归保护。

## Goal

让评审者从本地源码出发，通过统一 Diagnosis Application Service 运行任务并得到逐任务 Outcome Evaluation、Trajectory Evaluation 和人工因果核查记录。

## Scope

- 建立调用 Diagnosis Application Service 的 Evaluation Harness。
- 实现确定性的 Outcome Evaluation：Top-1 Root Symbol、补丁可应用性、Validation 和报告合同。
- 实现确定性的 Trajectory Evaluation：Hypothesis 绑定、Experiment 目的与预期、Evidence 引用、工具预算、停止原因和 Top-1 补丁规则。
- 输出逐任务结果，不汇总带泛化暗示的成功率。
- 提供触发条件、缺陷位置、传播路径和失败表现的人工核查表。
- 文档化本地环境、模型 preflight、索引、诊断、评测和产物检查流程。
- 默认自动化测试使用 FakeModelProvider；真实模型和 Docker Evaluation 显式运行。
- 明确完整目标与 Day-7 降级后的实际范围。

## Out of Scope

- LLM Judge、Baseline、统计显著性、重复稳定性实验或大规模 Benchmark。
- PyPI、Docker Compose、Web UI、托管服务、认证或多用户部署。
- 将因果文本相似度用作 Root Symbol 命中的替代指标。

## Technical Approach

Evaluation Harness 作为应用服务适配器读取 Ground Truth 和 Diagnosis Run 产物，不另建第二套 Agent 执行路径。Outcome 与 Trajectory 分开报告，补丁 Validation 不能替代 RCA 正确性。人工因果核查保持结构化但不引入自动 Judge。交付文档只声明实际通过的任务和边界。

## Implementation Steps

1. 固定 Evaluation 输入、逐任务结果和失败分类合同。
2. 实现 Outcome Evaluation 的确定性检查器与 fixture。
3. 实现 Trajectory Evaluation 的不变量检查器与 fixture。
4. 建立人工因果核查模板和逐任务结果记录。
5. 让 Harness 通过 Diagnosis Application Service 执行 Fake 与真实模式。
6. 编写从环境准备到产物审查的本地验收步骤。
7. 执行完整目标或已触发的降级任务集，并记录实际结果和失败。

## Acceptance Criteria

- [ ] CLI 与 Evaluation Harness 调用同一个 Diagnosis Application Service。
- [ ] Outcome Evaluation 分别报告 Top-1 Root Symbol、补丁可应用性、Validation 和报告合同结果。
- [ ] Trajectory Evaluation 能检测未绑定 Hypothesis、无目的或预期的 Experiment、无 Observation 来源的 Evidence、预算越界、非法停止和非 Top-1 补丁。
- [ ] 合法与故意违规的 Evaluation fixture 均产生预期确定性结果。
- [ ] 输出按 Task 1、Task 2，以及完整目标中的 Task 3 逐项列出，不计算成功率。
- [ ] 补丁通过不会覆盖 Root Symbol 未命中或因果核查失败。
- [ ] 人工核查分别记录触发条件、缺陷位置、传播路径和失败表现。
- [ ] 默认测试无需 `GEMINI_API_KEY`、GPU 和网络；真实模型/Docker Evaluation 只能显式启动。
- [ ] 本地验收说明涵盖模型 preflight、索引、诊断、评测、运行产物和已知失败。
- [ ] 如果采用 Day-7 降级，文档、任务集和报告合同同步反映实际范围。

## Testing Strategy

- 用命中、未命中、补丁失败、Validation 失败和报告缺字段 fixture 测试 Outcome Evaluation。
- 用合法和逐项违反核心不变量的 JSONL 轨迹测试 Trajectory Evaluation。
- 对 Harness 运行 FakeModelProvider 端到端测试，验证它没有绕过应用服务。
- 在干净本地检出环境按文档执行一次 smoke acceptance。
- 将真实任务结果作为显式工程 Evaluation 产物，不纳入默认 CI。

## Dependencies

完整目标：

- CRCA-007 — 完成一次 Top-1 补丁 Validation 闭环
- CRCA-010 — 使用 Task 2 验证 RAG 诊断路径
- CRCA-011 — 使用 Task 3 验证 Hypothesis 竞争机制

Day-7 降级路径：

- CRCA-007 — 完成一次 Top-1 补丁 Validation 闭环
- CRCA-010 — 使用 Task 2 验证 RAG 诊断路径

## Risks

- Evaluation 扩张成研究项目；只实现 Spec 中确定性的逐任务检查。
- Harness 复制 Agent 逻辑导致结果失真；强制以 Diagnosis Application Service 为唯一最高入口。
- 文档宣称超过实际实现；验收记录必须包含失败任务、停止原因和降级范围。
- 本地新检出复现耗时；保持单镜像、单环境和显式依赖版本。

## Estimated Effort

1 engineer-day

## Related Spec Sections

- User Stories 21–32, 33–34, 63–76
- Implementation Decisions 2, 36–45
- Testing Decisions 1–6, 21–27
- Out of Scope
- Further Notes — 合理简历表述

## Related ADRs

- ADR-0001 — 使用自研显式诊断状态机
- ADR-0002 — 使用结构化工具运行时且不实现 MCP
- ADR-0007 — 两周 MVP 使用固定混合检索管线
- ADR-0008 — 两周 MVP 按 Diagnosis Run 目录保存记录
- ADR-0011 — 两周 MVP 使用单一 Gemini 云端模型 API
- ADR-0010 — 两周 MVP 采用最小 Docker 执行边界
