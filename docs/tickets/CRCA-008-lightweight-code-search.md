# CRCA-008 — 实现 Lightweight Code Search

## Priority

P0

## Milestone

M3 — Agent Code Exploration

## Background

Task 1 可以通过 diff 与定点代码阅读完成，但当 Root Symbol 未在初始失败信息中暴露时，Agent 仍需要一种自主发现候选代码位置的工具。完整 AST/BM25/向量混合检索与 CPU reranker 会把 MVP 的主要成本转移到检索基础设施；CodeRCA 当前需要的是可控、可追溯、足以支持诊断 Observation 的轻量搜索。

## Goal

让 Agent 能为当前 Active Hypothesis 调用受控 `search_code`，在 Task Manifest 指定 Faulty Commit 工作区中执行确定性的内容/符号文本或路径搜索，并把有界结果作为可追溯 Observation 接入既有 Evidence 与 Context 流程。

## Scope

- 定义最小 `search_code` Tool Spec、输入和结果合同。
- 支持关键词以及函数、类、方法名称的字面量内容搜索。
- 支持仓库相对文件路径或文件名的字面量搜索。
- 优先使用 ripgrep，以参数数组执行，不拼接或开放任意 Shell。
- 输入包含有界非空查询、显式搜索类型、可选受限路径范围、结果上限和上下文行数。
- 结果包含规范化查询、`matched`/`no_matches`、仓库相对路径、精确行号或行区间、有界片段、截断状态和 Artifact 引用。
- 将调用绑定 Active Hypothesis、Experiment 元数据和 Tool Budget，并生成带 provenance 的 Observation。
- 在 Faulty Commit 工作区与 Manifest `read_paths` 内执行路径、版本和输入隔离检查。
- 对完整结果落盘，只让既有 ContextBuilder 通过 Observation/Evidence 接收有界内容及引用。

## Out of Scope

- Python AST semantic chunking、BM25、embedding、向量数据库/索引、dense retrieval、融合和 CPU reranker。
- 预处理索引、增量索引、检索缓存、Retrieval Provider、插件系统和自动后端探测。
- 检索消融、参数调优、相关性 Benchmark 或量化增益声明。
- 自动推断 AST Symbol、调用图或把匹配结果声明为 Ground Truth Root Symbol。
- 修改 ContextBuilder、DiagnosisStateMachine 或固定 Agent 工具调用顺序。

## Technical Approach

内容搜索使用 ripgrep fixed-string、行号和有界上下文选项；路径搜索从 Faulty Commit 工作区枚举仓库相对文件，并用确定性字面量规则过滤路径/文件名。Tool Runtime 在执行前解析并规范化工作区根、可选搜索范围和 Manifest `read_paths`，拒绝路径穿越、仓库外路径和符号链接逃逸，不向模型开放命令行拼接。

ripgrep 退出码 0 映射 `matched`，退出码 1 映射成功的 `no_matches`；超时映射 `timeout`，其他非零执行异常映射 `execution_failed`。Schema/范围问题分别使用 `invalid_arguments` 和 `permission_denied`。匹配结果只发现候选位置：Tool Result 生成 Observation，模型再创建 Evidence；匹配顺序或数量不成为 Evidence Score 或 Hypothesis Ranking。

## Implementation Steps

1. 在既有 Tool Runtime 风格下冻结 `SearchCodeInput`、`SearchCodeResult` 和 `SearchMatch` 的最小字段及上限。
2. 建立 Faulty Commit 工作区根、Manifest `read_paths`、禁止输入与符号链接边界校验。
3. 实现 argv-based ripgrep fixed-string 内容搜索和确定性路径搜索。
4. 规范化路径/行区间，执行匹配数、上下文、片段及总输出截断，并持久化完整 Tool Result Artifact。
5. 将结果接入 Experiment → Observation → Evidence → 既有 ContextBuilder 数据流及调用审计。
6. 在冻结仓库 fixture 上建立命中、零结果、边界、错误、截断和可复现性测试。

