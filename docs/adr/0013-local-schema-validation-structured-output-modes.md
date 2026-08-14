# ADR-0013：本地 Schema 校验与显式结构化输出模式

- 状态：Accepted
- 日期：2026-08-14
- 取代：ADR-0012

## 背景

ADR-0012 正确地把 Agent Core 与具体云端供应商隔离，但把 OpenAI `response_format.type=json_schema` 与 `strict=true` 规定为所有真实模型的最低能力。实际兼容性检查表明，MiniMax-M3 可以返回普通 Chat Completions 和 JSON，却不可靠执行原生 strict JSON Schema；ModelScope 上的 GLM-5.2 可以完成普通非流式请求，但加入该 `response_format` 后可能返回空 `choices`。因此，Provider 原生能力不能代表 CodeRCA 真正需要维护的系统不变量。

CodeRCA 真正依赖的是：每次结构化模型交互都必须先在本地完成确定性 JSON 解析和 Pydantic 校验，只有成功后的对象才能进入 Agent State。Provider 原生 strict JSON Schema 能提高可靠性，但不是所有 OpenAI-compatible Endpoint 的通用能力。

## 决策

Model Configuration 必须通过 `CODERCA_MODEL_STRUCTURED_OUTPUT_MODE` 显式选择一种 Structured Output Mode，不根据 Endpoint、Model ID 或供应商品牌推断。仅支持：

- `native_json_schema`：请求包含 `response_format.type=json_schema`、阶段 JSON Schema 和 `strict=true`。
- `json_text`：请求不包含 `response_format`，Prompt 明确要求只返回满足阶段 JSON Schema 的原始 JSON 值。

两种模式共享同一响应边界：读取 `message.content`，直接执行 `json.loads`，再用对应阶段的 Pydantic Contract 校验。解析或校验成功前，模型输出不得进入 Agent State。CodeRCA 不剥离 Markdown fence 或 `<think>` 标签，不提取 JSON 子串，不猜测字段，也不模糊修复非法结构。

Model Configuration 可以通过可选的 `CODERCA_MODEL_REQUEST_EXTENSIONS` 显式提供一个 JSON object，作为 Endpoint invocation configuration 在 HTTP 边界附加到请求。缺失或空值等同于 `{}`；非法 JSON 或非 object 值属于 `configuration_error`。Request Extensions 不得包含 `model`、`messages`、`stream`、`temperature` 或 `response_format`，Provider 必须先构造受控标准 payload，再合并已经校验的扩展。Generic Provider 不根据 Endpoint、Model ID 或供应商品牌生成这些配置。

CRCA-003 对非法 JSON 或 Schema mismatch 立即返回现有结构化失败，不增加 retry framework。未来 Diagnosis Run 是否保留一次明确纠错机会由状态机决策单独约束，不改变 Provider 的确定性边界。

Generic Provider 不根据品牌关闭 reasoning，也不后处理 reasoning 内容。受控 Request Extensions 只是一个显式且受保护键约束的 HTTP seam，不是任意 Provider plugin 或自动探测机制；如果操作者没有提供 Endpoint 所需配置，且 Endpoint 无法让 `message.content` 只包含 JSON，当前 Model Configuration 将不能通过 `json_text` 门禁。

Model Compatibility Gate 在配置的 Structured Output Mode 下运行相同的一次 preflight 和四个能力探针。Model Compatibility Report Schema 升级为版本 `2`，记录 `structured_output_mode`、通用请求配置、探针结果、失败分类和脱敏原始响应引用，但报告与响应 Artifact 均不得持久化 Request Extension 字符串值。Gate 仍然 fail-fast，不授权或阻止 Diagnosis Run，也不自动切换模式。

API Key、Authorization Header 和其他 secret 不得进入 Prompt、报告、响应 Artifact、Diagnosis Run 产物、日志、Git、Tool 参数或 Docker。

## 备选方案

- 继续强制原生 strict JSON Schema：请求合同最强，但排除能够稳定输出 JSON 并通过本地校验的 Endpoint。
- 自动探测或按 Provider 名称选择模式：减少配置，但把供应商品牌知识和不稳定启发式引入 Agent Core。
- 接受任意未校验的 `extra_body`：最灵活，但允许覆盖核心请求字段，也扩大凭证泄漏和不可复现配置的风险。
- 对非法输出做 fence/thinking 清理或 JSON 修复：提高表面成功率，但破坏确定性失败语义，并可能让错误模型输出进入 Agent State。
- 立即增加一次自动 retry：可能改善 `json_text` 成功率，但扩大 CRCA-003 范围并增加调用预算与测试矩阵。

## 后果

- 正面：更多 OpenAI-compatible Endpoint 可以在不修改 Agent Core 的情况下参与兼容性检查。
- 正面：本地 JSON 解析与 Pydantic 校验成为所有结构化模型交互的单一不变量。
- 正面：模式是显式可复现配置，不依赖供应商品牌或自动探测。
- 正面：少量 Endpoint 专属 invocation 参数可以在不污染 Agent/Gate abstraction 的情况下显式附加。
- 负面：`json_text` 的结构化可靠性通常低于 Provider 原生 strict JSON Schema。
- 负面：Request Extensions 的可移植性由操作者负责，且报告不会保存其值。
- 负面：会在 `message.content` 中输出 reasoning 标签或自然语言包装的模型将明确失败。
- 中性：若后续实验表明一次 bounded retry 必要，需要新的范围与调用预算决策。
