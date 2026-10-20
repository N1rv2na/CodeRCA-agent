# ADR-0018：结构化 Patch Intent 与确定性补丁编译

- 状态：Accepted
- 日期：2026-10-20
- 补充：ADR-0002、ADR-0010、ADR-0013（不替代）

## 背景

CRCA-010 的真实模型运行中，模型正确定位 `waffle/utils.py:keyfmt`，也提出了正确的
单行修复，但生成的 unified diff hunk 声明七行、实际只包含五行。该输出通过了
`PatchDecision` 的字符串 Schema，却被 `git apply --check` 以 `corrupt patch` 拒绝，
导致 Public Validation 尚未运行静态检查和注册测试便终止。

这表明当前边界把两类不同职责都交给了模型：模型既决定修复语义，又负责计算
unified diff 的行号和 hunk 计数。后者是确定性的序列化工作，不应成为模型能力或
随机性的组成部分。

## 决策

模型不再直接生成 unified diff，而提交绑定 supported Hypothesis 的结构化
`Patch Intent`。Patch Intent 指定一个允许的业务源码路径、修复机制，以及一至三个
`Exact Replacement`；每个替换包含非空 `old_text` 和允许为空的 `new_text`。

程序在 Faulty Commit 工作区内执行 `Patch Compiler`：授权目标路径，对每个
`old_text` 做大小写敏感的精确唯一匹配，拒绝缺失、歧义、重叠和 no-op 编辑，在内存中
应用替换，并在不归一化 LF/CRLF 的前提下确定性生成规范 unified diff。程序生成的 `Candidate Patch` 仍须通过现有
单文件与路径检查以及 `git apply --check`，之后才能创建 Patch Validation Action 并进入
Public Validation。

Patch Compiler 不执行模糊匹配、空白修复、大小写归一化、substring 猜测或语义修复。
Patch Intent 无法编译时，可以复用现有的一次结构化决策纠错；纠错成功前不产生
Candidate Patch、不创建 Patch Validation Action，也不消耗工具预算。第二次仍失败则
确定性停止。Candidate Patch 一旦进入 Public Validation，无论通过或失败都不生成第二个
Patch Intent，因此每个 Diagnosis Run 仍最多只有一个正式候选补丁。

Model Compatibility Gate 的补丁探针同步改为验证模型能否产生可编译且行为正确的
Patch Intent，而不再把手写 unified diff 语法作为模型最低能力。Public Validation 继续
负责判断修复行为是否正确；确定性编译只保证补丁语法、路径和可应用性，不保证修复语义。

## 备选方案

- 强化 Prompt 并在 diff 失败后重试一次：改动较小，但补丁语法仍然依赖模型且重试仍可失败。
- 自动重算损坏 diff 的 hunk header：需要解释一个已经损坏的语言，可能掩盖错误范围或上下文，逐步演变成 fuzzy repair。
- 让模型返回修改后的完整文件：可以由程序生成 diff，但显著增加上下文和输出，并可能覆盖无关代码。

## 结果与取舍

模型继续拥有“如何修复”的语义决策权，程序则拥有精确编辑定位、diff 序列化、安全边界和
生命周期不变量。真实运行中出现的 hunk 计数错误将被结构性消除，Run Artifact 也能明确区分
模型 Patch Intent、程序 Candidate Patch 和 Public Validation。

代价是 MVP 只支持单个 UTF-8 文本文件和一至三个精确替换；模型必须提供能够在 Faulty
Commit 中唯一匹配的原文，复杂重构和无锚点插入不在范围内。确定性编译不会把错误修复变成
正确修复，注册测试和静态检查仍可能以 `validation_failed` 结束运行。
