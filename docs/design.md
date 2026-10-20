# CodeRCA 两周 MVP 设计文档

| 属性 | 内容 |
|---|---|
| 状态 | Accepted |
| 决策日期 | 2026-08-06 |
| 交付目标 | 单人两周内完成可真实运行的 Agent 求职原型 |
| 主要招聘信号 | Agent 工作流与 Tool Runtime |
| 支持范围 | 一个冻结 Django 仓库中的业务逻辑回归 |
| 权威术语 | [CodeRCA Context](../CONTEXT.md) |

## 1. 摘要

CodeRCA 是一个诊断单仓库 CI 测试失败的 AI Agent 原型。用户提交一个指向 Faulty Commit、CI 日志和注册测试命令的 Diagnosis Task，Agent 依次形成并检验一个 Active Hypothesis，通过 Experiment、Observation 和 Evidence 主动尝试证伪；如果当前 Hypothesis 结束，则基于累积诊断知识进行最多两次 Reformulation。supported Hypothesis 产生结构化 Patch Intent，程序将其确定性编译为唯一 Candidate Patch，随后执行 Validation 并生成可追溯的 Root Cause Report。

MVP 的目标不是证明 CodeRCA 在大规模数据集上优于其他系统，也不是交付通用故障平台。它要用一条真实、可检查的纵向闭环证明：模型决策可以被程序约束，工具调用可以服务于可证伪 Hypothesis，错误 H1 可以被真实 Evidence 否定，后续 Hypothesis 可以利用已积累知识 Reformulate，最终判断可以通过受控 Experiment 和 Validation 获得支持。

## 2. 产品定位与成功定义

### 2.1 第一目标

本项目首先是 AI Agent 开发岗位的求职作品。面试官应能通过源码、自动化测试和真实 Diagnosis Run 产物验证以下能力：

1. 最小显式状态机与受约束 ReAct 的组合；
2. 结构化 Tool Spec、权限、超时、错误与审计；
3. 有界上下文和结构化 Agent 状态；
4. Agent 自主选择的 Lightweight Code Search 与可追溯代码 Observation；
5. Docker 中的真实 Experiment 与 supported Hypothesis 补丁 Validation；
6. 面向结果和轨迹的工程回归 Evaluation。

### 2.2 MVP 完成条件

MVP 完成必须同时满足：

- 一个通过 Model Compatibility Gate 检查的已配置 OpenAI-compatible 云端模型能够完成至少一个真实端到端 Diagnosis Run；
- 五个工具均通过统一契约测试；
- Agent 任意时刻最多维护一个 Active Hypothesis，并按 H1、H2、H3 维护 append-only Hypothesis History；
- Agent 能通过 Contradicting Evidence 拒绝当前 Hypothesis，并在预算内基于累积知识 Reformulate；
- Agent 能为 supported Hypothesis 形成可编译 Patch Intent，由程序生成可应用 Candidate Patch，并在 Docker 中运行注册 Validation；
- 运行过程保存结构化事件和 Root Cause Report；
- 三个冻结任务可以执行确定性的 Outcome Evaluation 与 Trajectory Evaluation；
- 默认自动化测试不依赖真实模型 API、API Key 或网络。

三个任务的结果只作为工程回归证据，不用于声称统计显著性、跨仓库泛化或相对 Baseline 的总体优势。

## 3. 范围

### 3.1 正式支持

- Python/Django 单仓库；
- 一个冻结的开源 Django 项目快照；
- 由已知代码变更导致的业务逻辑回归；
- 同一仓库、同一 Docker 镜像和同一注册命令集合下的新 Diagnosis Task；
- CI 日志、Faulty Commit 和失败测试可稳定复现的任务；
- 单用户、本机、串行 CLI 运行。

### 3.2 实现可扩展但不作保证

- Task Manifest 使用通用 Schema，不在代码中硬编码三个任务 ID；
- Lightweight Code Search 接收受约束的仓库路径、查询和结果上限，不硬编码具体任务目录；
- ModelProvider 与具体推理服务隔离；
- Tool Runtime 可以注册后续工具。

这些边界用于避免不必要的重写，不构成对任意 Python 仓库、任意模型或任意工具的兼容承诺。

### 3.3 明确延期

- API 契约变化和配置错误；
- 外部服务、性能、随机、flaky 和并发故障；
- 多仓库、跨仓库和非 Python 诊断；
- 生产 Trace、Metrics、告警和日志平台接入；
- Raw Model Baseline、Fixed Pipeline 和大规模 Benchmark；
- Python AST 分块、BM25、embedding、向量索引、混合融合、CPU reranker、检索消融和参数搜索；
- LLM Judge、大规模隐藏集和重复稳定性实验；
- 多个补丁并行生成与验证；
- FastAPI、后台 Worker、Web UI 和静态 HTML 报告；
- SQLite、内容寻址 Artifact、崩溃恢复和事件回放；
- 本地模型后端、原生厂商 SDK、多真实后端、模型路由、自动选择、回退和运行回放兜底；
- PyPI 发布、Docker Compose 和公网部署；
- MCP、任意 Shell、自动推送分支或创建 PR；
- 生产级沙箱安全与恶意代码防御。

