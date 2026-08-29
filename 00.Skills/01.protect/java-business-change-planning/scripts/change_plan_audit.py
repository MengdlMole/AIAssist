#!/usr/bin/env python3
"""Validate a Java business change-plan contract against a frozen macro flow."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


PLAN_STATUSES = {"impact-review", "design-draft", "developer-review", "approved", "superseded"}
IMPACT_TYPES = {"direct", "contract", "data", "operational", "unknown"}
ANALYSIS_MODES = {"reuse-report", "refresh-with-java-code-flow-analysis"}
EVIDENCE_COVERAGE = {"complete", "partial", "stale", "unknown"}
CHANGE_KINDS = {"add", "modify", "remove", "config", "schema"}
CONTRACT_KINDS = {"api", "event", "data", "state", "config"}
W_ID = re.compile(r"W[1-9]\d*$")
FLOW_REF = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]*)/(N\d+(?:\.\d+)*)$")


def nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def load(path: Path, label: str, errors: list[str]) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"cannot load {label} {path}: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{label} must be a JSON object")
        return {}
    return value


def has_cycle(dependencies: dict[str, list[str]]) -> bool:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        if any(visit(target) for target in dependencies.get(node, [])):
            return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in dependencies)


def audit(plan: dict, macro: dict, require_approved: bool) -> list[str]:
    errors: list[str] = []
    for field in (
        "schema_version",
        "plan_id",
        "version",
        "status",
        "repository_baseline",
        "macro_ref",
        "change_brief",
        "impact_scope",
        "work_packages",
        "cross_flow_contracts",
        "conflicts",
        "blocking_open_decisions",
        "approval",
    ):
        if field not in plan:
            errors.append(f"missing field: {field}")
    if plan.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    for field in ("plan_id", "version"):
        if not nonempty(plan.get(field)):
            errors.append(f"{field} must be non-empty")
    if not nonempty(plan.get("repository_baseline")):
        errors.append("repository_baseline must be non-empty")
    if plan.get("status") not in PLAN_STATUSES:
        errors.append(f"invalid status: {plan.get('status')!r}")

    macro_ids = {
        phase.get("id")
        for phase in macro.get("phases", [])
        if isinstance(phase, dict) and nonempty(phase.get("id"))
    }
    flow_ids = {
        flow.get("flow_id")
        for flow in macro.get("source_flows", [])
        if isinstance(flow, dict) and nonempty(flow.get("flow_id"))
    }
    source_nodes = {
        flow.get("flow_id"): {
            node for node in flow.get("node_ids", []) if isinstance(node, str)
        }
        for flow in macro.get("source_flows", [])
        if isinstance(flow, dict)
        and nonempty(flow.get("flow_id"))
        and isinstance(flow.get("node_ids"), list)
    }
    allowed_macro_flow_pairs = {
        (phase.get("id"), ref.split("/", 1)[0])
        for phase in macro.get("phases", [])
        if isinstance(phase, dict)
        for ref in phase.get("flow_refs", [])
        if isinstance(ref, str) and "/" in ref
    }
    macro_ref = plan.get("macro_ref")
    if not isinstance(macro_ref, dict):
        errors.append("macro_ref must be an object")
        macro_ref = {}
    if macro.get("status") != "frozen" or macro_ref.get("status") != "frozen":
        errors.append("macro flow and macro_ref must both be frozen")
    macro_approval = macro.get("approval")
    if (
        not isinstance(macro_approval, dict)
        or macro_approval.get("status") != "approved"
        or not nonempty(macro_approval.get("decision_ref"))
        or not nonempty(macro_approval.get("approved_at"))
    ):
        errors.append("macro contract lacks explicit developer approval")
    if any(
        isinstance(item, dict) and item.get("blocking") is True
        for item in macro.get("unresolved", [])
    ):
        errors.append("macro contract still has blocking unresolved items")
    if any(not isinstance(item, dict) for item in macro.get("unresolved", [])):
        errors.append("macro contract has malformed unresolved items")
    if any(
        isinstance(handoff, dict)
        and handoff.get("critical") is True
        and handoff.get("evidence_status") in {"inferred", "unresolved"}
        for handoff in macro.get("handoffs", [])
    ):
        errors.append("macro contract has an unconfirmed critical handoff")
    if any(
        isinstance(phase, dict)
        and phase.get("critical") is True
        and phase.get("evidence_status") in {"inferred", "unresolved"}
        for phase in macro.get("phases", [])
    ):
        errors.append("macro contract has an unconfirmed critical phase")
    for field in ("macro_flow_id", "version"):
        if macro_ref.get(field) != macro.get(field):
            errors.append(f"macro_ref.{field} does not match macro contract")

    brief = plan.get("change_brief")
    if not isinstance(brief, dict):
        errors.append("change_brief must be an object")
        brief = {}
    for field in ("goal", "decision_ref"):
        if not nonempty(brief.get(field)):
            errors.append(f"change_brief.{field} must be non-empty")
    if not isinstance(brief.get("acceptance_criteria"), list) or not brief["acceptance_criteria"]:
        errors.append("change_brief.acceptance_criteria must be a non-empty array")
    for field in ("non_goals", "constraints"):
        if not isinstance(brief.get(field), list):
            errors.append(f"change_brief.{field} must be an array")

    impacts = plan.get("impact_scope")
    impact_keys: set[tuple[str, str]] = set()
    if not isinstance(impacts, list) or not impacts:
        errors.append("impact_scope must be a non-empty array")
        impacts = []
    for index, impact in enumerate(impacts):
        if not isinstance(impact, dict):
            errors.append(f"impact_scope[{index}] must be an object")
            continue
        node_id, flow_id = impact.get("macro_node_id"), impact.get("flow_id")
        if node_id not in macro_ids:
            errors.append(f"impact_scope[{index}] references unknown macro node: {node_id!r}")
        if flow_id not in flow_ids:
            errors.append(f"impact_scope[{index}] references unknown flow: {flow_id!r}")
        if isinstance(node_id, str) and isinstance(flow_id, str):
            impact_keys.add((node_id, flow_id))
            if (node_id, flow_id) not in allowed_macro_flow_pairs:
                errors.append(
                    f"impact_scope[{index}] flow {flow_id!r} is not traced by macro node {node_id!r}"
                )
        if impact.get("impact_type") not in IMPACT_TYPES:
            errors.append(f"impact_scope[{index}] has invalid impact_type")
        if not nonempty(impact.get("reason")):
            errors.append(f"impact_scope[{index}].reason must be non-empty")
        if not isinstance(impact.get("developer_confirmed"), bool):
            errors.append(f"impact_scope[{index}].developer_confirmed must be boolean")
        if impact.get("developer_confirmed") is True and not nonempty(impact.get("decision_ref")):
            errors.append(f"impact_scope[{index}] confirmed without decision_ref")

    packages = plan.get("work_packages")
    package_ids: set[str] = set()
    dependencies: dict[str, list[str]] = {}
    covered: set[tuple[str, str]] = set()
    change_owners: dict[tuple[str, str], str] = {}
    if not isinstance(packages, list):
        errors.append("work_packages must be an array")
        packages = []
    elif plan.get("status") != "impact-review" and not packages:
        errors.append("work_packages must be non-empty after impact-review")
    if packages and any(
        impact.get("developer_confirmed") is not True for impact in impacts if isinstance(impact, dict)
    ):
        errors.append("work packages cannot be created before all impacts are developer-confirmed")
    for index, package in enumerate(packages):
        if not isinstance(package, dict):
            errors.append(f"work_packages[{index}] must be an object")
            continue
        package_id = package.get("id")
        if not isinstance(package_id, str) or not W_ID.fullmatch(package_id):
            errors.append(f"invalid work package id: {package_id!r}")
            continue
        if package_id in package_ids:
            errors.append(f"duplicate work package id: {package_id}")
        package_ids.add(package_id)
        flow_id = package.get("flow_id")
        if flow_id not in flow_ids:
            errors.append(f"work package {package_id} references unknown flow: {flow_id!r}")
        node_ids = package.get("macro_node_ids")
        if not isinstance(node_ids, list) or not node_ids:
            errors.append(f"work package {package_id}.macro_node_ids must be non-empty")
            node_ids = []
        for node_id in node_ids:
            if node_id not in macro_ids:
                errors.append(f"work package {package_id} references unknown macro node: {node_id!r}")
            if isinstance(flow_id, str) and isinstance(node_id, str):
                covered.add((node_id, flow_id))
                if (node_id, flow_id) not in allowed_macro_flow_pairs:
                    errors.append(
                        f"work package {package_id} flow {flow_id!r} is not traced by macro node {node_id!r}"
                    )
        for field in ("objective", "report_baseline"):
            if not nonempty(package.get(field)):
                errors.append(f"work package {package_id}.{field} must be non-empty")
        if package.get("analysis_mode") not in ANALYSIS_MODES:
            errors.append(f"work package {package_id} has invalid analysis_mode")
        if package.get("evidence_coverage") not in EVIDENCE_COVERAGE:
            errors.append(f"work package {package_id} has invalid evidence_coverage")
        if package.get("analysis_mode") == "reuse-report" and (
            package.get("report_baseline") != plan.get("repository_baseline")
            or package.get("evidence_coverage") != "complete"
        ):
            errors.append(
                f"work package {package_id} cannot reuse a stale or incomplete report"
            )
        for field in ("change_points", "dependencies", "tests", "risks"):
            if not isinstance(package.get(field), list):
                errors.append(f"work package {package_id}.{field} must be an array")
        for point_index, point in enumerate(package.get("change_points", [])):
            if not isinstance(point, dict):
                errors.append(f"work package {package_id}.change_points[{point_index}] must be an object")
                continue
            if point.get("kind") not in CHANGE_KINDS:
                errors.append(f"work package {package_id}.change_points[{point_index}] has invalid kind")
            for field in ("path", "symbol", "change"):
                if not nonempty(point.get(field)):
                    errors.append(
                        f"work package {package_id}.change_points[{point_index}].{field} must be non-empty"
                    )
            if nonempty(point.get("path")) and nonempty(point.get("symbol")):
                change_key = (point["path"], point["symbol"])
                owner = change_owners.get(change_key)
                if owner is not None and owner != package_id:
                    errors.append(
                        f"change point {change_key[0]}::{change_key[1]} has multiple owners: "
                        f"{owner}, {package_id}"
                    )
                else:
                    change_owners[change_key] = package_id
            refs = point.get("evidence_refs")
            if not isinstance(refs, list):
                errors.append(
                    f"work package {package_id}.change_points[{point_index}].evidence_refs must be an array"
                )
                refs = []
            if point.get("kind") != "add" and not refs:
                errors.append(
                    f"work package {package_id}.change_points[{point_index}] requires existing evidence_refs"
                )
            for ref in refs:
                match = FLOW_REF.fullmatch(ref) if isinstance(ref, str) else None
                if not match or match.group(1) != flow_id:
                    errors.append(
                        f"work package {package_id}.change_points[{point_index}] has invalid flow evidence: {ref!r}"
                    )
                elif match.group(2) not in source_nodes.get(flow_id, set()):
                    errors.append(
                        f"work package {package_id}.change_points[{point_index}] references unknown source node: {ref!r}"
                    )
        if isinstance(package.get("tests"), list) and not package["tests"]:
            errors.append(f"work package {package_id}.tests must be non-empty")
        dependencies[package_id] = package.get("dependencies", [])

    for package_id, targets in dependencies.items():
        for target in targets:
            if target not in package_ids:
                errors.append(f"work package {package_id} depends on unknown package {target!r}")
    if has_cycle(dependencies):
        errors.append("work package dependency cycle detected")

    for field in ("cross_flow_contracts", "conflicts", "blocking_open_decisions"):
        if not isinstance(plan.get(field), list):
            errors.append(f"{field} must be an array")
    contract_ids: set[str] = set()
    for index, contract in enumerate(plan.get("cross_flow_contracts", [])):
        if not isinstance(contract, dict):
            errors.append(f"cross_flow_contracts[{index}] must be an object")
            continue
        contract_id = contract.get("id")
        if not nonempty(contract_id):
            errors.append(f"cross_flow_contracts[{index}].id must be non-empty")
        elif contract_id in contract_ids:
            errors.append(f"duplicate cross-flow contract id: {contract_id}")
        else:
            contract_ids.add(contract_id)
        if contract.get("kind") not in CONTRACT_KINDS:
            errors.append(f"cross_flow_contracts[{index}] has invalid kind")
        if contract.get("owner_work_package") not in package_ids:
            errors.append(f"cross_flow_contracts[{index}] has unknown owner_work_package")
        for field in ("producers", "consumers"):
            if not isinstance(contract.get(field), list) or not contract[field]:
                errors.append(f"cross_flow_contracts[{index}].{field} must be non-empty")
        for field in ("change", "compatibility", "migration"):
            if not nonempty(contract.get(field)):
                errors.append(f"cross_flow_contracts[{index}].{field} must be non-empty")
        if contract.get("status") not in {"draft", "confirmed"}:
            errors.append(f"cross_flow_contracts[{index}] has invalid status")
    for index, conflict in enumerate(plan.get("conflicts", [])):
        if not isinstance(conflict, dict):
            errors.append(f"conflicts[{index}] must be an object")
            continue
        if not nonempty(conflict.get("id")) or not nonempty(conflict.get("summary")):
            errors.append(f"conflicts[{index}] requires id and summary")
        if conflict.get("status") not in {"resolved", "unresolved"}:
            errors.append(f"conflicts[{index}] has invalid status")
        if conflict.get("status") == "resolved" and not nonempty(conflict.get("resolution")):
            errors.append(f"conflicts[{index}] resolved without resolution")
    approval = plan.get("approval")
    if not isinstance(approval, dict):
        errors.append("approval must be an object")
        approval = {}

    if require_approved or plan.get("status") == "approved":
        if plan.get("status") != "approved":
            errors.append("status must be approved")
        if (
            approval.get("status") != "approved"
            or not nonempty(approval.get("decision_ref"))
            or not nonempty(approval.get("approved_at"))
        ):
            errors.append("approved plan requires explicit decision_ref and approved_at")
        if any(impact.get("developer_confirmed") is not True for impact in impacts if isinstance(impact, dict)):
            errors.append("all impact_scope entries must be developer-confirmed")
        if any(impact.get("impact_type") == "unknown" for impact in impacts if isinstance(impact, dict)):
            errors.append("approved impact_scope cannot retain impact_type=unknown")
        missing_coverage = sorted(impact_keys - covered)
        if missing_coverage:
            errors.append(f"confirmed impact entries lack work packages: {missing_coverage!r}")
        if plan.get("blocking_open_decisions"):
            errors.append("blocking_open_decisions must be empty")
        if any(
            isinstance(contract, dict) and contract.get("status") != "confirmed"
            for contract in plan.get("cross_flow_contracts", [])
        ):
            errors.append("all cross-flow contracts must be confirmed")
        if any(
            isinstance(conflict, dict) and conflict.get("status") != "resolved"
            for conflict in plan.get("conflicts", [])
        ):
            errors.append("unresolved conflicts remain")
        for package in packages:
            if isinstance(package, dict) and not package.get("change_points"):
                errors.append(f"approved work package {package.get('id')} has no change_points")
            if isinstance(package, dict) and (
                package.get("report_baseline") != plan.get("repository_baseline")
                or package.get("evidence_coverage") != "complete"
            ):
                errors.append(f"approved work package {package.get('id')} lacks current complete evidence")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("macro_contract", type=Path)
    parser.add_argument("--require-approved", action="store_true")
    args = parser.parse_args()
    errors: list[str] = []
    plan = load(args.plan, "plan", errors)
    macro = load(args.macro_contract, "macro contract", errors)
    errors.extend(audit(plan, macro, args.require_approved))
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"OK: valid change plan contract: {args.plan}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
