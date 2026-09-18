---
name: java-business-change-planning
description: 基于已冻结的宏观业务流程、明确需求和子流程 Flow Pack，识别影响范围并形成可追溯的 Java 开发规划；子流程可独立且并行有收益时再按工作包委派。用于跨流程业务改造的代码设计、改动点、数据契约、测试和发布规划；不用于创建宏观流程、直接修改代码或代替开发者批准方案。
---

# Java 业务变更开发规划

## 目标与边界

把业务需求映射到冻结宏观流程，在受影响子流程中定位现状证据和代码改动点，统一设计 API、事件、数据、状态、事务、兼容性、测试和发布顺序。

- 默认处于只读设计阶段；没有单独实现授权时不修改代码。
- 冻结宏观流程是输入基线，本 skill 不静默修改其阶段、交接或版本。
- 发现宏观流程错误时输出 `macro revision request`，停止受影响部分并返回 `java-business-flow-synthesis` 修订；不相关部分可以继续分析。

## 启动门禁

正式规划需要：

1. 已冻结且明确批准的 `macro-flow.contract.json`。
2. 开发者变更 brief：目标、可观察验收结果、非目标和约束。
3. 宏观契约引用的子流程 Flow Pack 及当前代码基线。

宏观流程未冻结时只能输出候选影响预览，不能创建正式工作包或批准方案。

## 按需加载

生成文件前完整读取 [references/output-standard.md](references/output-standard.md)。

按层加载 Flow Pack：

1. 影响扫描：`flow / stage / decision / sink / unknown`。
2. 范围确认后：仅对纳入流程读取 `node / edge / rule / lineage / config / transaction / retry`。
3. 只有涉及可观测性变更或排障要求时读取 `log`。

Flow Pack 与当前基线一致、相关切片足够且没有阻塞未知时使用 `reuse-flow-pack`；否则对分配的入口和场景使用 `java-code-flow-analysis` 局部刷新，不机械重做整个流程。

## 工作流

1. **锁定基线**：校验冻结宏观契约、来源 Flow Pack 和当前各流程代码基线。
2. **映射影响**：从验收结果反向定位直接宏观节点，再沿交接、共享状态、数据终点、事件和失败路径扩展 `direct / contract / data / operational / unknown` 影响。
3. **确认范围**：开发者确认整体纳入/排除边界及有争议、高风险项；无需逐条确认代码已明确的影响。决定记录在一个 scope decision 中。
4. **建立工作包**：按子流程或共享契约划分 `W`。同一 `path + symbol` 或契约只有一个主所有者；其他工作包声明依赖。
5. **复核现状**：引用 Flow Pack 的 `S/N/R/D/M/L/C/U` 事实。过期、缺失或覆盖不足时局部刷新。
6. **局部设计**：每个工作包说明当前行为、目标行为、差异、代码/配置/Schema 改动、数据和契约、事务/幂等/异常、测试、风险和未知。
7. **全局合并**：裁决 API、事件、状态和数据冲突，检查兼容性、迁移、发布顺序、回滚和端到端验收。
8. **评审批准**：阻塞决定与冲突为零、范围已确认、证据足够且共享契约已确认后，才能标记 `approved`。

## 工作包与协作

工作包结果使用：

- `change-required`：需要代码、配置或 Schema 改动；必须有改动点。
- `verification-only`：只需验证兼容性、配置、数据或运行行为；必须有验证动作和预期结果。
- `no-change`：证据表明无需修改；必须给出理由和证据。

单流程、小范围或高度耦合改动保持单分析者。只有子流程边界清晰、共享代码少且并行净收益为正时才委派；协作者只获得确认的宏观切片、Flow Pack 切片、基线、brief、共享契约草案和停止边界，不改写宏观流程或全局编号。

## 输出

默认生成：

- `change-plan.md`：面向开发者和实施者的可读规划。
- `change-plan.contract.json`：影响、工作包、契约、依赖和批准状态的机器契约。

不默认为每个工作包生成独立文件；只有跨团队交接或用户明确要求时拆分。

批准前从本 skill 目录运行：

`python3 scripts/change_plan_audit.py <plan.json> <macro-contract.json> --report <change-plan.md> --require-approved`
