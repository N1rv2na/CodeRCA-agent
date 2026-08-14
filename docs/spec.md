# CodeRCA Two-Week MVP Specification

| 属性 | 内容 |
|---|---|
| 状态 | Ready for implementation |
| 日期 | 2026-08-06 |
| 权威设计 | [CodeRCA 两周 MVP 设计](design.md) |
| 产品范围 | 一个冻结 Django 仓库中的业务逻辑回归 |
| 主要招聘信号 | Agent 工作流与 Tool Runtime |
| 最高测试缝 | Diagnosis Application Service |

## Problem Statement

后端工程师面对由已知代码变更引起的 CI 测试失败时，需要在失败日志、Git diff、相关代码和测试行为之间反复切换，才能定位真正的 Root Cause。单次模型回答容易把失败表象当成根因，也无法持续维护可证伪的 Hypothesis、通过 Experiment 收集 Supporting Evidence 与 Contradicting Evidence，或用真实 Validation 检查修复建议。

对项目作者而言，目标是在两周内完成一个可真实运行、可检查的 AI Agent 求职原型，而不是构建研究级 Benchmark 或通用故障平台。MVP 必须把有限开发时间集中在显式 Agent 工作流、结构化 Tool Runtime、有界上下文、代码 RAG 和 Docker Experiment 上，同时通过小规模工程 Evaluation 防止核心行为回归。

## Solution

CodeRCA 提供一个本机 CLI。用户提交符合 Schema 的 Task Manifest，描述同一冻结 Django 仓库中的 Faulty Commit、CI 日志、注册测试命令、Docker 镜像和执行边界。Diagnosis Application Service 创建 Diagnosis Run，并由最小显式状态机控制生命周期；诊断循环内部使用受约束 ReAct，让操作者配置的 OpenAI-compatible 云端模型提出最多三个 Hypothesis、选择 Experiment、解释 Observation 和更新 Evidence。

Agent 通过五个结构化工具检查 diff、检索代码、读取源码、运行测试和应用补丁。代码检索使用固定的 Python AST 分块、BM25/向量混合和 CPU reranker 管线。每个工具调用必须关联一个活跃 Hypothesis、调用目的和预期 Observation。程序负责 Schema、权限、超时、错误、Evidence Score、八次工具预算和停止条件。

诊断完成后，系统只为 Top-1 Root Cause Candidate 生成一个候选补丁，并在最小 Docker 执行边界中运行注册 Validation。CLI 输出实时摘要，完整事件、模型响应、工具结果、补丁和 Root Cause Report 保存到独立运行目录。三个冻结任务分别验证 diff/代码证据、RAG 证据和测试 Experiment 路径；Evaluation Harness 只进行确定性的 Outcome Evaluation 与 Trajectory Evaluation，不产生统计性泛化结论。

## User Stories

### 后端工程师与 CLI 用户

1. 作为后端工程师，我希望通过 Task Manifest 提交 Diagnosis Task，从而使用可复现的故障输入启动诊断。
2. 作为后端工程师，我希望 Manifest 明确 Faulty Commit、CI 日志和测试命令，从而知道 Agent 正在诊断哪个失败版本。
3. 作为后端工程师，我希望系统在运行前校验任务是否属于受支持仓库和环境，从而避免把环境错误误认为诊断失败。
4. 作为后端工程师，我希望通过 CLI 启动 Diagnosis Run，从而无需部署服务或使用 Web UI。
5. 作为后端工程师，我希望 CLI 显示当前生命周期状态，从而知道系统正在形成 Hypothesis、执行工具、更新 Evidence 还是验证补丁。
6. 作为后端工程师，我希望查看最多三个 Root Cause Candidate，从而理解 Agent 考虑了哪些可能根因。
7. 作为后端工程师，我希望每个候选包含 Root Symbol 和简短故障机制，从而能快速检查位置与解释是否合理。
8. 作为后端工程师，我希望 Supporting Evidence 与 Contradicting Evidence 分开显示，从而区分支持结论和排除候选的依据。
9. 作为后端工程师，我希望每次 Experiment 说明所属 Hypothesis、目的和预期 Observation，从而判断工具调用是否具有诊断价值。
10. 作为后端工程师，我希望代码 Evidence 引用文件、符号和行区间，从而能够追溯到原始实现。
11. 作为后端工程师，我希望测试 Evidence 引用实际命令和输出，从而确认结论来自真实执行而非模型猜测。
12. 作为后端工程师，我希望 Agent 能根据新 Observation 改变候选排序，从而体现动态诊断而非固定工具流水线。
13. 作为后端工程师，我希望 Agent 只为 Top-1 生成一个候选补丁，从而控制诊断成本和补丁搜索范围。
14. 作为后端工程师，我希望候选补丁在临时 Docker 工作区中执行注册 Validation，从而避免直接修改真实仓库。
15. 作为后端工程师，我希望无论 Validation 通过或失败都生成 Root Cause Report，从而保留完整诊断结果。
16. 作为后端工程师，我希望证据不足或预算耗尽时系统明确停止并说明原因，从而不强行生成确定结论。
17. 作为后端工程师，我希望模型、Schema、工具和沙箱错误被明确记录，从而能够区分基础设施失败与诊断错误。
18. 作为后端工程师，我希望每次运行保存独立的事件、报告、补丁和测试输出，从而可以在运行结束后检查过程。
19. 作为后端工程师，我希望为同一冻结仓库的新故障编写符合 Schema 的 Manifest，从而复用 Agent 工作流而不是只能运行三个硬编码案例。
20. 作为后端工程师，我希望系统明确只保证一个仓库中的业务逻辑回归，从而不会误解原型的泛化能力。