## 4. 核心设计原则

1. **Agent 优先**：状态、决策约束和工具语义优先于功能数量。
2. **Hypothesis 驱动**：每个工具调用必须关联一个活跃 Hypothesis、目的和预期 Observation。
3. **Falsification 优先**：Experiment 优先寻找能够否定当前 Hypothesis 的高信息量 Observation；Evidence 不打分、不排名。
4. **模型决策、程序约束**：模型提出 Hypothesis、选择 Experiment 和 Patch Intent；程序校验 Schema、状态、权限、预算和停止条件，并确定性编译 Candidate Patch。
5. **按决策重建上下文**：每一步从结构化状态和相关诊断知识投影 Working Context，不重放完整 Conversation History。
6. **真实 Experiment**：至少一个诊断路径必须在 Docker 中运行测试并验证 supported Hypothesis 的补丁。
7. **失败可见**：Schema、模型、工具、沙箱和诊断失败必须留下结构化结果。
8. **声明不超过证据**：三个任务只证明原型闭环和工程回归，不证明广泛泛化能力。

## 5. 系统上下文

```mermaid
flowchart LR
    User[开发者 / 面试评审者] --> CLI[CLI]
    CLI --> App[Diagnosis Application Service]
    Eval[Evaluation Harness] --> App
    App --> Agent[Lifecycle State Machine]
    Agent --> Model[OpenAI-compatible ModelProvider]
    Agent --> Runtime[Tool Runtime]
    Runtime --> Diff[Git Diff]
    Runtime --> Search[Lightweight Code Search]
    Runtime --> Sandbox[Docker Sandbox]
    App --> Runs[Run Directory]
```

| 边界 | 职责 | 不负责 |
|---|---|---|
| Task Intake | 读取 Task Manifest，校验同仓库任务输入 | 任意仓库导入和环境修复 |
| Diagnosis | 管理 Active Hypothesis、Hypothesis History、Evidence、Experiment、Reformulation 与停止 | 直接执行命令或读取任意文件 |
| Model | 通过 OpenAI-compatible Chat Completions 协议请求阶段决策和 Patch Intent | unified diff 序列化、模型托管、厂商原生 SDK、路由和回退 |
| Tool Runtime | Schema、权限、超时、错误、Patch Intent 编译和审计 | Root Cause 推理与修复语义决策 |
| Code Search | 在 Faulty Commit 工作区执行有界文本与路径搜索 | 推断 AST Symbol、选择最终 Root Cause |
| Sandbox | 在临时容器工作区运行注册命令和补丁 | 恶意代码与生产多租户防御 |
| Reporting | 保存事件、报告、补丁和测试输出 | Web 展示和长期查询 |
| Evaluation | 检查三个任务的 Outcome 和 Trajectory | Benchmark、Judge 和统计推断 |

CLI 和 Evaluation Harness 调用同一个 Diagnosis Application Service，不复制 Agent 逻辑。

## 6. 领域模型与不变量

### 6.1 Diagnosis Task

Diagnosis Task 由 Task Manifest 表达。Manifest 至少包含：

- 任务 ID 和版本；
- 固定仓库标识、基础快照与 Faulty Commit；
- CI 日志位置；
- 注册测试命令 ID；
- Docker 镜像标识；
- 允许读取和修改的路径；
- 工具调用上限。

Agent 可见输入不得包含 Root Symbol 标准答案、参考补丁、修复后代码或 Evaluation 结果。MVP 只保证 Manifest 引用同一个冻结仓库和已注册运行环境。

### 6.2 Diagnosis Run

Diagnosis Run 是 Agent 对一个 Diagnosis Task 的一次执行。它拥有：

- 按 H1、H2、H3 追加的 Hypothesis History；
- 零个或一个 Active Hypothesis；
- Supporting Evidence 和 Contradicting Evidence；
- Experiment 与 Observation；
- 当前 Active Hypothesis 已用和剩余的 Experiment Budget；
- 已用工具预算；
- supported Hypothesis 的 Patch Intent、程序编译的 Candidate Patch 及 Validation；
- 停止原因和 Root Cause Report。

关键不变量：

