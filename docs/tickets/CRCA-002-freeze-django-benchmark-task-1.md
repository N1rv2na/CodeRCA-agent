# CRCA-002 — 冻结 Django 基准仓库并构造 Task 1

## Priority

P0

## Milestone

M0 — Walking Skeleton & Risk Gates

## Background

Agent 闭环只有在故障输入可重复、答案不泄漏且测试环境固定时才可验收。Task 1 是最早的真实 Diagnosis Task，主要验证 Git diff 与代码阅读证据路径。

## Goal

提供一个在冻结开源 Django 仓库中能够稳定复现业务逻辑回归的 Task 1，并将 Agent 可见输入与 Evaluation Ground Truth 明确隔离。

## Scope

- 选择并记录一个许可证合适、依赖可固定的开源 Django 仓库快照。
- 构造或选定 Task 1 的 Faulty Commit、清洗后的 Agent 可见 CI artifact 和注册测试命令。
- 冻结基础快照、容器镜像输入和允许的读写边界。
- 编写 Task Manifest，并单独记录 Root Symbol、触发条件、故障机制、失败表现和参考修复行为。
- 验证 Agent 可见材料不包含答案性 commit message、参考补丁或修复后代码。

## Out of Scope

- Task 2、Task 3 和统计性 Benchmark。
- 实现诊断 Agent、RAG 或 Docker Tool Runtime。
- 支持第二个仓库、任意 Django 版本或任意本地 Python 仓库。

## Technical Approach

把任务定义视为不可变版本化输入。用固定 commit 标识故障版本，用命令 ID 而不是任意 Shell 描述测试入口。Ground Truth 仅供 Evaluation 使用，与 Task Manifest 物理分离。优先选择测试耗时短、失败机制单一且能由 diff/代码证据解释的回归。

## Implementation Steps

1. 按许可证、构建稳定性和测试耗时筛选并冻结仓库版本。
2. 创建或提取单一业务逻辑缺陷，确定 Faulty Commit。
3. 重复验证注册命令的目标失败语义，并冻结不泄漏答案的规范化 CI artifact。
4. 固定依赖与 Django 镜像构建输入。
5. 编写 Task 1 Manifest 和独立 Ground Truth。
6. 增加重复复现、输入隔离和 Manifest 合法性检查。

## Acceptance Criteria

- [ ] 从冻结基础快照检出 Faulty Commit 后，注册命令连续运行三次均产生预期失败。
- [ ] Task Manifest 包含规范要求的仓库、commit、日志、命令、镜像、权限和预算字段。
- [ ] Ground Truth 精确标注一个规范 Root Symbol，并记录完整因果字段。
- [ ] Agent 可见输入不包含 Root Symbol 标准答案、参考补丁、修复后代码或答案性文本。
- [ ] 故障属于受支持的业务逻辑回归，且不依赖外部服务、性能、并发或随机行为。
- [ ] 仓库来源、许可证、冻结版本和复现步骤可审计。

## Testing Strategy

- 在干净工作区重复执行注册命令并断言稳定失败表现；不要求 probe 原始 stderr 与清洗后的 CI artifact 逐字相同。
- 对 Manifest 和 Ground Truth 分别做 Schema 校验与泄漏检查。
- 构建冻结镜像并验证 Faulty Commit 能在预期环境复现。
- 用故意篡改的 commit、命令 ID 和路径验证任务校验会拒绝无效输入。

## Dependencies

- CRCA-001 — 建立 Manifest-to-Run 纵向骨架

## Risks

- 上游仓库依赖安装不稳定；选择时应把离线可缓存和构建耗时作为硬门槛。
- 人工注入缺陷过于显眼；故障应简单但不能直接从测试名或 commit message 泄漏答案。
- Ground Truth 与 Agent 输入混放导致评测污染。

## Estimated Effort

1 engineer-day

## Related Spec Sections

- Product Scope
- User Stories 1–3, 19–20, 55–59, 62, 74
- Implementation Decisions 1, 3–5, 33, 40
- Testing Decisions 19, 25

## Related ADRs

- ADR-0010 — 两周 MVP 采用最小 Docker 执行边界