### 技术评审者与面试官

21. 作为技术评审者，我希望看到生命周期状态机与诊断 ReAct 循环的边界，从而判断编排逻辑是否由项目自身控制。
22. 作为技术评审者，我希望看到 Hypothesis、Evidence、Experiment 和 Observation 的结构化状态，从而验证项目不是单次模型调用。
23. 作为技术评审者，我希望看到不同冻结任务产生不同必要工具路径，从而验证诊断轨迹不是完全硬编码。
24. 作为技术评审者，我希望每个工具共享 Tool Spec 契约，从而检查 Schema、权限、超时、错误和审计设计。
25. 作为技术评审者，我希望模型只负责提出决策而程序维护不变量，从而理解系统如何约束外部模型。
26. 作为技术评审者，我希望查看每一步重新组装的有界状态快照，从而评估 Context Engineering 是否避免无限历史追加。
27. 作为技术评审者，我希望 `search_code` 返回 AST 符号元数据和排序结果，从而检查代码 RAG 如何支持 Root Cause 定位。
28. 作为技术评审者，我希望检索实现明确采用固定混合管线，从而不会把未经评测的配置选择描述为可量化增益。
29. 作为技术评审者，我希望看到 Docker 中真实运行的测试与补丁结果，从而确认 Experiment 不只是模拟响应。
30. 作为技术评审者，我希望看到逐任务 Outcome Evaluation 与 Trajectory Evaluation，从而判断 Agent 修改后是否发生行为回归。
31. 作为技术评审者，我希望项目公开失败任务和停止原因，从而避免只展示成功路径。
32. 作为技术评审者，我希望设计明确列出延期能力和安全声明，从而区分已实现证据与未来愿景。

### 项目开发者

