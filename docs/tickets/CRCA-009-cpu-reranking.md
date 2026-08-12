# CRCA-009 — 增加固定 CPU Reranker

## Priority

P1

## Milestone

M3 — Retrieval & Generalization Evidence

## Background

完整目标希望展示 BM25、向量融合后的小候选集重排，但 reranker 不应改变 Agent 工具协议，也不能成为两周闭环的必要条件。它是 Spec 明确允许在第七天首先删除的增强项。

## Goal

在保持 `search_code` 输入输出合同不变的前提下，用一个固定 CPU reranker 对融合候选进行可复现重排。

## Scope

- 冻结一个 CPU 可运行的 reranker 及其版本。
- 固定 rerank 输入候选数、批大小和最终 Top-K。
- 在运行产物中记录融合前后顺序和分数。
- 保持 `search_code` 对 Agent 暴露的 Tool Spec 不变。
- 为关闭 reranker 的降级配置保留相同结果 Schema。

## Out of Scope

- GPU reranking、模型选择 Benchmark、参数搜索或消融研究。
- 声明 reranker 带来可量化命中率提升。
- 修改 Agent Prompt 或让模型决定是否 rerank。

## Technical Approach

把 reranker 作为固定检索管线内部的可删除阶段。它只接收融合后的有限候选，在 CPU 上执行，并产出同一种 Search Result。开启与降级关闭两种配置都必须保持工具合同、元数据和审计字段稳定。

## Implementation Steps

1. 选择并冻结 CPU reranker、候选数、批大小和 Top-K。
2. 接入融合候选到重排结果的数据路径。
3. 保存重排前后候选、分数和配置元数据。
4. 实现关闭 reranker 时的合同兼容路径。
5. 增加确定性、性能门槛和接口兼容测试。

## Acceptance Criteria

- [ ] reranker 在 CPU 上运行，不初始化 CUDA，也不要求本地诊断 GPU。
- [ ] 相同索引、查询和配置产生相同的候选顺序。
- [ ] 重排前后的候选、分数和固定配置可从运行产物审计。
- [ ] 开启或关闭 reranker 时，`search_code` Tool Spec 与结果 Schema 不变。
- [ ] reranker 不可用时明确失败；仅在显式降级配置中跳过，不静默改变算法。
- [ ] 文档不声称已证明 reranker 的独立效果。

## Testing Strategy

- 使用固定小候选集测试稳定排序、同分规则和 Top-K 截断。
- 对开启/关闭配置执行同一 `search_code` 合同测试。
- 监测测试进程不初始化 CUDA，并设置可接受的 CPU 延迟上限。
- 验证运行记录包含模型版本和重排前后结果。

## Dependencies

- CRCA-008 — 实现固定的混合代码检索流水线

## Risks

- CPU 延迟超过五分钟单任务预算；限制候选集并在 Day-7 降级时删除该阶段。
- 本地依赖安装复杂；选择与 Python 环境兼容且可固定版本的轻量实现。
- 排序分数被误当概率；仅作为检索内部排序信号。

## Estimated Effort

0.5 engineer-day

## Related Spec Sections

- User Stories 28, 49–50
- Implementation Decisions 28, 31, 44
- Testing Decisions 17, 27
- Further Notes — 固定 reranker 与 Top-K

## Related ADRs

- ADR-0007 — 两周 MVP 使用固定混合检索管线
- ADR-0011 — 两周 MVP 使用单一 Gemini 云端模型 API
