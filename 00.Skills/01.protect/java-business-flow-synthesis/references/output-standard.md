# 宏观流程输出规范

## 共同规则

`macro-flow.md` 与 `macro-flow.contract.json` 共用 `M/H`、阶段名称、交接方向和证据状态。宏观正文不复制子流程调用树、SQL、日志或完整代码 reference；需要追溯时引用 `<flow_id>/<typed-id>`。

## 开发者文档

````markdown
# <宏观流程名称>

> ID/版本：`<macro_flow_id>@<version>`<br>
> 状态：`draft / developer-review / frozen / superseded`<br>
> 业务起点：`<自然语言>`；入口阶段：`<M...>`<br>
> 业务终点：`<自然语言>`；终点阶段：`<M...>`

## 1. 目标、范围与结论

- 目标：`<开发者目标>`
- 纳入：`<flow_id...>`；排除：`<范围外>`
- 结论：`<3–6条主干、关键状态、交接和风险>`

## 2. 流程概述

<用1–3段业务语言说明谁触发、经历哪些阶段、如何交接、最终结果以及主要异常终点。>

## 3. 分层宏观流程树

```text
M1 [端到端] 订单生命周期 — 从订单提交到履约完成 {both-confirmed}
├─ M1.1 [阶段] 创建订单 — 生成可支付订单 {code-confirmed}
├~ H1 [事件] order.created；orderId → 库存处理
├─ M1.2 [阶段] 处理库存 — 锁定商品库存 {both-confirmed}
└─ M1.3 [阶段] 完成履约 — 形成最终履约状态 {developer-confirmed}
```

`├─/└─` 表示层级，`├~/└~ H` 表示跨阶段交接。树中名称和结果必须与契约一致。

## 4. 分阶段说明

### M1.1 <阶段名称>

<3–6句说明进入条件、业务目的、关键处理、数据/状态结果、交接与失败出口。不要翻译 Java 方法。>

追溯：`<flow/S...>`；必要证据：`<flow/M...、flow/D...、flow/R...>`。

## 5. 关键交接

### H1 <交接名称>：M1.1 → M1.2

- 类型/条件：`<sync/event/manual/shared-state/...；发生条件>`
- 载荷或状态：`<最小业务信息>`；关联键：`<orderId等>`
- 结果/失败：`<下游获得什么；失败、重试或补偿>`
- 依据：`<typed refs；证据状态；开发者决定引用>`

## 6. 关键状态与不变量

- I1 `<必须始终成立的业务约束>`；适用阶段 `<M...>`；依据 `<flow/R...或开发者决定>`。

## 7. 未决项与冻结状态

- U1 `<问题>`；影响 `<主干/旁支>`；阻塞 `<是/否>`；验证 `<方式>`。
- 冻结：`<未批准/开发者明确批准及决定引用>`。

## 8. 追溯索引

- `M1.1 → order-create/S1, order-create/D1`
- `H1 → order-create/M1, inventory-handle/S1`
````

只有参与者顺序、人工步骤、补偿或异步时点明显比树更重要时才增加 Mermaid `sequenceDiagram`；其中字面 `#` 写为 `#35;`。不强制树和时序图重复同一信息。

## 契约最小结构

