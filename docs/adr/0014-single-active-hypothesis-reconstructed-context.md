# ADR-0014：单 Active Hypothesis 与按决策重建上下文

- 状态：Accepted
- 日期：2026-10-17
- 取代：ADR-0001

## 背景

ADR-0001 选择显式状态机是正确的，但把三个初始 Hypothesis 同时保留并通过 Evidence Score 竞争。初始形成时 Agent 尚未读取 diff、代码或测试 Observation，固定候选集合会过早裁剪搜索空间；人工整数权重又增加 Ranking、Tie-break 和 Top-1 状态，却不能补回遗漏的 Root Cause。与此同时，简单状态快照不足以让后续 Experiment、Evidence 更新和 Reformulation 使用已经积累的诊断知识，而完整 Conversation History replay 会混合审计记录与模型真正需要的输入。

## 决策

CodeRCA 保留小型显式状态机和受约束 ReAct，但一次 Diagnosis Run 在任意时刻最多只有一个 Active Hypothesis。程序按 append-only 顺序分配 H1、H2、H3；当前 Hypothesis 只能通过 falsification-oriented Experiment、Observation、Evidence 和受校验的 Assessment 继续、进入 `supported`、`rejected` 或 `inconclusive`。只有 `rejected` 或 `inconclusive` 且预算剩余时才能 Reformulate；H3 结束后确定性停止，不允许 H4。Evidence 保留 provenance、Observation 引用、方向和解释，但不计算数值分数，不进行 Diagnosis Candidate Ranking。

初始形成和 Reformulation 使用不同合同。`FormHypothesisDecision` 不暴露 Evidence Basis，程序创建 H1 时固定保存空值，因为 Task、Manifest 和 CI Failure 还不是正式 Evidence。`ReformulateHypothesisDecision` 为 H2/H3 引用至少一个有序、唯一 Evidence ID；程序只接受能够解析为真实 Evidence、且所属 Hypothesis 已在同一 History 中进入 `rejected` 或 `inconclusive` 的引用。模型不能用自由文本伪造 Evidence Basis。

每次 Model Decision 都从 Diagnosis Task 与结构化 Diagnosis State 重建 decision-specific Working Context。形成 H1、选择 Experiment、更新 Evidence、评估 Hypothesis、Reformulate 和 Validation 使用不同的确定性 Context View，只选择相关 Evidence、Observation 摘要和必要的 bounded raw excerpt。完整 Model Response、Tool Result、代码、日志和测试输出保存在 Run Artifact 中，不作为 Agent State，也不默认重放给模型。

## 备选方案

- 保留多个初始候选与固定分数：实现候选比较直观，但继续承担过早冻结搜索空间和虚假精确性的缺陷。
- 完整 Conversation History replay：实现简单，却使上下文随运行无限增长，并把无关原始输出重复发送给模型。
- 多 Active Hypothesis、概率更新或 beam search：搜索能力更强，但明显超出两周 MVP 的状态、调试和评测预算。

## 后果

- 正面：Agent 可以在 H1 错误时利用真实 Observation 自我纠正，同时保持 H1–H3 的确定性上界。
- 正面：状态、上下文和审计产物职责分离，Context Engineering 可以通过固定投影规则测试。
- 正面：删除 Evidence Score、Candidate Ranking 和 Tie-break，降低实现与解释复杂度。
- 负面：顺序搜索一次只检验一个方向，错误 H1 会消耗工具预算。
- 负面：H2/H3 仍依赖模型正确解释 Evidence，最多三次形成不保证找到 Root Cause。
- 中性：检索管线内部的 BM25、向量融合、reranker 排序与 Top-K 不受影响；它们不是 Diagnosis Hypothesis Ranking。
