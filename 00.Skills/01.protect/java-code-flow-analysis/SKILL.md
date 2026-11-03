---
name: java-code-flow-analysis
description: 从指定 Java 入口、场景和终点追踪真实调用关系、关键规则与数据去向，生成开发者可读流程和可复用 Flow Pack。用于代码走读、改造前现状分析和故障定位；不用于全仓库架构盘点、直接修改代码或仅凭日志推断源码流程。
---

# Java 代码流程梳理

## 目标

围绕一个明确的 `入口 + 场景 + 终点`，让开发者快速看懂代码如何完成业务，并让后续 AI 用较少上下文恢复同一流程。

分析可以深入，呈现保持克制：调用树负责导航，阶段叙述解释业务过程，事实卡精确定义关键规则和数据终点；同一事实只详细写一次。

## 输出模式

正式落盘默认生成两个同名文件：

- `<flow>.md`：开发者文档，自包含且可顺序阅读。
- `<flow>.flow.jsonl`：AI Flow Pack，保存可组合的结构化事实。

只有审计、事故复盘、高风险改造或用户要求完整证据时，才增加 `<flow>.evidence.md`。仅在对话中回答时不为凑格式创建文件。

分析深度与输出长度分开：`quick / standard（默认）/ deep` 决定调查强度；开发者文档仍优先简洁。

## 按需读取

- `standard / deep` 或存在多实现、AOP、动态分派时，完整读取 [references/core-tracing.md](references/core-tracing.md)；边界简单的 `quick` 直接使用本文件。
- 涉及数据库、缓存、RPC、MQ、异步、配置、事务、日志或复杂字段血缘时，完整读取 [references/data-and-boundaries.md](references/data-and-boundaries.md)。
- 生成正式文件时完整读取 [references/report-template.md](references/report-template.md)。
- 调用图明显超出单上下文、需要检查点或独立子图协作时，完整读取 [references/large-codebase-strategy.md](references/large-codebase-strategy.md)。

## 分析流程

1. **固定范围**：确定 `入口 + 场景 + 终点 + 关注点 + 代码基线`；只有多个解释会实质改变方向时才询问用户。
2. **建立骨架**：先枚举相关直接调用和兄弟分支，再按业务重要性深挖，避免沿单链过早钻到底。
3. **扫描语义**：同时检查方法内部会改变对象、范围、顺序、数值、状态、副作用或失败结果的逻辑，不把规则伪造成调用节点。
4. **闭合边界**：证明接口到实现及适用的数据、外部调用、异步、事务和异常边界；无法确定动态绑定时保留候选和未知。
5. **形成账本**：为阶段、节点、规则、终点和未知分配稳定 ID；正式 Flow Pack 的边使用 `from + to + kind + callsite` 标识，不分配跨产物 ID。从同一事实账本生成所有输出。
6. **反向验证**：从用户结果、异常、状态、SQL、消息或响应反向核对来源和控制条件，检查遗漏与证据边界。

## 不变量

- 默认只读；未获授权不改代码、不新增日志、不启动依赖真实外部系统的应用。
- 静态可达不等于运行时必经。调用、表、消费者、配置值和运行结果必须有代码、配置或运行证据，否则标为候选或未知。
- 只展开影响业务控制、数据、状态、副作用、异常、事务、线程或可观测性的内容；机械映射和无语义框架调用可折叠。
- 相关直接调用必须归类为 `expanded / folded / boundary / out-of-scope / unresolved`；递归和回边引用已有节点。
- 关键数据必须按 `来源 → 转换/筛选 → 传递边界 → 可确认终点` 闭环；`save/send/async` 不是天然终点。
- 证据状态只使用 `代码已证实 / 运行已证实 / 推断 / 未知`。完整 reference 使用 `相对路径:行号 · 全限定符号`，调用边优先引用 callsite。

## 输出契约

- Markdown 按“范围与结论 → 概述 → 调用树 → 阶段说明”组织，再按事实补充规则、数据、日志和未知；简单同步流程不增加时序图。
- Flow Pack 使用语义化 JSONL 记录 `flow / stage / node / edge / crosscut / decision / rule / sink / lineage / log / config / transaction / retry / unknown`。首条记录 baseline、scope、coverage、frontier 和 unresolved 计数。
- Markdown 与 Flow Pack 共用 ID、动作语义和证据状态；一个事实只定义一次。正式字段、模板和示例以 `report-template.md` 为准。

## 完成标准

交付前确认：

- 主路径从入口连续到用户终点；重要分支说明条件、两侧结果和业务影响。
- 每个展示方法已扫描内部关键逻辑；异步/MQ 仅在用户终点需要时继续追踪消费者结果。
- 关键数据已到达可确认终点，或以 `U` 说明边界、影响和验证方式。
- Markdown 可独立读懂业务；Flow Pack 可独立恢复阶段、节点关系、分支和数据终点。
- 正式输出从本 skill 目录运行：`python3 scripts/report_id_audit.py <flow>.md --flow-pack <flow>.flow.jsonl`。
- 深度档有图账本时再运行本 skill 的 `scripts/graph_audit.py`；存在未分类 frontier 时只能称“阶段性骨架”，不得称完整。