33. 作为项目开发者，我希望 CLI 和 Evaluation Harness 调用同一个 Diagnosis Application Service，从而只有一个最高端到端测试缝。
34. 作为项目开发者，我希望使用 FakeModelProvider 驱动确定性 Diagnosis Run，从而在默认 CI 中测试真实状态机而不依赖 API Key、网络或 GPU。
35. 作为项目开发者，我希望不同生命周期阶段使用各自的小型 Schema，从而提高模型结构输出的稳定性。
36. 作为项目开发者，我希望第一次 Schema Failure 后只允许一次明确纠错，从而避免模糊解析和无限重试。
37. 作为项目开发者，我希望状态机拒绝非法阶段转换，从而保证工具、Evidence 和补丁只在合法阶段出现。
38. 作为项目开发者，我希望初始 Hypothesis 数量限制为一至三个，从而保持候选竞争有界。
39. 作为项目开发者，我希望初始候选形成后不动态补充、替换或重新激活，从而控制两周 MVP 的状态复杂度。
40. 作为项目开发者，我希望程序按固定 Evidence Score 更新候选排序，从而不依赖模型自报置信度。
41. 作为项目开发者，我希望 Supporting Evidence 加分且 Contradicting Evidence 扣分，从而使排序变化可解释并可测试。
42. 作为项目开发者，我希望一次 Diagnosis Run 最多调用八次工具，从而保证 Agent 有确定终止上限。
43. 作为项目开发者，我希望工具结果、模型响应和 Schema 错误保存到运行目录，从而可以调试失败步骤。
44. 作为项目开发者，我希望五个工具通过统一注册与执行入口，从而避免各自实现不同的权限和错误逻辑。
45. 作为项目开发者，我希望工具默认不自动重试，从而避免重复执行有副作用的操作。
46. 作为项目开发者，我希望路径校验拒绝仓库外读取和非允许源码修改，从而保护宿主文件与任务基础设施。
47. 作为项目开发者，我希望 ModelProvider 只依赖 OpenAI-compatible Chat Completions 协议，从而不把厂商 SDK、模型托管、路由或回退耦合进 Agent 核心。
48. 作为项目开发者，我希望显式运行通用 Model Compatibility Gate 验证已配置模型的 Schema、工具参数、Evidence 更新和补丁能力，从而降低末期集成风险。
49. 作为项目开发者，我希望每次运行只接受一个由环境变量配置的端点和模型，从而避免模型发现、自动选择和多后端状态复杂度。
50. 作为项目开发者，我希望 embedding 在索引阶段预计算且 reranker 在 CPU 运行，从而让本地检索与云端诊断模型相互隔离。
51. 作为项目开发者，我希望索引器按函数、方法和类建立 AST 语义块，从而保留代码结构和 Root Symbol 元数据。
52. 作为项目开发者，我希望源码变化时整库重建索引，从而避免实现增量索引和缓存迁移。
53. 作为项目开发者，我希望每次模型调用从结构化状态重新组装上下文，从而避免 Prompt 随历史无限增长。
54. 作为项目开发者，我希望大日志和测试输出只通过运行文件引用，从而让模型上下文保持有界。

### Diagnosis Task 维护者

55. 作为任务维护者，我希望三个冻结任务共享仓库、Docker 镜像和索引流程，从而降低环境维护成本。
56. 作为任务维护者，我希望每个任务拥有独立 Faulty Commit、CI 日志和注册测试入口，从而保持故障可复现。
57. 作为任务维护者，我希望 Agent 输入与 Root Symbol、参考修复和 Evaluation 答案分离，从而避免答案泄漏。
58. 作为任务维护者，我希望 Task 1 主要需要 diff 和代码阅读，从而验证变更证据路径。
59. 作为任务维护者，我希望 Task 2 的 Root Symbol 不能从堆栈直接读取，从而验证混合代码检索路径。
60. 作为任务维护者，我希望 Task 3 存在至少两个合理候选并需要测试 Experiment 排除错误候选，从而验证假设竞争。
61. 作为任务维护者，我希望 Task 3 在核心 Prompt、Schema 和工具策略基本冻结后运行，从而提供有限的未见故障检查。
62. 作为任务维护者，我希望每个任务标注 Root Symbol、触发条件、故障机制、失败表现和参考修复行为，从而支持确定性 Evaluation 与人工核查。

### Evaluation 执行者与本地操作者

63. 作为 Evaluation 执行者，我希望精确比较 Top-1 Root Symbol，从而确定性判断根因位置是否命中。
64. 作为 Evaluation 执行者，我希望检查候选补丁是否可应用和注册 Validation 是否通过，从而评价可执行结果。
65. 作为 Evaluation 执行者，我希望检查 Root Cause Report 的必需字段，从而防止缺失因果解释或 Evidence 引用。
66. 作为 Evaluation 执行者，我希望检查所有工具调用是否绑定合法 Hypothesis，从而验证核心轨迹不变量。
67. 作为 Evaluation 执行者，我希望检查 Experiment 是否声明目的和预期 Observation，从而拒绝无目标工具探索。
68. 作为 Evaluation 执行者，我希望检查 Evidence 是否引用真实 Observation，从而拒绝无来源的模型判断。
69. 作为 Evaluation 执行者，我希望检查八次工具预算和合法停止原因，从而发现循环或越界行为。
70. 作为 Evaluation 执行者，我希望检查只有 Top-1 进入补丁 Validation，从而保证缩减后的补丁策略未被破坏。
71. 作为 Evaluation 执行者，我希望输出三个任务的逐任务结果，从而避免小样本百分比造成误导。
72. 作为 Evaluation 执行者，我希望由作者人工核查因果机制，从而不引入额外 LLM Judge。
73. 作为本地操作者，我希望可以显式运行 Model Compatibility Gate 检查当前 Model Configuration，从而在 Diagnosis Run 前发现协议或能力问题，而不把报告作为运行授权。
74. 作为本地操作者，我希望只构建一个冻结的 Django Docker 镜像，从而控制环境和构建成本。
75. 作为本地操作者，我希望容器默认禁网、只运行注册命令并设置超时，从而降低正常测试的意外副作用。
76. 作为本地操作者，我希望 API Key 和云端模型流量不进入测试容器，也不写入运行产物，从而保持执行与凭证边界清晰。

