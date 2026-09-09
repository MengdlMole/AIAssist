# 大型 Java 项目的上下文与多 Agent 策略

## 核心判断

纯 BFS 可以帮助发现同层兄弟分支，但会在工具方法、框架调用和多实现处迅速膨胀；纯 DFS 上下文成本低，却容易过早沉入一个分支并遗漏兄弟路径。默认采用受约束的混合策略：

`范围固定 -> 浅层 BFS 骨架 -> 优先级驱动的子图深挖 -> 返回/异常反向验证 -> 全局完整性审计`

这里的“完整”始终相对于用户场景、仓库源码和显式停止边界。反射、运行时配置或仓库外实现无法证明时，完整性意味着已经准确记录未知，而不是猜出唯一调用链。

## 经济性原则

大型项目协议本身有成本：账本维护、任务上下文复制、子 agent 启动、重复读共享代码以及结果合并。只有其降低的遗漏风险或节省的串行阅读时间大于这些协调成本时才使用。

- 先由主 agent 完成入口定位和浅层骨架，不在尚不清楚子图边界时预先并发。
- 使用满足目标所需的最少 agent。增加 agent 不是完整性的证明；证据闭环才是。
- 子图只有在边界清晰、与其他子图共享代码少、需要读取多处实现且可以独立产出节点/边增量时才适合委派。
- 直接调用链较短、关键逻辑集中在少数文件、多个候选任务高度重叠，或核心问题是一个运行时绑定时，保持单 agent 通常更经济准确。
- 优先并行同层兄弟子图；每波先合并、验证实际收益，再决定是否启动下一波。不要一次性填满所有并发槽位。
- 子 agent 输入只包含其根节点、祖先条件、必要账本切片和返回契约，不复制全仓库说明或全部历史分析。
- 中间账本保存符号、边、状态、路径和简短摘要，不保存可随时从源码重读的大段代码。
- 成本压力不能改变用户范围；只能调整优先级或分阶段交付。不要把尚未分析但处于范围内的节点标为 `out-of-scope`。

可用一个简单判断：

`协作净收益 = 避免的串行深读与上下文压力 - 启动、重复阅读、沟通、合并与冲突成本`

净收益不明显时不委派。无法准确估算时，先单 agent 展开一个高优先级节点，再根据实际扇出和证据量决定是否升级。

## 委派前横切预检

主 agent 在划分业务子图前，用最小读取确认以下内容，并把结论列入共享节点清单：

- 入口映射、参数绑定与 Bean Validation。
- Security filter/interceptor、URL 授权配置和身份上下文来源。
- Controller advice、统一异常映射和入口日志切面。
- 事务注解可能出现的接口、实现、父类及事务启用配置。
- 缓存、重试、异步等会改变调用语义的 AOP 注解或 pointcut。
- MQ listener/container 或 scheduler 注册配置。

只摘要真正覆盖目标入口的横切节点。子 agent 获得这些已证实事实后不得重复分析，除非发现直接冲突；这既避免漏链，也减少每个子图重复读取 Controller、事务和异常处理。

## 1. 建立可恢复的图账本

不要依赖对话上下文保存整个调用树。只有当前上下文无法可靠容纳图状态时，才在临时目录维护紧凑检查点；除最终 Markdown 外不要把中间产物写进目标仓库。推荐内容：

- `scope.md`：入口、场景条件、终点、范围内/外、停止边界和版本基线。
- `nodes.md` 或 `nodes.jsonl`：规范符号键、角色、状态、摘要和证据。
- `edges.md` 或 `edges.jsonl`：调用点、条件、边类型、置信度和证据。
- `frontier.md`：待展开节点、优先级与原因。
- `findings/`：各子图的结构化返回结果。

规范符号键优先使用：

`<module>:<fully-qualified-class>#<method>(<parameter-types>)`

重载方法必须包含参数类型。节点去重使用规范符号键；同一方法从不同条件到达时共享节点，但每个调用点、路径条件和调用上下文仍是独立边。循环调用只记录回边，不重复展开。

### 节点最小字段

