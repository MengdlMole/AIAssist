# 输出规范与模板

## 共同规则

先建立事实账本，再生成 Markdown 和 Flow Pack。两份文件共用 ID、动作语义、证据状态和 reference；不要分别重新分析。一个事实只详细定义一次，其他位置用 ID 引用。

正式输出文件：

```text
<flow>.md
<flow>.flow.jsonl
<flow>.evidence.md   # 仅按需
```

## 开发者文档模板

没有事实的小节可以省略；“未发现关键日志/数据库操作”等影响理解的负面结论用一句话说明，不保留空表。

````markdown
# <流程名称>

> 入口：`<触发方式和代码入口>`<br>
> 场景：`<本次成立条件>`<br>
> 终点：`<分析停止处>`<br>
> 基线：`<commit/branch；工作区状态>`<br>
> 覆盖：`<主流程 / 关键路径已覆盖 / 阶段性骨架 / 深度分析>`

## 1. 范围与结论

- 范围内：`<模块、分支、异步结果>`
- 范围外/边界：`<未追踪内容和原因>`
- 核心结论：`<2–5条，写业务结果、关键分支和主要副作用>`

## 2. 流程概述

<用1–3个自然段说明触发者、输入、主要阶段、正常结果、提前结束条件和异步后续。使用业务语言，不逐节点翻译类名。>

## 3. 树形调用链

```text
N1 [HTTP] Controller#create — 接收创建请求；请求参数 → 创建命令 {代码已证实}
└─ N1.1 [TX][R:R1] Service#create — 校验并创建业务对象；有效命令 → 持久化结果 {代码已证实}
   ├─ [当 <条件>]
   │  └─ N1.1.1 [DB:D1] Repository#insert — 新增主记录；实体 → 已持久化ID {代码已证实}
   └~ N1.1.2 [MQ:M1][LOG:L1] Publisher#send — 发布创建事件；业务结果 → Topic消息 {代码已证实}
      └~ N1.1.2.1 [ASYNC][DB:D2] Listener#consume — 消费事件并更新下游状态；消息 → 最终副作用 {配置绑定已证实}
```

规则：

- `└─/├─` 表示同步调用，`└~/├~` 表示异步或消息因果边，`↩` 表示回边。
- 节点动作包含业务对象、关键条件/输入和结果/影响；标签只索引下文事实。
- 方法内逻辑用紧邻节点的 `↳ R1 ...` 或在“关键规则”说明，不伪造 `N`。
- 完整 reference 放在事实或证据处，不把路径塞满整棵树。

## 4. 分阶段说明

### S1 <业务阶段>（N1～N1.1）

<3–6句说明进入条件、关键输入及来源、处理和选择、数据/状态变化、退出结果与下一阶段。不要重复调用树的方法清单。>

### S2 <业务阶段>（N1.1.1～N1.1.2.1）

<同上。异步阶段说明事务/线程切换，以及上游成功与下游完成的区别。>

## 5. 关键分支与业务规则

### R1 <业务化名称> @ N1.1

- 目的：`<为什么需要这段逻辑>`
- 条件/输入：`<字段、来源、配置或时间>`
- 规则：`<可核对的公式、顺序、映射或优先级>`
- 结果：`<输出值、集合、状态或两侧路径>`
- 边界：`<时区、精度、开闭区间、空值、fallback>`
- 影响：`<如何改变范围、状态、副作用或失败结果>`
- 代码：`<reference；证据状态>`

复杂分支在“结果”中分别写命中与未命中路径；简单规则可以压成一行。不要为每个 if 建卡片，只保留改变业务结果的决策。

## 6. 关键数据流与数据操作

### <关键数据名>

`<source.field> → <command.field> → <entity/事件字段> → <最终表字段/外部接口/响应>`

说明：`<转换、默认、筛选、重命名、用途及最终去向；无法确认时引用U-ID>`

### D1 <操作名称> @ N1.1.1

- 目标：`<逻辑数据源；库/schema；表/缓存/索引/文件>`
- 操作：`<SELECT/INSERT/...>`；条件：`<WHERE、范围、锁、批量或发生条件>`
- 关键字段：`<来源 → 目标字段；只列业务关键字段>`
- 事务/结果：`<事务归属、业务影响和失败行为>`
- 代码：`<SQL/映射 reference；callsite；证据状态>`

消息或外部出口使用同样的紧凑卡片：

### M1 <交接名称> @ N1.1.2

- 目标：`<服务/接口/Topic/路由>`；载荷：`<类型和关键字段>`
- 条件与时点：`<何时发送，事务前/后>`
- 下游：`<消费者/响应/当前可确认边界>`
- 失败行为：`<异常、重试、fallback、ack>`
- 代码：`<reference；证据状态>`

## 7. 关键日志

### L1 @ N1.1.2

- 内容：`<源码稳定模板；变量含义>`
- 位置：`<path:line · symbol>`
- 打印条件/时点：`<代码分支和运行条件；after-return等>`
- 诊断含义：`<能证明什么>`；不能证明：`<commit/消费完成等>`
- 关联字段：`<traceId/业务主键/无>`；来源/级别：`<code/aspect；INFO等>`

## 8. 关键配置与边界

### C1 `<完整配置key>` @ N1.1 / R1

`<值格式和业务含义>`；默认值：`<证实值/未知>`；当前值：`<开发者提供/待开发者确认>`；作用：`<如何改变路径、范围或结果>`；代码：`<reference>`。

