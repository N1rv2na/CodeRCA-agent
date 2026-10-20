# ADR-0017：可执行 Experiment 与单 Hypothesis 诊断预算

- 状态：Accepted
- 日期：2026-10-20
- 补充：ADR-0002、ADR-0014（不替代）

## 背景

CRCA-005 的真实模型运行表明，仅向模型提供工具名和输入 Schema 不足以约束
Experiment：模型可能要求未注册的 instrumentation、临时补丁或任意测试；也可能在
一个错误机制上反复选择低信息量读取，直到耗尽整个 Run 的 Tool Budget。此时
Observation 可能已经暴露更具体的替代机制，但 Evidence 与 Assessment 仍被旧
Hypothesis 锚定。

## 决策

每个 Tool Spec 除输入合同外，还声明 `observation_capabilities` 和 `limitations`，并由
Tool Runtime 动态投影到 Select Experiment、Assess Hypothesis 和 Reformulation
Context。Experiment 必须能由所选工具在这些已注册边界内直接产生预期 Observation；
不得假定任意 Shell、诊断期补丁、未注册测试或 instrumentation。

每个 Active Hypothesis 最多执行三个诊断 Experiment。该预算与整个 Diagnosis Run
最多十次工具调用的 Tool Budget 相互独立；十次上限可容纳 H1～H3 各三次
Experiment 与一次 Patch Validation。第三次 Evidence 形成后，
`continue_testing` 不再合法；模型必须提交 `sufficiently_supported`、`falsified` 或
`inconclusive`。程序校验预算并复用现有的一次结构化纠错，但不根据预算自动决定
Hypothesis 语义。

Evidence Direction 仍只相对当前 Active Hypothesis。Evidence explanation 可以指出
Observation 暗示的具体替代机制，但不能借此重写当前 Hypothesis。若决定性 Experiment
在工具能力内不可执行，或 Observation 已建立更好的替代方向，Assessment 可以将当前
Hypothesis 结束为 `inconclusive`；后续 H2/H3 必须引用正式 Evidence ID，并提出能由
当前 Tool Catalog 检验的新机制和 falsification criterion。

## 备选方案

- 仅增强 Prompt，不增加程序预算：无法确定性阻止无限或重复测试。
- 为替代机制增加新的 Schema 字段或 Hypothesis 图：增加状态与迁移复杂度，超出 MVP。
- 开放任意 instrumentation、Shell 或诊断期 `apply_patch`：破坏注册工具和安全边界。
- 第一次无信息 Observation 后立即 Reformulate：过早放弃仍可被现有工具有效检验的假设。

## 结果与取舍

Agent 能区分“理论上有价值的实验”和“当前工具真正可执行的实验”，并在错误 H 上有界
停止；Tool Catalog 新增工具时会自动进入 Context，不需要修改 ContextBuilder 的固定
工具列表。代价是三个 Experiment 可能不足以检验复杂机制，工具能力描述需要保持准确，
模型仍可能错误解释 Evidence。此决策不增加新工具、不改变 Single Active Hypothesis、
H1～H3、总 Tool Budget、一次 Schema Correction 或本地结构校验合同。