## Acceptance Criteria

- [ ] `search_code` 通过统一 Tool Runtime 与 Tool Spec 执行，并且每次调用绑定当前 Active Hypothesis、目的、预期 Observation 和 falsification relevance。
- [ ] 内容/符号文本查询与路径/文件名查询具有显式、稳定且不依赖预处理索引的输入语义。
- [ ] 查询由参数数组传递，不允许 Shell 字符串、任意命令或未经校验的 ripgrep option 注入。
- [ ] 命中结果包含规范化查询、仓库相对路径、精确行号或行区间、有界片段、截断状态和完整 Artifact 引用。
- [ ] 合法零结果返回成功的 `no_matches`，不分类为 `execution_failed`。
- [ ] `invalid_arguments`、`permission_denied`、`timeout` 和 `execution_failed` 与既有 Tool Runtime 合同一致且默认不重试。
- [ ] 搜索只访问 Faulty Commit 工作区和 Manifest `read_paths`；路径穿越、仓库外文件、符号链接逃逸、Ground Truth、参考补丁和修复后代码均不可读取。
- [ ] 查询长度、路径范围、匹配数量、上下文行数、单片段长度和总输出长度均有确定性上限。
- [ ] Search Tool Result 生成可追溯 Observation；现有 ContextBuilder 无需修改即可通过 Observation/Evidence 使用有界搜索信息。
- [ ] 文档与结果不把文本匹配自动标注为 AST Symbol、Root Symbol Ground Truth、Evidence Score 或 Hypothesis Ranking。

## Testing Strategy

- 用关键词、函数名、类名、方法名、文件名和路径片段覆盖两种搜索类型。
- 对相同 Faulty Commit、查询和上限重复执行，验证稳定顺序和相同结构化结果。
- 覆盖 `matched`、`no_matches`、非法参数、权限拒绝、超时、ripgrep 执行失败和输出截断。
- 用路径穿越、绝对路径、越界 `read_paths`、符号链接及答案文件 fixture 验证输入隔离。
- 通过 Tool Runtime 验证 Hypothesis/Experiment 绑定、Tool Budget、审计事件、Artifact 和 Observation provenance。
- 验证默认测试不访问网络、不下载 embedding 模型，也不修改现有 ContextBuilder 测试合同。

## Dependencies

- CRCA-002 — 冻结 Django 基准仓库并构造 Task 1
- CRCA-005 — 通过 Diff 与代码 Evidence 检验并 Reformulate Hypothesis

CRCA-008 不是 Task 1 端到端闭环的前置条件；Task 1 可以只使用 `inspect_diff`、`read_code`、`run_tests` 和 `apply_patch`。

## Risks

- 失败描述与源码词汇完全不一致时，字面量搜索可能漏掉关键位置；MVP 通过多轮 Agent 查询、diff 线索与 `read_code` 组合缓解，不声称语义检索能力。
- Agent 生成过宽查询导致大量匹配；固定查询、结果和片段上限，并把完整结果留在 Artifact。
- 路径或符号文本命中被误当成根因；Evidence 必须解释与 Hypothesis 的关系，最终 Root Symbol 仍由诊断与 Validation 确定。
- ripgrep 平台行为差异影响复现；冻结最低版本和参数集合，并在目标开发环境执行合同测试。

## Estimated Effort

1 engineer-day

## Related Spec Sections

- User Stories 10, 19, 23–28, 44–46, 50–52, 59
- Implementation Decisions 18–25, 28–32, 40, 44
- Testing Decisions 13–18

## Related ADRs

- ADR-0015 — CodeRCA MVP 使用 Lightweight Code Search
- ADR-0002 — 使用结构化工具运行时且不实现 MCP
- ADR-0014 — 单 Active Hypothesis 与按决策重建上下文
- ADR-0008 — 两周 MVP 按 Diagnosis Run 目录保存记录