- 工具调用只能关联当前 Active Hypothesis；
- 任意时刻 Active Hypothesis 不超过一个；
- Hypothesis ID 只能由程序按 H1、H2、H3 分配，History append-only；
- 只有当前 Hypothesis 进入 `rejected` 或 `inconclusive` 且预算剩余时才能 Reformulate；
- rejected Hypothesis 不得复活、覆盖或重新定义，H3 之后不得形成 H4；
- H1 的 Formation Schema 不含 Evidence Basis，程序将其固定为空；
- H2/H3 的 Evidence Basis 只能来自 `ReformulateHypothesisDecision` 引用的有序、唯一 Evidence ID，且程序验证这些 Evidence 属于已结束的 Hypothesis History；
- Evidence 必须引用工具结果或输入 artifact；
- Evidence 只有方向、来源和解释，不包含数值 Score 或 Ranking；
- 只有 supported Hypothesis 可以提交 Patch Intent；只有程序成功编译的 Candidate Patch 可以进入 Validation；
- 诊断工具调用使用绑定 Active Hypothesis 的 Experiment；终态 `apply_patch` 使用绑定 supported Hypothesis 的 Patch Validation Action；
- 一次 Diagnosis Run 最多调用十次工具，诊断 Experiment 与 Patch Validation Action 共用该预算；该上限覆盖 H1～H3 各三次 Experiment 与一次 Validation 的完整最大生命周期；
- 每个 Active Hypothesis 最多执行三个诊断 Experiment；第三次 Evidence 后不得继续测试，但程序不自动决定其终态；
- 真实仓库保持只读，修改只发生在临时工作区。

### 6.3 Root Cause Report

最小报告包含：

- 最终 supported Hypothesis 的简短故障机制，以及独立的最终 location；Hypothesis.root_symbol 仅是形成时的暂定符号；
- 触发条件、传播路径、故障机制和失败表现；
- H1～H3 Hypothesis History 及每个条目的终态；
- Supporting Evidence 与 Contradicting Evidence 引用；
- 修复建议、候选补丁和 Validation 结果；
- 停止原因。

完整工具输出、耗时和错误保存在事件及运行文件中，不复制进报告正文。

最终 `location` 必须显式返回对象或 null；对象包含仓库相对 path、可空 symbol、
Faulty Commit 的 1-based 闭区间 start_line/end_line 和非空唯一 evidence_refs。
至少一项当前 supported Hypothesis 的直接代码 Evidence，或其显式 `evidence_basis`
引用的历史代码 Evidence，必须覆盖声明区间；允许来源包括 `read_code`、
`inspect_diff` 和严格限定的 `search_code(content)`。合格搜索来源必须为
`matched`、单项未截断、路径相同且区间完整覆盖；路径搜索、零结果、截断或不覆盖
匹配均不合格。历史 Evidence 保留原 Hypothesis ID 与 Direction，只证明审计过的
坐标，不变成当前 H 的 Supporting Evidence。程序检查来源链、读取权限、版本和文件
边界，不从补丁或测试成功反推位置；supported H 仍需自己的因果 Supporting Evidence。
既有 generate_report Context 增加最多 64 个代码来源区间，不新增模型阶段、工具调用
或修改初始假设。非法位置复用一次结构化纠错，无法定位应返回 null。
本地来源检查不证明符号语义或因果正确；窄定位与机制一致性仍需人工审核。
旧产物只在读取入口补 null，不修改历史文件。见 ADR-0016。

## 7. Agent 工作流

### 7.1 最小显式状态机

```mermaid
stateDiagram-v2
    [*] --> Preparing
    Preparing --> FormingHypothesis: task valid
    Preparing --> Finalizing: invalid or environment failure
    FormingHypothesis --> Diagnosing: append H1/H2/H3
    Diagnosing --> ExecutingTool: valid experiment decision
    ExecutingTool --> UpdatingEvidence: observation recorded
    UpdatingEvidence --> Diagnosing: hypothesis remains plausible
    UpdatingEvidence --> FormingHypothesis: rejected or inconclusive, budget remains
    UpdatingEvidence --> Validating: sufficiently supported
    UpdatingEvidence --> Finalizing: H3 ended or tool budget exhausted
    Validating --> Finalizing: validation recorded
    Finalizing --> [*]
```

状态机只控制生命周期与不变量。`Diagnosing → ExecutingTool → UpdatingEvidence` 是受约束 ReAct 循环：模型选择针对 Active Hypothesis 的下一 Experiment；程序执行工具并记录 Observation；模型解释 Evidence 并提交 Assessment；程序校验 Evidence 引用、Budget 与合法转换后更新状态。

Experiment 必须能由所选 Tool Spec 声明的 `observation_capabilities` 在当前参数和权限边界内直接产生预期 Observation，并遵守 `limitations`。模型不能假定任意 instrumentation、Shell、临时诊断补丁或未注册测试。Tool Catalog 由 Runtime 动态投影，新增工具不需要在 ContextBuilder 中维护名称列表。

### 7.2 阶段输出 Schema

模型不填写一个万能决策对象。各阶段使用字段较少的独立 Schema：

- `FormHypothesisDecision`：形成一个不带 ID、也不带 Evidence Basis 的初始 H1 Proposal；
- `ReformulateHypothesisDecision`：形成一个 H2/H3 Proposal，并引用至少一个有序、唯一的既有 Evidence ID；
- `SelectExperimentDecision`：选择 Hypothesis、工具、目的、预期 Observation 和参数；
- `UpdateEvidenceDecision`：将 Observation 解释为支持、反对或无信息 Evidence；
- `HypothesisAssessmentDecision`：基于 Evidence 提议继续、falsified、sufficiently supported 或 inconclusive；
- `PatchIntentDecision`：为 supported Hypothesis 提交一个目标文件和一至三个 Exact Replacement；
- `CandidatePatch`：程序根据合法 Patch Intent 确定性生成的规范 unified diff，不是模型阶段输出；
- `ReportDecision`：补全最小 Root Cause Report 的因果字段。

