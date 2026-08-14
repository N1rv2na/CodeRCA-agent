# CRCA-008 — 实现固定的混合代码检索流水线

## Priority

P0

## Milestone

M3 — Retrieval & Generalization Evidence

## Background

Task 2 的 Root Symbol 不会直接出现在失败堆栈中，因此 Agent 必须从故障语义、diff 和代码结构构造查询。该能力也是项目展示 Context Engineering 与代码 RAG 的主要证据。

## Goal

让 Agent 能为活跃 Hypothesis 调用 `search_code`，在 Faulty Commit 快照的固定 AST/BM25/向量混合索引中返回可追溯的 Root Symbol 候选。

## Scope

- 以 Python 函数、方法和类建立 AST 语义块。
- 保存路径、符号、父类、行区间和源码等元数据。
- 对超长语义块分窗并保留所属符号与重叠上下文。
- 在索引阶段预计算 embedding。
- 实现 BM25、向量召回和固定融合。
- 实现 `search_code` Tool Spec，返回稳定 Top-K 结果及代码位置。
- 源码快照变化时整库重建索引。
- 冻结 embedding、融合权重、候选数和 Top-K 配置。

## Out of Scope

- CPU reranker；由 CRCA-009 单独交付。
- 检索消融、参数搜索、在线调参或量化增益声明。
- 增量索引、任意仓库质量保证、完整调用图或独立符号分析工具。
- 将修复后代码或 Ground Truth 纳入索引。

## Technical Approach

索引仅针对 Task Manifest 指定的 Faulty Commit。所有分块以 Root Symbol 为语义锚点，融合规则和 Top-K 固定，Agent 只能提供与 Hypothesis 绑定的动态查询而不能选择检索算法。`search_code` 通过既有 Tool Runtime 执行，并把大块源码留在运行产物中，只把必要片段和元数据送入上下文。

## Implementation Steps

1. 冻结 embedding 模型、排除规则、融合权重、候选数和 Top-K。
2. 实现 Python AST 语义块与超长块分窗。
3. 建立 BM25 索引和预计算向量索引。
4. 实现固定融合与确定性排序规则。
5. 将 `search_code` 接入统一 Tool Runtime 和 Hypothesis 审计。
6. 实现快照标识校验与整库重建策略。
7. 在冻结仓库上建立分块、检索和索引重建测试。

## Acceptance Criteria

- [ ] 函数、方法和类语义块保留路径、符号、父类和精确行区间。
- [ ] 超长块分窗后仍能追溯到唯一所属 Root Symbol，并保留配置化重叠。
- [ ] 索引只包含 Faulty Commit 源码，不包含参考修复或 Evaluation Ground Truth。
- [ ] `search_code` 同时使用 BM25 与向量召回及固定融合，返回稳定 Schema 和 Top-K。
- [ ] 每个动态查询关联一个活跃 Hypothesis，并记录查询来源和结果引用。
- [ ] Faulty Commit 变化会拒绝旧索引并触发整库重建。
- [ ] 运行期 embedding 不依赖云端诊断模型或其计算资源。

## Testing Strategy

- 用嵌套类、方法、装饰器、超长函数和语法边界 fixture 测试 AST 分块。
- 在冻结快照上验证 BM25、向量与融合输出的 Schema、元数据和可复现性。
- 用变更快照测试旧索引失效和整库重建。
- 用包含修复后代码标记的 fixture 验证索引输入隔离。
- 通过 Tool Runtime 测试 Hypothesis 绑定、结果上限和 artifact 引用。

## Dependencies

- CRCA-002 — 冻结 Django 基准仓库并构造 Task 1
- CRCA-005 — 使用 Diff 与代码证据完成诊断循环

## Risks

- embedding 依赖下载或模型过大；应选择可在本机 CPU 索引阶段稳定运行的固定模型。
- 混合排序细节拖入实验优化；只冻结一组可用配置，不作效果归因。
- Django 仓库 AST 边界存在解析异常；记录跳过文件并对目标源码建立硬验收。

## Estimated Effort

1.5 engineer-days

## Related Spec Sections

- User Stories 10, 19, 27–28, 49–52, 59
- Implementation Decisions 21–22, 28–32
- Testing Decisions 16–18
- Further Notes — 固定检索组件仍需早期冻结

## Related ADRs

- ADR-0002 — 使用结构化工具运行时且不实现 MCP
- ADR-0007 — 两周 MVP 使用固定混合检索管线
- ADR-0012 — 使用可配置的 OpenAI-compatible 云端模型 Provider
