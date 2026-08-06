# CRCA-006 — 在最小 Docker 边界中运行测试 Experiment

## Priority

P0

## Milestone

M2 — Experiment & Patch Validation

## Background

代码阅读证据无法充分区分多个合理 Hypothesis。CodeRCA 需要在受控环境中执行真实测试，把预先声明的预期与实际 Observation 对照，形成强度最高的 Experiment Evidence。

## Goal

让 Agent 通过统一 Tool Runtime 在临时 Docker 工作区执行已注册的测试命令，并将结果作为可追溯 Observation 更新对应 Hypothesis。

## Scope

- 实现 `run_tests` Tool Spec 和注册测试命令解析。
- 使用一个预构建 Django 镜像和每次调用独立的临时工作区。
- 默认禁网、设置统一超时、不挂载模型凭证。
- 拒绝未知命令、任意 Shell 和 Manifest 范围外路径。
- 保存命令、退出状态、截断摘要和完整输出引用。
- 将测试 Observation 转换成 Supporting 或 Contradicting Experiment Evidence。

## Out of Scope

- 生产级沙箱、恶意代码防御、容器逃逸保证和完整资源限制矩阵。
- 多镜像、Docker Compose、跨平台一致性或后台任务。
- 应用补丁和 Top-1 Validation。

## Technical Approach

`run_tests` 接受注册命令 ID 而不是原始 Shell 字符串。宿主为 Faulty Commit 创建隔离工作副本并挂载到单次容器；模型服务和凭据始终留在容器外。Experiment 调用前必须声明目的与预期 Observation，运行结果通过普通文件引用进入有界状态。

## Implementation Steps

1. 固定测试命令注册表及其 Manifest 引用规则。
2. 定义 `run_tests` 输入输出、权限、超时和错误合同。
3. 建立临时工作区和单镜像容器执行路径。
4. 配置禁网、统一超时和凭据不挂载边界。
5. 将输出保存为运行产物并生成结构化 Observation。
6. 接入 Evidence 更新和 Diagnosis Run 事件流。
7. 增加 Task 1 镜像上的 Docker 集成测试。

## Acceptance Criteria

- [ ] 合法注册测试命令能在临时 Docker 工作区运行并返回真实退出状态。
- [ ] 未知命令、任意 Shell、路径越界和非法参数在启动容器前被拒绝。
- [ ] 容器默认无网络，并且不接收模型凭据或模型服务配置。
- [ ] 超时测试被终止并分类为 timeout，不自动重试。
- [ ] 完整输出保存到 Diagnosis Run，模型上下文只接收摘要和引用。
- [ ] 每个测试 Observation 绑定发起 Experiment 与 Hypothesis，并按 `+4/-4` 形成 Evidence。
- [ ] 文档和错误信息不将该边界宣传为生产级安全沙箱。

## Testing Strategy

- 在冻结镜像中覆盖测试通过、测试失败、执行错误和超时。
- 用网络探测与环境检查 fixture 验证禁网和凭据不挂载。
- 对未知命令和 Shell 注入输入进行权限合同测试。
- 通过应用服务执行一次 FakeModelProvider 驱动的测试 Experiment，检查事件、Observation、Evidence 和产物引用。

## Dependencies

- CRCA-002 — 冻结 Django 基准仓库并构造 Task 1
- CRCA-005 — 使用 Diff 与代码证据完成诊断循环

## Risks

- Windows/WSL 与 Docker 文件挂载差异增加调试成本；MVP 只验收当前开发环境和文档声明的平台。
- 测试耗时挤占五分钟单任务预算；冻结最小注册命令并设置硬超时。
- 安全承诺被夸大；验收仅覆盖 ADR-0010 明确列出的最小边界。

## Estimated Effort

1 engineer-day

## Related Spec Sections

- User Stories 9, 11–12, 14, 24, 29, 56, 67, 74–76
- Implementation Decisions 18–23, 33–34
- Testing Decisions 13–15, 19

## Related ADRs

- ADR-0001 — 使用自研显式诊断状态机
- ADR-0002 — 使用结构化工具运行时且不实现 MCP
- ADR-0010 — 两周 MVP 采用最小 Docker 执行边界

