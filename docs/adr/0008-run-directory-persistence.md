# ADR-0008：两周 MVP 按 Diagnosis Run 目录保存记录

- 状态：Accepted
- 日期：2026-08-06
- 取代：ADR-0005

## 背景

单机 CLI 原型只有三个冻结任务，不需要长期查询、并发 Worker、去重或中断恢复。SQLite 与内容寻址 Artifact 会引入事务、迁移和双写一致性，却不增强 Agent 核心招聘信号。

## 决策

每次 Diagnosis Run 使用独立目录保存 Task Manifest 快照、JSONL 事件、JSON 报告、模型响应、工具输出、补丁和 Validation 结果。大文本使用普通文件引用，不实现数据库、内容寻址、跨运行去重或崩溃恢复。

## 后果

运行产物仍可审计并支持工程 Evaluation，但不提供跨运行查询和服务级恢复语义。未来引入服务化需求时再设计数据库迁移，而不是让文件布局冒充稳定存储 API。