## Implementation Decisions

1. **产品边界**：MVP 只支持一个冻结开源 Django 仓库中的业务逻辑回归。Task Manifest 可以描述同仓库的新故障，但不构成任意仓库兼容承诺。
2. **应用入口**：Diagnosis Application Service 是 CLI 与 Evaluation Harness 共享的最高入口，负责接收 Diagnosis Task、创建 Diagnosis Run 并返回状态、事件、Root Cause Report 与运行产物引用。
3. **Task Manifest**：Manifest 必须版本化，并包含任务 ID、仓库标识、基础快照、Faulty Commit、CI 日志、注册测试命令 ID、Docker 镜像、读写范围和工具调用上限。
4. **输入隔离**：Agent 可见输入不得包含 Root Symbol 标准答案、参考补丁、修复后代码、答案性 commit message 或 Evaluation 结果。
5. **任务校验**：MVP 校验 Manifest Schema、受支持仓库、commit、日志、注册命令、镜像和路径边界；不负责自动修复未知环境。
6. **生命周期编排**：使用最小显式状态机管理 Preparing、Forming Hypotheses、Diagnosing、Executing Tool、Updating Evidence、Validating Top-1 和 Finalizing 阶段。
7. **受约束 ReAct**：Diagnosing、Executing Tool 和 Updating Evidence 构成诊断 ReAct 循环；状态机管理生命周期和不变量，不暴露自由的无限 ReAct。
8. **阶段 Schema**：形成 Hypothesis、选择 Experiment、更新 Evidence、生成补丁和生成报告分别使用字段较少的结构化 Schema。
9. **Schema Failure**：结构输出失败时保存原始响应和校验错误，允许一次明确纠错；再次失败产生 Schema Failure，不使用模糊正则恢复。
10. **候选范围**：模型初始形成一至三个 Hypothesis。初始候选形成后不再动态补充、替换或重新激活。
11. **Hypothesis 生命周期**：候选状态限定为 proposed、testing、supported、rejected 和 inconclusive；被拒绝候选不再参与工具选择。
12. **Experiment 契约**：每个工具调用必须包含活跃 Hypothesis ID、目的、预期 Observation、工具名和结构化参数。
13. **Evidence 契约**：Evidence 必须引用输入或真实工具 Observation，并明确为 Supporting、Contradicting 或无信息结果。
14. **Evidence Score**：程序使用固定整数规则排序候选。来源强度依次为可复现实验、直接代码/堆栈/断言、Git diff 关联和检索相似性；反证使用对应负权重。分数不是概率。
15. **工具预算**：一次 Diagnosis Run 最多执行八次工具调用。总运行超时由 CLI 外层统一控制，不实现 Token、费用和多级时间预算。
16. **停止条件**：Top-1 完成 Validation、工具预算耗尽、所有候选 rejected/inconclusive、二次 Schema Failure 或不可恢复的模型/工具/沙箱错误都会停止运行。
17. **Top-1 补丁**：只为当前 Top-1 生成一个正式候选补丁。无论 Validation 结果如何，不执行第二轮自动补丁搜索，也不为 Top-2/Top-3 生成补丁。
18. **Tool Spec**：每个工具声明名称、版本、描述、输入输出 Schema、权限类别、超时、结果上限、副作用和结构化错误。
19. **工具错误**：统一错误至少包括 invalid arguments、permission denied、timeout 和 execution failed；工具默认不自动重试。
20. **工具审计**：调用事件记录 Hypothesis、目的、预期 Observation、参数摘要、耗时、状态和结果引用，不记录或要求私有思维链。
21. **冻结工具集**：MVP 只有 `inspect_diff`、`search_code`、`read_code`、`run_tests` 和 `apply_patch` 五个工具，不实现 MCP 或任意 Shell。
22. **工具合并**：符号信息由 `search_code` 返回的 AST 元数据承载，不实现独立符号分析工具；语法和轻量静态检查并入注册 Validation。
23. **路径权限**：只读工具只能访问 Manifest 允许的仓库范围；补丁只能修改允许的业务源码，不能修改测试、依赖锁、任务定义或 Evaluation 数据。
24. **上下文快照**：每次模型请求重新组装 Diagnosis Task 摘要、最多三个 Hypothesis、Evidence 摘要、最近 Observation、剩余预算和少量必要原文。
25. **上下文外数据**：完整日志、代码、测试输出和模型响应保存到运行目录；MVP 不实现自动摘要、长期记忆、按需 Artifact 召回或历史重放。
26. **ModelProvider**：只实现一个 OpenAI-compatible HTTP ModelProvider。每次进程运行通过 `CODERCA_MODEL_BASE_URL`、`CODERCA_MODEL_ID` 和 `CODERCA_MODEL_API_KEY` 配置一个 Chat Completions 端点和模型；请求必须非流式、`temperature=0`、使用 strict JSON Schema，并通过本地 Pydantic 校验。
27. **Model Compatibility Gate**：显式命令最多执行一次预检和四个一次性能力探针，覆盖阶段 Schema、合法工具参数、Evidence 更新和可应用的小型 Python 补丁，输出脱敏 Model Compatibility Report。它是建议性兼容检查，不授权或阻止 Diagnosis Run。
28. **计算边界**：诊断模型由云端 API 托管。代码 embedding 在索引阶段预计算，reranker 在本机 CPU 上执行小候选集重排；MVP 不管理诊断模型 GPU、量化或加载。
29. **RAG 索引**：只索引 Faulty Commit 快照。以 Python AST 函数、方法和类为主要语义单元，保存路径、符号、父类、行区间和源码。
30. **索引更新**：仓库路径和排除规则由配置提供；源码变化时整库重建，不实现增量索引、缓存迁移或任意仓库质量保证。
31. **固定检索管线**：`search_code` 使用 BM25 与向量召回、固定融合、CPU reranker 和固定 Top-K。Agent 不选择算法，MVP 不实现消融、参数搜索或在线调参。
32. **检索查询**：查询可以使用异常类型、消息、堆栈、失败测试、diff 符号和 Hypothesis 语义描述；动态查询必须关联对应 Hypothesis。
33. **Docker 边界**：MVP 使用一个预构建 Django 镜像和临时工作区，默认禁网，只执行注册命令，设置统一超时且不挂载 `CODERCA_MODEL_API_KEY`；云端模型请求只由宿主 Agent 进程发起。
34. **安全声明**：Docker 边界只降低正常测试的意外副作用，不承诺生产级沙箱、恶意代码防御、容器逃逸防护或跨平台一致性。
35. **Validation 流程**：Top-1 补丁通过路径校验后应用到临时工作区，再运行注册测试与轻量静态检查；结果成为 Evidence 和报告字段。
36. **运行记录**：每个 Diagnosis Run 使用独立目录保存 Manifest 快照、JSONL 事件、JSON 报告、模型响应、工具输出、补丁和 Validation 结果。
37. **持久化边界**：大文本使用普通文件引用；不实现 SQLite、内容寻址、跨运行去重、数据库迁移、崩溃恢复或回放。
38. **CLI**：CLI 负责读取 Manifest、启动 Diagnosis Run、显示关键状态与事件、输出最终报告和运行目录；不提供交互式任务创建、后台执行、HTTP API 或并发。
39. **Root Cause Report**：报告包含 Top-1/Top-3 候选、位置与 Root Symbol、简短机制、Top-1 因果字段、支持/反对 Evidence、修复建议、补丁、Validation 和停止原因。
40. **冻结任务**：三个任务共享仓库、镜像和索引流程，但分别强制使用 diff/代码、RAG 和测试 Experiment 证据路径。Task 3 在 Prompt、Schema 和工具策略基本冻结后运行。
41. **Evaluation**：Outcome Evaluation 检查 Root Symbol、补丁可应用性、Validation 和报告契约；Trajectory Evaluation 检查 Hypothesis 绑定、Experiment 目的、Evidence 引用、预算、停止和 Top-1 补丁不变量。
42. **结果表达**：Evaluation 输出逐任务结果，不调用 LLM Judge，不与 Baseline 比较，不汇总具有统计或泛化暗示的成功率；因果机制由作者人工核查。
43. **交付方式**：MVP 通过源码、本地 Python 环境、操作者配置的 OpenAI-compatible 云端模型 API、一个 Docker 镜像和 CLI 交付，不发布 PyPI、Compose 或托管服务。
44. **第七天降级**：如果第七天仍未完成真实纵向闭环，依次删除 reranker、将任务从三个减少到两个、将报告从 Top-3 减少到 Top-1，同时保留内部多个 Hypothesis。
45. **不可削减核心**：最小状态机、五工具协议、已配置的真实云端模型、一个 Docker Experiment 和 Top-1 补丁 Validation 不得因进度被替换为模拟实现。

