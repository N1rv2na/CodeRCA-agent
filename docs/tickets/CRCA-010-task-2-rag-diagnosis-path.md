# CRCA-010 — 使用 Task 2 验证 RAG 诊断路径

## Priority

P0

## Milestone

M3 — Retrieval & Generalization Evidence

## Background

仅实现检索组件不能证明 Agent 会在需要时使用 RAG。Task 2 必须让 Root Symbol 无法从失败堆栈直接读取，使 `search_code` 成为定位根因的必要证据路径，同时仍复用同一 Diagnosis Task 工作流。

## Goal

新增一个冻结业务逻辑回归任务，并用真实 Gemini 模型证明 Agent 能通过与 Hypothesis 绑定的混合检索定位 Root Symbol、生成 Top-1 补丁并完成 Validation。

## Scope

- 在同一冻结 Django 仓库和镜像中构造 Task 2。
- 保证 Root Symbol 不直接出现在 CI 堆栈和失败断言中。
- 编写独立 Task Manifest 和隔离的 Ground Truth。
- 冻结一个需要故障语义或调用方线索才能检索到 Root Symbol 的路径。
- 执行真实 Diagnosis Run，并保存检索 Evidence、补丁和 Validation。
- 在降级模式下允许不使用 reranker，但保持 `search_code` 合同不变。

## Out of Scope

- 第二个仓库、任意新 Django 项目或统计性泛化声明。
- 检索消融和组件效果归因。
- Task 3 的多候选 Experiment 路径。

## Technical Approach

Task 2 复用已经冻结的仓库、镜像、索引流程、Prompt、Schema 和五工具协议，只替换 Task Manifest 所描述的 Faulty Commit、CI 日志与注册测试。验收不只检查最终 Root Symbol，还检查运行轨迹中存在对正确 Hypothesis 有贡献的 `search_code` Observation 和可追溯元数据。

## Implementation Steps

1. 构造 Root Symbol 不在堆栈中的单一业务逻辑回归。
2. 冻结 Faulty Commit、CI 日志、注册命令、Manifest 和 Ground Truth。
3. 验证故障稳定复现且无答案泄漏。
4. 建立 Task 2 的确定性 Outcome 和 Trajectory 期望。
5. 使用真实 Gemini 模型运行完整 Diagnosis Run。
6. 记录并人工检查检索路径、因果机制和 Validation 结果。

## Acceptance Criteria

- [ ] Task 2 在同一仓库、镜像和索引流程中稳定复现。
- [ ] Root Symbol 的规范名称和所在代码不直接出现在 CI 堆栈或失败断言中。
- [ ] Agent 可见输入与 Root Symbol、参考补丁和 Evaluation 答案隔离。
- [ ] 完整运行至少包含一次绑定活跃 Hypothesis 的 `search_code` 调用。
- [ ] 支持 Top-1 的 Evidence 引用检索命中的正确 Root Symbol 元数据，而不是仅引用失败表象。
- [ ] 真实 Gemini 模型运行输出正确 Top-1 Root Symbol、可应用补丁和一次 Validation 结果。
- [ ] 未启用 reranker 的降级运行仍使用相同 Manifest、Agent 工作流和工具合同。

## Testing Strategy

- 重复执行注册测试，验证失败确定性和堆栈不泄漏 Root Symbol。
- 对 Task Manifest/Ground Truth 做 Schema 与输入隔离检查。
- 用 FakeModelProvider 建立必经 `search_code` 的轨迹测试。
- 显式执行真实模型端到端验收并保存 Diagnosis Run 目录。
- 人工核查触发条件、缺陷位置、传播路径和失败表现。

## Dependencies

完整目标：

- CRCA-007 — 完成一次 Top-1 补丁 Validation 闭环
- CRCA-008 — 实现固定的混合代码检索流水线
- CRCA-009 — 增加固定 CPU Reranker

Day-7 降级路径：

- CRCA-007 — 完成一次 Top-1 补丁 Validation 闭环
- CRCA-008 — 实现固定的混合代码检索流水线

## Risks

- 任务虽然隐藏了堆栈位置，但可由 diff 直接猜中；应确保检索 Evidence 对定位具有实质作用。
- 为强制 RAG 而硬编码工具路径；Agent 仍需基于 Hypothesis 选择工具，评测只检查必要轨迹证据。
- Gemini 模型未命中不等于检索失败；分别保存 Search Result 与 Agent 决策以定位问题。

## Estimated Effort

0.5 engineer-day

## Related Spec Sections

- User Stories 19, 23, 27–30, 55–57, 59, 62
- Implementation Decisions 29–32, 40–42, 44
- Testing Decisions 17, 23–27

## Related ADRs

- ADR-0007 — 两周 MVP 使用固定混合检索管线
- ADR-0008 — 两周 MVP 按 Diagnosis Run 目录保存记录
- ADR-0011 — 两周 MVP 使用单一 Gemini 云端模型 API
- ADR-0010 — 两周 MVP 采用最小 Docker 执行边界
