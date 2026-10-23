# Task 3：Bounded Self-Correction 轨迹

这是一份从 Run `ef028279-b64d-41a2-a98f-4459c65318c0` 的结构化事件与报告中提取的脱敏轨迹。它只保留可审计的状态、Experiment、Observation/Evidence 引用和 Validation 结果，不包含原始模型响应、私有推理、API 凭证或本机路径。

```text
H1 proposed
  机制：底层 Flag evaluator 错误地返回 active
        │
        ▼
X1 / run_tests
  O1：direct_flag_state=False，但 inverse guard 仍拒绝请求
  E1：contradicting，绑定 H1 与 O1
        │
        ▼
Assess H1 → falsified → H1 rejected
        │
        ▼
Reformulate H2 from E1
  机制：inverse decorator branch 缺少逻辑取反
        │
        ├─ X2 / search_code → O2 → E2 inconclusive
        │     H2 保持 testing，继续选择不同 Experiment
        │
        └─ X3 / inspect_diff → O3 → E3 supporting
                              │
                              ▼
                    Assess H2 → sufficiently_supported
                              │
                              ▼
                    Patch Intent → Candidate Patch
                              │
                              ▼
                    Docker Validation passed
```

## 可验证不变量

- 任意时刻只有一个 Active Hypothesis；
- H1 的 `evidence_basis` 为空；
- H2 的 `evidence_basis` 只引用程序已记录的 H1 Evidence `E1`；
- H1 先进入 `rejected`，随后才能形成 H2；
- `E1` 来自绑定 H1 的真实 `run_tests` Observation；
- H2 在 `E2` 不充分时保持 `testing`，没有被过早标记为 supported；
- 只有 H2 被 Supporting Evidence 支持后，才进入 Patch 与 Validation；
- 最终 Outcome 与 Trajectory 自动检查通过，人工 Causal Review 仍为 pending。

对应的机器可读摘要见 [task-3-evaluation.json](task-3-evaluation.json)。完整本地验收方式见 [Engineering Evaluation 与本地验收](../evaluation.md)。
