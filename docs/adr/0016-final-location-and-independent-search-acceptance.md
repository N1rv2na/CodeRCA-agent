# ADR-0016：最终定位独立于暂定位置，搜索验收独立于 Outcome

- 状态：Accepted
- 日期：2026-10-20
- 修订：2026-10-20，允许严格限定的内容搜索和显式 Evidence Basis 证明最终位置坐标
- 补充：ADR-0014、ADR-0015（不替代）

## 背景与决策

探索前形成的 Hypothesis 可能机制正确但位置宽泛。把不可变 root_symbol 同时
作为最终定位答案，会使后续真实代码探索无法精确报告根因。保留此字段表示
形成时的暂定符号，在已有 generate_report 响应增加必需且可空的 location，
不新增模型阶段或改变 Hypothesis History。最终定位引用 supported Hypothesis 的
直接代码 Evidence，或其 `evidence_basis` 显式引用的历史代码 Evidence，并使用
Faulty Commit 的路径和行区间；不能依据补丁路径、
路径搜索、零结果、截断结果或测试通过补全答案。`search_code(content)` 的命中只有
在结果为 `matched`、单项匹配未截断、仓库相对路径相同且行区间完整覆盖声明位置，
并通过 Evidence → Observation → Tool Result → Experiment → Artifact 审计时，才可
作为位置坐标来源。历史 Evidence 保留原 Hypothesis ID 与 Direction，不被复制、
重标或视为当前 H 的 Supporting Evidence。原始机制不能借定位细化而被偷偷改写。

Outcome 分别检查最终 location、修复 Validation 和报告字段；因果正确性仍需
人工核查。搜索能力独立报告 verified / not_demonstrated / invalid_trajectory。
不搜索不代表诊断失败，搜索成功不代表根因正确；强制展示搜索只能作为操作者
显式选择的附加验收条件，不能进入 Agent 的固定工具序列。

## 取舍

复用最终报告而非增加定位阶段，减少模型调用与状态路径。代价是旧报告没有
最终 location，读取时只能显示未提供，不能从旧 Hypothesis 猜测补齐。
程序校验来源/边界不等于验证因果或 AST 符号语义。精确位置仍可能为空。
旧 Task 2 保留为回归样例；新探索任务另行设计，不因模型结果移动答案标准。

允许严格内容搜索结果覆盖位置，避免要求 Agent 在已经获得精确、未截断代码片段后
机械地追加一次 `read_code`。代价是定位校验必须同时验证搜索类型、命中状态、单项
截断标记、路径、行区间和完整 provenance。该放宽只证明源码坐标曾被真实观察；
搜索文本不能自动确定 `symbol`、Hypothesis 真伪或因果机制。

Evidence Direction 是相对其原 Hypothesis 的解释，而源码坐标 provenance 是由真实
Artifact 确立的客观事实。允许 supported H 显式 Evidence Basis 提供位置坐标，避免
为报告格式重复读取已经审计过的代码；不在 `evidence_basis` 中的历史 Evidence 仍然
禁止引用。supported 状态仍需当前 H 自己的 Supporting Evidence，历史位置来源不能
替代因果支持或 Public Validation。
