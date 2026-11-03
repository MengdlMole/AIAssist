# 开发规划输出规范

## 开发者文档

`change-plan.md` 与机器契约共用 `A/W` 编号、范围、工作包结果和依赖。正文解释设计，不复制 Flow Pack 或协作者原始返回。

````markdown
# <变更名称>开发规划

> Plan：`<plan_id>@<version>`；状态：`impact-review / design-draft / developer-review / approved / superseded`<br>
> 宏观基线：`<macro_flow_id>@<version>`<br>
> 代码基线：`<flow_id=commit...>`

## 1. 目标、范围与验收结果

- 目标：`<业务目标>`
- 验收：`<可观察结果>`
- 非目标/约束：`<明确排除和技术约束>`
- 范围决定：`<纳入/排除摘要及开发者决定引用>`

## 2. 影响摘要

- A1 `M1.2 / order-pay / direct`：`<原因>`；依据 `<flow/S或R/D/M>`。
- A2 `M1.3 / inventory-handle / contract`：`<原因>`；依据 `<typed refs>`。

只列对设计有用的影响，不把每个间接调用都升级为影响项。

## 3. 目标行为变化

<用1–3段说明现状、目标和用户可见差异。若需要修改宏观阶段或交接，在此明确 revision request，而不是偷偷改 M/H。>

## 4. 工作包

### W1 <名称> — change-required

- 范围：`<A...；M...；flow_id>`
- 分析证据：`<reuse/refresh；Flow Pack路径@baseline；digest；typed refs>`
- 当前行为：`<基于 Flow Pack 的现状和证据>`
- 目标行为：`<可观察结果>`
- 差异与改动点：
  - `modify <path> · <fqcn#method(types)>`：`<简洁变化>`；依据 `<flow/N...、flow/R...>`
- 数据/契约：`<表、字段、事件、API、状态、兼容和迁移>`
- 一致性：`<事务、幂等、并发、异常和重试>`
- 测试/可观测性：`<测试与预期；必要日志/指标变化>`
- 依赖/风险：`<W...；风险和缓解>`

`verification-only` 写验证动作、环境和预期；`no-change` 写无需修改的证据与理由，不虚构改动点。

## 5. 跨流程契约与数据变化

按 API、事件、数据、状态或配置列出唯一所有者、生产者、消费者、变化、兼容和迁移。不涉及则简要说明。

## 6. 实施、迁移与发布顺序

`<W依赖顺序 → 兼容窗口 → 数据迁移 → 发布步骤 → 回滚条件>`

## 7. 验证

把单元、集成、契约、端到端、数据核对和可观测性验收映射到 change brief 的验收条件。

## 8. 风险、未决项与批准状态

- `<冲突、风险、阻塞决定、所有者和解决方式>`
- 批准：`<未批准/开发者明确批准及决定引用>`
````

## 机器契约