Schema 校验失败时保存原始响应与错误，并允许一次明确纠错；再次失败产生 Schema Failure 并停止当前 Diagnosis Run。禁止通过模糊正则猜测模型意图。

### 7.3 停止条件

满足任一条件即进入 `Finalizing`：

- supported Hypothesis 补丁完成 Validation；
- 达到十次工具调用；
- 当前 Hypothesis 已执行三次 Experiment 时，禁止再次 `continue_testing`，必须先进入 supported、rejected 或 inconclusive；
- H3 进入 `rejected` 或 `inconclusive`；
- 纠错后仍发生 Schema Failure；
- 模型、工具或沙箱发生不可恢复错误。

CLI 在状态机外设置一次总运行超时。MVP 不同时维护 Token、费用和多级时间预算。

### 7.4 Hypothesis Evaluation 与 Reformulation

Observation 不直接改变 Hypothesis 生命周期。模型先把 Observation 解释为带 provenance 的 Supporting、Contradicting 或 Inconclusive Evidence，再提交引用具体 Evidence ID 的结构化 Assessment。程序检查所有引用属于当前 Active Hypothesis，并将 `falsified`、`sufficiently_supported` 等 Assessment 映射到合法状态；模型不能分配 ID、写入状态或维护 Budget。Evidence Direction 始终相对当前机制；explanation 可以指出 Observation 暗示的具体替代机制，但不能重写当前 H。

H1 可基于 Task 与 CI Failure 形成，但这些初始线索不是正式 Evidence，因此其 Schema 不暴露 `evidence_basis`，程序保存的 Evidence Basis 固定为空。H2/H3 使用独立的 `ReformulateHypothesisDecision` 引用推动 Reformulation 的 Evidence ID；程序拒绝空值、重复、未知 ID，以及不属于 `rejected`/`inconclusive` History 的 Evidence。Reformulation 同时看到已经结束的 Hypothesis History、相关代码/diff/测试 Observation、Tool Catalog 和剩余预算，不得仅换一种措辞重复 rejected 机制；新 falsification criterion 必须能由现有工具检验。决定性 Experiment 不可执行或已出现更好的 observation-grounded 机制时，当前 H 可以先以 inconclusive 结束，再进行 Reformulation。

## 8. 上下文工程与模型边界

### 8.1 Decision-Specific Reconstructed Working Context

Agent State 是真相源，Working Context 是当前 Decision 对结构化状态的确定性投影。每次模型调用重新构造 Context，但不同 Decision 只包含必要信息：

- Form H1：Task Context、CI Failure、空 History 和剩余预算；
- Select Experiment：Active Hypothesis、Falsification Criterion、Evidence Basis Knowledge、当前 H 的相关 Evidence/Observation、Tool Catalog、Tool Budget 与单 H Experiment Budget；
- Update Evidence：Active Hypothesis、Current Experiment、Expected Observation、Latest Observation、Evidence Basis Knowledge 和当前 H 已有 Evidence；
- Assess Hypothesis：Active Hypothesis、Evidence Basis Knowledge、当前 H 的相关 Evidence/Observation、Tool Catalog 与剩余预算；
- Reformulate H2/H3：原始 Task、已经结束的 Hypothesis History、否定或结束当前机制的 Evidence、相关代码/diff/测试事实、Tool Catalog 和剩余预算；
- Validation：supported Hypothesis、Evidence Basis Knowledge、当前 H 的相关 Evidence、代码/测试 Observation 与修复上下文。

选择规则使用 Hypothesis ID、固定字段、固定条数和字符长度限制。完整 CI 日志、代码、测试输出、Tool Result 和 Model Response 保存在 Run Artifact 中；Structured State 只保存 Observation/Evidence 及引用。MVP 不实现自动摘要、语义记忆检索、长期记忆、通用 Token Optimizer 或完整 Conversation History replay。

### 8.2 ModelProvider

CodeRCA 只实现一个 OpenAI-compatible HTTP ModelProvider。每次进程运行由操作者通过 `CODERCA_MODEL_BASE_URL`、`CODERCA_MODEL_ID`、`CODERCA_MODEL_API_KEY` 和 `CODERCA_MODEL_STRUCTURED_OUTPUT_MODE` 配置一个云端 Chat Completions 端点、模型和 Structured Output Mode；可选的 `CODERCA_MODEL_REQUEST_EXTENSIONS` JSON object 显式提供少量 Endpoint 专属 invocation 参数。Agent 不进行模型发现、自动选择、路由或回退。

