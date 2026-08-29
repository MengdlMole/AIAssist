# 宏观流程输出规范

## `macro-flow.md`

保留以下章节，无内容的非必需章节删除：

1. **文档信息**：`macro_flow_id`、版本、状态、目标、起点/终点、来源报告及基线。
2. **开发者启动输入**：原意摘要、范围、已知锚点关系和决策引用。
3. **结论**：3–6 条主干、关键状态、交接与未决风险。
4. **分层宏观树**：文本树，格式 `M1.1 [阶段] 名称 — 业务结果 {确认状态}`。
5. **宏观时序图**：Mermaid `sequenceDiagram`，只显示业务参与者、`M` 阶段、`H` 交接和业务结果；不显示 Java 方法。
6. **交接表**：`H / from / to / type / payload or state / correlation key / evidence / source`。
7. **状态与不变量**：聚合、前状态、触发、后状态、失败结果；不变量标证据。
8. **追溯索引**：`M node -> flow_id/N node -> report`，代码细节只在原报告中展开。
9. **未决项与决策**：区分 blocking/non-blocking，附责任人或验证方式。
10. **冻结记录**：只有开发者明确批准时填 `frozen`、决定引用和时间；不伪造审批人。

树与时序图的 `M` 节点集合和业务语义必须一致。Mermaid 中如需显示字面 `#`，写为 `#35;`。

## `macro-flow.contract.json`

最小结构：

```json
{
  "schema_version": 1,
  "macro_flow_id": "order-lifecycle",
  "version": "1.0",
  "status": "draft",
  "developer_brief": {
    "goal": "<business goal>",
    "start": "<business start>",
    "end": "<business end>",
    "scope": "<included/excluded scope>",
    "included_flow_ids": ["order-create", "order-pay"],
    "anchor_relations": [
      {"from_flow": "order-create", "to_flow": "order-pay", "relation": "precedes", "decision_ref": "decision-log:D1"}
    ],
    "decision_ref": "<conversation or decision-log reference>"
  },
  "source_flows": [
    {"flow_id": "order-create", "report": "<path>", "baseline": "<commit/version>", "node_ids": ["N1", "N1.2"]},
    {"flow_id": "order-pay", "report": "<path>", "baseline": "<commit/version>", "node_ids": ["N1"]}
  ],
  "phases": [
    {
      "id": "M1",
      "parent": null,
      "name": "Order lifecycle",
      "entry": "<condition>",
      "exit": "<outcome>",
      "flow_refs": ["order-create/N1", "order-pay/N1"],
      "evidence_status": "both-confirmed",
      "decision_ref": "decision-log:D1",
      "critical": true
    },
    {"id": "M1.1", "parent": "M1", "name": "Create order", "entry": "<condition>", "exit": "<outcome>", "flow_refs": ["order-create/N1"], "evidence_status": "code-confirmed", "decision_ref": "", "critical": true},
    {"id": "M1.2", "parent": "M1", "name": "Pay order", "entry": "<condition>", "exit": "<outcome>", "flow_refs": ["order-pay/N1"], "evidence_status": "code-confirmed", "decision_ref": "", "critical": true}
  ],
  "handoffs": [
    {
      "id": "H1",
      "from": "M1.1",
      "to": "M1.2",
      "type": "event",
      "correlation_keys": ["orderId"],
      "evidence_status": "both-confirmed",
      "evidence_refs": ["order-create/N1.2", "order-pay/N1"],
      "decision_ref": "decision-log:D1",
      "critical": true
    }
  ],
  "unresolved": [],
  "approval": {"status": "pending", "decision_ref": "", "approved_at": ""}
}
```

`status` 只用 `draft / developer-review / frozen / superseded`。锚点 `relation` 只用 `precedes / triggers / follows`，冻结时必须存在同方向 `H` 路径。`critical` 表示达到 brief.end 或决定声明结果/状态所必需；每个 phase 和 handoff 都必须显式给出。冻结时仍为 `inferred/unresolved` 的非关键项必须提供 `noncritical_reason`。`approval` 只记录已发生的明确决定。

phase 与 handoff 使用相同证据状态。`source_flows.node_ids` 必须从来源报告逐项提取；所有 `<flow_id>/N<level>` 引用都必须命中该清单。`code-confirmed/both-confirmed` phase 必须有代码引用；`developer-confirmed/both-confirmed` phase 必须有 `decision_ref`。冻结时关键 phase 不得为 `inferred/unresolved`。

## `decision-log.md`

每条仅记录 `D id / context / decision / rationale / source / status`。保留开发者原意的可核对摘要，不伪造姓名或批准。
