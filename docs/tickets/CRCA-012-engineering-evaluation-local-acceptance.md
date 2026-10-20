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
- 实现确定性的 Outcome Evaluation：最终报告 location 的路径/规范符号/缺陷行范围、程序生成的 Candidate Patch 可应用性、Validation 和报告合同；不得以 Hypothesis 暂定符号替代。搜索展示独立验收，不作为默认诊断成功前提（ADR-0016）。
- 实现确定性的 Trajectory Evaluation：single-active、append-only History、Experiment 目的/预期/falsification relevance、Evidence 引用、reject-before-reformulate、H1～H3 Budget、停止原因和 supported-H patch 规则。
- 输出逐任务结果，不汇总带泛化暗示的成功率。
- 提供触发条件、缺陷位置、传播路径和失败表现的人工核查表。
- 文档化本地环境、模型 preflight、Lightweight Code Search 可用性、诊断、评测和产物检查流程。
- 默认自动化测试使用 FakeModelProvider；Model Compatibility Gate、真实模型和 Docker Evaluation 显式运行。
- 明确 Task 1 优先、Task 2 代码探索与可选 Task 3 的实际交付范围。

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
7. 按 Task 1 → Task 2 → Task 3 的交付优先级执行实际任务集，并记录实际结果和失败。

## Acceptance Criteria

- [ ] CLI 与 Evaluation Harness 调用同一个 Diagnosis Application Service。
- [ ] Outcome Evaluation 分别报告最终 Root Symbol、Patch Intent 编译结果、Candidate Patch 可应用性、Validation 和报告合同结果。
- [ ] Trajectory Evaluation 能检测并行 Active H、History 覆盖/复活/H4、未绑定 Experiment、缺少 falsification relevance、无 Observation 来源的 Evidence、未结束当前 H 就 Reformulate、预算越界、非法停止和非 supported-H patch。
- [ ] 合法与故意违规的 Evaluation fixture 均产生预期确定性结果。
- [ ] 输出按 Task 1、Task 2，以及完整目标中的 Task 3 逐项列出，不计算成功率。
- [ ] 补丁通过不会覆盖 Root Symbol 未命中或因果核查失败。
- [ ] 人工核查分别记录触发条件、缺陷位置、传播路径和失败表现。
- [ ] 默认测试无需 API Key、GPU 和网络；Model Compatibility Gate 与真实模型/Docker Evaluation 只能显式启动。
- [ ] 本地验收说明涵盖 Model Configuration、兼容性门禁、Lightweight Code Search、诊断、评测、运行产物和已知失败，不包含索引准备步骤。
- [ ] 如果总周期不足而延期 Task 3，文档、任务集和报告合同同步反映实际范围，同时保留已有 Falsification 与 Bounded Reformulation 不变量检查。

## Testing Strategy

- 用命中、未命中、Patch Intent 编译失败、Candidate Patch 失败、Validation 失败和报告缺字段 fixture 测试 Outcome Evaluation。
- 用合法和逐项违反 single-active、append-only、reject-before-reformulate、Evidence provenance 与 Budget 不变量的 JSONL 轨迹测试 Trajectory Evaluation。
- 对 Harness 运行 FakeModelProvider 端到端测试，验证它没有绕过应用服务。
- 在干净本地检出环境按文档执行一次 smoke acceptance。
- 将真实任务结果作为显式工程 Evaluation 产物，不纳入默认 CI。

## Dependencies

完整验收目标：

- CRCA-007 — 完成 Supported Hypothesis 补丁 Validation 闭环
- CRCA-010 — 使用 Task 2 验证 Code Exploration 与 Root Cause Localization
- CRCA-011 — 使用 Task 3 验证 Bounded Self-Correction

最小发布验收：

- CRCA-007 — 完成 Supported Hypothesis 补丁 Validation 闭环
- CRCA-010 — 使用 Task 2 验证 Code Exploration 与 Root Cause Localization

CRCA-011 仅影响 Task 3 的实际验收集合，不阻塞 Evaluation Harness 与 Task 1/Task 2 的确定性检查器实现。

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

- ADR-0016 — 最终定位与搜索能力独立验收
- ADR-0014 — 单 Active Hypothesis 与按决策重建上下文
- ADR-0002 — 使用结构化工具运行时且不实现 MCP
- ADR-0015 — CodeRCA MVP 使用 Lightweight Code Search
- ADR-0008 — 两周 MVP 按 Diagnosis Run 目录保存记录
- ADR-0013 — 本地 Schema 校验与显式 Structured Output Mode
- ADR-0010 — 两周 MVP 采用最小 Docker 执行边界
