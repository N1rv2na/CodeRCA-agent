# ADR-0009：两周 MVP 只连接一个外部本地模型服务

- 状态：Superseded by ADR-0011
- 日期：2026-08-06
- 取代：ADR-0006

## 背景

项目没有云端 API 预算，开发机只有 RTX 4060 Ti 8 GB。让 CodeRCA 同时负责模型加载、多后端兼容或云端兜底，会把模型部署问题放入 Agent 核心关键路径。

## 决策

CodeRCA 只实现一个固定 HTTP ModelProvider，连接用户预先启动的外部本地推理服务。诊断模型独占 GPU；embedding 在索引阶段预计算，reranker 在 CPU 运行。自动化测试使用 FakeModelProvider，不实现云端、多真实后端或回放兜底。

## 后果

真实运行依赖本地模型质量和服务可用性，因此必须在开发早期用最小探针验证阶段 Schema、工具参数、Evidence 更新和补丁输出。MVP 接受没有现场降级路径的风险。
