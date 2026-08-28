#!/usr/bin/env python3
"""Validate a versioned macro business-flow contract."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


STATUSES = {"draft", "developer-review", "frozen", "superseded"}
EVIDENCE = {
    "code-confirmed",
    "developer-confirmed",
    "both-confirmed",
    "inferred",
    "unresolved",
}
HANDOFF_TYPES = {"sync", "async", "event", "manual", "shared-state", "external"}
M_ID = re.compile(r"M1(?:\.\d+){0,2}$")
H_ID = re.compile(r"H[1-9]\d*$")
FLOW_REF = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]*)/(N\d+(?:\.\d+)*)$")


def nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def load(path: Path, errors: list[str]) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"cannot load {path}: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append("contract must be a JSON object")
        return {}
    return value


def disconnected_critical_leaves(phases: list[dict], handoffs: list[dict]) -> list[str]:
    phase_ids = {phase.get("id") for phase in phases if isinstance(phase, dict)}
    parents = {
        phase.get("parent")
        for phase in phases
        if isinstance(phase, dict) and phase.get("parent") in phase_ids
    }
    leaves = sorted(
        phase.get("id")
        for phase in phases
        if isinstance(phase, dict)
        and phase.get("critical") is True
        and phase.get("id") not in parents
    )
    if len(leaves) < 2:
        return []
    graph = {leaf: set() for leaf in leaves}

    def leaves_under(phase_id: object) -> list[str]:
        if not isinstance(phase_id, str):
            return []
        return [leaf for leaf in leaves if leaf == phase_id or leaf.startswith(phase_id + ".")]

    for handoff in handoffs:
        if not isinstance(handoff, dict):
            continue
        left, right = leaves_under(handoff.get("from")), leaves_under(handoff.get("to"))
        for source in left:
            for target in right:
                graph[source].add(target)
                graph[target].add(source)
    reached = {leaves[0]}
    frontier = [leaves[0]]
    while frontier:
        node = frontier.pop()
        for target in graph[node] - reached:
            reached.add(target)
            frontier.append(target)
    return sorted(set(leaves) - reached)


def audit(contract: dict, require_frozen: bool) -> list[str]:
    errors: list[str] = []
    for field in (
        "schema_version",
        "macro_flow_id",
        "version",
        "status",
        "developer_brief",
        "source_flows",
        "phases",
        "handoffs",
        "unresolved",
        "approval",
    ):
        if field not in contract:
            errors.append(f"missing field: {field}")

    if contract.get("schema_version") != 1:
        errors.append("schema_version must be 1")
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
    for field in ("included_flow_ids", "anchor_relations"):
        if not isinstance(brief.get(field), list) or not brief[field]:
            errors.append(f"developer_brief.{field} must be a non-empty array")
    brief_flow_ids = {
        value for value in brief.get("included_flow_ids", []) if isinstance(value, str) and value
    }
    anchors = brief.get("anchor_relations", [])

    sources = contract.get("source_flows")
    source_ids: set[str] = set()
    if not isinstance(sources, list) or not sources:
        errors.append("source_flows must be a non-empty array")
        sources = []
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            errors.append(f"source_flows[{index}] must be an object")
            continue
        flow_id = source.get("flow_id")
        if not nonempty(flow_id):
            errors.append(f"source_flows[{index}].flow_id must be non-empty")
        elif flow_id in source_ids:
            errors.append(f"duplicate flow_id: {flow_id}")
        else:
            source_ids.add(flow_id)
        for field in ("report", "baseline"):
            if not nonempty(source.get(field)):
                errors.append(f"source_flows[{index}].{field} must be non-empty")
    if brief_flow_ids != source_ids:
        errors.append(
            "developer_brief.included_flow_ids must equal source flow IDs; "
            f"brief-only={sorted(brief_flow_ids - source_ids)}, "
            f"source-only={sorted(source_ids - brief_flow_ids)}"
        )
    for index, anchor in enumerate(anchors):
        if not isinstance(anchor, dict):
            errors.append(f"developer_brief.anchor_relations[{index}] must be an object")
            continue
        source, target = anchor.get("from_flow"), anchor.get("to_flow")
        if source not in source_ids or target not in source_ids:
            errors.append(f"anchor relation {index} references an unknown flow")
        if source == target:
            errors.append(f"anchor relation {index} cannot connect a flow to itself")
        for field in ("relation", "decision_ref"):
            if not nonempty(anchor.get(field)):
                errors.append(f"anchor relation {index}.{field} must be non-empty")

    phases = contract.get("phases")
    phase_ids: set[str] = set()
    if not isinstance(phases, list) or not phases:
        errors.append("phases must be a non-empty array")
        phases = []
    for index, phase in enumerate(phases):
        if not isinstance(phase, dict):
            errors.append(f"phases[{index}] must be an object")
            continue
        phase_id = phase.get("id")
        if not isinstance(phase_id, str) or not M_ID.fullmatch(phase_id):
            errors.append(f"invalid phase id: {phase_id!r}")
            continue
        if phase_id in phase_ids:
            errors.append(f"duplicate phase id: {phase_id}")
        phase_ids.add(phase_id)
        parent = phase.get("parent")
        expected = None if phase_id == "M1" else phase_id.rsplit(".", 1)[0]
        if parent != expected:
            errors.append(f"phase {phase_id} parent must be {expected!r}")
        for field in ("name", "entry", "exit"):
            if not nonempty(phase.get(field)):
                errors.append(f"phase {phase_id}.{field} must be non-empty")
        refs = phase.get("flow_refs")
        if not isinstance(refs, list):
            errors.append(f"phase {phase_id}.flow_refs must be an array")
            refs = []
        else:
            for ref in refs:
                match = FLOW_REF.fullmatch(ref) if isinstance(ref, str) else None
                if not match:
                    errors.append(f"phase {phase_id} has invalid flow reference: {ref!r}")
                elif match.group(1) not in source_ids:
                    errors.append(f"phase {phase_id} references unknown flow: {ref!r}")
        evidence_status = phase.get("evidence_status")
        if evidence_status not in EVIDENCE:
            errors.append(f"phase {phase_id} has invalid evidence_status")
        if not isinstance(phase.get("critical"), bool):
            errors.append(f"phase {phase_id}.critical must be boolean")
        if evidence_status in {"code-confirmed", "both-confirmed"} and not refs:
            errors.append(f"phase {phase_id} requires code flow_refs")
        if evidence_status in {"developer-confirmed", "both-confirmed"} and not nonempty(
            phase.get("decision_ref")
        ):
            errors.append(f"phase {phase_id} requires decision_ref")
    if "M1" not in phase_ids:
        errors.append("root phase M1 is required")
    for phase_id in phase_ids:
        if "." in phase_id and phase_id.rsplit(".", 1)[0] not in phase_ids:
            errors.append(f"phase {phase_id} has a missing parent")

    handoffs = contract.get("handoffs")
    handoff_ids: set[str] = set()
    if not isinstance(handoffs, list):
        errors.append("handoffs must be an array")
        handoffs = []
    for index, handoff in enumerate(handoffs):
        if not isinstance(handoff, dict):
            errors.append(f"handoffs[{index}] must be an object")
            continue
        handoff_id = handoff.get("id")
        if not isinstance(handoff_id, str) or not H_ID.fullmatch(handoff_id):
            errors.append(f"invalid handoff id: {handoff_id!r}")
            continue
        if handoff_id in handoff_ids:
            errors.append(f"duplicate handoff id: {handoff_id}")
        handoff_ids.add(handoff_id)
        for endpoint in ("from", "to"):
            if handoff.get(endpoint) not in phase_ids:
                errors.append(f"handoff {handoff_id} has unknown {endpoint}: {handoff.get(endpoint)!r}")
        if handoff.get("type") not in HANDOFF_TYPES:
            errors.append(f"handoff {handoff_id} has invalid type")
        if handoff.get("evidence_status") not in EVIDENCE:
            errors.append(f"handoff {handoff_id} has invalid evidence_status")
        if not isinstance(handoff.get("critical"), bool):
            errors.append(f"handoff {handoff_id}.critical must be boolean")
        for field in ("correlation_keys", "evidence_refs"):
            if not isinstance(handoff.get(field), list):
                errors.append(f"handoff {handoff_id}.{field} must be an array")
        if handoff.get("evidence_status") in {"code-confirmed", "both-confirmed"} and not handoff.get(
            "evidence_refs"
        ):
            errors.append(f"handoff {handoff_id} requires code evidence_refs")
        for ref in handoff.get("evidence_refs", []):
            match = FLOW_REF.fullmatch(ref) if isinstance(ref, str) else None
            if not match:
                errors.append(f"handoff {handoff_id} has invalid evidence reference: {ref!r}")
            elif match.group(1) not in source_ids:
                errors.append(f"handoff {handoff_id} references unknown evidence flow: {ref!r}")
        if handoff.get("evidence_status") in {"developer-confirmed", "both-confirmed"} and not nonempty(
            handoff.get("decision_ref")
        ):
            errors.append(f"handoff {handoff_id} requires decision_ref")

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
    approval = contract.get("approval")
    if not isinstance(approval, dict):
        errors.append("approval must be an object")
        approval = {}

    if require_frozen or contract.get("status") == "frozen":
        if contract.get("status") != "frozen":
            errors.append("status must be frozen")
        if (
            approval.get("status") != "approved"
            or not nonempty(approval.get("decision_ref"))
            or not nonempty(approval.get("approved_at"))
        ):
            errors.append("frozen contract requires explicit decision_ref and approved_at")
        for handoff in handoffs:
            if handoff.get("critical") is True and handoff.get("evidence_status") in {
                "inferred",
                "unresolved",
            }:
                errors.append(f"critical handoff {handoff.get('id')} is not confirmed")
            if (
                handoff.get("critical") is False
                and handoff.get("evidence_status") in {"inferred", "unresolved"}
                and not nonempty(handoff.get("noncritical_reason"))
            ):
                errors.append(
                    f"noncritical handoff {handoff.get('id')} requires noncritical_reason"
                )
        for phase in phases:
            if (
                isinstance(phase, dict)
                and phase.get("critical") is True
                and phase.get("evidence_status") in {"inferred", "unresolved"}
            ):
                errors.append(f"critical phase {phase.get('id')} is not confirmed")
            if (
                isinstance(phase, dict)
                and phase.get("critical") is False
                and phase.get("evidence_status") in {"inferred", "unresolved"}
                and not nonempty(phase.get("noncritical_reason"))
            ):
                errors.append(f"noncritical phase {phase.get('id')} requires noncritical_reason")
        if any(isinstance(item, dict) and item.get("blocking") is True for item in unresolved):
            errors.append("blocking unresolved items remain")
        disconnected = disconnected_critical_leaves(phases, handoffs)
        if disconnected:
            errors.append(
                "critical leaf phases are disconnected from the handoff graph: "
                + ", ".join(disconnected)
            )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("contract", type=Path)
    parser.add_argument("--require-frozen", action="store_true")
    args = parser.parse_args()
    errors: list[str] = []
    contract = load(args.contract, errors)
    errors.extend(audit(contract, args.require_frozen))
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"OK: valid macro flow contract: {args.contract}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