## Testing Decisions

1. **测试哲学**：测试观察公开契约、领域不变量和外部行为，不断言私有函数调用顺序、Prompt 逐字内容或模型私有思维链。
2. **最高测试缝**：Diagnosis Application Service 是唯一最高验收缝。测试提交 Diagnosis Task，并观察 Diagnosis Run 结果、结构化事件、Root Cause Report、运行产物、停止原因和失败结果。
3. **适配器测试**：CLI 与 Evaluation Harness 通过同一应用服务测试，不各自复制完整 Agent 端到端体系。
4. **测试先例**：仓库当前没有实现或测试文件，因此不存在可复用测试先例；本 specification 建立应用服务主缝和分层测试边界。
5. **FakeModelProvider 闭环**：至少一个确定性测试使用 FakeModelProvider 驱动 Manifest 读取、Hypothesis、工具调用、Evidence、补丁、Validation、报告和运行事件的完整纵向路径。
6. **真实模型隔离**：默认 CI 不读取 API Key、不访问网络且不需要 GPU。Model Compatibility Gate 和三个真实模型 Agent Evaluation 任务必须显式运行。
7. **状态机测试**：验证合法与非法阶段转换、终态不可继续执行、不可恢复错误进入 Finalizing，以及真实工具不会在错误阶段调用。
8. **Hypothesis 测试**：验证一至三个初始候选、超过三个被拒绝、候选不动态补充或复活，以及 rejected 候选不能再被选择。
9. **Evidence Score 测试**：验证实验、直接证据、diff 和检索相似性的单调强度关系，Contradicting Evidence 扣分，并验证分数不作为概率输出。
10. **预算与停止测试**：验证八次工具上限、候选耗尽、Top-1 Validation、Schema Failure 和不可恢复错误均产生合法停止原因。
11. **Schema 测试**：分别覆盖五类阶段 Schema 的合法输出、首次失败后纠错成功、二次失败终止，以及原始响应与校验错误落盘。
12. **上下文测试**：验证每一步上下文从当前结构化状态重建，完整历史不会无限追加，大日志和测试输出只通过引用进入状态快照。
13. **统一工具契约测试**：五个工具执行同一套输入输出 Schema、权限、超时、错误、审计和结果上限测试。
14. **工具安全测试**：验证路径穿越、仓库外读取、禁止源码修改、测试修改、依赖锁修改、未知测试命令和任意 Shell 均被拒绝。
15. **工具错误测试**：分别注入非法参数、权限拒绝、超时和执行失败，验证事件与 Diagnosis Run 保留正确分类且默认不重试。
16. **RAG 分块测试**：验证函数、方法和类的 AST 语义块保留路径、符号、父类和行区间，超长分窗仍保留所属符号。
17. **RAG 集成测试**：在冻结代码快照上执行 BM25、向量融合和 CPU reranker，验证结果具有稳定 Schema、可追溯代码位置且不访问修复后代码。
18. **索引重建测试**：验证快照变化触发整库重建，旧索引不会被错误用于新的 Faulty Commit。
19. **Docker 集成测试**：验证临时工作区、默认禁网、注册命令、统一超时和 `CODERCA_MODEL_API_KEY` 不挂载；不把未承诺的生产安全能力写成验收条件。
20. **补丁测试**：验证只允许 Top-1 进入补丁阶段，补丁只能修改允许源码，Validation 后停止且不会启动第二轮补丁搜索。
21. **运行记录测试**：验证 Manifest 快照、JSONL 事件、JSON 报告、模型响应、工具输出、补丁和 Validation 结果均写入独立运行目录。
22. **Root Cause Report 测试**：验证 Top 候选、Root Symbol、因果字段、Supporting/Contradicting Evidence、修复建议、补丁、Validation 和停止原因的最小合同。
23. **Outcome Evaluation 测试**：用人工构造的命中、未命中、补丁失败和报告缺字段样例验证确定性规则，不使用模糊文本相似度替代 Root Symbol。
24. **Trajectory Evaluation 测试**：用合法轨迹和违反 Hypothesis 绑定、Experiment 目的、Evidence 引用、预算、停止或 Top-1 规则的轨迹验证检测器。
25. **三个任务验收**：逐任务记录 Root Symbol、补丁、Validation、报告和轨迹结果；不以三个任务计算具有泛化暗示的成功率。
26. **人工因果核查**：作者对触发条件、故障机制和失败表现逐任务核查并记录差异，不实现自动 Judge 或一致率研究。
27. **降级验收**：若触发第七天降级，文档、Manifest、Evaluation 期望和报告合同必须同步反映实际范围，不保留虚假能力声明。

