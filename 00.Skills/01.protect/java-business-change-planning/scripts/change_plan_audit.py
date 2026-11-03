#!/usr/bin/env python3
"""Validate a change-plan contract against a frozen macro contract and Flow Packs."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


PLAN_STATUSES = {"impact-review", "design-draft", "developer-review", "approved", "superseded"}
IMPACT_TYPES = {"direct", "contract", "data", "operational", "unknown"}
IMPACT_STATUSES = {"confirmed", "inferred", "unknown"}
ANALYSIS_MODES = {"reuse-flow-pack", "refresh-with-java-code-flow-analysis"}
EVIDENCE_COVERAGE = {"sufficient", "partial", "stale", "unknown"}
FLOW_COVERAGE = {"main-path", "key-paths-covered", "static-scope-complete", "partial"}
OUTCOMES = {"change-required", "verification-only", "no-change"}
CHANGE_KINDS = {"add", "modify", "remove", "config", "schema"}
CONTRACT_KINDS = {"api", "event", "data", "state", "config"}
A_ID = re.compile(r"A[1-9]\d*$")
W_ID = re.compile(r"W[1-9]\d*$")
TYPED_ID = r"(?:S\d+|N\d+(?:\.\d+)*|[RDMLCUX]\d+)"
FLOW_REF = re.compile(rf"([A-Za-z0-9][A-Za-z0-9._-]*)/({TYPED_ID})$")


def nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def load_json(path: Path, label: str, errors: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"cannot load {label} {path}: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{label} must be a JSON object")
        return {}
    return value


def load_flow_pack(path: Path, errors: list[str]) -> tuple[dict[str, Any], set[str]]:
    records: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        errors.append(f"cannot load Flow Pack {path}: {exc}")
        return {}, set()
    for line_number, raw in enumerate(lines, start=1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            errors.append(f"Flow Pack {path}:{line_number}: {exc.msg}")
            continue
        if not isinstance(value, dict):
            errors.append(f"Flow Pack {path}:{line_number}: record must be an object")
            continue
        records.append(value)
    if not records or records[0].get("type") != "flow":
        errors.append(f"Flow Pack {path}: first record must have type 'flow'")
        return {}, set()
    facts = {
        record["id"]
        for record in records[1:]
        if isinstance(record.get("id"), str) and re.fullmatch(TYPED_ID, record["id"])
    }
    return records[0], facts


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def section(text: str, title: str) -> str:
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.startswith("## ") and title in line:
            start = index + 1
            break
    if start is None:
        return ""
    end = len(lines)
    for index in range(start, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break
    return "\n".join(lines[start:end])


def audit_report(report: Path, impacts: list[dict], packages: list[dict]) -> list[str]:
    errors: list[str] = []
    text = report.read_text(encoding="utf-8")
    for heading in ("目标、范围与验收结果", "影响摘要", "目标行为变化", "工作包", "验证"):
        if not section(text, heading):
            errors.append(f"report: missing or empty '{heading}' section")
    report_impacts = set(re.findall(r"(?<![A-Za-z0-9])(A[1-9]\d*)(?![A-Za-z0-9])", text))
    contract_impacts = {item.get("id") for item in impacts if isinstance(item.get("id"), str)}
    if report_impacts != contract_impacts:
        errors.append("report: impact IDs differ from contract")
    report_packages = set(re.findall(r"(?<![A-Za-z0-9])(W[1-9]\d*)(?![A-Za-z0-9])", text))
    contract_packages = {item.get("id") for item in packages if isinstance(item.get("id"), str)}
    if report_packages != contract_packages:
        errors.append("report: work-package IDs differ from contract")
    work_section = section(text, "工作包")
    for package in packages:
        package_pattern = re.compile(
            rf"^###\s+{re.escape(str(package.get('id')))}\s+"
            rf"{re.escape(str(package.get('name', '')))}\s+[—-]\s+"
            rf"{re.escape(str(package.get('outcome', '')))}\s*$",
            re.MULTILINE,
        )
        if not package_pattern.search(work_section):
            errors.append(f"report: work package {package.get('id')} name/outcome differs from contract")
    for block_index, block in enumerate(re.findall(r"```mermaid\s*\n(.*?)```", text, re.DOTALL), start=1):
        if re.search(r"#(?!35;)", block):
            errors.append(f"report: Mermaid block {block_index} contains raw '#'")
    return errors


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


def audit(
    plan: dict[str, Any],
    plan_path: Path,
    macro: dict[str, Any],
    macro_path: Path,
    require_approved: bool,
) -> list[str]:
    errors: list[str] = []
    required = {
        "schema_version", "plan_id", "version", "status", "macro_ref",
        "repository_baselines", "change_brief", "impact_scope", "scope_decision",
        "work_packages", "cross_flow_contracts", "implementation_order", "conflicts",
        "blocking_open_decisions", "approval",
    }
    for field in sorted(required - set(plan)):
        errors.append(f"missing field: {field}")
    if plan.get("schema_version") != 2:
        errors.append("schema_version must be 2")
    for field in ("plan_id", "version"):
        if not nonempty(plan.get(field)):
            errors.append(f"{field} must be non-empty")
    if plan.get("status") not in PLAN_STATUSES:
        errors.append(f"invalid status: {plan.get('status')!r}")

    if macro.get("schema_version") != 2 or macro.get("status") != "frozen":
        errors.append("macro contract must be schema 2 and frozen")
    macro_approval = macro.get("approval") if isinstance(macro.get("approval"), dict) else {}
    if macro_approval.get("status") != "approved" or not nonempty(macro_approval.get("decision_ref")) or not nonempty(macro_approval.get("approved_at")):
        errors.append("macro contract lacks explicit approval")
    if any(isinstance(item, dict) and item.get("blocking") is True for item in macro.get("unresolved", [])):
        errors.append("macro contract has blocking unresolved items")

    macro_ref = plan.get("macro_ref")
    if not isinstance(macro_ref, dict):
        errors.append("macro_ref must be an object")
        macro_ref = {}
    for field in ("macro_flow_id", "version", "status"):
        if macro_ref.get(field) != macro.get(field):
            errors.append(f"macro_ref.{field} does not match macro contract")
    try:
        actual_macro_digest = digest(macro_path)
    except OSError as exc:
        errors.append(f"cannot hash macro contract: {exc}")
    else:
        if macro_ref.get("contract_digest") != actual_macro_digest:
            errors.append("macro_ref.contract_digest does not match macro contract")

    phases = {item.get("id"): item for item in macro.get("phases", []) if isinstance(item, dict) and nonempty(item.get("id"))}
    sources = {item.get("flow_id"): item for item in macro.get("source_flows", []) if isinstance(item, dict) and nonempty(item.get("flow_id"))}
    source_facts: dict[str, set[str]] = {}
    for flow_id, source in sources.items():
        pack_value = source.get("flow_pack")
        if not nonempty(pack_value):
            errors.append(f"macro source {flow_id} has no flow_pack")
            continue
        pack_path = Path(pack_value)
        if not pack_path.is_absolute():
            pack_path = macro_path.parent / pack_path
        header, facts = load_flow_pack(pack_path, errors)
        source_facts[flow_id] = facts
        if header.get("id") != flow_id or header.get("baseline") != source.get("baseline"):
            errors.append(f"macro source {flow_id} no longer matches its Flow Pack")
        if nonempty(source.get("pack_digest")):
            try:
                if source["pack_digest"] != digest(pack_path):
                    errors.append(f"macro source {flow_id} Flow Pack digest changed")
            except OSError as exc:
                errors.append(f"cannot hash source {flow_id}: {exc}")

    phase_flows = {
        phase_id: {
            match.group(1)
            for ref in phase.get("flow_refs", [])
            if isinstance(ref, str) and (match := FLOW_REF.fullmatch(ref))
        }
        for phase_id, phase in phases.items()
    }

    baselines = plan.get("repository_baselines")
    if not isinstance(baselines, dict):
        errors.append("repository_baselines must be an object")
        baselines = {}
    for flow_id, value in baselines.items():
        if flow_id not in sources or not nonempty(value):
            errors.append(f"repository_baselines has invalid entry {flow_id!r}")

    refreshed_value = plan.get("refreshed_flows", [])
    if not isinstance(refreshed_value, list):
        errors.append("refreshed_flows must be an array")
        refreshed_value = []
    refreshed_sources: dict[str, dict[str, Any]] = {}
    refreshed_headers: dict[str, dict[str, Any]] = {}
    refreshed_facts: dict[str, set[str]] = {}
    for index, refreshed in enumerate(refreshed_value):
        if not isinstance(refreshed, dict):
            errors.append(f"refreshed_flows[{index}] must be an object")
            continue
        flow_id = refreshed.get("flow_id")
        if not nonempty(flow_id) or flow_id not in sources or flow_id in refreshed_sources:
            errors.append(f"refreshed_flows[{index}] has invalid or duplicate flow_id")
            continue
        refreshed_sources[flow_id] = refreshed
        for field in ("flow_pack", "baseline", "pack_digest"):
            if not nonempty(refreshed.get(field)):
                errors.append(f"refreshed flow {flow_id}.{field} must be non-empty")
        pack_value = refreshed.get("flow_pack")
        if not nonempty(pack_value):
            continue
        pack_path = Path(pack_value)
        if not pack_path.is_absolute():
            pack_path = plan_path.parent / pack_path
        header, facts = load_flow_pack(pack_path, errors)
        refreshed_headers[flow_id] = header
        refreshed_facts[flow_id] = facts
        if header.get("id") != flow_id:
            errors.append(f"refreshed flow {flow_id} does not match its Flow Pack id")
        if header.get("baseline") != refreshed.get("baseline"):
            errors.append(f"refreshed flow {flow_id} baseline does not match its Flow Pack")
        if header.get("coverage") not in FLOW_COVERAGE:
            errors.append(f"refreshed flow {flow_id} has invalid Flow Pack coverage")
        frontier_count = header.get("frontier_count")
        if not isinstance(frontier_count, int) or frontier_count < 0:
            errors.append(f"refreshed flow {flow_id} has invalid frontier_count")
        elif (frontier_count > 0) != (header.get("coverage") == "partial"):
            errors.append(f"refreshed flow {flow_id} frontier_count and coverage are inconsistent")
        unresolved_count = header.get("unresolved_count")
        if not isinstance(unresolved_count, int) or unresolved_count < 0:
            errors.append(f"refreshed flow {flow_id} has invalid unresolved_count")
        if baselines.get(flow_id) != refreshed.get("baseline"):
            errors.append(f"repository_baselines[{flow_id!r}] does not match refreshed Flow Pack")
        try:
            if refreshed.get("pack_digest") != digest(pack_path):
                errors.append(f"refreshed flow {flow_id} Flow Pack digest changed")
        except OSError as exc:
            errors.append(f"cannot hash refreshed flow {flow_id}: {exc}")

    brief = plan.get("change_brief")
    if not isinstance(brief, dict):
        errors.append("change_brief must be an object")
        brief = {}
    for field in ("goal", "decision_ref"):
        if not nonempty(brief.get(field)):
            errors.append(f"change_brief.{field} must be non-empty")
    if not isinstance(brief.get("acceptance_criteria"), list) or not brief.get("acceptance_criteria"):
        errors.append("change_brief.acceptance_criteria must be non-empty")
    for field in ("non_goals", "constraints"):
        if not isinstance(brief.get(field), list):
            errors.append(f"change_brief.{field} must be an array")

    impacts = plan.get("impact_scope")
    if not isinstance(impacts, list) or not impacts:
        errors.append("impact_scope must be a non-empty array")
        impacts = []
    impact_by_id: dict[str, dict] = {}
    for index, impact in enumerate(impacts):
        if not isinstance(impact, dict):
            errors.append(f"impact_scope[{index}] must be an object")
            continue
        impact_id = impact.get("id")
        if not isinstance(impact_id, str) or not A_ID.fullmatch(impact_id) or impact_id in impact_by_id:
            errors.append(f"impact_scope[{index}] has invalid or duplicate id")
            continue
        impact_by_id[impact_id] = impact
        macro_node, flow_id = impact.get("macro_node_id"), impact.get("flow_id")
        if macro_node not in phases:
            errors.append(f"impact {impact_id} references unknown macro node")
        if flow_id not in sources:
            errors.append(f"impact {impact_id} references unknown flow")
        elif flow_id not in phase_flows.get(macro_node, set()):
            errors.append(f"impact {impact_id} flow is not traced by its macro node")
        if impact.get("impact_type") not in IMPACT_TYPES or impact.get("status") not in IMPACT_STATUSES:
            errors.append(f"impact {impact_id} has invalid type or status")
        if not nonempty(impact.get("reason")):
            errors.append(f"impact {impact_id}.reason must be non-empty")
        refs = impact.get("evidence_refs")
        if not isinstance(refs, list):
            errors.append(f"impact {impact_id}.evidence_refs must be an array")
            refs = []
        for ref in refs:
            match = FLOW_REF.fullmatch(ref) if isinstance(ref, str) else None
            if not match or match.group(1) != flow_id or match.group(2) not in source_facts.get(flow_id, set()):
                errors.append(f"impact {impact_id} has invalid evidence ref {ref!r}")
        if impact.get("status") == "confirmed" and not refs:
            errors.append(f"confirmed impact {impact_id} requires evidence_refs")

    decision = plan.get("scope_decision")
    if not isinstance(decision, dict):
        errors.append("scope_decision must be an object")
        decision = {}
    included = decision.get("included_impact_ids")
    excluded = decision.get("excluded_impact_ids")
    if not isinstance(included, list) or not isinstance(excluded, list):
        errors.append("scope_decision included/excluded IDs must be arrays")
        included, excluded = [], []
    if set(included) & set(excluded):
        errors.append("scope_decision cannot both include and exclude an impact")
    if set(included) | set(excluded) != set(impact_by_id):
        errors.append("scope_decision must classify every impact exactly once")
    if decision.get("confirmed") is True and not nonempty(decision.get("decision_ref")):
        errors.append("confirmed scope_decision requires decision_ref")

    packages = plan.get("work_packages")
    if not isinstance(packages, list):
        errors.append("work_packages must be an array")
        packages = []
    if packages and decision.get("confirmed") is not True:
        errors.append("work packages require a confirmed scope_decision")
    package_by_id: dict[str, dict] = {}
    dependencies: dict[str, list[str]] = {}
    change_owners: dict[tuple[str, str], str] = {}
    covered_impacts: set[str] = set()
    used_refreshed_flows: set[str] = set()
    for index, package in enumerate(packages):
        if not isinstance(package, dict):
            errors.append(f"work_packages[{index}] must be an object")
            continue
        package_id = package.get("id")
        if not isinstance(package_id, str) or not W_ID.fullmatch(package_id) or package_id in package_by_id:
            errors.append(f"work_packages[{index}] has invalid or duplicate id")
            continue
        package_by_id[package_id] = package
        for field in ("name", "objective", "current_behavior", "target_behavior"):
            if not nonempty(package.get(field)):
                errors.append(f"work package {package_id}.{field} must be non-empty")
        flow_id = package.get("flow_id")
        if flow_id not in sources:
            errors.append(f"work package {package_id} references unknown flow")
        macro_nodes = package.get("macro_node_ids")
        impact_ids = package.get("impact_ids")
        if not isinstance(macro_nodes, list) or not macro_nodes:
            errors.append(f"work package {package_id}.macro_node_ids must be non-empty")
            macro_nodes = []
        if not isinstance(impact_ids, list) or not impact_ids:
            errors.append(f"work package {package_id}.impact_ids must be non-empty")
            impact_ids = []
        for macro_node in macro_nodes:
            if macro_node not in phases or flow_id not in phase_flows.get(macro_node, set()):
                errors.append(f"work package {package_id} has invalid macro node/flow pair")
        for impact_id in impact_ids:
            impact = impact_by_id.get(impact_id)
            if impact_id not in included or not impact or impact.get("flow_id") != flow_id:
                errors.append(f"work package {package_id} has invalid included impact {impact_id!r}")
            else:
                covered_impacts.add(impact_id)
        if package.get("outcome") not in OUTCOMES:
            errors.append(f"work package {package_id} has invalid outcome")
        analysis_mode = package.get("analysis_mode")
        if analysis_mode not in ANALYSIS_MODES:
            errors.append(f"work package {package_id} has invalid analysis_mode")
        if package.get("evidence_coverage") not in EVIDENCE_COVERAGE:
            errors.append(f"work package {package_id} has invalid evidence_coverage")
        package_facts = source_facts.get(flow_id, set())
        if analysis_mode == "reuse-flow-pack" and (
            baselines.get(flow_id) != sources.get(flow_id, {}).get("baseline")
            or package.get("evidence_coverage") != "sufficient"
        ):
            errors.append(f"work package {package_id} cannot reuse stale or insufficient Flow Pack evidence")
        elif analysis_mode == "refresh-with-java-code-flow-analysis":
            refreshed = refreshed_sources.get(flow_id)
            if not refreshed:
                errors.append(f"work package {package_id} requires a refreshed_flows entry")
            else:
                used_refreshed_flows.add(flow_id)
                package_facts = refreshed_facts.get(flow_id, set())
                header = refreshed_headers.get(flow_id, {})
                if package.get("evidence_coverage") == "sufficient" and (
                    header.get("coverage") == "partial"
                    or header.get("frontier_count", 0) != 0
                ):
                    errors.append(f"work package {package_id} cannot claim sufficient refreshed evidence with an open frontier")
        evidence_refs = package.get("evidence_refs")
        if analysis_mode == "refresh-with-java-code-flow-analysis" and (
            not isinstance(evidence_refs, list) or not evidence_refs
        ):
            errors.append(f"refreshed work package {package_id} requires evidence_refs")
            evidence_refs = []
        elif evidence_refs is None:
            evidence_refs = []
        elif not isinstance(evidence_refs, list):
            errors.append(f"work package {package_id}.evidence_refs must be an array")
            evidence_refs = []
        for ref in evidence_refs:
            match = FLOW_REF.fullmatch(ref) if isinstance(ref, str) else None
            if not match or match.group(1) != flow_id or match.group(2) not in package_facts:
                label = "refreshed evidence" if analysis_mode == "refresh-with-java-code-flow-analysis" else "evidence"
                errors.append(f"work package {package_id} has invalid {label} {ref!r}")

        points = package.get("change_points")
        verification = package.get("verification")
        if not isinstance(points, list):
            errors.append(f"work package {package_id}.change_points must be an array")
            points = []
        if not isinstance(verification, list) or not verification:
            errors.append(f"work package {package_id}.verification must be non-empty")
        if not isinstance(package.get("risks"), list):
            errors.append(f"work package {package_id}.risks must be an array")
        outcome = package.get("outcome")
        if outcome == "change-required" and not points:
            errors.append(f"work package {package_id} requires change_points")
        if outcome in {"verification-only", "no-change"} and points:
            errors.append(f"work package {package_id} with outcome {outcome} cannot own change_points")
        if outcome == "no-change" and not nonempty(package.get("no_change_reason")):
            errors.append(f"work package {package_id} no-change requires no_change_reason")

        for point_index, point in enumerate(points):
            if not isinstance(point, dict):
                errors.append(f"work package {package_id}.change_points[{point_index}] must be an object")
                continue
            if point.get("kind") not in CHANGE_KINDS:
                errors.append(f"work package {package_id}.change_points[{point_index}] has invalid kind")
            for field in ("path", "symbol", "change"):
                if not nonempty(point.get(field)):
                    errors.append(f"work package {package_id}.change_points[{point_index}].{field} must be non-empty")
            if nonempty(point.get("path")) and nonempty(point.get("symbol")):
                key = (point["path"], point["symbol"])
                if key in change_owners and change_owners[key] != package_id:
                    errors.append(f"change point {key} has multiple owners")
                else:
                    change_owners[key] = package_id
            refs = point.get("evidence_refs")
            if not isinstance(refs, list):
                errors.append(f"work package {package_id}.change_points[{point_index}].evidence_refs must be an array")
                refs = []
            if point.get("kind") != "add" and not refs:
                errors.append(f"existing change point in {package_id} requires evidence_refs")
            if point.get("kind") == "add" and not refs and not nonempty(point.get("requirement_ref")):
                errors.append(f"new change point in {package_id} requires evidence_refs or requirement_ref")
            if point.get("kind") == "add" and point.get("proposed") is not True:
                errors.append(f"new change point in {package_id} must set proposed=true")
            for ref in refs:
                match = FLOW_REF.fullmatch(ref) if isinstance(ref, str) else None
                if not match or match.group(1) != flow_id or match.group(2) not in package_facts:
                    errors.append(f"work package {package_id} has invalid change evidence {ref!r}")

        deps = package.get("dependencies")
        if not isinstance(deps, list):
            errors.append(f"work package {package_id}.dependencies must be an array")
            deps = []
        dependencies[package_id] = deps

    for package_id, deps in dependencies.items():
        for dependency in deps:
            if dependency not in package_by_id or dependency == package_id:
                errors.append(f"work package {package_id} has invalid dependency {dependency!r}")
    if has_cycle(dependencies):
        errors.append("work package dependency cycle detected")
    unused_refreshed = set(refreshed_sources) - used_refreshed_flows
    if unused_refreshed:
        errors.append(f"refreshed_flows entries are not used by refresh work packages: {sorted(unused_refreshed)}")

    implementation_order = plan.get("implementation_order")
    if not isinstance(implementation_order, list) or set(implementation_order) != set(package_by_id) or len(implementation_order) != len(package_by_id):
        errors.append("implementation_order must contain every work package exactly once")
        implementation_order = []
    positions = {package_id: index for index, package_id in enumerate(implementation_order)}
    for package_id, deps in dependencies.items():
        for dependency in deps:
            if dependency in positions and package_id in positions and positions[dependency] > positions[package_id]:
                errors.append("implementation_order violates work-package dependencies")

    for field in ("cross_flow_contracts", "conflicts", "blocking_open_decisions"):
        if not isinstance(plan.get(field), list):
            errors.append(f"{field} must be an array")
    contract_ids: set[str] = set()
    for index, item in enumerate(plan.get("cross_flow_contracts", [])):
        if not isinstance(item, dict):
            errors.append(f"cross_flow_contracts[{index}] must be an object")
            continue
        contract_id = item.get("id")
        if not nonempty(contract_id) or contract_id in contract_ids:
            errors.append(f"cross_flow_contracts[{index}] has missing or duplicate id")
        else:
            contract_ids.add(contract_id)
        if item.get("kind") not in CONTRACT_KINDS or item.get("owner_work_package") not in package_by_id:
            errors.append(f"cross_flow_contracts[{index}] has invalid kind or owner")
        for field in ("producers", "consumers"):
            if not isinstance(item.get(field), list) or not item[field]:
                errors.append(f"cross_flow_contracts[{index}].{field} must be non-empty")
        for field in ("change", "compatibility", "migration"):
            if not nonempty(item.get(field)):
                errors.append(f"cross_flow_contracts[{index}].{field} must be non-empty")
        if item.get("status") not in {"draft", "confirmed"}:
            errors.append(f"cross_flow_contracts[{index}] has invalid status")
    for index, conflict in enumerate(plan.get("conflicts", [])):
        if not isinstance(conflict, dict) or not nonempty(conflict.get("id")) or not nonempty(conflict.get("summary")):
            errors.append(f"conflicts[{index}] requires id and summary")
            continue
        if conflict.get("status") not in {"resolved", "unresolved"}:
            errors.append(f"conflicts[{index}] has invalid status")
        if conflict.get("status") == "resolved" and not nonempty(conflict.get("resolution")):
            errors.append(f"conflicts[{index}] resolved without resolution")

    approval = plan.get("approval") if isinstance(plan.get("approval"), dict) else {}
    if require_approved or plan.get("status") == "approved":
        if plan.get("status") != "approved":
            errors.append("status must be approved")
        if approval.get("status") != "approved" or not nonempty(approval.get("decision_ref")) or not nonempty(approval.get("approved_at")):
            errors.append("approved plan requires explicit approval")
        if decision.get("confirmed") is not True:
            errors.append("approved plan requires confirmed scope_decision")
        if any(impact_by_id[impact_id].get("impact_type") == "unknown" or impact_by_id[impact_id].get("status") == "unknown" for impact_id in included if impact_id in impact_by_id):
            errors.append("approved included impacts cannot remain unknown")
        missing = set(included) - covered_impacts
        if missing:
            errors.append(f"included impacts lack work-package coverage: {sorted(missing)}")
        if any(package.get("evidence_coverage") != "sufficient" for package in packages if isinstance(package, dict)):
            errors.append("approved work packages require sufficient evidence")
        if plan.get("blocking_open_decisions"):
            errors.append("blocking_open_decisions must be empty")
        if any(isinstance(item, dict) and item.get("status") != "confirmed" for item in plan.get("cross_flow_contracts", [])):
            errors.append("all cross-flow contracts must be confirmed")
        if any(isinstance(item, dict) and item.get("status") != "resolved" for item in plan.get("conflicts", [])):
            errors.append("unresolved conflicts remain")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("macro_contract", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--require-approved", action="store_true")
    args = parser.parse_args()
    errors: list[str] = []
    plan = load_json(args.plan, "plan", errors)
    macro = load_json(args.macro_contract, "macro contract", errors)
    errors.extend(audit(plan, args.plan, macro, args.macro_contract, args.require_approved))
    if args.report:
        errors.extend(audit_report(args.report, plan.get("impact_scope", []), plan.get("work_packages", [])))
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"OK: valid change plan contract: {args.plan}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
