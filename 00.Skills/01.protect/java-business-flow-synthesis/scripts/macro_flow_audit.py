#!/usr/bin/env python3
"""Validate a macro-flow contract against source Flow Packs and optional Markdown."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


STATUSES = {"draft", "developer-review", "frozen", "superseded"}
EVIDENCE = {"code-confirmed", "developer-confirmed", "both-confirmed", "inferred", "unresolved"}
HANDOFF_TYPES = {"sync", "async", "event", "manual", "shared-state", "external"}
RELATIONS = {"precedes", "triggers", "follows"}
COVERAGE = {"main-path", "key-paths-covered", "static-scope-complete", "partial"}
M_ID = re.compile(r"M1(?:\.\d+){0,2}$")
H_ID = re.compile(r"H[1-9]\d*$")
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
            record = json.loads(raw)
        except json.JSONDecodeError as exc:
            errors.append(f"Flow Pack {path}:{line_number}: {exc.msg}")
            continue
        if not isinstance(record, dict):
            errors.append(f"Flow Pack {path}:{line_number}: record must be an object")
            continue
        records.append(record)
    if not records or records[0].get("type") != "flow":
        errors.append(f"Flow Pack {path}: first record must have type 'flow'")
        return {}, set()
    fact_ids = {
        record["id"]
        for record in records[1:]
        if isinstance(record.get("id"), str) and re.fullmatch(TYPED_ID, record["id"])
    }
    return records[0], fact_ids


def sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def reachable(graph: dict[str, set[str]], starts: set[str]) -> set[str]:
    reached, frontier = set(starts), list(starts)
    while frontier:
        current = frontier.pop()
        for target in graph.get(current, set()) - reached:
            reached.add(target)
            frontier.append(target)
    return reached


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


def audit_report(report: Path, phases: list[dict], handoffs: list[dict]) -> list[str]:
    errors: list[str] = []
    text = report.read_text(encoding="utf-8")
    for heading in ("目标、范围与结论", "流程概述", "分层宏观流程树", "分阶段说明"):
        if not section(text, heading):
            errors.append(f"report: missing or empty '{heading}' section")

    tree = section(text, "分层宏观流程树")
    report_phase_ids = set(re.findall(r"(?<![A-Za-z0-9.])(M1(?:\.\d+){0,2})(?![A-Za-z0-9.])", tree))
    contract_phase_ids = {phase.get("id") for phase in phases if isinstance(phase.get("id"), str)}
    if report_phase_ids != contract_phase_ids:
        errors.append(
            "report: phase IDs differ from contract; "
            f"report-only={sorted(report_phase_ids - contract_phase_ids)}, "
            f"contract-only={sorted(contract_phase_ids - report_phase_ids)}"
        )
    for phase in phases:
        phase_pattern = re.compile(
            rf"^.*(?<![A-Za-z0-9.]){re.escape(str(phase.get('id')))}(?![A-Za-z0-9.]).*"
            rf"{re.escape(str(phase.get('name', '')))}.*$",
            re.MULTILINE,
        )
        if phase.get("id") in report_phase_ids and not phase_pattern.search(tree):
            errors.append(f"report: phase {phase.get('id')} name is inconsistent with contract")

    report_handoffs = set(re.findall(r"(?<![A-Za-z0-9])(H[1-9]\d*)(?![A-Za-z0-9])", text))
    contract_handoffs = {item.get("id") for item in handoffs if isinstance(item.get("id"), str)}
    if report_handoffs != contract_handoffs:
        errors.append(
            "report: handoff IDs differ from contract; "
            f"report-only={sorted(report_handoffs - contract_handoffs)}, "
            f"contract-only={sorted(contract_handoffs - report_handoffs)}"
        )
    for handoff in handoffs:
        direction = re.compile(
            rf"^.*(?<![A-Za-z0-9]){re.escape(str(handoff.get('id')))}(?![A-Za-z0-9]).*"
            rf"{re.escape(str(handoff.get('from')))}\s*(?:→|->)\s*{re.escape(str(handoff.get('to')))}.*$",
            re.MULTILINE,
        )
        if not direction.search(text):
            errors.append(f"report: handoff {handoff.get('id')} direction differs from contract")
    for block_index, block in enumerate(re.findall(r"```mermaid\s*\n(.*?)```", text, re.DOTALL), start=1):
        if re.search(r"#(?!35;)", block):
            errors.append(f"report: Mermaid block {block_index} contains raw '#'")
    return errors


def audit(contract: dict[str, Any], contract_path: Path, require_frozen: bool) -> list[str]:
    errors: list[str] = []
    required = {
        "schema_version", "macro_flow_id", "version", "status", "developer_brief",
        "source_flows", "entry_phase", "end_phases", "phases", "handoffs",
        "invariants", "unresolved", "decisions", "approval",
    }
    for field in sorted(required - set(contract)):
        errors.append(f"missing field: {field}")
    if contract.get("schema_version") != 2:
        errors.append("schema_version must be 2")
    for field in ("macro_flow_id", "version"):
        if not nonempty(contract.get(field)):
            errors.append(f"{field} must be non-empty")
    if contract.get("status") not in STATUSES:
        errors.append(f"invalid status: {contract.get('status')!r}")

    brief = contract.get("developer_brief")
    if not isinstance(brief, dict):
        errors.append("developer_brief must be an object")
        brief = {}
    for field in ("goal", "start", "end", "scope", "decision_ref"):
        if not nonempty(brief.get(field)):
            errors.append(f"developer_brief.{field} must be non-empty")
    included = brief.get("included_flow_ids")
    if not isinstance(included, list) or len(included) < 2:
        errors.append("developer_brief.included_flow_ids must contain at least two flows")
        included = []
    anchors = brief.get("anchor_relations")
    if not isinstance(anchors, list):
        errors.append("developer_brief.anchor_relations must be an array")
        anchors = []
    if not anchors and brief.get("allow_relation_proposals") is not True:
        errors.append("no anchor relation: allow_relation_proposals must be true")

    source_flows = contract.get("source_flows")
    if not isinstance(source_flows, list) or len(source_flows) < 2:
        errors.append("source_flows must contain at least two flows")
        source_flows = []
    source_ids: set[str] = set()
    source_facts: dict[str, set[str]] = {}
    for index, source in enumerate(source_flows):
        if not isinstance(source, dict):
            errors.append(f"source_flows[{index}] must be an object")
            continue
        flow_id = source.get("flow_id")
        if not nonempty(flow_id) or flow_id in source_ids:
            errors.append(f"source_flows[{index}] has missing or duplicate flow_id")
            continue
        source_ids.add(flow_id)
        for field in ("flow_pack", "baseline", "coverage"):
            if not nonempty(source.get(field)):
                errors.append(f"source_flows[{index}].{field} must be non-empty")
        if source.get("coverage") not in COVERAGE:
            errors.append(f"source_flows[{index}] has invalid coverage")
        pack_value = source.get("flow_pack")
        if not nonempty(pack_value):
            continue
        pack_path = Path(pack_value)
        if not pack_path.is_absolute():
            pack_path = contract_path.parent / pack_path
        header, fact_ids = load_flow_pack(pack_path, errors)
        source_facts[flow_id] = fact_ids
        if header.get("id") != flow_id:
            errors.append(f"source {flow_id}: Flow Pack id does not match")
        if header.get("baseline") != source.get("baseline"):
            errors.append(f"source {flow_id}: baseline does not match Flow Pack")
        if header.get("coverage") != source.get("coverage"):
            errors.append(f"source {flow_id}: coverage does not match Flow Pack")
        digest = source.get("pack_digest")
        if nonempty(digest):
            try:
                actual_digest = sha256(pack_path)
            except OSError as exc:
                errors.append(f"source {flow_id}: cannot hash Flow Pack: {exc}")
            else:
                if digest != actual_digest:
                    errors.append(f"source {flow_id}: pack_digest does not match")
        elif require_frozen or contract.get("status") == "frozen":
            errors.append(f"source {flow_id}: frozen contract requires pack_digest")

    if set(included) != source_ids:
        errors.append("included_flow_ids must exactly match source_flows")

    for index, anchor in enumerate(anchors):
        if not isinstance(anchor, dict):
            errors.append(f"anchor_relations[{index}] must be an object")
            continue
        source, target = anchor.get("from_flow"), anchor.get("to_flow")
        if source not in source_ids or target not in source_ids or source == target:
            errors.append(f"anchor_relations[{index}] has invalid endpoints")
        if anchor.get("relation") not in RELATIONS:
            errors.append(f"anchor_relations[{index}] has invalid relation")
        if not nonempty(anchor.get("decision_ref")):
            errors.append(f"anchor_relations[{index}].decision_ref must be non-empty")

    phases = contract.get("phases")
    if not isinstance(phases, list) or not phases:
        errors.append("phases must be a non-empty array")
        phases = []
    phase_by_id: dict[str, dict] = {}
    phase_flows: dict[str, set[str]] = {}
    for index, phase in enumerate(phases):
        if not isinstance(phase, dict):
            errors.append(f"phases[{index}] must be an object")
            continue
        phase_id = phase.get("id")
        if not isinstance(phase_id, str) or not M_ID.fullmatch(phase_id) or phase_id in phase_by_id:
            errors.append(f"phases[{index}] has invalid or duplicate id {phase_id!r}")
            continue
        phase_by_id[phase_id] = phase
        expected_parent = None if phase_id == "M1" else phase_id.rsplit(".", 1)[0]
        if phase.get("parent") != expected_parent:
            errors.append(f"phase {phase_id}.parent must be {expected_parent!r}")
        for field in ("name", "entry", "action", "outcome"):
            if not nonempty(phase.get(field)):
                errors.append(f"phase {phase_id}.{field} must be non-empty")
        refs = phase.get("flow_refs")
        if not isinstance(refs, list):
            errors.append(f"phase {phase_id}.flow_refs must be an array")
            refs = []
        ref_flows: set[str] = set()
        for ref in refs:
            match = FLOW_REF.fullmatch(ref) if isinstance(ref, str) else None
            if not match or match.group(1) not in source_ids:
                errors.append(f"phase {phase_id} has invalid flow ref {ref!r}")
            elif match.group(2) not in source_facts.get(match.group(1), set()):
                errors.append(f"phase {phase_id} references missing Flow Pack fact {ref!r}")
            else:
                ref_flows.add(match.group(1))
        phase_flows[phase_id] = ref_flows
        evidence = phase.get("evidence_status")
        if evidence not in EVIDENCE:
            errors.append(f"phase {phase_id} has invalid evidence_status")
        if not isinstance(phase.get("critical"), bool):
            errors.append(f"phase {phase_id}.critical must be boolean")
        if evidence in {"code-confirmed", "both-confirmed"} and not refs:
            errors.append(f"phase {phase_id} requires flow_refs")
        if evidence in {"developer-confirmed", "both-confirmed"} and not nonempty(phase.get("decision_ref")):
            errors.append(f"phase {phase_id} requires decision_ref")
    if "M1" not in phase_by_id:
        errors.append("root phase M1 is required")
    for phase_id in phase_by_id:
        if "." in phase_id and phase_id.rsplit(".", 1)[0] not in phase_by_id:
            errors.append(f"phase {phase_id} has a missing parent")

    parents = {phase.get("parent") for phase in phases if isinstance(phase, dict)}
    leaves = set(phase_by_id) - {parent for parent in parents if isinstance(parent, str)}
    entry_phase = contract.get("entry_phase")
    end_phases = contract.get("end_phases")
    if entry_phase not in leaves:
        errors.append("entry_phase must be a leaf phase")
    if not isinstance(end_phases, list) or not end_phases:
        errors.append("end_phases must be a non-empty array")
        end_phases = []
    for endpoint in end_phases:
        if endpoint not in leaves:
            errors.append(f"end phase {endpoint!r} must be a leaf phase")

    handoffs = contract.get("handoffs")
    if not isinstance(handoffs, list):
        errors.append("handoffs must be an array")
        handoffs = []
    handoff_ids: set[str] = set()
    graph = {leaf: set() for leaf in leaves}
    for index, handoff in enumerate(handoffs):
        if not isinstance(handoff, dict):
            errors.append(f"handoffs[{index}] must be an object")
            continue
        handoff_id = handoff.get("id")
        if not isinstance(handoff_id, str) or not H_ID.fullmatch(handoff_id) or handoff_id in handoff_ids:
            errors.append(f"handoffs[{index}] has invalid or duplicate id")
            continue
        handoff_ids.add(handoff_id)
        for field in ("name", "condition", "payload_or_state"):
            if not nonempty(handoff.get(field)):
                errors.append(f"handoff {handoff_id}.{field} must be non-empty")
        source, target = handoff.get("from"), handoff.get("to")
        if source not in leaves or target not in leaves:
            errors.append(f"handoff {handoff_id} endpoints must be leaf phases")
        elif source == target:
            errors.append(f"handoff {handoff_id} cannot self-loop")
        else:
            graph[source].add(target)
        if handoff.get("type") not in HANDOFF_TYPES:
            errors.append(f"handoff {handoff_id} has invalid type")
        refs = handoff.get("evidence_refs")
        if not isinstance(refs, list):
            errors.append(f"handoff {handoff_id}.evidence_refs must be an array")
            refs = []
        for ref in refs:
            match = FLOW_REF.fullmatch(ref) if isinstance(ref, str) else None
            if not match or match.group(1) not in source_ids or match.group(2) not in source_facts.get(match.group(1), set()):
                errors.append(f"handoff {handoff_id} has invalid evidence ref {ref!r}")
        if not isinstance(handoff.get("correlation_keys"), list):
            errors.append(f"handoff {handoff_id}.correlation_keys must be an array")
        evidence = handoff.get("evidence_status")
        if evidence not in EVIDENCE:
            errors.append(f"handoff {handoff_id} has invalid evidence_status")
        if not isinstance(handoff.get("critical"), bool):
            errors.append(f"handoff {handoff_id}.critical must be boolean")
        if evidence in {"code-confirmed", "both-confirmed"} and not refs:
            errors.append(f"handoff {handoff_id} requires evidence_refs")
        if evidence in {"developer-confirmed", "both-confirmed"} and not nonempty(handoff.get("decision_ref")):
            errors.append(f"handoff {handoff_id} requires decision_ref")

    if isinstance(entry_phase, str):
        from_entry = reachable(graph, {entry_phase})
        reverse = {leaf: set() for leaf in leaves}
        for source, targets in graph.items():
            for target in targets:
                reverse[target].add(source)
        to_end = reachable(reverse, {endpoint for endpoint in end_phases if endpoint in leaves})
        for endpoint in end_phases:
            if endpoint not in from_entry:
                errors.append(f"end phase {endpoint!r} is not reachable from entry_phase")
        for phase_id in leaves:
            phase = phase_by_id.get(phase_id, {})
            if phase.get("critical") is True and (phase_id not in from_entry or phase_id not in to_end):
                errors.append(f"critical leaf phase {phase_id} is not on an entry-to-end path")

    for index, anchor in enumerate(anchors):
        if not isinstance(anchor, dict) or anchor.get("relation") not in RELATIONS:
            continue
        source_flow, target_flow = anchor.get("from_flow"), anchor.get("to_flow")
        if anchor.get("relation") == "follows":
            source_flow, target_flow = target_flow, source_flow
        sources = {phase_id for phase_id in leaves if source_flow in phase_flows.get(phase_id, set())}
        targets = {phase_id for phase_id in leaves if target_flow in phase_flows.get(phase_id, set())}
        if not sources or not targets or not (reachable(graph, sources) & targets):
            errors.append(f"anchor relation {index} is not supported by a directed handoff path")

    unresolved = contract.get("unresolved")
    if not isinstance(unresolved, list):
        errors.append("unresolved must be an array")
        unresolved = []
    for index, item in enumerate(unresolved):
        if not isinstance(item, dict):
            errors.append(f"unresolved[{index}] must be an object")
            continue
        for field in ("id", "summary", "resolution"):
            if not nonempty(item.get(field)):
                errors.append(f"unresolved[{index}].{field} must be non-empty")
        if not isinstance(item.get("blocking"), bool):
            errors.append(f"unresolved[{index}].blocking must be boolean")
    for field in ("invariants", "decisions"):
        if not isinstance(contract.get(field), list):
            errors.append(f"{field} must be an array")

    approval = contract.get("approval") if isinstance(contract.get("approval"), dict) else {}
    if require_frozen or contract.get("status") == "frozen":
        if contract.get("status") != "frozen":
            errors.append("status must be frozen")
        if approval.get("status") != "approved" or not nonempty(approval.get("decision_ref")) or not nonempty(approval.get("approved_at")):
            errors.append("frozen contract requires explicit approval")
        if any(isinstance(item, dict) and item.get("blocking") is True for item in unresolved):
            errors.append("blocking unresolved items remain")
        for item in [*phases, *handoffs]:
            if isinstance(item, dict) and item.get("critical") is True and item.get("evidence_status") in {"inferred", "unresolved"}:
                errors.append(f"critical item {item.get('id')} is not confirmed")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("contract", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--require-frozen", action="store_true")
    args = parser.parse_args()
    errors: list[str] = []
    contract = load_json(args.contract, "macro contract", errors)
    errors.extend(audit(contract, args.contract, args.require_frozen))
    if args.report:
        errors.extend(audit_report(args.report, contract.get("phases", []), contract.get("handoffs", [])))
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"OK: valid macro flow contract: {args.contract}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
