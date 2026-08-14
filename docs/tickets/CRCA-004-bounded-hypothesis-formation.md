# CRCA-004 — 形成受约束的初始诊断假设

## Priority

P0

## Milestone

M1 — Evidence-Driven Diagnosis

## Background

CodeRCA 的核心招聘信号不是自由对话式 ReAct，而是由程序维护生命周期和不变量、模型负责有限诊断决策。第一个可验证能力是从 Diagnosis Task 形成一至三个可证伪 Hypothesis。

## Goal

让 Diagnosis Run 经过合法生命周期形成有界、结构化且可追踪的初始 Hypothesis 集合，并对模型结构失败采取确定的终止策略。

## Scope

- 实现 Preparing、Forming Hypotheses、Diagnosing 和失败时 Finalizing 的最小状态路径。
- 定义 Hypothesis 形成阶段的小型 Schema。
- 限制初始 Hypothesis 数量为一至三个，并固定初始顺序。
- 初始形成后禁止增加、替换、复活或重新激活候选。
- 每次模型调用从当前 Diagnosis Task 和结构化状态重新组装有界上下文。
- Schema 首次失败允许一次明确纠错，第二次失败产生 Schema Failure。

## Out of Scope

- 工具执行、Evidence Score、补丁和 Validation。
- 候选动态扩充、恢复运行或多级预算。
- Prompt 逐字冻结或公开模型私有思维链。

## Technical Approach

使用轻量显式状态机控制生命周期，把诊断循环的自由度限制在阶段 Schema 内。Hypothesis 至少包含稳定 ID、候选 Root Symbol 或待定位描述、可证伪机制和状态。模型只提出候选；程序校验数量、状态和转移。上下文由当前状态快照重建，不追加完整消息历史。

## Implementation Steps

1. 定义生命周期阶段、合法转移和终态规则。
2. 定义 Hypothesis 与形成阶段输出 Schema。
3. 实现有界上下文组装和模型调用适配。
4. 实现一次 Schema 纠错与 Schema Failure 终止路径。
5. 将阶段、模型响应引用和校验错误写入 Diagnosis Run 事件。
6. 用 FakeModelProvider 和真实兼容模型验证形成路径。

## Acceptance Criteria

- [ ] 合法运行只形成一至三个带稳定 ID 的初始 Hypothesis。
- [ ] 超过三个、零个或字段非法的候选触发一次纠错；再次非法产生 Schema Failure。
- [ ] 初始集合形成后，程序拒绝新增、替换、复活或重新激活 Hypothesis。
- [ ] 非法阶段转换被拒绝，终态不能继续执行诊断动作。
- [ ] 每次模型请求由当前结构化状态重建，完整历史和大日志不被无限追加。
- [ ] CLI 和事件流可观察当前阶段、Hypothesis 摘要和失败分类。

## Testing Strategy

- 用表驱动测试覆盖全部合法和非法阶段转移。
- 用 FakeModelProvider 覆盖一个、三个、零个、四个候选以及一次纠错成功和二次失败。
- 验证同一 Hypothesis ID、初始顺序和不可复活不变量。
- 用超长日志 fixture 验证上下文只包含摘要或引用。
- 显式运行真实模型形成测试，不纳入默认 CI。

## Dependencies

- CRCA-001 — 建立 Manifest-to-Run 纵向骨架
- CRCA-003 — 建立 OpenAI-compatible 模型兼容性门禁

## Risks

- 状态机过度抽象导致工期失控；只实现 Spec 已列阶段和当前转移。
- 已配置模型在单个大 Schema 上可能不稳定；保持阶段 Schema 小而独立。
- 测试绑定 Prompt 文本；测试只断言公开 Schema 和领域不变量。

## Estimated Effort

1 engineer-day

## Related Spec Sections

- User Stories 5–7, 16–17, 21–22, 25–26, 35–39, 53–54
- Implementation Decisions 6–10, 24–25
- Testing Decisions 1, 7–8, 11–12

## Related ADRs

- ADR-0001 — 使用自研显式诊断状态机
- ADR-0008 — 两周 MVP 按 Diagnosis Run 目录保存记录
- ADR-0013 — 本地 Schema 校验与显式 Structured Output Mode