真实请求固定使用非流式调用和 `temperature=0`。`native_json_schema` 发送 `response_format.type=json_schema` 与 `strict=true`；`json_text` 不发送 `response_format`，而在 Prompt 中要求只返回满足阶段 Schema 的原始 JSON。模式必须显式配置，不根据 Endpoint、Model ID 或供应商品牌推断。

无论使用哪种模式，`message.content` 都必须直接通过 `json.loads` 和本地 Pydantic Schema 校验，成功前不得进入 Agent State。Provider 不剥离 Markdown fence 或 `<think>`，不提取 JSON 子串，不猜测字段，也不模糊修复非法结构。Request Extensions 在标准 payload 构造后合并，禁止覆盖 `model`、`messages`、`stream`、`temperature` 和 `response_format`，不按 Endpoint、Model ID 或品牌推断，且其值不写入兼容性报告；响应中回显的 extension 字符串值在进入 Artifact 前脱敏。CRCA-003 对非法结果立即失败，不实现自动 retry、任意未校验 `extra_body`、服务专属 Tool Calling 或原生厂商 SDK。

Model Compatibility Gate 是显式运行的兼容性检查，不是 Diagnosis Run 的授权门禁，也不是模型 Benchmark。它最多发起一次预检和以下五个一次性探针：

- 阶段 Schema 输出；
- 工具选择和合法参数；
- 根据 Observation 更新 Evidence；
- 使用真实 `HypothesisAssessmentDecision` 合同评估 Active Hypothesis；
- 生成可由本地 Patch Compiler 编译并通过行为检查的小型 Python Patch Intent。

Assessment 应用与 Gate 共享正向精确输出合同：模型只能返回 `outcome`、`evidence_refs` 和 `rationale` 三个键，并看到一个完整合法 JSON 形状。未知字段仍由本地 Pydantic `extra="forbid"` 拒绝，不做删除或修复。

两种 Structured Output Mode 运行相同探针。门禁生成记录 mode 的脱敏 Model Compatibility Report；失败返回非零退出码，但 Diagnosis Run 只读取当前 Model Configuration，不隐式读取门禁报告、自动切换 mode 或阻止运行。自动化测试使用 FakeModelProvider。MVP 不实现本地模型后端、原生厂商 SDK、多真实后端、路由、回退或录制轨迹回放。

### 8.3 云端数据与凭证边界

Diagnosis Run 会把所需的公开基准代码片段、CI 日志和结构化状态发送到操作者配置的云端 API。MVP 仅处理冻结的公开开源基准仓库，不承诺私有代码或生产数据的隐私能力。

API Key 只从进程环境读取，不写入 Task Manifest、运行目录、日志、Model Compatibility Report 或 Docker 容器。错误与审计信息必须脱敏，不记录 Authorization Header。

每次 Diagnosis 模型决策在 `model-requests/` 保存脱敏的应用到 Provider
请求快照：Decision Type、序号、attempt、System Prompt、Working Context、
Response Schema 与对应 response artifact 引用；Schema Correction 也独立保存。
它不包含 HTTP Header、endpoint configuration，也不代表 Provider 追加格式指令后的
完整 HTTP payload。未声明安全脱敏能力的自定义 Provider 仅记录调用元数据。
快照用于审计，不回放到模型上下文；任意仓库内容仍可能敏感，不应公开整个 Run Directory。

Evidence 解释必须区分观察事实与推断：未检查的被调用函数仍是未知，局部或截断
搜索未发现行为不代表全路径不存在。Assessment 须核对原证伪条件与实际观察覆盖，
不能仅凭 contradicting 标签 Reject。Select Experiment 优先补足未检查的因果环节，
并说明预期信息增量。Reformulation 需说明机制的实质变化，不仅改写措辞。
这些是模型决策约束，不是程序对语义正确性的保证。
Evidence Direction 始终相对 Active Hypothesis 的 mechanism，而非
falsification_criterion 或 expected_observation。否定证伪条件本身不构成支持；
支持需要正向机制事实。若 Assessment 发现事实、解释和已注册 direction 冲突，
不能重标已有 Evidence，不能靠附加 note 字段覆盖它；应说明冲突并继续有信息增量
的 Experiment，或在没有可执行实验、已出现更具体的替代机制时 inconclusive。
每个 Active Hypothesis 最多三次 Experiment；预算耗尽后的 continue_testing 由程序
拒绝并复用一次 Schema Correction。总 Tool Budget 与方向校验保持不变，不新增
语义评分或自动修复。
H2/H3 的 Select Experiment、Update Evidence、Assess Hypothesis 和 Validation
Context 都携带 `evidence_basis` 明确引用的历史 Evidence 与对应 Observation 的有界
excerpt；该 Evidence Basis Knowledge 与当前 H 的 relevant Evidence 分开，历史
Direction 不能直接用于当前 H 的 Assessment。Assessment 另含当前假设的 Observation
有界 excerpt，以便核查 Evidence 解释。每条沿用 2,000 字符上限与截断标记，数量受
既有 Tool Budget 约束，不携带完整原始输出或无关历史。

## 9. Tool Runtime

