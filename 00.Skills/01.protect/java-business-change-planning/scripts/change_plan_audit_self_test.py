#!/usr/bin/env python3
"""Regression tests for refreshed Flow Pack evidence binding."""

from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path

from change_plan_audit import audit, digest


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_pack(path: Path, baseline: str, rule_id: str) -> None:
    records = [
        {
            "type": "flow",
            "id": "order-pay",
            "name": "订单支付",
            "intent": "处理支付结果",
            "trigger": "pay",
            "entry": "N1",
            "end": ["N1"],
            "baseline": baseline,
            "scope": {"scenario": "支付成功", "included": "支付处理", "excluded": "履约"},
            "coverage": "key-paths-covered",
            "frontier_count": 0,
            "unresolved_count": 0,
        },
        {"type": "stage", "id": "S1", "name": "处理支付", "nodes": ["N1"]},
        {"type": "node", "id": "N1", "parent": None, "symbol": "PayService#apply", "action": "处理支付结果"},
        {"type": "rule", "id": rule_id, "at": "N1", "purpose": "选择订单状态"},
    ]
    path.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in records) + "\n", encoding="utf-8")


def expect_error(errors: list[str], fragment: str) -> None:
    if not any(fragment in error for error in errors):
        raise AssertionError(f"expected error containing {fragment!r}, got: {errors}")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="change-plan-audit-") as temp_dir:
        temp = Path(temp_dir)
        old_pack = temp / "order-pay.old.flow.jsonl"
        new_pack = temp / "order-pay.new.flow.jsonl"
        macro_path = temp / "macro-flow.contract.json"
        plan_path = temp / "change-plan.contract.json"
        write_pack(old_pack, "commit-old", "R1")
        write_pack(new_pack, "commit-new", "R2")

        macro = {
            "schema_version": 2,
            "macro_flow_id": "order-lifecycle",
            "version": "1.0",
            "status": "frozen",
            "source_flows": [{
                "flow_id": "order-pay",
                "flow_pack": old_pack.name,
                "baseline": "commit-old",
                "pack_digest": digest(old_pack),
            }],
            "phases": [{"id": "M1.1", "flow_refs": ["order-pay/S1"]}],
            "unresolved": [],
            "approval": {"status": "approved", "decision_ref": "developer:macro", "approved_at": "2026-01-01T00:00:00Z"},
        }
        write_json(macro_path, macro)

        plan = {
            "schema_version": 2,
            "plan_id": "refresh-order-pay",
            "version": "1.0",
            "status": "approved",
            "macro_ref": {
                "macro_flow_id": "order-lifecycle",
                "version": "1.0",
                "status": "frozen",
                "contract_digest": digest(macro_path),
            },
            "repository_baselines": {"order-pay": "commit-new"},
            "refreshed_flows": [{
                "flow_id": "order-pay",
                "flow_pack": new_pack.name,
                "baseline": "commit-new",
                "pack_digest": digest(new_pack),
            }],
            "change_brief": {
                "goal": "调整支付状态",
                "acceptance_criteria": ["支付成功后写入目标状态"],
                "non_goals": [],
                "constraints": [],
                "decision_ref": "developer:change",
            },
            "impact_scope": [{
                "id": "A1",
                "macro_node_id": "M1.1",
                "flow_id": "order-pay",
                "impact_type": "direct",
                "reason": "支付状态规则变化",
                "evidence_refs": ["order-pay/R1"],
                "status": "confirmed",
            }],
            "scope_decision": {
                "confirmed": True,
                "included_impact_ids": ["A1"],
                "excluded_impact_ids": [],
                "decision_ref": "developer:scope",
            },
            "work_packages": [{
                "id": "W1",
                "name": "调整支付状态",
                "flow_id": "order-pay",
                "macro_node_ids": ["M1.1"],
                "impact_ids": ["A1"],
                "objective": "按新规则选择状态",
                "outcome": "change-required",
                "analysis_mode": "refresh-with-java-code-flow-analysis",
                "evidence_coverage": "sufficient",
                "evidence_refs": ["order-pay/R2"],
                "current_behavior": "刷新分析确认当前状态规则",
                "target_behavior": "使用目标状态规则",
                "change_points": [{
                    "kind": "modify",
                    "path": "src/PayService.java",
                    "symbol": "PayService#apply",
                    "change": "调整状态选择",
                    "evidence_refs": ["order-pay/R2"],
                }],
                "dependencies": [],
                "verification": ["支付成功后状态正确"],
                "risks": [],
                "no_change_reason": "",
            }],
            "cross_flow_contracts": [],
            "implementation_order": ["W1"],
            "conflicts": [],
            "blocking_open_decisions": [],
            "approval": {"status": "approved", "decision_ref": "developer:plan", "approved_at": "2026-01-01T00:00:00Z"},
        }
        write_json(plan_path, plan)

        errors = audit(plan, plan_path, macro, macro_path, True)
        if errors:
            raise AssertionError(f"valid refreshed plan failed: {errors}")

        stale_evidence = copy.deepcopy(plan)
        stale_evidence["work_packages"][0]["evidence_refs"] = ["order-pay/R1"]
        stale_evidence["work_packages"][0]["change_points"][0]["evidence_refs"] = ["order-pay/R1"]
        errors = audit(stale_evidence, plan_path, macro, macro_path, True)
        expect_error(errors, "invalid refreshed evidence")
        expect_error(errors, "invalid change evidence")

        wrong_digest = copy.deepcopy(plan)
        wrong_digest["refreshed_flows"][0]["pack_digest"] = digest(old_pack)
        errors = audit(wrong_digest, plan_path, macro, macro_path, True)
        expect_error(errors, "Flow Pack digest changed")

        missing_refresh = copy.deepcopy(plan)
        missing_refresh["refreshed_flows"] = []
        errors = audit(missing_refresh, plan_path, macro, macro_path, True)
        expect_error(errors, "requires a refreshed_flows entry")

    print("OK: refreshed Flow Pack evidence binding rejects stale, missing, and digest-mismatched evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