| 字段 | 含义 |
| --- | --- |
| key | 规范符号键 |
| file/symbol | 文件、行号、类与方法 |
| role | 入口、编排、校验、DB、RPC、消息等 |
| state | discovered、claimed、expanded、partial、folded、boundary、out-of-scope、unresolved |
| summary | 一句话说明与用户场景的关系 |
| evidence | 代码已证实、运行已证实、推断、未知 |
| evidence_basis | 项目源码、配置绑定、生成契约、框架契约、运行证据，可多选 |
| direct_calls_complete | 是否已完整枚举该方法在当前场景下的相关直接调用与出口 |
| context | 已知参数事实、事务、线程和到达该节点的场景条件 |

### 边最小字段

| 字段 | 含义 |
| --- | --- |
| edge_id | 具体调用点的稳定标识；不能只按调用者/被调者去重 |
| from/to | 调用者与被调者规范键；无法解析时 `to` 为候选集合或外部边界 |
| callsite | 调用文件与行号 |
| condition | 分支条件、配置条件或异常条件 |
| type | sync、async、event、mq、rpc、db、aop、callback、return、exception |
| confidence | certain、configured、inferred、unknown |
| evidence_summary | 一句话记录绑定依据、关键参数事实或异常传播；未知时说明所缺证据 |
| evidence_basis | project-source、configuration-binding、generated-contract、framework-contract、runtime-evidence，可多选 |

进入 Mapper/Repository 或数据库边界且会执行 SQL 的调用边使用 `type=db`；每项 `database_operations.edge_id` 必须精确引用该边，完成态下每条 `db` 边至少有一项操作，不能靠“同节点存在任意数据库操作”代替映射。

最终展示编号由主 agent 在图合并、折叠和树结构稳定后统一分配：根为 `N1`，直接子调用为 `N1.1`、`N1.2`，下一层按路径扩展。同一方法可共享规范节点，但每个 `<规范符号键>@<incoming edge_id>[context]` 调用身份分别编号；循环/递归使用 `↩ <已有编号>` 回指。横切共享节点若由框架拦截或分派而非普通直接调用，使用独立 `X` 编号，不伪装成 `N` 的子调用。子 agent 只返回规范符号键、edge_id、上下文和一句业务动作，不分配展示编号。

## 2. 第一阶段：受约束的浅层 BFS

目标是尽快回答“入口下面有哪些主要方向”，不是立刻理解每个实现细节。

1. 将入口加入 frontier。
2. 读取当前节点的方法签名、方法体、相关注解和必要绑定配置，只深入到足以枚举用户范围内的直接调用点、关键分支与边界。
3. 将直接调用分类并登记边：
   - 业务相关且尚未分析：`discovered`，进入下一层 frontier。
   - 无条件透传且不改变数据/控制/事务/线程/异常：`folded`，记录折叠理由。
   - 数据库、缓存、中间件、仓库外服务或第三方框架：`boundary`。
   - 明确与用户场景无关：`out-of-scope`。
   - 动态绑定无法确认：`unresolved`，记录候选和所缺证据。
4. 当前层每个相关调用点都完成分类后，才推进下一层。
5. 通常扫描到能够识别主要业务子图和边界即可停止统一 BFS；不要把所有叶子都按相同深度机械展开。之后仍以同一 frontier 循环“局部一跳全量发现 -> 关键子图深挖”，而不是永久切换成单链 DFS。

“当前层完整”不等于列出方法体内所有 Java/JDK 调用，但也不只检查调用表达式。每个方法还必须完成一次语义扫描：分支、校验/规范化、筛选/排序/聚合/计算、结果组装、状态写入和异常转换都已提取为节点、决策或 `business_rules`。每个可能改变本场景业务控制、数据、状态、副作用、异常、事务、线程或可观测性的调用点都有分类。

## 3. 第二阶段：给 frontier 排优先级

优先展开满足以下条件的节点：

- 直接决定用户问题或期望终点。
- 高扇出、包含关键分支、策略选择或状态机。
- 写数据库、修改缓存、调用外部系统、发送消息或切换线程。
- 建立事务、锁、重试、降级、补偿或异常映射。
- 存在接口多实现、AOP、动态路由等高不确定性。
- 位于关键数据从请求到返回/写入之间的转换断点。

