# CRCA-003 — 建立本地模型兼容性门禁

## Priority

P0

## Milestone

M0 — Walking Skeleton & Risk Gates

## Background

CodeRCA 只连接用户预先启动的一个外部本地模型服务，且开发机显存有限。若到开发末期才发现模型无法稳定输出结构化决策或补丁，状态机和 Prompt 都可能被迫返工。

## Goal

用一个固定 HTTP ModelProvider 和最小能力探针，在主体 Agent 开发前冻结可用的本地模型服务配置或明确判定候选不兼容。

## Scope

- 定义单一 HTTP ModelProvider 请求、响应、超时和错误合同。
- 提供 Diagnosis Run 启动前的服务与模型可用性检查。
- 建立四类小探针：阶段 Schema、合法工具参数、Evidence 更新和小型 Python 补丁。
- 记录选定服务、模型标识、关键生成参数和探针结果。
- 自动化测试使用 FakeModelProvider 验证同一 Provider 抽象。

## Out of Scope

- 模型下载、加载、量化、CUDA 或显存管理。
- 云端兜底、多真实模型适配、自动模型选择或性能 Benchmark。
- 正式诊断 Prompt 优化和三项 Agent Evaluation。

## Technical Approach

将本地模型视为外部依赖，只固定 CodeRCA 所需的最小 HTTP 合同。探针关注协议兼容性和任务所需能力，不形成模型排行榜。每类结构化输出只允许显式校验；探针失败应阻断真实运行并保留可操作的错误，而不是加入模糊解析。

## Implementation Steps

1. 固定 Provider 配置、HTTP 请求响应和失败分类。
2. 实现服务连通性、模型标识和请求超时的 preflight。
3. 编写四类最小能力探针及其结构化验收规则。
4. 运行候选本地模型并冻结通过门禁的配置。
5. 增加 FakeModelProvider 合同测试和真实探针的显式执行入口。
6. 记录失败诊断信息和更换候选模型的操作边界。

## Acceptance Criteria

- [ ] Provider 只通过固定 HTTP 协议连接外部本地服务，CodeRCA 不加载模型。
- [ ] preflight 能区分服务不可达、模型不可用、超时和非法响应。
- [ ] 选定候选能够分别输出合法阶段对象、工具参数、Evidence 更新和可应用的小型 Python patch。
- [ ] 探针保存模型标识、生成配置、原始响应引用和校验结果。
- [ ] 不兼容候选会明确失败，不进入正式 Diagnosis Run。
- [ ] 默认自动化测试使用 FakeModelProvider，且不需要 GPU 或网络。

## Testing Strategy

- 用伪 HTTP 服务覆盖成功、超时、非 JSON、错误状态码和错误模型场景。
- 对 FakeModelProvider 和真实 Provider 执行共享合同测试。
- 将真实模型探针标记为显式本地检查，避免进入默认 CI。
- 使用不可应用 patch 和非法工具参数 fixture 验证门禁确实拒绝。

## Dependencies

- CRCA-001 — 建立 Manifest-to-Run 纵向骨架

## Risks

- 候选模型偶尔通过探针但正式任务不稳定；固定生成参数并保存原始响应以便诊断。
- 为兼容弱模型而破坏阶段 Schema；门禁失败应优先更换候选，不扩大模糊解析范围。
- HTTP 服务实现差异过大；第一版只承诺一个已经冻结的服务合同。

## Estimated Effort

0.5 engineer-day

## Related Spec Sections

- User Stories 17, 35–36, 47–50, 73
- Implementation Decisions 8–9, 26–28
- Testing Decisions 5–6, 11
- Further Notes — 模型能力探针

## Related ADRs

- ADR-0009 — 两周 MVP 只连接一个外部本地模型服务

