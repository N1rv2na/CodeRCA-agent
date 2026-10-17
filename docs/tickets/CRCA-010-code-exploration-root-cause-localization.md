# CRCA-010 — 使用 Task 2 验证 Code Exploration 与 Root Cause Localization

## Priority

P0

## Milestone

M3 — Agent Code Exploration

## Background

只实现 `search_code` 不能证明 Agent 会在需要时自主探索代码。Task 2 应隐藏初始失败信息中的直接 Root Symbol 线索，但仍提供可由 Lightweight Code Search、diff 和代码阅读发现的真实路径，以验证搜索 Observation 是否真正推进了 Hypothesis 诊断。

## Goal

新增一个冻结业务逻辑回归任务，并用已配置的 OpenAI-compatible 云端模型证明 Agent 能自主选择诊断工具、利用实际搜索结果定位 Root Cause、形成可追溯 Evidence、生成一个补丁并完成 Validation。

## Scope

- 在同一冻结 Django 仓库和镜像中构造 Task 2。
- 保证 Root Symbol 及其规范位置不直接出现在初始 CI 堆栈或失败断言中。
- 编写独立 Task Manifest、Faulty Commit、CI Failure Log、注册测试和隔离 Ground Truth。
- 保留可由关键词、符号文本、路径线索、diff 或调用方代码逐步发现的根因路径。
- 让 Agent 基于当前 Active Hypothesis 自主选择 `search_code`、`inspect_diff`、`read_code` 或测试 Experiment，不硬编码固定调用顺序。
- 执行真实 Diagnosis Run，并保存对最终诊断有贡献的搜索/代码 Observation、Evidence、补丁和 Validation。
- 建立确定性的 Outcome 与 Trajectory 验收，重点检查搜索结果是否被实际用于诊断。

## Out of Scope

- 第二个仓库、任意新 Django 项目或统计性泛化声明。
- 强制 BM25、dense retrieval、hybrid fusion、reranker 或任一检索算法路径。
- Retrieval Evaluation、消融、参数调优和算法效果归因。
- Task 3 的 bounded self-correction 路径。
- 为通过 Task 2 在 Agent 中硬编码 `search_code` 调用或固定工具序列。

## Technical Approach

Task 2 复用已经冻结的仓库、镜像、Prompt、Schema、五工具协议和 decision-specific ContextBuilder，只替换 Task Manifest 描述的 Faulty Commit、CI 日志与注册测试。故障不能从初始日志直接抄出答案，也不应制造只有向量语义搜索才能解决的词汇鸿沟。

验收同时检查最终 Root Symbol 与轨迹：成功路径中至少一个真实 `search_code` Tool Result 形成带 Artifact provenance 的 Observation，并被 Evidence 或后续 Experiment 引用，从而对定位最终 supported Hypothesis 有实质贡献。该要求约束可观察结果，不规定搜索必须紧跟 H1 或采用固定调用顺序。

## Implementation Steps

1. 设计一个 Root Symbol 不在初始失败信息中、但可通过轻量代码探索发现的单一业务逻辑回归。
2. 冻结 Faulty Commit、CI 日志、注册命令、Manifest 和隔离 Ground Truth。
3. 验证故障稳定复现、输入不泄漏答案，并确认无需高级语义检索才能找到有效线索。
4. 定义搜索 Observation 对最终定位有贡献的可观察 Trajectory 期望。
5. 用 FakeModelProvider 验证自主工具路径、Observation/Evidence provenance 和非固定顺序。
6. 使用通过门禁检查的已配置云端模型运行完整 Diagnosis Run。
7. 记录并人工检查代码探索、Root Symbol、因果机制、补丁和 Validation。

## Acceptance Criteria

- [ ] Task 2 在同一冻结仓库和镜像中稳定复现，并拥有独立 Faulty Commit、CI Failure Log、注册测试、Manifest 和 Ground Truth。
- [ ] Root Symbol 的规范名称与直接代码位置不出现在初始 CI 堆栈或失败断言中。
- [ ] Agent 可见输入与 Ground Truth、参考补丁、修复后代码和 Evaluation 答案隔离。
- [ ] 任务可通过 Lightweight Code Search、diff 与代码阅读发现，不依赖 BM25、embedding、向量索引或 reranker。
- [ ] 完整成功运行至少包含一次绑定当前 Active Hypothesis 和 Experiment 元数据的 `search_code` 调用，但 Agent 实现不硬编码固定工具序列。
- [ ] 至少一个搜索 Tool Result 形成有 Artifact provenance 的 Observation，并被 Evidence 或后续 Experiment 用于推进最终 Root Cause Localization。
- [ ] 搜索匹配本身不被当作 Root Symbol Ground Truth；最终 Root Symbol 与 Causal Mechanism 由代码 Evidence 和 Validation 支持。
- [ ] 已配置的真实模型运行输出正确最终 Root Symbol、可应用补丁和一次 Validation 结果。

## Testing Strategy

- 重复执行注册测试，验证失败确定性和初始日志不泄漏 Root Symbol。
- 对 Task Manifest、Ground Truth、Faulty Commit 和输入隔离做合同测试。
- 用 FakeModelProvider 覆盖不同合法工具顺序，并验证成功轨迹使用真实搜索 Observation 而非硬编码阶段。
- 显式执行真实模型端到端验收并保存 Diagnosis Run 目录。
- 人工核查触发条件、缺陷位置、传播路径、失败表现和搜索 Observation 的实际贡献。

## Dependencies

- CRCA-007 — 完成 Supported Hypothesis 补丁 Validation 闭环
- CRCA-008 — 实现 Lightweight Code Search

CRCA-009 不再是依赖；CPU Reranker 已退出 CodeRCA MVP。

## Risks

- 任务虽然隐藏堆栈位置，但可由显眼 diff 直接猜中；应确保搜索或代码探索 Observation 对定位具有可说明的贡献。
- 为强制展示搜索而把轨迹写死；只验收成功轨迹中搜索信息的实际用途，不规定固定调用时机或顺序。
- 字面量搜索无法跨越完全不同的词汇；任务应体现真实探索难度，但不得人为要求高级语义检索。
- 诊断模型未利用有效结果不等于搜索失败；分别保存 Tool Result、Observation、Evidence 与后续决策。

## Estimated Effort

0.5 engineer-day

## Related Spec Sections

- User Stories 19, 23, 27–30, 55–59, 62
- Implementation Decisions 29–32, 40–44
- Testing Decisions 16–18, 23–27

## Related ADRs

- ADR-0015 — CodeRCA MVP 使用 Lightweight Code Search
- ADR-0014 — 单 Active Hypothesis 与按决策重建上下文
- ADR-0008 — 两周 MVP 按 Diagnosis Run 目录保存记录
- ADR-0013 — 本地 Schema 校验与显式 Structured Output Mode
- ADR-0010 — 两周 MVP 采用最小 Docker 执行边界