简单 DTO 映射、无条件 facade 和已证明的机械透传可以后置或折叠。优先级用于调度顺序，不得把未展开节点悄悄删除；低优先级节点最终也必须有 `folded`、`out-of-scope` 或其他明确状态。

## 4. 第三阶段：按子图委派，而不是按单个方法委派

通过经济性门禁且协作能力可用时，将具有清晰所有权和停止边界的子图交给子 agent，例如“库存校验子图”“支付 RPC 子图”“订单持久化与事务子图”“事件发布到消费子图”。不要为每个方法创建一个任务，否则协调成本和重复阅读会超过收益。

避免同时把祖先节点和其内部后代节点交给不同 agent；优先选择同一层、互不重叠的兄弟子图并行。每一波结果合并后再决定下一波，防止基于过期 frontier 继续派工。

### 子 agent 任务契约

每个任务必须提供：

- 用户意图和场景条件。
- 子图根节点的规范符号键、文件与已知调用点。
- 已知输入、调用前置条件和期望停止边界。
- 允许读取的模块/目录及明确范围外内容。
- 当前节点/边账本快照、已知祖先路径、运行时绑定和避免重复的 claimed 节点。
- 主 agent 已完成的共享横切节点与禁止重复展开的符号清单。
- 合理的深度或上下文预算；预算只决定何时返回 partial，不改变完成标准。
- 必须覆盖成功、关键分支、异常、返回/数据流、数据库表操作、日志和动态绑定。
- 对每个展开方法分别确认直接调用和方法内语义扫描完成；从业务汇点反向提取关键决策的条件值来源，以及影响对象集合、范围、顺序、数值、状态或副作用的关键逻辑，不为内联逻辑虚构节点。
- 必须汇总能改变子图可达性、实现选择、处理范围、计算口径或结果的配置；当前值只接受开发者输入。
- 只读约束与证据状态定义。
- 下面的统一返回格式。

### 子 agent 返回格式

深度档使用机器可校验 JSON 增量，避免 Markdown 表格枚举漂移和人工合并错误。只返回被分配子图的增量，不重复祖先、共享横切节点或其他子图。字段摘要保持一句话；不复制源码，不附带未请求的代码审计报告。