## Out of Scope

- API 契约变化和配置错误；
- 外部服务、性能、容量、随机、flaky 和并发故障；
- 任意 Python/Django 仓库、多仓库、跨仓库和非 Python 诊断保证；
- 生产 Trace、Metrics、告警、日志平台和网络查询；
- Raw Model Baseline、Fixed Pipeline、大规模 Benchmark 和统计显著性结论；
- BM25、向量、混合与 reranker 的多配置消融、参数搜索和在线调参；
- LLM Judge、大规模隐藏集、稳定性重复实验和 Judge 一致率研究；
- 完整 Hidden Validation、自动语义防投机和 Top-3 补丁逐个验证；
- 动态增加、替换、恢复或重新激活 Hypothesis；
- 多轮自动补丁搜索；
- 独立符号关系工具、完整 Python 调用图和独立静态检查工具；
- 自动摘要、长期记忆、Artifact 召回和运行回放；
- SQLite、内容寻址 Artifact、跨运行去重、崩溃恢复和后台 Worker；
- FastAPI、Web UI、静态 HTML 报告和远程协作；
- 本地模型后端、原生厂商 SDK、多真实模型适配、模型发现、自动选择、路由、回退、模型加载、量化和诊断模型 GPU 管理；
- MCP、任意 Shell、任意网络访问和生产工具；
- 生产级沙箱、恶意代码防御、容器逃逸防护和跨平台安全保证；
- 自动修改真实仓库、推送分支或创建 PR；
- PyPI 发布、Docker Compose、公网部署、认证和多用户能力。

