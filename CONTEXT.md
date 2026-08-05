# CodeRCA

CodeRCA 的领域是对单仓库 CI 测试失败进行假设驱动的根因诊断。本文定义诊断、验证和评测中必须统一使用的领域语言。

## Language

### 诊断任务

**Diagnosis Task（诊断任务）**:
一组不可变的故障输入与执行约束，描述需要诊断的问题。
_Avoid_: Job、Case、一次模型运行

**Diagnosis Run（诊断运行）**:
Agent 针对一个 Diagnosis Task 的一次独立执行实例。
_Avoid_: Diagnosis Task、评测任务

**Faulty Commit（故障版本）**:
包含待诊断缺陷、并能够复现目标 CI 失败的代码版本。
_Avoid_: 修复版本、当前最新版

### 根因推理

**Root Cause（根因）**:
导致可观察失败的缺陷位置与因果机制的组合。
_Avoid_: 错误日志、失败断言、仅有代码位置

**Root Cause Candidate（根因候选）**:
尚待验证或已经验证，并参与 Top-1/Top-3 排序的潜在 Root Cause。
_Avoid_: 无证据猜测、最终结论

**Root Symbol（根因符号）**:
被标注为缺陷位置的函数、方法或类，是位置命中评测的规范单位。
_Avoid_: 同文件中的任意相关代码、调用链上的任意符号

**Hypothesis（假设）**:
能够被 Evidence 支持并被 Experiment 证伪的 Root Cause 陈述。
_Avoid_: 最终结论、模型直觉

**Evidence（证据）**:
具有可追溯来源、方向和强度，能够改变某个 Hypothesis 可信度的信息记录。
_Avoid_: 模型自信度、无引用解释、一般知识

**Supporting Evidence（支持证据）**:
提高某个 Hypothesis 可信度的 Evidence。
_Avoid_: 已经证明假设

**Contradicting Evidence（反对证据）**:
降低或否定某个 Hypothesis 可信度的 Evidence。
_Avoid_: 普通工具错误、没有产生新信息的失败

**Experiment（实验）**:
为区分、支持或证伪 Hypothesis 而执行，并预先声明预期观察的受控动作。
_Avoid_: 任意工具调用、无预期结果的探索

**Observation（观察结果）**:
Experiment 实际产生且可以被引用的结果。
_Avoid_: Agent 对结果的解释、未执行的预期

**Evidence Score（证据分数）**:
根据支持与反对 Evidence 计算、仅用于 Root Cause Candidate 排序的规则分数。
_Avoid_: 校准概率、模型置信概率

### 修复验证

**Validation（验证）**:
使用测试与静态约束检查候选补丁是否恢复预期行为。
_Avoid_: 因果解释评分、模型代码审查

**Public Validation（公开验证）**:
Agent 在 Diagnosis Run 中可见并能用于调整 Hypothesis 的 Validation。
_Avoid_: Hidden Validation、最终评测反馈

**Hidden Validation（隐藏验证）**:
候选补丁封存后由独立评测器执行，且结果不得反馈给 Agent 的 Validation。
_Avoid_: Agent 可反复迭代的测试、公开测试

### 评测

**Baseline（基线）**:
在相同任务、模型和环境约束下，预先冻结并用于衡量 CodeRCA 增益的诊断方案。
_Avoid_: 临时调弱的对照、使用不同输入的方案

**Raw Model Baseline（裸模型基线）**:
只接收 CI 日志与 Git diff，并通过单次模型调用完成诊断的 Baseline。
_Avoid_: 固定工具流水线、无模型关键词搜索

**Fixed Pipeline（固定流水线）**:
工具顺序和调用次数预先冻结，不能根据中间 Evidence 改变路径的 Baseline。
_Avoid_: 动态 Agent、Raw Model Baseline

**Run Manifest（运行清单）**:
不可变地记录一次 Diagnosis Run 的模型、prompt、索引、仓库、环境、预算和随机性配置的复现清单。
_Avoid_: Root Cause 报告、运行事件流

### 运行结果

**Invalid Task（无效任务）**:
因输入或环境不可复现而无法合法开始诊断的 Diagnosis Task。
_Avoid_: Agent 诊断错误、Infrastructure Failure

**Infrastructure Failure（基础设施失败）**:
由模型服务、容器或工具运行设施导致，而不是由诊断决策导致的运行失败。
_Avoid_: Root Cause 未命中、错误 Hypothesis

**Schema Failure（结构失败）**:
模型在一次纠错机会后仍无法输出符合约定 Schema 的结果。
_Avoid_: 工具业务执行失败、错误的因果解释