### 9.1 Tool Spec

每个工具声明：

- 名称、版本和描述；
- 输入输出 Schema；
- 权限类别：只读、代码执行或文件修改；
- 超时；
- 结果大小上限；
- 副作用；
- 可直接产生的 Observation 能力；
- 明确不支持的诊断行为和限制；
- 结构化错误语义。

统一错误至少包括：

- `invalid_arguments`；
- `permission_denied`；
- `timeout`；
- `execution_failed`。

工具默认不自动重试。每次调用记录 Hypothesis ID、目的、预期 Observation、耗时、状态和结果引用。

### 9.2 五个工具

| 工具 | 职责 | 关键限制 |
|---|---|---|
| `inspect_diff` | 查看基础快照到 Faulty Commit 的变更 | 不暴露参考修复或未来代码 |
| `search_code` | 执行有界关键词、符号文本和路径搜索 | 不开放 Shell，不把匹配声明为 Root Symbol |
| `read_code` | 读取指定文件和行区间 | 路径必须位于允许读取范围 |
| `run_tests` | 在 Docker 中运行注册测试命令 | 不接受任意 Shell |
| `apply_patch` | 在临时工作区应用候选补丁 | 只能修改允许的业务源码路径 |

`search_code` 返回仓库相对路径、行号或行区间、有界代码片段、截断状态和 Artifact 引用。轻量文本搜索不能可靠推断 AST Symbol，因此匹配结果不得自动成为 Root Symbol Ground Truth。严格的未截断内容匹配可以证明模型观察过某个源码坐标，但不能单独证明 `symbol` 或因果机制；最终 Root Symbol 仍由诊断过程结合代码、测试和其他 Evidence 确定。语法和轻量静态检查作为注册 Validation 命令的一部分，不设置独立 `static_check`。

## 10. Lightweight Code Search

### 10.1 输入输出合同

`search_code` 使用简单、明确且可复现的合同，不要求预处理索引。输入至少包含：

- 有界的非空字面量 `query`；
- 显式 `search_kind`：`content` 或 `path`；
- 可选的仓库相对搜索范围，且必须落在 Manifest `read_paths` 内；
- 受程序上限约束的 `max_results` 与上下文行数。

内容搜索同时支持关键词以及函数、类、方法等符号名称的字面量匹配；路径搜索支持文件路径或文件名片段。每次成功执行返回规范化查询信息、`matched` 或 `no_matches` 状态、匹配文件的仓库相对路径、精确行号或行区间、有界代码片段、每项及总体截断状态，以及 Tool Result Artifact 引用。`no_matches` 是合法查询的成功结果，不等同于基础设施失败。

完整 Tool Result 写入 Run Artifact；Observation 只保存结果摘要、有界片段和来源引用。Evidence 再解释搜索结果与 Active Hypothesis 的关系。匹配顺序、数量或文本相关性不是 Evidence Score，也不参与 Hypothesis Ranking。

### 10.2 执行、安全与版本边界

MVP 优先使用成熟的 ripgrep 实现内容搜索，并以仓库相对文件枚举加确定性字面量过滤实现路径搜索。Tool Runtime 使用参数数组启动进程，不拼接 Shell；内容查询默认采用 fixed-string 语义。ripgrep 退出码 0 表示命中，1 表示合法 `no_matches`，超时分类为 `timeout`，其他执行异常分类为 `execution_failed`。参数和范围校验继续使用 `invalid_arguments` 与 `permission_denied`。

搜索只作用于 Task Manifest 指定 Faulty Commit 的已准备工作区。程序在执行前规范化工作区根目录、搜索范围和 `read_paths`，禁止路径穿越，不跟随符号链接，不读取仓库外文件；Ground Truth、参考补丁、修复后代码和未来 commit 不得出现在该工作区或搜索范围。查询长度、搜索范围、结果数量、上下文行数、单片段长度和总输出长度均使用固定上限。

Agent 根据当前 Active Hypothesis 自主选择是否调用 `search_code`；状态机不强制形成 Hypothesis 后固定调用搜索。调用必须携带 Experiment 目的、预期 Observation 和 falsification relevance，并计入 Tool Budget。搜索负责发现候选位置，不判断 Hypothesis 是否正确。

Python AST 分块、BM25、embedding、向量数据库或索引、dense retrieval、融合、CPU reranker、检索缓存、Provider/插件框架和 Retrieval Evaluation 均不属于 CodeRCA MVP。

## 11. Docker Experiment 与补丁 Validation

### 11.1 最小隔离边界

MVP 使用一个预构建 Django Docker 镜像。每次执行创建临时工作区，并满足：

- 真实仓库与基础快照只读；
- 默认关闭网络；
- 只执行注册命令；
- 每次命令有统一超时；
- 不向容器挂载 `CODERCA_MODEL_API_KEY` 或其他模型凭证；
- 云端模型请求由宿主 Agent 进程发起，不经过默认禁网的测试容器。