```json
{
  "schema_version": 2,
  "plan_id": "partial-refund",
  "version": "1.0",
  "status": "developer-review",
  "macro_ref": {
    "macro_flow_id": "order-lifecycle",
    "version": "1.0",
    "status": "frozen",
    "contract_digest": "sha256:<digest>"
  },
  "repository_baselines": {
    "order-pay": "<commit>",
    "refund-notify": "<commit>"
  },
  "refreshed_flows": [],
  "change_brief": {
    "goal": "支持部分退款",
    "acceptance_criteria": ["退款金额小于订单金额时订单保持部分退款状态"],
    "non_goals": ["不改变支付渠道退款协议"],
    "constraints": ["兼容已有全额退款"],
    "decision_ref": "developer:change-1"
  },
  "impact_scope": [
    {
      "id": "A1",
      "macro_node_id": "M1.2",
      "flow_id": "order-pay",
      "impact_type": "direct",
      "reason": "退款计算和状态写入发生变化",
      "evidence_refs": ["order-pay/R2", "order-pay/D1"],
      "status": "confirmed"
    }
  ],
  "scope_decision": {
    "confirmed": true,
    "included_impact_ids": ["A1"],
    "excluded_impact_ids": [],
    "decision_ref": "developer:scope-1"
  },
  "work_packages": [
    {
      "id": "W1",
      "name": "调整退款计算和状态",
      "flow_id": "order-pay",
      "macro_node_ids": ["M1.2"],
      "impact_ids": ["A1"],
      "objective": "支持部分退款并保持全额退款兼容",
      "outcome": "change-required",
      "analysis_mode": "reuse-flow-pack",
      "evidence_coverage": "sufficient",
      "evidence_refs": ["order-pay/N1.2", "order-pay/R2"],
      "current_behavior": "仅支持全额退款并写入REFUNDED",
      "target_behavior": "根据累计退款金额写入PARTIAL_REFUNDED或REFUNDED",
      "change_points": [
        {
          "kind": "modify",
          "path": "src/main/java/.../RefundService.java",
          "symbol": "a.b.RefundService#apply(RefundCommand)",
          "change": "计算累计退款额并选择目标状态",
          "evidence_refs": ["order-pay/N1.2", "order-pay/R2"]
        }
      ],
      "dependencies": [],
      "verification": ["部分退款后状态为PARTIAL_REFUNDED"],
      "risks": [],
      "no_change_reason": ""
    }
  ],
  "cross_flow_contracts": [],
  "implementation_order": ["W1"],
  "conflicts": [],
  "blocking_open_decisions": [],
  "approval": {"status": "pending", "decision_ref": "", "approved_at": ""}
}
```

## 约束

- `status`：`impact-review / design-draft / developer-review / approved / superseded`。
- `impact_type`：`direct / contract / data / operational / unknown`；`status`：`confirmed / inferred / unknown`。
- 开发者通过一个 `scope_decision` 确认整体纳入/排除边界；不要求每条代码已证实影响单独审批。正式工作包只能覆盖 included impacts。
- `analysis_mode`：`reuse-flow-pack / refresh-with-java-code-flow-analysis`。复用要求当前 baseline 与宏观来源一致、相关证据覆盖 `sufficient` 且无阻塞未知。
- 使用 refresh 时，顶层 `refreshed_flows` 必须为对应 `flow_id` 提供唯一的 `flow_pack / baseline / pack_digest`；路径相对 `change-plan.contract.json` 解析。其 header 的 `id/baseline`、文件 SHA-256 和 `repository_baselines` 必须一致；声明 `sufficient` 时不得保留开放 frontier。没有 refresh 工作包时省略该字段或使用空数组。
- `impact_scope.evidence_refs` 仍引用冻结宏观契约的来源 Flow Pack，用于证明影响范围；refresh 工作包的 `evidence_refs` 以及其 `change_points.evidence_refs` 必须引用刷新后的 Flow Pack，用于证明当前实现和改动点。不得用旧事实冒充刷新结果。
- `evidence_refs` 支持 `<flow_id>/<S|N|R|D|M|L|C|U id>`。新增代码可没有现有 `N`，但应引用驱动新增的阶段、规则或契约事实；确无现有事实时说明来自验收条件。
- `change_points.kind`：`add / modify / remove / config / schema`。现有代码使用 `path + symbol`；新增必须写 `"proposed": true`，不伪造行号；没有现有 Flow Pack 证据时用 `requirement_ref` 指向验收条件。
- 工作包 outcome：`change-required` 必须有 change points；`verification-only` 必须有验证项；`no-change` 必须有 `no_change_reason`、证据和验证项。
- 同一 `path + symbol` 只有一个工作包拥有；依赖不可成环。`implementation_order` 必须包含每个工作包一次并尊重依赖。
- 跨流程契约记录 `api/event/data/state/config`、唯一 owner、生产者、消费者、变化、兼容、迁移和状态。批准时全部为 `confirmed`。
- 批准时所有 included impacts 被工作包覆盖，evidence coverage 为 `sufficient`，阻塞决定为空，冲突已解决，宏观契约 digest 未变化。

## 自检

- 每个改动点是否说明当前、目标、差异和证据，而非只列文件？
- 数据最终去向、状态、事件/API 和迁移是否与相关 `D/M/R` 对齐？
- 是否为本来无需改动的流程虚构 change point？
- 测试是否对应验收结果和关键风险？
- Markdown 与契约的 `A/W`、outcome 和依赖是否一致？
