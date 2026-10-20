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

- CRCA-005～008：Evidence/Assessment/Reformulation 循环、Tool Runtime、Docker 测试与单次补丁 Validation、Lightweight Code Search。
- CRCA-010：冻结 Task 2 与专用验收器已存在；真实模型 Run `7c40fa56-d099-4578-ba16-90aea2940516` 使用 7/10 Tool Budget，Reformulate H2 后定位 `waffle/utils.py::keyfmt` 的大小写折叠，生成正确补丁并通过 Public Validation。最终位置同时引用 H1 Evidence Basis 与 H2 直接代码 Evidence；专用验收器报告 `location=hit`、`repair_validation=passed`、`search_capability=verified`、`outcome_pass=true`，仍需人工因果审核。
- [ADR-0016](adr/0016-final-location-and-independent-search-acceptance.md)：最终报告定位独立于初始 Hypothesis 猜测；supported H 的直接 Evidence 或显式 Evidence Basis 可证明坐标，但不自动证明符号或因果；Outcome 与搜索展示分离。
- [ADR-0017](adr/0017-executable-experiments-and-bounded-hypothesis-testing.md)：工具能力约束可执行 Experiment，并将每个 Active Hypothesis 的诊断 Experiment 限制为三次。
- [ADR-0018](adr/0018-deterministic-patch-compilation.md)：模型提交结构化 Patch Intent，程序确定性编译唯一 Candidate Patch，再进入 Public Validation。

通用 Evaluation Harness 尚待实现。ContextBuilder 的确定性 Context View 已实现并有单元测试；Patch Intent 编译不重构 ContextBuilder。Task 2 数据保持冻结；专用自动验收已经通过，但仍不得把单任务 Outcome 或搜索能力通过表述为通用诊断能力，且因果结论仍需人工审核。
