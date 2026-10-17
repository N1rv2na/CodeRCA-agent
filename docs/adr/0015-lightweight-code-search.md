# ADR-0015：CodeRCA MVP 使用 Lightweight Code Search

- 状态：Accepted
- 日期：2026-10-17
- 取代：ADR-0007

## 背景

ADR-0007 计划在两周 MVP 中实现 Python AST 分块、BM25/向量混合召回和 CPU reranker。该方案能够展示完整 Code RAG 数据路径，但会把有限开发时间投入索引、模型依赖、融合、重排和检索测试，而 CodeRCA 的核心目标是展示 falsification-first Diagnosis、结构化工具、Evidence 驱动的自我纠正、Context Engineering 和真实 Validation。独立 RAG 项目将承担 Chunking、Embedding、Hybrid Retrieval、Reranking 与 Retrieval Evaluation 的展示职责。

## 决策

CodeRCA MVP 保留五工具中的 `search_code`，但以受控 Lightweight Code Search 替代完整混合 Code RAG。优先使用成熟的 ripgrep 可执行程序，对 Task Manifest 指定的 Faulty Commit 工作区提供可复现的内容/符号文本搜索和文件路径/文件名搜索，不要求预处理索引。

`search_code` 仍通过 ADR-0002 的 Tool Runtime 执行，并绑定当前 Active Hypothesis、Experiment 目的、预期 Observation、falsification relevance、Tool Budget、权限、超时、错误和审计合同。完整结果保存为 Run Artifact；有界片段及引用形成 Observation，再由模型解释为 Supporting、Contradicting 或 Inconclusive Evidence。现有 ADR-0014 ContextBuilder 继续按 Decision 从结构化状态选择 Observation 与 Evidence，不重放完整搜索历史。

搜索实现必须以参数数组而非 Shell 拼接调用 ripgrep，默认使用字面量内容查询；路径搜索使用仓库相对文件列表和确定性字面量过滤。所有范围先按 Faulty Commit 工作区根目录与 Manifest `read_paths` 做规范化校验，不跟随符号链接，不读取 Ground Truth、参考补丁、修复后代码或仓库外文件。查询长度、路径范围、匹配数量、上下文行数、片段长度和总输出均有固定上限。

搜索成功分为 `matched` 与 `no_matches`；零结果不是基础设施失败。ripgrep 内容搜索退出码 0 表示命中、1 表示合法零结果，超时单独分类，其他执行异常映射为 `execution_failed`。`invalid_arguments` 与 `permission_denied` 继续使用统一 Tool Runtime 错误。匹配项至少记录规范化查询、仓库相对路径、精确行号或行区间、有界片段、截断状态和 Artifact/provenance 引用。文本匹配不得自动声明 AST Symbol、Root Symbol Ground Truth、Evidence Score 或 Hypothesis Ranking。

## 替代方案

- 保留 ADR-0007 的 AST/BM25/向量/重排管线：检索能力更丰富，但依赖、开发量和调试面会挤压核心 Agent 闭环。
- 完全删除 `search_code`：范围最小，但 Agent 在未知代码位置时只能依赖 diff 和逐文件读取，削弱自主代码探索价值。
- 引入 Retrieval Provider、插件或自动后端选择：扩展性更强，但当前只有一个冻结仓库与一种轻量实现，属于提前抽象。

## 理由

Lightweight Code Search 保留了 Agent 自主选择工具、产生真实代码 Observation、建立 Evidence provenance 和通过 Task 2 验证代码探索的能力，同时删除与 CodeRCA 核心招聘信号无关的检索基础设施。固定字面量与路径语义也更容易测试、审计和复现。

## 后果

- 正面：无需 embedding、向量索引、BM25 融合、CPU reranker、AST chunking 或索引准备步骤，显著降低交付和 Debug 风险。
- 正面：`search_code` 仍是受约束 Agent Tool，Task 2 仍可验证自主代码探索与 Root Cause Localization。
- 正面：搜索结果能够沿用现有 Experiment → Observation → Evidence → ContextBuilder 数据流。
- 负面：纯文本与路径搜索不能处理词汇完全不一致的语义检索，也不能可靠推断 AST Symbol 或调用关系。
- 负面：查询质量更依赖模型从失败信息、diff 和当前 Hypothesis 提炼有效关键词。
- 中性：只有当冻结任务反复因词汇鸿沟失败，且已有足够查询/相关性标注可以独立评估高级检索收益时，才重新考虑 BM25、dense retrieval 或 reranking。

## 被取代的 ADR

本 ADR 取代 ADR-0007。ADR-0003 与 ADR-0007 保留为历史记录。ADR-0014 的 Single Active Hypothesis 与 decision-specific reconstructed context 决策不变。