```json
{
  "root_key": "<canonical key>",
  "coverage": "expanded | partial | blocked",
  "nodes": [
    {
      "key": "<canonical key>",
      "state": "discovered | claimed | expanded | partial | folded | boundary | out-of-scope | unresolved",
      "direct_calls_complete": true,
      "semantic_scan_complete": true,
      "fold_reason": "<required only when state=folded>",
      "evidence": "code-confirmed | runtime-confirmed | inferred | unknown",
      "evidence_basis": ["project-source"],
      "file_symbol": "<path:line / symbol>",
      "role": "<entry/orchestration/validation/db/rpc/message/...>",
      "context": "<condition, transaction and thread facts>",
      "summary": "<one sentence>"
    }
  ],
  "edges": [
    {
      "edge_id": "<callsite-stable id>",
      "from": "<canonical key>",
      "to": "<canonical key or boundary:... or unresolved:...>",
      "type": "sync | async | event | mq | rpc | db | aop | callback | return | exception",
      "confidence": "certain | configured | inferred | unknown",
      "resolution_status": "resolved | boundary | excluded | unresolved",
      "callsite": "<path:line>",
      "condition": "<condition>",
      "evidence_summary": "<binding, argument or exception fact>",
      "channel": "<required for async/event/mq: topic/queue/event/executor>",
      "payload": "<required for async/event/mq: message/event/task payload>",
      "binding_reference": "<required for async/event/mq: producer-consumer binding evidence>",
      "failure_semantics": "<required for async/event/mq: ack/retry/dead-letter/callback or unknown>",
      "evidence_basis": ["project-source"]
    }
  ],
  "decision_points": [
    {
      "decision_id": "<callsite-stable id>",
      "node_key": "<canonical key containing the decision>",
      "business_question": "<what is being decided>",
      "condition": "<code condition>",
      "operand_refs": ["<field/config/rule/db/edge/node>:<existing id>"],
      "evaluation_order": "<order/precedence>",
      "matched_target": "<edge/node/result/boundary>:<existing id or explicit result>",
      "unmatched_target": "<edge/node/result/boundary>:<existing id or explicit result>",
      "business_effect": "<effect on result/state/side effect>",
      "reference": "<path:line>",
      "evidence": "code-confirmed | runtime-confirmed | inferred | unknown",
      "evidence_basis": ["project-source"]
    }
  ],
  "key_fields": [
    {
      "field_key": "<source + field stable id>",
      "name": "<field/parameter>",
      "source": "<request/config/DB/derived>",
      "business_meaning": "<meaning>",
      "node_keys": ["<canonical key>"],
      "flow_effect": "<effect on branch/range/state/result>",
      "transform_rule": "<parse/default/null/unit/mapping>",
      "destination": "<query/state/message/response>",
      "reference": "<path:line>",
      "evidence": "code-confirmed | runtime-confirmed | inferred | unknown",
      "evidence_basis": ["project-source"]
    }
  ],
  "business_rules": [
    {
      "rule_key": "<reference-stable id; final R id assigned by main agent>",
      "node_keys": ["<canonical key>"],
      "name": "<business logic name>",
      "business_meaning": "<business-language purpose>",
      "applicability": "<when/under which condition it applies>",
      "input_refs": ["<field/config/rule/db/edge/node>:<existing id>"],
      "calculation": "<formula/mapping/algorithm>",
      "output": "<value/set/state produced>",
      "boundary_semantics": "<unit/timezone/precision/inclusive-exclusive>",
      "business_effect": "<effect on scope/result/state/side effect>",
      "reference": "<path:line>",
      "evidence": "code-confirmed | runtime-confirmed | inferred | unknown",
      "evidence_basis": ["project-source"]
    }
  ],
  "database_operations": [
    {
      "operation_id": "<stable SQL/callsite + table id>",
      "edge_id": "<matching db edge id>",
      "node_key": "<canonical key of the direct DB operation>",
      "table": "<schema.table or unresolved:expression>",
      "operation": "SELECT | SELECT_LOCK | INSERT | UPDATE | DELETE | UPSERT | MERGE | CALL",
      "business_purpose": "<one sentence>",
      "condition": "<branch and WHERE/join condition>",
      "key_fields": ["<primary/business/status field>"],
      "transaction_context": "<transaction or none/unknown>",
      "result_effect": "<how rows/result affect the flow>",
      "sql_reference": "<XML/annotation/DSL reference or unavailable>",
      "mapping_reference": "<Mapper/Repository declaration and callsite>",
      "core": true,
      "core_reason": "<state change, branch/output, lock/idempotency, or auxiliary reason>",
      "evidence": "code-confirmed | runtime-confirmed | inferred | unknown",
      "evidence_basis": ["project-source"]
    }
  ],
  "key_logs": [
    {
      "log_id": "<path:line>",
      "node_key": "<canonical key>",
      "source_type": "code | aspect | filter | interceptor | wrapper",
      "event_type": "arrival | decision | handoff | external-result | state-change | failure",
      "timing": "before | after-return | after-commit | on-exception | finally",
      "exception_mechanism": "<catch | advice | listener-error-callback | retry-hook; only for on-exception>",
      "relative_to": "<call, transaction or handler>",
      "level": "<TRACE/DEBUG/INFO/WARN/ERROR>",
      "stable_template": "<source template with semantic placeholders>",
      "condition": "<code branch and runtime logging condition>",
      "correlation_fields": ["<traceId/business key/...>"],
      "proves": "<what this event proves>",
      "does_not_prove": "<nearest likely overclaim>",
      "evidence": "code-confirmed | runtime-confirmed | inferred | unknown",
      "evidence_basis": ["project-source"],
      "sensitive_risk": "<none or concise risk>"
    }
  ],
  "configurations": [
    {
      "name": "<full configuration key>",
      "description": "<business meaning>",
      "effect": "<how it changes reachability, implementation or result>",
      "default_value": "<evidenced value or unknown>",
      "current_value": "<developer-input-required or developer-provided value>",
      "current_value_source": "developer-input-required | developer-provided",
      "affected_node_keys": ["<canonical key>"],
      "affected_rule_keys": ["<stable rule_key; empty when not applicable>"],
      "declaration_reference": "<path:line or unavailable>",
      "read_reference": "<path:line>",
      "evidence": "code-confirmed | runtime-confirmed | inferred | unknown",
      "evidence_basis": ["project-source"]
    }
  ],
  "data_flows": [],
  "unresolved": [],
  "frontier": []
}
```

