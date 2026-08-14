# 架构决策记录

| ADR | 状态 | 决策 |
|---|---|---|
| [0001](0001-explicit-diagnosis-state-machine.md) | Accepted | 使用自研显式诊断状态机 |
| [0002](0002-typed-tool-runtime.md) | Accepted | 使用结构化工具运行时，不实现 MCP |
| [0003](0003-retrieval-ablation-boundary.md) | Superseded by 0007 | 统一检索接口并隔离检索消融 |
| [0004](0004-container-sandbox-boundary.md) | Superseded by 0010 | 采用有限威胁模型的容器沙箱 |
| [0005](0005-persistence-and-artifacts.md) | Superseded by 0008 | 分离 SQLite 元数据与大对象 Artifact |
| [0006](0006-model-provider-strategy.md) | Superseded by 0009 | 本地优先、云端兜底，并隔离模型服务 |
| [0007](0007-fixed-retrieval-pipeline.md) | Accepted | 固定混合检索与 CPU 重排，不做消融 |
| [0008](0008-run-directory-persistence.md) | Accepted | 按 Diagnosis Run 目录保存结构化记录 |
| [0009](0009-single-local-model-provider.md) | Superseded by 0012 | 只连接一个外部本地模型服务 |
| [0010](0010-minimal-docker-execution-boundary.md) | Accepted | 单镜像、临时工作区、禁网、注册命令和超时 |
| [0011](0011-single-gemini-cloud-model-provider.md) | Superseded by 0012 | 只连接 Gemini 云端模型 API |
| [0012](0012-configurable-openai-compatible-cloud-provider.md) | Accepted | 使用单个可配置的 OpenAI-compatible 云端模型 |

ADR 被接受后不直接改写历史结论。若决策改变，应新增 ADR 并标记被替代关系。
