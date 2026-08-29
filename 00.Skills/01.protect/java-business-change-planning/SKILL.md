---
name: java-business-change-planning
description: 基于已冻结的宏观业务流程、明确需求和子流程证据，识别影响范围，编排子 agent 分析现有 Java 实现，并合并为可追溯的代码开发规划。用于跨流程业务改造的设计和改动点规划；不用于创建或改写宏观流程、直接修改代码或代替开发者批准方案。
---

# Java 业务变更开发规划

## 目标与边界

将一次业务需求映射到已冻结的宏观 `M` 节点，用子流程代码证据确定改动点，再统一设计 API/事件/数据/状态、事务、兼容性、测试和发布顺序。

- 默认为只读设计阶段；未获得单独的实现授权时不修改业务代码。
- 已冻结宏观流程是输入基线，本 Skill 不静默改写其节点、交接或版本。
- 发现宏观流程错误时输出 `macro revision request` 并停止相关规划，返回 `java-business-flow-synthesis` 修订和重新冻结。

## 启动与影响门禁

正式规划需要：

1. `status=frozen` 的 `macro-flow.contract.json` 及其版本。
2. 开发者变更 brief：目标、可验收结果、非目标和约束。
3. 相关子流程报告及代码基线。

缺少冻结契约时不用草稿冒充，也不启动开发规划；返回 `java-business-flow-synthesis` 先完成评审与冻结。

委派前主 agent 先给出候选影响矩阵：受影响 `M` 节点、子流程、共享契约、理由和未知。开发者确认范围后才创建子 agent；不得从沉默推断批准。

## 工作流

1. **锁定基线**：运行宏观契约审计，记录 `macro_flow_id + version + status`、仓库 commit 和子流程报告基线。
2. **映射影响**：从验收结果向前映射直接节点，再沿交接、共享数据/事件和失败路径扩展间接影响；区分 `direct / contract / data / operational / unknown`。
3. **开发者确认**：确认纳入/排除的 `M` 节点、共享契约所有者和关键技术约束；决策落入 decision reference。
4. **分配工作包**：按互不重叠的子流程或共享契约划分 `W1`、`W2`。同一 `path + symbol` 或契约只设一个主所有者，其他工作包依赖该输出。
5. **复核现状**：逐项回查来源报告，确认引用的 `N` 节点真实存在。报告与当前 commit 一致且覆盖变更点时可复用；否则子 agent 必须使用 `java-code-flow-analysis` 对分配入口/场景重新追踪。
6. **局部设计**：每个工作包输出现状证据、目标行为、文件/符号改动、契约与数据变化、事务/幂等/异常、日志、测试、风险和未决项；不修改代码。
7. **全局合并**：主 agent 裁决 API/事件/状态/数据冲突，检查事务边界、兼容性、迁移、发布顺序、回滚和端到端测试。
8. **评审**：输出草案供开发者批准。只有 blocking decision 和未解决冲突为零、影响范围已确认时才可标 `approved`。

## 子 Agent 契约与经济性

子 agent 只获得已确认的宏观切片、子流程报告、代码基线、变更 brief、共享契约草案和停止边界。子 agent 不改写 `M` 流程、不分配全局工作包、不扩展到其他子流程。

单一或高度耦合的改动保持单 agent。只在子流程边界清晰且并行收益高于重复阅读、沟通和合并成本时委派。

## 输出

生成文件前完整读取 [references/output-standard.md](references/output-standard.md)。输出 `change-plan.md` 和 `change-plan.contract.json`；对可批准方案运行 `python3 scripts/change_plan_audit.py <plan.json> <macro-contract.json> --require-approved`。