`evidence_basis` 至少选择一个合法值：`project-source / configuration-binding / generated-contract / framework-contract / runtime-evidence`。`exception_mechanism` 仅在 `timing=on-exception` 时必填，其他时点省略。

`expanded` 节点必须同时满足 `direct_calls_complete=true` 和 `semantic_scan_complete=true`；前者证明直接调用已分类，后者证明方法体内影响业务语义的非调用逻辑也已检查。`folded` 节点必须给出 `fold_reason`，且理由只能是已读实现后确认的机械透传，不能是层级深、方法私有或上下文不足。

`async/event/mq` 边必须填写 `channel/payload/binding_reference/failure_semantics`，其他边省略这四项。生产者到消费者只有在 destination/routing 与 listener 绑定能够对应时才使用 `resolved`；否则停在 `boundary/unresolved`。消费者入口是新的执行上下文，但在最终调用树中以 `~~异步~~>` 因果子节点继续编号，其内部普通调用继续使用同步子节点。

`decision_points` 只记录改变结果、状态、副作用、实现或异常出口的判断。来源引用只用 `field/config/rule/db/edge/node:<已存在ID>`；`edge:` 目标必须是从决策节点发出的边，`node:` 目标必须是沿已解析边可达的后继节点；无后续调用时写 `result/boundary:<明确结果>`，禁止自由字符串。`key_fields` 不收录机械透传字段。`business_rules` 名称仅为兼容内部协议，语义覆盖所有关键业务逻辑而非仅配置规则；子 agent 从 decision、DB 条件/写入、外部载荷和 response 等汇点反向切片，使用稳定 `rule_key`，主 agent 合并后才编号为 `R1...`。`input_refs` 使用同一来源引用。业务步骤 `B1...` 由主 agent 基于全局图聚合，子 agent 不自行编号。

`database_operations` 对每个实际表逐项记录；JOIN/子查询多表拆项，软删除使用 `UPDATE`。`edge_id` 必须指向实际 `db` 边；同一节点、同类操作、同一表发生多次时仍以不同 `operation_id/edge_id` 保留。无法解析动态表名时以 `unresolved:` 开头并同步加入 `unresolved`。主 agent 将 `operation_id` 映射为 `D1...`、将 `node_key` 转成最终 `N`，并在时序图和调用树的直接节点附 `[DB <D-ID> <OP> <table>]`，不向祖先传播。

`configurations` 只收录改变流程、处理范围、口径或结果的配置。`current_value_source=developer-input-required` 时，`current_value` 必须固定为同名占位；不得把源码默认值、仓库配置或环境变量表达式当作当前运行值。配置影响关键逻辑时以 `affected_rule_keys` 关联；主 agent 合并后将 node/rule key 转成最终 `N/R` 编号。

子 agent 不分配最终 `N` 编号、不修改最终文档、不新增枚举值、不把推断改写成事实。若发现代码缺陷，只在它改变本子图控制/数据语义时用一句事实描述，不继续扩展审计。若发现范围外的新子图，只登记到 frontier，不自行无限追踪。默认保持单层委派；只有协调者明确给出命名空间和合并协议时才继续递归委派。上下文或时间预算耗尽时必须返回 `partial`、已覆盖调用点、未完成 frontier 和下一步，不得返回 `expanded`。