该边界只用于降低正常测试造成意外副作用的风险，不承诺抵御恶意代码、容器逃逸或生产多租户攻击。完整 CPU/内存配额、只读根文件系统矩阵和跨平台兼容延期。

### 11.2 Supported Hypothesis 补丁流程

1. 当前 Active Hypothesis 经 Evidence Assessment 进入 `supported`；
2. 模型提交绑定 supported Hypothesis 的 Patch Intent，包含一个允许目标文件和一至三个 Exact Replacement；
3. Tool Runtime 校验路径、UTF-8 文本、原文唯一匹配、编辑不重叠和非 no-op；失败时复用一次结构化决策纠错；
4. Patch Compiler 在内存中应用精确替换，生成规范 Candidate Patch，并以 `git apply --check` 验证可应用性；它不做 fuzzy matching 或语义修复；
5. 编译成功后，程序登记一个绑定 supported Hypothesis、计入 Tool Budget 的 Patch Validation Action，并由 `apply_patch` 在临时工作区应用 Candidate Patch；
6. 静态检查和注册测试执行 Public Validation；
7. 结果作为 Evidence 与报告字段保存；
8. 无论通过或失败，MVP 不自动生成第二个 Patch Intent 或进行第二轮补丁搜索。

禁止修改或删除已有测试、依赖锁、任务定义和评测数据。MVP 不实现完整 Hidden Validation 或自动语义防投机系统。

## 12. CLI、运行记录与报告

### 12.1 CLI

CLI 支持：

- 读取一个 Task Manifest 并启动 Diagnosis Run；
- 实时显示当前状态、Hypothesis、工具调用和 Evidence 更新；
- 显示最终 Root Cause Report 和运行目录。

不提供交互式任务创建、后台任务、HTTP API 或并发执行。

### 12.2 运行目录

每次 Diagnosis Run 保存到独立目录，包含：

- 运行配置和 Task Manifest 快照；
- JSONL 结构化事件；
- 最终 JSON Root Cause Report；
- 模型原始响应与 Schema 错误；
- 工具输出、候选补丁和 Validation 结果。

大文本使用普通文件引用。MVP 不使用 SQLite、内容寻址、跨运行去重、数据库迁移或崩溃恢复。

## 13. 三个冻结任务

三个任务共享同一个基础仓库、Docker 镜像和五工具合同，但拥有不同 Faulty Commit、CI 日志和注册测试入口：

| 任务 | 设计目的 | 必要诊断行为 |
|---|---|---|
| Task 1 | 变更证据 | 主要通过 diff 与代码阅读定位 Root Cause |
| Task 2 | 代码探索证据 | Root Symbol 不由初始失败信息直接暴露，Agent 利用自主搜索和代码阅读定位 |
| Task 3 | Self-Correction 证据 | 初始 H1 错误，通过测试 Observation 否定 H1 并 Reformulate H2 |

Task 1 用于开发和必要时的现场运行；Task 2 用于工作流回归；Task 3 在核心 Prompt、Schema 和工具策略基本冻结后运行，作为有限的未见故障检查。三个任务均为人工注入的业务逻辑回归，不寻找真实历史修复 commit。

标准答案与 Agent 输入分离，至少记录 Root Symbol、触发条件、故障机制、失败表现和参考修复行为。

## 14. Engineering Evaluation

Evaluation Harness 调用 Diagnosis Application Service，并输出逐任务检查结果。

### 14.1 Outcome Evaluation

- 最终 root_cause_analysis.location 的路径、规范 Root Symbol 与缺陷行范围是否命中，而非初始 Hypothesis.root_symbol；
- 候选补丁是否可应用；
- 注册 Validation 是否通过；
- Root Cause Report 是否包含必需结构化字段。

### 14.2 Trajectory Evaluation

- 工具调用是否绑定有效 Hypothesis；
- 是否声明目的与预期 Observation；
- 是否至少产生一条可追溯 Evidence；
- Task 2 是否使用真实搜索 Observation 推进诊断，而不是把搜索算法或固定工具顺序作为验收目标；
- Supporting 和 Contradicting 方向是否合法；
- 是否遵守十次工具预算；
- 是否产生合法停止原因；
- 是否只有 supported Hypothesis 进入补丁 Validation；
- 任意时刻是否最多一个 Active Hypothesis；
- 是否只有结束当前 H 后才形成下一个，且 History 未超过 H3；
- Reformulation 是否引用否定旧 H 的 Evidence 与相关 Observation。

Evaluation 不调用 LLM Judge，不与 Baseline 比较，不汇总具有泛化暗示的成功率。因果解释由作者依据冻结答案进行人工核查，自动化 Harness 只验证结构和确定性字段。

## 15. 测试策略

### 15.1 单元测试

- 状态转移和非法转换；
- 单 Active Hypothesis 与 append-only H1～H3 History；
- rejected 不可复活、reject-before-reformulate 和 no-H4；
- Assessment 必须引用当前 H 的真实 Evidence；
- 十次工具预算和停止条件；
- 各阶段 Schema 与一次纠错；
- decision-specific reconstructed Working Context。