```json
{
  "schema_version": 2,
  "macro_flow_id": "order-lifecycle",
  "version": "1.0",
  "status": "developer-review",
  "developer_brief": {
    "goal": "完成订单从创建到履约的业务闭环",
    "start": "用户提交订单",
    "end": "履约完成或进入明确失败终点",
    "scope": "纳入创建、库存和履约流程",
    "included_flow_ids": ["order-create", "inventory-handle"],
    "anchor_relations": [
      {"from_flow": "order-create", "to_flow": "inventory-handle", "relation": "triggers", "decision_ref": "developer:D1"}
    ],
    "allow_relation_proposals": true,
    "decision_ref": "developer:brief-1"
  },
  "source_flows": [
    {
      "flow_id": "order-create",
      "flow_pack": "flows/order-create.flow.jsonl",
      "developer_doc": "flows/order-create.md",
      "baseline": "<commit>",
      "coverage": "key-paths-covered",
      "pack_digest": "sha256:<digest>"
    },
    {
      "flow_id": "inventory-handle",
      "flow_pack": "flows/inventory-handle.flow.jsonl",
      "developer_doc": "flows/inventory-handle.md",
      "baseline": "<commit>",
      "coverage": "key-paths-covered",
      "pack_digest": "sha256:<digest>"
    }
  ],
  "entry_phase": "M1.1",
  "end_phases": ["M1.2"],
  "phases": [
    {
      "id": "M1",
      "parent": null,
      "name": "订单生命周期",
      "entry": "用户提交订单",
      "action": "完成订单创建和履约",
      "outcome": "履约完成或明确失败",
      "flow_refs": ["order-create/S1", "inventory-handle/S1"],
      "evidence_status": "both-confirmed",
      "decision_ref": "developer:D1",
      "critical": true
    },
    {
      "id": "M1.1",
      "parent": "M1",
      "name": "创建订单",
      "entry": "创建请求有效",
      "action": "校验并持久化订单",
      "outcome": "生成订单编号",
      "flow_refs": ["order-create/S1", "order-create/D1"],
      "evidence_status": "code-confirmed",
      "decision_ref": "",
      "critical": true
    },
    {
      "id": "M1.2",
      "parent": "M1",
      "name": "处理库存",
      "entry": "收到订单创建事件",
      "action": "校验并锁定商品库存",
      "outcome": "库存处理结果已持久化",
      "flow_refs": ["inventory-handle/S1", "inventory-handle/D1"],
      "evidence_status": "both-confirmed",
      "decision_ref": "developer:D1",
      "critical": true
    }
  ],
  "handoffs": [
    {
      "id": "H1",
      "name": "触发库存处理",
      "from": "M1.1",
      "to": "M1.2",
      "type": "event",
      "condition": "订单事务完成",
      "payload_or_state": "orderId和商品明细",
      "correlation_keys": ["orderId"],
      "evidence_status": "both-confirmed",
      "evidence_refs": ["order-create/M1", "inventory-handle/S1"],
      "decision_ref": "developer:D1",
      "critical": true
    }
  ],
  "invariants": [],
  "unresolved": [],
  "decisions": [],
  "approval": {"status": "pending", "decision_ref": "", "approved_at": ""}
}
```

## 约束

- `status`：`draft / developer-review / frozen / superseded`。
- `relation`：`precedes / triggers / follows`。草稿可无锚点，但此时 `allow_relation_proposals=true`；冻结前主干关系必须在 `H` 中闭合。
- `flow_refs/evidence_refs` 使用 `<flow_id>/<S|N|R|D|M|L|C|U id>`，且必须存在于对应 Flow Pack。
- 来源 Flow Pack 的 `flow.id`、baseline 和 coverage 必须与 `source_flows` 一致；冻结契约必须记录并匹配 SHA-256。
- `entry_phase` 和所有 `end_phases` 必须是关键叶阶段。冻结时入口可达所有终点，每个关键叶阶段都位于入口到某个终点的有向路径。
- `code-confirmed/both-confirmed` 必须有 Flow Pack 引用；`developer-confirmed/both-confirmed` 必须有 `decision_ref`。
- 冻结时关键阶段/交接不得为 `inferred/unresolved`，不得保留 blocking unresolved，且 approval 必须记录明确批准。
- 普通决定保存在 `decisions`；只有用户要求独立评审历史时再输出 `decision-log.md`。

## 自检

- 开发者只看概述、树和阶段说明，能否复述端到端业务？
- 每个 `H` 是否说明触发、载荷/状态、关联键、结果和失败？
- 每个宏观结论能否回到 Flow Pack 或开发者决定？
- 是否把代码细节、日志表或完整子流程树误搬进宏观正文？
- Markdown 和契约中的 `M/H` 集合、名称、方向是否一致？