主 agent 将 JSON 增量保存到临时目录并使用 [scripts/graph_audit.py](../scripts/graph_audit.py) 合并校验。单根可自动识别入口；多片段/多根必须传 `--entry-root '<入口规范键>'`。静态范围分析使用 `--require-analyzed`；只有要求调用图完全闭合时使用 `--require-closed`。脚本会检查入口可达性和 `db edge ↔ database_operations` 映射；主 agent 仍须复核源码证据、动态绑定及 Mermaid participant 的语义方向。

## 5. 主 agent 合并协议

每一波完成后，主 agent：

1. 以规范符号键合并节点，以 edge_id/调用点合并边；允许同一节点从 `discovered -> claimed -> partial -> 终态` 被更完整片段替换，终态或代码符号冲突必须回读源码裁决。
2. 检查子图根节点能否从入口已有边连续到达，终点是否正确接回全局图。
3. 领取任务前将节点原子地标为 claimed；合并后将新发现节点加入 frontier，并更新 expanded、partial、boundary、unresolved 等状态，避免不同 agent 重复领取。
4. 对重复读取的共享节点保留证据更强、范围更完整的结果，不拼接矛盾摘要。
5. 合并决策、关键字段和业务逻辑，裁决同一代码位置的适用条件、输入/输出或处理规则冲突；图稳定后再聚合 `B`、分配 `R` 并映射最终 `N`。
6. 重新计算下一波优先级；在账本合并前不派发依赖上一波结果的新任务。
7. 独立复核所有高影响负面结论，尤其是“无事务、无数据库表操作、无日志、无流程配置、无关键业务逻辑、无实际实现、无消费者、无异常处理”。缺少搜索范围和证据的负面结论一律降为 unknown。

上下文紧张时，主 agent只保留 scope、节点/边摘要、frontier 和未决冲突在当前上下文中；详细代码摘录留在检查点，需要裁决时再读取源文件，不复制所有子 agent 长篇说明。

## 6. 第四阶段：反向验证

自叶子或边界向入口反查一次，弥补只看向下调用的盲区：

- 返回对象是否逐层组装到最终响应。
- 异常是否被捕获、转换、吞掉或触发回滚/重试。
- 数据库结果、外部响应和消息载荷的关键字段是否连续传递。
- 异步生产者能否以 topic、event type、consumer group 或配置证据连接消费者。
- AOP、事务、缓存和安全拦截是否真正覆盖目标方法。

发现断链时把节点重新放入 frontier，不要用合理猜测补齐。

## 7. 完整性审计与停止条件

达到“静态范围分析完成”必须满足：

- frontier 与 partial 为空；所有发现节点均为 expanded、folded、boundary、out-of-scope 或 unresolved。
- 每个 expanded 方法内的相关调用点都有对应边或明确分类。
- 每个关键条件分支、异常出口和返回路径均有去向。
- 每个关键决策都有条件值来源和两侧结果；关键逻辑均说明适用条件、输入、处理、输出、边界、业务影响和证据。
- 每条可达数据库边已解析到表、操作、事务与 SQL/映射证据，或显式记为 unresolved。
- 接口多实现、配置路由、反射与 AOP 已解析，或作为 unresolved 列出候选、影响和验证方式。
- 所有改变流程走向的配置已汇总并关联节点；缺少当前值时已覆盖候选路径并标明实际选择未知。
- 异步/MQ 边已连接到消费者，或明确停在无法证明的边界。
- 循环、递归和重入以回边表达，不造成无限展开。
- 控制流与数据/返回流能够互相解释，关键日志已映射到稳定节点。
- 每个折叠、范围外和边界决定都有理由，不存在“因为上下文不够所以省略”的隐式缺口。

只有 unresolved 节点、边和清单也全部为零，才能升级为“调用图已闭合”并声称“声明范围内调用链已完整解析”。外部边界不算 unresolved，但必须有明确停止理由。

达到上下文、时间或可用 agent 限制但 frontier 未清空时，只能交付“阶段性骨架”，并量化剩余 frontier、最高风险未展开节点及继续分析方式；不能把它称为完整调用链。
