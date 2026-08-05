# 架构决策记录

| ADR | 状态 | 决策 |
|---|---|---|
| [0001](0001-explicit-diagnosis-state-machine.md) | Accepted | 使用自研显式诊断状态机 |
| [0002](0002-typed-tool-runtime.md) | Accepted | 使用结构化工具运行时，不实现 MCP |
| [0003](0003-retrieval-ablation-boundary.md) | Accepted | 统一检索接口并隔离检索消融 |
| [0004](0004-container-sandbox-boundary.md) | Accepted | 采用有限威胁模型的容器沙箱 |
| [0005](0005-persistence-and-artifacts.md) | Accepted | 分离 SQLite 元数据与大对象 Artifact |
| [0006](0006-model-provider-strategy.md) | Accepted | 本地优先、云端兜底，并隔离模型服务 |

ADR 被接受后不直接改写历史结论。若决策改变，应新增 ADR 并标记被替代关系。
