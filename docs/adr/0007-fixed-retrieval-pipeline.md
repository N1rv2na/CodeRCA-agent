# ADR-0007：两周 MVP 使用固定混合检索管线

- 状态：Accepted
- 日期：2026-08-06
- 取代：ADR-0003

## 背景

完整比较 BM25、向量、混合和 reranker 四种配置需要冻结查询、标注 Root Symbol、运行消融并解释指标。该工作服务于研究结论，却不阻塞 Agent 工作流的真实闭环。

## 决策

MVP 只实现一条冻结的 AST 分块、BM25/向量混合与 CPU reranker 管线。embedding 预计算，融合与 Top-K 固定，Agent 只调用 `search_code`。不实现多配置切换、参数搜索或检索消融。

## 后果

CodeRCA 可以展示完整代码 RAG 数据路径，但只能声明使用了混合检索与重排，不能声明任何组件带来可量化增益。进度落后时先删除 reranker，保持统一检索接口不变。