## Further Notes

- 实现、测试、事件和报告必须使用 `CONTEXT.md` 中的 Diagnosis Task、Task Manifest、Diagnosis Run、Root Cause、Root Cause Candidate、Root Symbol、Hypothesis、Evidence、Experiment、Observation、Validation、Outcome Evaluation 和 Trajectory Evaluation 等规范术语。
- 当前有效 ADR 为显式状态机、结构化 Tool Runtime、固定混合检索管线、按运行目录持久化、可配置的单一 OpenAI-compatible 云端 ModelProvider 和最小 Docker 执行边界。旧的检索消融、SQLite、模型兜底和完整容器控制 ADR 已被取代。
- 具体开源 Django 仓库、运行时 Model Configuration、embedding 模型、融合权重、reranker、候选数和 Top-K 仍需在实现早期冻结；具体云端模型由操作者选择，不写死在本 specification 中，且选择不得扩大产品范围。
- Model Compatibility Gate 是兼容性风险检查，不是 Benchmark 或 Diagnosis Run 授权。若已配置模型无法满足阶段 Schema、工具参数、Evidence 更新和小型补丁要求，操作者应更换 Model Configuration，而不是在末期重写 Agent 协议。
- MVP 的合理简历表述是“在一个冻结 Django 项目上实现可复用的 Diagnosis Task 工作流，并以三个业务逻辑回归任务验证动态工具选择、Evidence 更新和补丁 Validation”。不得表述为能够泛化诊断任意 Python/Django 项目。
- 在 GitHub issue tracker 中，本 specification 应使用 `ready-for-agent` 标签。后续 ticket 拆解必须以本文件和权威设计为准，不得从旧研究级 specification 恢复已延期能力。
