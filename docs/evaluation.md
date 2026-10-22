# Engineering Evaluation 与本地验收

CodeRCA 的 Engineering Evaluation 逐任务报告结果，不计算成功率，也不以补丁通过替代根因定位或因果核查。默认自动化测试完全离线；模型门禁、真实模型调用和 Docker Validation 只能由操作者显式启动。

## 1. 环境准备

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

Lightweight Code Search 使用本机 `rg`。确认它可用：

```bash
rg --version
```

它不需要 AST、Embedding、向量数据库、BM25 索引或 Reranker，因此没有索引准备步骤。

## 2. 模型配置与兼容性门禁

```bash
export CODERCA_MODEL_BASE_URL="https://your-endpoint.example/v1"
export CODERCA_MODEL_ID="your-model-id"
read -rs "CODERCA_MODEL_API_KEY?API key: "
export CODERCA_MODEL_API_KEY
echo
export CODERCA_MODEL_STRUCTURED_OUTPUT_MODE="json_text"

.venv/bin/python -m coderca.model_gate_cli \
  --output-directory .coderca-model-gate
```

如 endpoint 需要少量非标准请求参数，应显式配置受保护的 request extension；例如：

```bash
export CODERCA_MODEL_REQUEST_EXTENSIONS='{"reasoning_split":true}'
```

门禁只证明当前配置在一次探针中满足本地 Schema 校验，不证明长期稳定性。

## 3. Docker 镜像与 Faulty Commit 工作区

三个任务复用同一冻结镜像：

```bash
docker build \
  -t coderca/django-waffle-task-1:5.0.0-py311-v2 \
  benchmarks/django-waffle/task-1
```

分别物化三个不含 Ground Truth 的 Faulty Commit 工作区：

```bash
.venv/bin/python -c 'from pathlib import Path; from coderca.benchmark import materialize_task_1; materialize_task_1(Path(".workspaces/task-1"))'
.venv/bin/python -c 'from pathlib import Path; from coderca.benchmark import materialize_task_2; materialize_task_2(Path(".workspaces/task-2"))'
.venv/bin/python -c 'from pathlib import Path; from coderca.benchmark import materialize_task_3; materialize_task_3(Path(".workspaces/task-3"))'
```

目标目录必须事先不存在。每个工作区的 `HEAD` 必须与对应 Manifest 的 `faulty_commit` 一致。

## 4. 运行真实 Diagnosis

按 Task 1、Task 2、Task 3 顺序运行：

```bash
.venv/bin/coderca benchmarks/django-waffle/task-1/manifest.json \
  --runs-dir .coderca-runs --model-provider openai-compatible \
  --workspace .workspaces/task-1

.venv/bin/coderca benchmarks/django-waffle/task-2/manifest.json \
  --runs-dir .coderca-runs --model-provider openai-compatible \
  --workspace .workspaces/task-2

.venv/bin/coderca benchmarks/django-waffle/task-3/manifest.json \
  --runs-dir .coderca-runs --model-provider openai-compatible \
  --workspace .workspaces/task-3
```

记录三个命令输出中的 `run_directory`。Task 1 是最小闭环；Task 2 展示自主代码探索与最终定位；Task 3 展示错误 H1 被真实 Evidence 反证后受限 Reformulation。

## 5. 人工因果核查

每个任务建立独立 JSON 文件。核查者对照冻结 Ground Truth 和最终结构化报告，分别判断四个字段，不使用模糊文本相似度：

```json
{
  "task_id": "crca-010-task-2",
  "reviewer": "project-author",
  "trigger_condition": "match",
  "defect_location": "match",
  "propagation_path": "match",
  "failure_manifestation": "match",
  "notes": "Compared report.json with frozen Ground Truth."
}
```

字段值只能是 `pending`、`match` 或 `mismatch`。任何 `mismatch` 都使因果核查失败；未完成的核查保持 `pending`，任务不能被标记为 accepted。

## 6. 运行 Engineering Evaluation

```bash
.venv/bin/coderca-evaluate \
  --run-directory .coderca-runs/<task-1-run-id> \
  --run-directory .coderca-runs/<task-2-run-id> \
  --run-directory .coderca-runs/<task-3-run-id> \
  --causal-review reviews/task-1.json \
  --causal-review reviews/task-2.json \
  --causal-review reviews/task-3.json \
  > evaluation.json
```

退出码：

- `0`：列出的每个任务均通过 Outcome、Trajectory 与人工因果核查；
- `1`：输入有效，但至少一个任务失败或人工核查仍 pending；
- `2`：Run、Ground Truth 或核查输入不可读取或不满足合同。

输出只包含逐任务 `tasks`，不包含总成功率。每个任务分别报告：

- `outcome`：最终位置命中、Patch Intent 编译、Candidate Patch 可应用性、Public Validation 和报告合同；
- `trajectory`：single-active、append-only、Evidence provenance、Reformulation、预算、停止条件与 supported-H patch 不变量；
- `search_capability`：被诊断决策实际引用的有效 `search_code` Evidence；不调用搜索不导致 Outcome 失败；
- `causal_review`：四字段人工核查；
- `accepted`：上述强制项全部满足时才为 `true`。

## 7. 审计 Run 产物

```bash
.venv/bin/python -m json.tool .coderca-runs/<run-id>/report.json
sed -n '1,240p' .coderca-runs/<run-id>/events.jsonl
find .coderca-runs/<run-id> -maxdepth 2 -type f -print
```

重点检查 `model-requests/`、`model-responses/`、`tool-results/`、`patches/` 和 `validation/`。完整原始结果用于审计，不会被全部重放到模型 Context；Run 可能含源码与日志，不应直接公开。

## 8. 已知边界

- 三个冻结任务是工程回归，不支持统计显著性或跨仓库泛化声明；
- 因果机制仍需人工核查，不使用 LLM Judge；
- 模型可能产生 Schema Failure、错误 Hypothesis、耗尽预算或失败补丁；这些失败应保留在报告中；
- Task 3 虽已实现，若实际发布周期只完成 Task 1/2，Evaluation 输出必须只列实际运行任务，并明确交付范围；
- 默认 `pytest` 使用 FakeModelProvider，不访问网络、不读取 API Key、不要求 GPU 或 Docker。
