# CodeRCA

CodeRCA 是一个面向 Python/Django 单仓库 CI 测试失败的根因分析 Agent。它围绕“Hypothesis → Evidence → Experiment”循环，自主检索相关代码、调用诊断工具、形成根因候选，并在隔离沙箱中验证候选补丁。

项目主要用于展示 AI Agent 工程能力，包括：

- 显式 Agent 工作流与状态管理；
- 结构化工具协议与权限边界；
- BM25、向量检索与 reranking 组合的代码 RAG；
- 容器沙箱中的实验与修复验证；
- 可复现的基线、消融和端到端评测。

## MVP 范围

第一版聚焦业务逻辑回归、API 契约变化和配置错误，不覆盖生产环境告警、性能问题、外部服务故障、随机失败或并发故障。

项目目前处于设计与实现准备阶段。

## 文档

- [MVP Specification](docs/specification.md)
- [项目设计](docs/design.md)
- [领域术语](CONTEXT.md)
- [架构决策记录](docs/adr/README.md)
