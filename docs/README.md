# CodeRCA 文档

- [两周 MVP 项目设计](design.md)：当前权威的产品范围、领域模型、架构、工作流、Lightweight Code Search、沙箱、评测与交付约束。
- [MVP Specification](spec.md)：当前实现合同、用户故事、技术决策、测试缝与验收边界。
- [统一语言表](../CONTEXT.md)：诊断、验证与评测共享的规范领域术语。
- [旧术语表入口](glossary.md)：为已有链接保留的兼容跳转页。
- [架构决策记录](adr/README.md)：关键设计选择、替代方案和后果。
- [Agent 配置](agents/)：Issue Tracker、triage 标签和领域文档使用约定。

建议先阅读项目设计，再按其中的链接查看具体 ADR。

## 当前实现状态

- CRCA-001：Manifest-to-Run walking skeleton；
- CRCA-002：冻结的 django-waffle Task 1、独立 Evaluation Ground Truth 与基准材料；
- CRCA-003：通用 OpenAI-compatible ModelProvider、两种 Structured Output Mode、受控 Request Extensions 与 Model Compatibility Gate。
- CRCA-004：单个初始 H1、append-only H1～H3 History 与 single-active 不变量、五类 decision-specific Context View、一次 Schema 纠错、Schema Failure 终止，以及显式选择 OpenAI-compatible Provider 的真实模型形成入口。

完整诊断工具循环、Tool Runtime、Lightweight Code Search、Docker Validation 和 Evaluation Harness 仍属于后续 Ticket，不能从当前代码状态推断为已经实现。ContextBuilder 的确定性 Context View 已经实现并有单元测试，不属于这些待开发项。