简要说明事务、线程、RPC、异步、重试或降级边界；没有显著边界可省略。

## 9. 未知项

- U1 `<未知内容>`：原因 `<缺失证据>`；影响 `<哪些结论不能确认>`；验证 `<配置、仓库、trace或测试>`。

## 10. 证据索引

- `<实际读取并支撑核心结论的代码、配置、SQL或测试文件>`

<!-- 只有确有必要时增加业务时序图；图中方法分隔符 # 必须写为 #35; -->
````

## 文字说明质量

- 概述讲“整个故事”，阶段说明讲“这一阶段为何、如何、产生什么”，事实卡讲“精确定义与证据”。三者不可逐句重复。
- 使用业务名词和明确动词，如“筛选待结算订单”“写入订单主记录”；避免“进行处理”“调用相关方法”。
- 分支必须同时说明两侧结果；异步必须区分“发送成功”和“消费完成”；数据库读写必须说明结果如何影响后续。
- 完整是语义完整，不是篇幅完整。省略机械映射和普通字段，但不能省略关键参数含义、数据终点、失败结果或未知边界。

## Flow Pack 规范

UTF-8 JSONL，一行一个合法 JSON 对象；`type` 使用完整英文单词。第一行为 `flow`，后续建议按 `stage → node/edge → decision/rule → sink/lineage → log/config/unknown` 排列。字段无事实时省略，不写空模板。

```jsonl
{"type":"flow","id":"order-create","name":"订单创建","intent":"校验并创建订单后触发库存处理","trigger":"POST /orders","entry":"N1","end":["D2"],"baseline":"<commit>","scope":{"scenario":"普通订单且库存充足","included":"创建订单到库存处理结果","excluded":"支付和履约"},"coverage":"key-paths-covered","frontier_count":0,"unresolved_count":1}
{"type":"stage","id":"S1","name":"校验并创建订单","nodes":["N1","N1.1","N1.1.1"],"input":"创建请求","action":"校验后写入订单","output":"orderId","next":"S2"}
{"type":"node","id":"N1.1","parent":"N1","kind":"service","symbol":"OrderService#create","action":"校验并创建订单；有效命令 → 已持久化订单","references":["R1","D1"],"code":"src/.../OrderService.java:68 · com.acme.OrderService#create(CreateOrderCommand)","evidence":"代码已证实"}
{"type":"edge","from":"N1","to":"N1.1","kind":"sync","when":"请求解析成功","callsite":"src/.../OrderController.java:42"}
{"type":"decision","id":"R1","at":"N1.1","question":"订单是否允许创建","condition":"商品有效且金额一致","yes":"N1.1.1","no":"result:返回校验失败且不写库","effect":"决定是否进入事务"}
{"type":"rule","id":"R2","at":"N1.1","purpose":"计算数据时间窗口","inputs":{"offsetDays":7,"durationDays":30},"calculation":"start=now-7d; end=start+30d","boundary":"[start,end)","effect":"决定查询范围","code":"src/.../OrderService.java:75"}
{"type":"sink","id":"D1","at":"N1.1.1","kind":"database","datasource":"orderDataSource","database":"unknown-runtime","target":"orders","operation":"INSERT","key":"order_id","transaction":"T1","effect":"创建订单主记录","code":"src/.../OrderMapper.xml:21"}
{"type":"sink","id":"M1","at":"N1.1.2","kind":"message","target":"order.created","operation":"SEND","payload":"OrderCreatedEvent(orderId,items)","next":"N1.1.2.1","effect":"触发异步库存处理"}
{"type":"lineage","data":"orderId","path":["request.clientOrderNo","orders.order_id","OrderCreatedEvent.orderId","inventory_record.order_id"],"finalUse":"关联订单与库存处理结果"}
{"type":"log","id":"L1","at":"N1.1.2","message":"order event published, orderId={}","when":"producer调用正常返回","timing":"after-return","proves":"生产调用返回","doesNotProve":"库存消费完成","code":"src/.../OrderPublisher.java:54"}
{"type":"unknown","id":"U1","item":"生产环境物理数据库实例","impact":"只能确认逻辑数据源和表","verify":"检查ORDER_DB_URL"}
```

Flow Pack 中 `node.action` 与 Markdown 树中同节点的动作语义必须一致；阶段覆盖的节点应存在；`at/parent/from/to/next` 引用必须存在或使用 `result:/boundary:`；每个 Markdown 标签引用的 `R/D/M/L/C/U` 应在 Pack 中定义。

`coverage` 只使用 `main-path / key-paths-covered / static-scope-complete / partial`。`frontier_count>0` 时必须为 `partial`；非 `partial` 时 frontier 必须为 0。`unresolved_count` 与 `unknown` 记录数一致，未知仍可存在于已完成的静态范围分析中。

## 可选证据文档

仅在审计模式把完整节点/调用点清单、SQL 与字段映射、配置解析、事务传播、动态绑定候选、frontier、折叠理由和最小源码片段写入 `<flow>.evidence.md`。主文档仍保持可读，不把证据附件复制回正文。

## 自检

- 开发者只看概述、调用树和阶段说明，能否说出主路径、关键分支和主要副作用？
- 数据是否追踪到表、Topic、外部接口、响应或明确未知，而非停在 `save/send/async`？
- 关键逻辑是否解释输入、处理、输出、边界和业务影响？
- 日志是否说明打印条件和证明边界？
- 两份文件是否共用 ID，且无无效引用、重复定义或原始 Mermaid `#`？
