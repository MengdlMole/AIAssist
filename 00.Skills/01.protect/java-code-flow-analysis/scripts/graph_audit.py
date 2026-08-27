#!/usr/bin/env python3
"""Merge and validate deep-mode Java call-graph JSON fragments."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


NODE_STATES = {
    "discovered",
    "claimed",
    "expanded",
    "partial",
    "folded",
    "boundary",
    "out-of-scope",
    "unresolved",
}
EVIDENCE = {"code-confirmed", "runtime-confirmed", "inferred", "unknown"}
EVIDENCE_BASIS = {
    "project-source",
    "configuration-binding",
    "generated-contract",
    "framework-contract",
    "runtime-evidence",
}
EDGE_TYPES = {
    "sync",
    "async",
    "event",
    "mq",
    "rpc",
    "db",
    "aop",
    "callback",
    "return",
    "exception",
}
CONFIDENCE = {"certain", "configured", "inferred", "unknown"}
RESOLUTION = {"resolved", "boundary", "excluded", "unresolved"}
OPEN_STATES = {"discovered", "claimed", "partial"}
LOG_SOURCES = {"code", "aspect", "filter", "interceptor", "wrapper"}
LOG_EVENTS = {
    "arrival",
    "decision",
    "handoff",
    "external-result",
    "state-change",
    "failure",
}
LOG_TIMINGS = {"before", "after-return", "after-commit", "on-exception", "finally"}
EXCEPTION_MECHANISMS = {"catch", "advice", "listener-error-callback", "retry-hook"}
LOG_LEVELS = {"TRACE", "DEBUG", "INFO", "WARN", "ERROR"}


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def require_fields(
    value: dict[str, Any], fields: tuple[str, ...], label: str, errors: list[str]
) -> None:
    for field in fields:
        if field not in value:
            fail(errors, f"{label}: missing field '{field}'")


def load_fragment(path: Path, errors: list[str]) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(errors, f"{path}: cannot load JSON: {exc}")
        return None
    if not isinstance(value, dict):
        fail(errors, f"{path}: top-level JSON must be an object")
        return None
    return value


def audit_evidence_basis(value: Any, label: str, errors: list[str]) -> None:
    if not isinstance(value, list) or not value:
        fail(errors, f"{label}: evidence_basis must be a non-empty array")
        return
    invalid = [item for item in value if item not in EVIDENCE_BASIS]
    if invalid:
        fail(errors, f"{label}: invalid evidence_basis {invalid!r}")


def audit_node(node: Any, source: Path, errors: list[str]) -> str | None:
    if not isinstance(node, dict):
        fail(errors, f"{source}: node must be an object")
        return None
    require_fields(
        node,
        (
            "key",
            "state",
            "direct_calls_complete",
            "evidence",
            "evidence_basis",
            "file_symbol",
            "role",
            "context",
            "summary",
        ),
        f"{source}: node",
        errors,
    )
    key = node.get("key")
    if not isinstance(key, str) or not key.strip():
        fail(errors, f"{source}: node key must be a non-empty string")
        return None
    state = node.get("state")
    if state not in NODE_STATES:
        fail(errors, f"{source}: node {key}: invalid state {state!r}")
    if node.get("evidence") not in EVIDENCE:
        fail(errors, f"{source}: node {key}: invalid evidence {node.get('evidence')!r}")
    audit_evidence_basis(node.get("evidence_basis"), f"{source}: node {key}", errors)
    direct_complete = node.get("direct_calls_complete")
    if not isinstance(direct_complete, bool):
        fail(errors, f"{source}: node {key}: direct_calls_complete must be boolean")
    if state == "expanded" and direct_complete is not True:
        fail(errors, f"{source}: expanded node {key} must have direct_calls_complete=true")
    for field in ("file_symbol", "role", "context", "summary"):
        if not isinstance(node.get(field), str) or not node[field].strip():
            fail(errors, f"{source}: node {key}: {field} must be a non-empty string")
    return key


def audit_edge(edge: Any, source: Path, errors: list[str]) -> str | None:
    if not isinstance(edge, dict):
        fail(errors, f"{source}: edge must be an object")
        return None
    require_fields(
        edge,
        (
            "edge_id",
            "from",
            "to",
            "type",
            "confidence",
            "resolution_status",
            "callsite",
            "condition",
            "evidence_summary",
            "evidence_basis",
        ),
        f"{source}: edge",
        errors,
    )
    edge_id = edge.get("edge_id")
    if not isinstance(edge_id, str) or not edge_id.strip():
        fail(errors, f"{source}: edge_id must be a non-empty string")
        return None
    if edge.get("type") not in EDGE_TYPES:
        fail(errors, f"{source}: edge {edge_id}: invalid type {edge.get('type')!r}")
    if edge.get("confidence") not in CONFIDENCE:
        fail(errors, f"{source}: edge {edge_id}: invalid confidence {edge.get('confidence')!r}")
    if edge.get("resolution_status") not in RESOLUTION:
        fail(
            errors,
            f"{source}: edge {edge_id}: invalid resolution_status {edge.get('resolution_status')!r}",
        )
    for field in ("from", "to", "callsite", "condition", "evidence_summary"):
        if not isinstance(edge.get(field), str) or not edge[field].strip():
            fail(errors, f"{source}: edge {edge_id}: {field} must be a non-empty string")
    audit_evidence_basis(edge.get("evidence_basis"), f"{source}: edge {edge_id}", errors)
    return edge_id


def audit_log(log: Any, source: Path, errors: list[str]) -> str | None:
    if not isinstance(log, dict):
        fail(errors, f"{source}: key_log must be an object")
        return None
    fields = (
        "log_id",
        "node_key",
        "source_type",
        "event_type",
        "timing",
        "relative_to",
        "level",
        "stable_template",
        "condition",
        "correlation_fields",
        "proves",
        "does_not_prove",
        "evidence",
        "evidence_basis",
        "sensitive_risk",
    )
    require_fields(log, fields, f"{source}: key_log", errors)
    log_id = log.get("log_id")
    if not isinstance(log_id, str) or not log_id.strip():
        fail(errors, f"{source}: log_id must be a non-empty string")
        return None
    enum_fields = (
        ("source_type", LOG_SOURCES),
        ("event_type", LOG_EVENTS),
        ("timing", LOG_TIMINGS),
        ("level", LOG_LEVELS),
        ("evidence", EVIDENCE),
    )
    for field, allowed in enum_fields:
        if log.get(field) not in allowed:
            fail(errors, f"{source}: key_log {log_id}: invalid {field} {log.get(field)!r}")
    audit_evidence_basis(log.get("evidence_basis"), f"{source}: key_log {log_id}", errors)
    if log.get("timing") == "on-exception" and log.get("exception_mechanism") not in EXCEPTION_MECHANISMS:
        fail(
            errors,
            f"{source}: key_log {log_id}: on-exception requires exception_mechanism",
        )
    for field in (
        "node_key",
        "relative_to",
        "stable_template",
        "condition",
        "proves",
        "does_not_prove",
        "sensitive_risk",
    ):
        if not isinstance(log.get(field), str) or not log[field].strip():
            fail(errors, f"{source}: key_log {log_id}: {field} must be a non-empty string")
    correlation_fields = log.get("correlation_fields")
    if not isinstance(correlation_fields, list) or any(
        not isinstance(item, str) or not item.strip() for item in correlation_fields
    ):
        fail(errors, f"{source}: key_log {log_id}: correlation_fields must be an array of strings")
    return log_id


def merge_fragments(
    paths: list[Path], require_analyzed: bool, require_closed: bool
) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}
    roots: list[str] = []
    coverage: list[str] = []
    frontier: list[Any] = []
    key_logs: dict[str, dict[str, Any]] = {}
    data_flows: list[Any] = []
    unresolved: list[Any] = []

    for path in paths:
        fragment = load_fragment(path, errors)
        if fragment is None:
            continue
        require_fields(
            fragment,
            ("root_key", "coverage", "nodes", "edges", "key_logs", "data_flows", "unresolved", "frontier"),
            str(path),
            errors,
        )
        root_key = fragment.get("root_key")
        if isinstance(root_key, str) and root_key:
            roots.append(root_key)
        else:
            fail(errors, f"{path}: root_key must be a non-empty string")
        fragment_coverage = fragment.get("coverage")
        if fragment_coverage not in {"expanded", "partial", "blocked"}:
            fail(errors, f"{path}: invalid coverage {fragment_coverage!r}")
        else:
            coverage.append(fragment_coverage)

        fragment_nodes = fragment.get("nodes", [])
        if not isinstance(fragment_nodes, list):
            fail(errors, f"{path}: nodes must be an array")
            fragment_nodes = []
        for node in fragment_nodes:
            key = audit_node(node, path, errors)
            if key is None:
                continue
            if key in nodes and nodes[key] != node:
                fail(errors, f"{path}: conflicting duplicate node key {key}")
            else:
                nodes[key] = node

        fragment_edges = fragment.get("edges", [])
        if not isinstance(fragment_edges, list):
            fail(errors, f"{path}: edges must be an array")
            fragment_edges = []
        for edge in fragment_edges:
            edge_id = audit_edge(edge, path, errors)
            if edge_id is None:
                continue
            if edge_id in edges:
                fail(errors, f"{path}: duplicate edge_id {edge_id}")
            else:
                edges[edge_id] = edge

        fragment_logs = fragment.get("key_logs", [])
        if not isinstance(fragment_logs, list):
            fail(errors, f"{path}: key_logs must be an array")
            fragment_logs = []
        for log in fragment_logs:
            log_id = audit_log(log, path, errors)
            if log_id is None:
                continue
            if log_id in key_logs:
                fail(errors, f"{path}: duplicate log_id {log_id}")
            else:
                key_logs[log_id] = log

        for field, target in (
            ("frontier", frontier),
            ("data_flows", data_flows),
            ("unresolved", unresolved),
        ):
            values = fragment.get(field, [])
            if not isinstance(values, list):
                fail(errors, f"{path}: {field} must be an array")
            else:
                target.extend(values)

    known_nodes = set(nodes)
    for root in roots:
        if root not in known_nodes:
            fail(errors, f"root_key {root!r} is not a known node")
    for edge_id, edge in edges.items():
        caller = edge.get("from")
        target = edge.get("to")
        resolution = edge.get("resolution_status")
        if caller not in known_nodes:
            fail(errors, f"edge {edge_id}: unknown caller node {caller!r}")
        if resolution == "resolved" and target not in known_nodes:
            fail(errors, f"edge {edge_id}: resolved target {target!r} is not a known node")
        if resolution in {"boundary", "unresolved"}:
            expected_prefix = f"{resolution}:"
            if not isinstance(target, str) or not target.startswith(expected_prefix):
                fail(errors, f"edge {edge_id}: {resolution} target must start with '{expected_prefix}'")

    for log_id, log in key_logs.items():
        if log.get("node_key") not in known_nodes:
            fail(errors, f"key_log {log_id}: unknown node_key {log.get('node_key')!r}")

    if require_analyzed or require_closed:
        open_nodes = sorted(key for key, node in nodes.items() if node.get("state") in OPEN_STATES)
        if open_nodes:
            fail(errors, f"completion audit: open node states remain: {', '.join(open_nodes)}")
        if frontier:
            fail(errors, f"completion audit: frontier is not empty ({len(frontier)} item(s))")
        if any(item != "expanded" for item in coverage):
            fail(errors, "analysis audit: every fragment coverage must be 'expanded'")

    if require_closed:
        unresolved_nodes = sorted(
            key for key, node in nodes.items() if node.get("state") == "unresolved"
        )
        if unresolved_nodes:
            fail(errors, "closure audit: unresolved nodes remain: " + ", ".join(unresolved_nodes))
        unresolved_edges = sorted(
            edge_id
            for edge_id, edge in edges.items()
            if edge.get("resolution_status") == "unresolved"
        )
        if unresolved_edges:
            fail(
                errors,
                "closure audit: unresolved edges remain: " + ", ".join(unresolved_edges),
            )
        if unresolved:
            fail(errors, f"closure audit: unresolved list is not empty ({len(unresolved)} item(s))")

    merged = {
        "root_keys": sorted(set(roots)),
        "coverage": coverage,
        "nodes": [nodes[key] for key in sorted(nodes)],
        "edges": [edges[key] for key in sorted(edges)],
        "key_logs": [key_logs[key] for key in sorted(key_logs)],
        "data_flows": data_flows,
        "unresolved": unresolved,
        "frontier": frontier,
    }
    return merged, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fragments", nargs="+", type=Path, help="JSON fragment files")
    parser.add_argument("--output", type=Path, help="write merged JSON to this path")
    parser.add_argument(
        "--require-analyzed",
        action="store_true",
        help="require empty frontier/partial; documented unresolved items are allowed",
    )
    parser.add_argument(
        "--require-closed",
        action="store_true",
        help="require analyzed scope with no unresolved nodes or edges",
    )
    parser.add_argument("--require-complete", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    require_closed = args.require_closed or args.require_complete
    merged, errors = merge_fragments(
        args.fragments,
        require_analyzed=args.require_analyzed or require_closed,
        require_closed=require_closed,
    )
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    rendered = json.dumps(merged, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