### 15.2 工具契约测试

五个工具共享契约套件，验证：

- 输入输出 Schema；
- 权限与路径越界；
- 超时；
- 四类结构化错误；
- 审计字段；
- 结果大小上限。

### 15.3 集成测试

- Lightweight Code Search 的命中、零结果、参数/权限错误、超时、执行失败、结果截断和 provenance；
- Docker 临时工作区；
- 注册测试命令；
- 补丁应用与 Validation；
- 运行目录和结构化事件。

### 15.4 Agent Evaluation

三个冻结任务显式运行，不进入默认 CI。默认 CI 使用 FakeModelProvider，不要求 API Key、真实模型、GPU 或联网。

## 16. 交付顺序与降级规则

### 16.1 纵向优先顺序

1. 一个 Task Manifest 与 FakeModelProvider 纵向骨架；
2. 冻结 django-waffle Task 1 的 Manifest、Faulty Commit、注册命令、CI artifact 与 Evaluation Ground Truth；
3. OpenAI-compatible 模型兼容性门禁；
4. 单 Active Hypothesis、H1～H3 History 与 decision-specific ContextBuilder；
5. `inspect_diff`/`read_code` 诊断循环、Docker `run_tests` 和 Task 1 补丁 Validation 闭环；
6. Lightweight Code Search 与 Task 2 代码探索验收；
7. bounded self-correction 与 Task 3；
8. Engineering Evaluation、测试、文档和运行产物。

前四项已经分别由 CRCA-001～CRCA-004 落地，但 CRCA-004 只把初始 H1 Formation 接入 Application Service；完整 Agent Loop 和 Tool Runtime 仍由后续 Ticket 实现。后续实现继续按 Ticket 依赖推进；这里的顺序描述实际纵向切片，不改变最终 MVP 的完成条件。

完整实现不能先于第一个真实纵向闭环。局部组件通过测试但没有真实 Diagnosis Run，不视为 MVP 完成。

### 16.2 第七天降级规则

Lightweight Code Search 已经是检索范围的最小实现，不再保留“先删除 reranker”的组件降级。如果第七天仍未跑通 Task 1 真实纵向闭环：

1. 暂停 Task 2/Task 3 工作，先完成 Task 1 的 Agent Loop、Docker Experiment 和 Patch Validation；
2. Task 1 闭环后再实现 Lightweight Code Search 与 Task 2；`search_code` 不是 Task 1 的前置条件；
3. 若总交付周期仍不足，延期 Task 3，但不削弱 Single Active Hypothesis、Falsification 或 Bounded Reformulation 的实现合同。

不得削减：最小状态机、单 Active Hypothesis 不变量、五工具协议、已配置的真实云端模型、一个 Docker Experiment 和 supported Hypothesis 补丁 Validation。

## 17. 主要风险

| 风险 | 影响 | 控制 |
|---|---|---|
| 已配置模式无法稳定产生本地 Schema 有效输出 | Agent 无法真实闭环 | 早期按 mode 运行兼容性门禁；优先 native schema；阶段小 Schema；本地 Pydantic 校验 |
| 三个任务仍过度定制 | 招聘证据被质疑 | 三种不同必要路径；Task 3 延后运行；公开逐任务轨迹 |
| Lightweight Search 查询与代码词汇不一致 | Task 2 找不到关键位置 | Task 2 保留可由文本/路径线索发现的真实路径；结合 diff、搜索与 `read_code`，不宣称语义检索能力 |
| Docker 在 WSL/开发机行为不一致 | Validation 不稳定 | 单镜像、单仓库、注册命令和统一超时 |
| 已配置模型输出不可应用补丁 | 核心验证失败 | 早期补丁探针；只允许一个 supported Hypothesis 的小型补丁 |
| Scope 再次膨胀 | 两周无法交付 | 延期列表和不可削减核心作为变更门禁 |

## 18. 架构决策记录

- [ADR-0014：单 Active Hypothesis 与按决策重建上下文](adr/0014-single-active-hypothesis-reconstructed-context.md)，取代 ADR-0001
- [ADR-0017：可执行 Experiment 与单 Hypothesis 诊断预算](adr/0017-executable-experiments-and-bounded-hypothesis-testing.md)
- [ADR-0002：结构化 Tool Runtime 且不实现 MCP](adr/0002-typed-tool-runtime.md)
- [ADR-0015：Lightweight Code Search](adr/0015-lightweight-code-search.md)，取代 ADR-0007
- [ADR-0008：按运行目录持久化](adr/0008-run-directory-persistence.md)，取代 ADR-0005
- [ADR-0013：本地 Schema 校验与显式 Structured Output Mode](adr/0013-local-schema-validation-structured-output-modes.md)，取代 ADR-0012
- [ADR-0010：最小 Docker 执行边界](adr/0010-minimal-docker-execution-boundary.md)，取代 ADR-0004

实现范围与验收合同见 [MVP Specification](spec.md)。
