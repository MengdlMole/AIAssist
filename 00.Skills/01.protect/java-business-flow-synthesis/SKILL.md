---
name: java-business-flow-synthesis
description: 将多个已完成的业务代码流程在开发者输入和评审下串联为分层、可追溯、版本化的宏观业务流程并生成冻结契约。用于跨入口、跨模块或跨系统的流程汇总；不用于单入口代码追踪、未经确认猜测业务关系或生成代码开发方案。
---

# Java 宏观业务流程提炼

## 目标与边界

以多份子流程报告为代码现状证据，在开发者确认的业务目标与边界内，提炼稳定的宏观阶段、跨流程交接、状态变化和业务不变量。

- 默认只读；不修改业务代码，不生成代码改造方案。
- 代码调用关系不自动等于业务顺序；共享主键也不能单独证明流程已连接。
- 宏观流程只保留业务阶段和必要边界；方法、Mapper、详细日志留在子流程报告中。

## 启动门禁

正式串联前必须有开发者输入，至少包含：`business goal + start + end + included sources + one known anchor relation or permission to propose candidates`。自然语言即可，由 agent 规范化为 synthesis brief。

输入不足时状态为 `waiting-for-developer-input`：只盘点报告、列候选连接并提出聚焦问题；不分配宏观编号，不输出可冻结流程。不得从开发者沉默推断批准。

## 证据与编号

- 交接证据只使用 `code-confirmed / developer-confirmed / both-confirmed / inferred / unresolved`。
- 开发者意图与代码现状冲突时并列记录，不互相覆盖。
- 宏观节点用层级 `M` 编号：`M1` 为端到端根，`M1.1` 为业务阶段，`M1.1.1` 为可独立分析的子流程；默认不超过三层。
- 从 brief.start 到 brief.end 必需，或决定声明业务结果/状态的 phase 和 handoff 必须标 `critical=true`，不得因证据不足主动降级。
- 跨节点交接用 `H1`、`H2`；子流程代码引用必须带命名空间，如 `order-create/N1.2`。
- 先稳定层级树和交接，再统一分配展示编号；子 agent 不分配全局 `M/H` 编号。

## 工作流

1. **盘点**：记录开发者 brief、子流程 `flow_id`、报告路径、代码基线和分析范围；不得隐藏基线不一致。
2. **归一**：从每个报告提取触发、前置条件、结果、状态变化、同步/异步交接、关联键和失败结果；缺失项标未知。
3. **提候选链**：仅依据显式调用、API、事件/MQ 绑定、状态转换或开发者输入连接；每条边附证据状态。
4. **开发者裁决**：在形成主干前确认顺序、业务语义、异常终点、重试/补偿和关键状态；决定落入 decision log。
5. **提炼**：输出同一组 `M` 节点的层级树和宏观业务时序图，再补交接、状态、不变量和追溯表。
6. **评审与冻结**：开发者显式批准后才设为 `frozen`。冻结前所有关键交接必须已确认，多个关键叶阶段必须由 `H` 形成同一交接网络，blocking unresolved 为零，并运行 `python3 scripts/macro_flow_audit.py <contract.json> --require-frozen`。

冻结不是永久不变；修订时创建新版本，旧版本标为 `superseded`，不静默覆写。

## 产物与经济性

需要生成文件时，完整读取 [references/output-standard.md](references/output-standard.md)，输出 `macro-flow.md`、`macro-flow.contract.json` 和精简 `decision-log.md`。宏观正文不复制子流程树和代码 reference，只在追溯表链接。

报告较多时，只可将互不重叠的“单报告契约提取”交给子 agent；主 agent 保留 brief、交接裁决、全局编号和冻结权。
