# 开发规划输出规范

## `change-plan.md`

1. **基线与状态**：规划 ID/版本/状态，冻结宏观流程 ID/版本，仓库 commit，子流程报告基线。
2. **变更 brief**：目标、验收条件、非目标、技术/业务约束和决定引用。
3. **影响矩阵**：`M node / flow_id / direct|contract|data|operational|unknown / reason / evidence / developer decision`。
4. **目标流程**：只画变更后必要的宏观切片，节点仍引用冻结 `M`；需要改宏观节点时输出 revision request。
5. **工作包**：每个 `W` 写范围、当前证据、目标行为、文件/符号改动、依赖、契约/数据、事务/幂等/异常、日志、测试和风险。
6. **跨流程契约**：API、事件、数据表/状态、兼容策略、迁移/发布顺序、主所有者和消费者。
7. **实施顺序**：依赖图、分阶段交付、数据迁移、兼容窗口和回滚条件。
8. **验证**：单元、集成、契约、端到端和可观测性验收点，对应验收条件。
9. **冲突、风险与未决项**：记录影响、所有者、解决方式和 blocking 状态。
10. **批准记录**：只记录开发者已明确批准的方案；未批准时保持 `developer-review`。

代码改动点使用 `<repo-relative-path>:<line when stable> · <fqcn#method(types)>`。“新增”节点没有现有行号，必须标 `proposed`，不伪造 reference。

## 子 Agent 返回字段

每个工作包使用同一结构，摘要保持一句话：

```json
{
  "work_package_id": "W1",
  "coverage": "complete",
  "current_evidence": ["flow-id/N1.2"],
  "target_behavior": "<observable behavior>",
  "change_points": [
    {
      "kind": "modify",
      "path": "src/main/java/.../Service.java",
      "symbol": "a.b.Service#method(Type)",
      "change": "<concise delta>",
      "evidence_refs": ["flow-id/N1.2"]
    }
  ],
  "contracts": [],
  "consistency": "<transaction/idempotency/error handling>",
  "observability": "<existing and proposed logs/metrics>",
  "tests": ["<test and expected result>"],
  "risks": [],
  "blocking_open_decisions": []
}
```

`coverage=partial` 时必须列出剩余分析边界，不得标记工作包已完成。

## `change-plan.contract.json`

```json
{
  "schema_version": 1,
  "plan_id": "partial-refund",
  "version": "1.0",
  "status": "developer-review",
  "repository_baseline": "<commit>",
  "macro_ref": {
    "macro_flow_id": "order-lifecycle",
    "version": "1.0",
    "status": "frozen"
  },
  "change_brief": {
    "goal": "<goal>",
    "acceptance_criteria": ["<observable result>"],
    "non_goals": ["<excluded result>"],
    "constraints": ["<constraint>"],
    "decision_ref": "<developer input reference>"
  },
  "impact_scope": [
    {
      "macro_node_id": "M1.2.1",
      "flow_id": "order-pay",
      "impact_type": "direct",
      "reason": "<reason>",
      "developer_confirmed": true,
      "decision_ref": "decision-log:D2"
    }
  ],
  "work_packages": [
    {
      "id": "W1",
      "flow_id": "order-pay",
      "macro_node_ids": ["M1.2.1"],
      "objective": "<objective>",
      "report_baseline": "<commit>",
      "evidence_coverage": "complete",
      "analysis_mode": "reuse-report",
      "change_points": [],
      "dependencies": [],
      "tests": ["<test>"],
      "risks": []
    }
  ],
  "cross_flow_contracts": [],
  "conflicts": [],
  "blocking_open_decisions": [],
  "approval": {"status": "pending", "decision_ref": "", "approved_at": ""}
}
```

`status` 只用 `impact-review / design-draft / developer-review / approved / superseded`；`analysis_mode` 只用 `reuse-report / refresh-with-java-code-flow-analysis`；`evidence_coverage` 只用 `complete / partial / stale / unknown`；`change_points.kind` 只用 `add / modify / remove / config / schema`。`reuse-report` 必须满足 `report_baseline == repository_baseline` 且 coverage 为 `complete`。除 `add` 外，改动点必须引用本工作包的 `<flow_id>/N...` 现有证据，且 `N` 必须存在于冻结宏观契约的来源节点清单。同一 `path + symbol` 不得由多个工作包拥有。

`cross_flow_contracts` 非空时，每项必须包含：`id`、`kind(api/event/data/state/config)`、`owner_work_package`、非空 `producers/consumers`、`change`、`compatibility`、`migration` 和 `status(draft/confirmed)`。已批准规划中所有跨流程契约必须为 `confirmed`。
