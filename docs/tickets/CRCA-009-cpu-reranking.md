# CRCA-009 — 增加固定 CPU Reranker

## Status

Superseded / Deferred — Out of MVP

本 Ticket 保留为历史规划记录。ADR-0015 已用 Lightweight Code Search 取代完整混合代码 RAG，当前 CodeRCA MVP 不实现 CPU Reranker；不得把本文件作为当前开发任务或其他 MVP Ticket 的必需依赖。

## Priority

Deferred

## Milestone

Future Retrieval Research（不属于 CodeRCA MVP）

## Background

ADR-0007 曾计划在 BM25/向量融合后使用固定 CPU Reranker，以展示完整 Code RAG 数据路径。项目现在将 Chunking、Embedding、Hybrid Retrieval、Reranking 和 Retrieval Evaluation 交给独立 RAG 项目，CodeRCA 聚焦 Agent Engineering。

## Goal

不在当前 MVP 中实施。未来只有在 Lightweight Code Search 对已冻结诊断任务反复出现可复现词汇鸿沟、已有独立相关性标注，并且高级检索收益可以与 Agent 决策分离评估时，才重新拆分新的 Retrieval Ticket。

## Scope

- 保留本地历史 Ticket 与原编号，说明范围决策的演化。
- 明确 CRCA-009 不属于当前 MVP、交付顺序或验收合同。

## Out of Scope

- 在 CodeRCA MVP 中选择、下载、集成或运行 reranker。
- 为 reranker 保留 Provider、配置开关、兼容 Schema 或降级路径。
- 修改 `search_code` Lightweight Code Search 合同。
- 把检索相关性分数引入 Evidence、Hypothesis Assessment 或 Evaluation。

## Technical Approach

无当前实现方案。历史上的固定 CPU reranking 方案由 ADR-0015 supersede，不在 CodeRCA 中留下提前抽象或兼容代码。

## Implementation Steps

无。若未来触发重新评估条件，应基于新的数据、指标和项目范围创建新 Ticket，而不是恢复本 Ticket。

## Acceptance Criteria

- [x] 本 Ticket 明确标记为 Superseded / Deferred / Out of MVP。
- [x] 当前 MVP Ticket 不再将 CRCA-009 列为必需依赖。
- [x] 当前设计、Spec 和 ADR 不再把 CPU Reranker 描述为 CodeRCA MVP 能力或降级阶段。

## Testing Strategy

不适用。当前一致性检查应证明默认依赖、实现计划和验收流程均不要求 reranker 或其模型依赖。

## Dependencies

无当前依赖。

## Risks

- 历史文件中的标题可能让读者误认为仍计划实施；Status 与本说明必须保持在文件顶部，Issue Tracker 后续同步时也应移除 `ready-for-agent` 语义。
- 未来在没有独立 Retrieval Evaluation 的情况下恢复 reranker，会重新混淆搜索质量与 Agent 诊断质量。

## Estimated Effort

Not estimated — Out of MVP

## Related Spec Sections

- Out of Scope — 高级检索基础设施
- Further Notes — Lightweight Code Search 边界

## Related ADRs

- ADR-0015 — CodeRCA MVP 使用 Lightweight Code Search
- ADR-0007 — 两周 MVP 使用固定混合检索管线（Superseded）
