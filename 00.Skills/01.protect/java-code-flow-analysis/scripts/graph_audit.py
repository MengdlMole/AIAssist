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
CONFIG_CURRENT_SOURCES = {"developer-input-required", "developer-provided"}
DB_OPERATIONS = {"SELECT", "SELECT_LOCK", "INSERT", "UPDATE", "DELETE", "UPSERT", "MERGE", "CALL"}


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
            "semantic_scan_complete",
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
    semantic_complete = node.get("semantic_scan_complete")
    if not isinstance(semantic_complete, bool):
        fail(errors, f"{source}: node {key}: semantic_scan_complete must be boolean")
    if state == "expanded":
        if direct_complete is not True:
            fail(errors, f"{source}: expanded node {key} must have direct_calls_complete=true")
        if semantic_complete is not True:
            fail(errors, f"{source}: expanded node {key} must have semantic_scan_complete=true")
    if state == "folded" and (
        not isinstance(node.get("fold_reason"), str) or not node["fold_reason"].strip()
    ):
        fail(errors, f"{source}: folded node {key} requires a non-empty fold_reason")
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
    if edge.get("type") in {"async", "event", "mq"}:
        for field in ("channel", "payload", "binding_reference", "failure_semantics"):
            if not isinstance(edge.get(field), str) or not edge[field].strip():
                fail(
                    errors,
                    f"{source}: edge {edge_id}: asynchronous edge requires non-empty {field}",
                )
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


def audit_configuration(config: Any, source: Path, errors: list[str]) -> str | None:
    if not isinstance(config, dict):
        fail(errors, f"{source}: configuration must be an object")
        return None
    fields = (
        "name",
        "description",
        "effect",
        "default_value",
        "current_value",
        "current_value_source",
        "affected_node_keys",
        "affected_rule_keys",
        "declaration_reference",
        "read_reference",
        "evidence",
        "evidence_basis",
    )
    require_fields(config, fields, f"{source}: configuration", errors)
    for field in (
        "name",
        "description",
        "effect",
        "default_value",
        "current_value",
        "declaration_reference",
        "read_reference",
    ):
        if not isinstance(config.get(field), str) or not config[field].strip():
            fail(errors, f"{source}: configuration: {field} must be a non-empty string")
    name = config.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    current_source = config.get("current_value_source")
    if current_source not in CONFIG_CURRENT_SOURCES:
        fail(errors, f"{source}: configuration {name}: invalid current_value_source")
    if current_source == "developer-input-required" and config.get("current_value") != current_source:
        fail(
            errors,
            f"{source}: configuration {name}: missing developer value must use "
            "current_value='developer-input-required'",
        )
    if current_source == "developer-provided" and config.get("current_value") == "developer-input-required":
        fail(errors, f"{source}: configuration {name}: developer-provided value is missing")
    if config.get("evidence") not in EVIDENCE:
        fail(errors, f"{source}: configuration {name}: invalid evidence")
    audit_evidence_basis(config.get("evidence_basis"), f"{source}: configuration {name}", errors)
    node_keys = config.get("affected_node_keys")
    if not isinstance(node_keys, list) or not node_keys or any(
        not isinstance(item, str) or not item.strip() for item in node_keys
    ):
        fail(errors, f"{source}: configuration {name}: affected_node_keys must be non-empty strings")
    rule_keys = config.get("affected_rule_keys")
    if not isinstance(rule_keys, list) or any(
        not isinstance(item, str) or not item.strip() for item in rule_keys
    ):
        fail(errors, f"{source}: configuration {name}: affected_rule_keys must be strings")
    read_reference = config.get("read_reference")
    return f"{name}@{read_reference}" if isinstance(read_reference, str) else None


def audit_database_operation(operation: Any, source: Path, errors: list[str]) -> str | None:
    if not isinstance(operation, dict):
        fail(errors, f"{source}: database_operation must be an object")
        return None
    fields = (
        "operation_id",
        "edge_id",
        "node_key",
        "table",
        "operation",
        "business_purpose",
        "condition",
        "key_fields",
        "transaction_context",
        "result_effect",
        "sql_reference",
        "mapping_reference",
        "core",
        "core_reason",
        "evidence",
        "evidence_basis",
    )
    require_fields(operation, fields, f"{source}: database_operation", errors)
    operation_id = operation.get("operation_id")
    if not isinstance(operation_id, str) or not operation_id.strip():
        fail(errors, f"{source}: database_operation operation_id must be non-empty")
        return None
    for field in (
        "edge_id",
        "node_key",
        "table",
        "business_purpose",
        "condition",
        "transaction_context",
        "result_effect",
        "sql_reference",
        "mapping_reference",
        "core_reason",
    ):
        if not isinstance(operation.get(field), str) or not operation[field].strip():
            fail(errors, f"{source}: database_operation {operation_id}: {field} must be non-empty")
    if operation.get("operation") not in DB_OPERATIONS:
        fail(errors, f"{source}: database_operation {operation_id}: invalid operation")
    if not isinstance(operation.get("core"), bool):
        fail(errors, f"{source}: database_operation {operation_id}: core must be boolean")
    if operation.get("evidence") not in EVIDENCE:
        fail(errors, f"{source}: database_operation {operation_id}: invalid evidence")
    audit_evidence_basis(
        operation.get("evidence_basis"), f"{source}: database_operation {operation_id}", errors
    )
    key_fields = operation.get("key_fields")
    if not isinstance(key_fields, list) or any(
        not isinstance(item, str) or not item.strip() for item in key_fields
    ):
        fail(errors, f"{source}: database_operation {operation_id}: key_fields must be strings")
    return operation_id


def audit_business_fact(
    value: Any,
    source: Path,
    kind: str,
    id_field: str,
    string_fields: tuple[str, ...],
    list_fields: tuple[str, ...],
    errors: list[str],
) -> str | None:
    if not isinstance(value, dict):
        fail(errors, f"{source}: {kind} must be an object")
        return None
    require_fields(
        value,
        (id_field, *string_fields, *list_fields, "evidence", "evidence_basis"),
        f"{source}: {kind}",
        errors,
    )
    item_id = value.get(id_field)
    if not isinstance(item_id, str) or not item_id.strip():
        fail(errors, f"{source}: {kind} {id_field} must be non-empty")
        return None
    for field in string_fields:
        if not isinstance(value.get(field), str) or not value[field].strip():
            fail(errors, f"{source}: {kind} {item_id}: {field} must be non-empty")
    for field in list_fields:
        items = value.get(field)
        if not isinstance(items, list) or not items or any(
            not isinstance(item, str) or not item.strip() for item in items
        ):
            fail(errors, f"{source}: {kind} {item_id}: {field} must be non-empty strings")
    if value.get("evidence") not in EVIDENCE:
        fail(errors, f"{source}: {kind} {item_id}: invalid evidence")
    audit_evidence_basis(value.get("evidence_basis"), f"{source}: {kind} {item_id}", errors)
    return item_id


def audit_decision(value: Any, source: Path, errors: list[str]) -> str | None:
    return audit_business_fact(
        value,
        source,
        "decision_point",
        "decision_id",
        (
            "node_key",
            "business_question",
            "condition",
            "evaluation_order",
            "matched_target",
            "unmatched_target",
            "business_effect",
            "reference",
        ),
        ("operand_refs",),
        errors,
    )


def audit_key_field(value: Any, source: Path, errors: list[str]) -> str | None:
    return audit_business_fact(
        value,
        source,
        "key_field",
        "field_key",
        (
            "name",
            "source",
            "business_meaning",
            "flow_effect",
            "transform_rule",
            "destination",
            "reference",
        ),
        ("node_keys",),
        errors,
    )


def audit_business_rule(value: Any, source: Path, errors: list[str]) -> str | None:
    return audit_business_fact(
        value,
        source,
        "business_rule",
        "rule_key",
        (
            "name",
            "business_meaning",
            "applicability",
            "calculation",
            "output",
            "boundary_semantics",
            "business_effect",
            "reference",
        ),
        ("node_keys", "input_refs"),
        errors,
    )


def validate_fact_ref(
    ref: Any,
    label: str,
    allowed: dict[str, set[str] | None],
    errors: list[str],
) -> None:
    if not isinstance(ref, str) or ":" not in ref:
        fail(errors, f"{label}: reference must use <kind>:<id>")
        return
    kind, value = ref.split(":", 1)
    if kind not in allowed or not value.strip():
        fail(errors, f"{label}: invalid reference {ref!r}")
        return
    known = allowed[kind]
    if known is not None and value not in known:
        fail(errors, f"{label}: unknown {kind} reference {value!r}")


def is_resolved_successor(
    start: str, target: str, edges: dict[str, dict[str, Any]]
) -> bool:
    """Return whether target is reachable after start through resolved call edges."""
    if start == target:
        return False
    adjacency: dict[str, set[str]] = {}
    for edge in edges.values():
        if edge.get("resolution_status") != "resolved":
            continue
        source, destination = edge.get("from"), edge.get("to")
        if isinstance(source, str) and isinstance(destination, str):
            adjacency.setdefault(source, set()).add(destination)
    pending = list(adjacency.get(start, ()))
    visited = {start}
    while pending:
        node = pending.pop()
        if node == target:
            return True
        if node in visited:
            continue
        visited.add(node)
        pending.extend(adjacency.get(node, ()))
    return False


def validate_decision_target_topology(
    ref: Any,
    decision_node: Any,
    label: str,
    edges: dict[str, dict[str, Any]],
    known_nodes: set[str],
    errors: list[str],
) -> None:
    """Ensure a branch target actually leaves the decision node."""
    if not isinstance(ref, str) or ":" not in ref or not isinstance(decision_node, str):
        return
    kind, value = ref.split(":", 1)
    if kind == "edge" and value in edges and edges[value].get("from") != decision_node:
        fail(errors, f"{label}: edge target must originate from decision node {decision_node!r}")
    elif kind == "node" and value in known_nodes and not is_resolved_successor(
        decision_node, value, edges
    ):
        fail(errors, f"{label}: node target must be a resolved successor of {decision_node!r}")


def merge_node(
    existing: dict[str, Any], incoming: dict[str, Any], source: Path, errors: list[str]
) -> dict[str, Any]:
    """Accept skeleton-to-detail progression while rejecting contradictory facts."""
    if existing == incoming:
        return existing
    key = str(existing.get("key"))
    if existing.get("file_symbol") != incoming.get("file_symbol"):
        fail(errors, f"{source}: conflicting file_symbol for node {key}")
        return existing
    rank = {"discovered": 0, "claimed": 1, "partial": 2}
    old_state, new_state = existing.get("state"), incoming.get("state")
    old_rank = rank.get(old_state, 3)
    new_rank = rank.get(new_state, 3)
    if old_rank == new_rank:
        fail(errors, f"{source}: conflicting duplicate node key {key}")
        return existing
    if old_rank == 3 or new_rank == 3:
        terminal = existing if old_rank == 3 else incoming
        return terminal
    return incoming if new_rank > old_rank else existing


def merge_fragments(
    paths: list[Path], require_analyzed: bool, require_closed: bool, entry_root: str | None = None
) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}
    roots: list[str] = []
    coverage: list[str] = []
    frontier: list[Any] = []
    key_logs: dict[str, dict[str, Any]] = {}
    decision_points: dict[str, dict[str, Any]] = {}
    key_fields: dict[str, dict[str, Any]] = {}
    business_rules: dict[str, dict[str, Any]] = {}
    database_operations: dict[str, dict[str, Any]] = {}
    configurations: dict[str, dict[str, Any]] = {}
    data_flows: list[Any] = []
    unresolved: list[Any] = []

    for path in paths:
        fragment = load_fragment(path, errors)
        if fragment is None:
            continue
        require_fields(
            fragment,
            (
                "root_key",
                "coverage",
                "nodes",
                "edges",
                "decision_points",
                "key_fields",
                "business_rules",
                "database_operations",
                "key_logs",
                "configurations",
                "data_flows",
                "unresolved",
                "frontier",
            ),
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
            nodes[key] = merge_node(nodes[key], node, path, errors) if key in nodes else node

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

        for field, target, audit_item, label in (
            ("decision_points", decision_points, audit_decision, "decision point"),
            ("key_fields", key_fields, audit_key_field, "key field"),
            ("business_rules", business_rules, audit_business_rule, "business rule"),
        ):
            values = fragment.get(field, [])
            if not isinstance(values, list):
                fail(errors, f"{path}: {field} must be an array")
                continue
            for value in values:
                item_id = audit_item(value, path, errors)
                if item_id is None:
                    continue
                if item_id in target and target[item_id] != value:
                    fail(errors, f"{path}: conflicting duplicate {label} {item_id}")
                else:
                    target[item_id] = value

        fragment_db_operations = fragment.get("database_operations", [])
        if not isinstance(fragment_db_operations, list):
            fail(errors, f"{path}: database_operations must be an array")
            fragment_db_operations = []
        for operation in fragment_db_operations:
            operation_id = audit_database_operation(operation, path, errors)
            if operation_id is None:
                continue
            if operation_id in database_operations and database_operations[operation_id] != operation:
                fail(errors, f"{path}: conflicting duplicate database operation {operation_id}")
            else:
                database_operations[operation_id] = operation

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

        fragment_configs = fragment.get("configurations", [])
        if not isinstance(fragment_configs, list):
            fail(errors, f"{path}: configurations must be an array")
            fragment_configs = []
        for config in fragment_configs:
            config_key = audit_configuration(config, path, errors)
            if config_key is None:
                continue
            if config_key in configurations and configurations[config_key] != config:
                fail(errors, f"{path}: conflicting duplicate configuration {config_key}")
            else:
                configurations[config_key] = config

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

    effective_entry_root = entry_root
    if require_analyzed or require_closed:
        unique_roots = sorted(set(roots))
        if effective_entry_root is None:
            if len(unique_roots) == 1:
                effective_entry_root = unique_roots[0]
            else:
                fail(errors, "analysis audit: multiple fragment roots require --entry-root")
        if effective_entry_root not in known_nodes:
            fail(errors, f"analysis audit: entry root {effective_entry_root!r} is not a known node")
        else:
            reachable = {effective_entry_root}
            changed = True
            while changed:
                changed = False
                for edge in edges.values():
                    if (
                        edge.get("resolution_status") == "resolved"
                        and edge.get("from") in reachable
                        and edge.get("to") in known_nodes
                        and edge.get("to") not in reachable
                    ):
                        reachable.add(edge["to"])
                        changed = True
            orphan_nodes = sorted(known_nodes - reachable)
            if orphan_nodes:
                fail(errors, "analysis audit: nodes unreachable from entry root: " + ", ".join(orphan_nodes))

    for log_id, log in key_logs.items():
        if log.get("node_key") not in known_nodes:
            fail(errors, f"key_log {log_id}: unknown node_key {log.get('node_key')!r}")
    for decision_id, decision in decision_points.items():
        if decision.get("node_key") not in known_nodes:
            fail(errors, f"decision_point {decision_id}: unknown node_key {decision.get('node_key')!r}")
    for field_key, field in key_fields.items():
        node_keys = field.get("node_keys")
        for node_key in node_keys if isinstance(node_keys, list) else []:
            if node_key not in known_nodes:
                fail(errors, f"key_field {field_key}: unknown node_key {node_key!r}")
    for rule_key, rule in business_rules.items():
        node_keys = rule.get("node_keys")
        for node_key in node_keys if isinstance(node_keys, list) else []:
            if node_key not in known_nodes:
                fail(errors, f"business_rule {rule_key}: unknown node_key {node_key!r}")
    configuration_names = {
        str(config.get("name")) for config in configurations.values() if config.get("name")
    }
    source_refs: dict[str, set[str] | None] = {
        "field": set(key_fields),
        "config": configuration_names,
        "rule": set(business_rules),
        "db": set(database_operations),
        "edge": set(edges),
        "node": known_nodes,
    }
    target_refs: dict[str, set[str] | None] = {
        "edge": set(edges),
        "node": known_nodes,
        "result": None,
        "boundary": None,
    }
    for decision_id, decision in decision_points.items():
        operand_refs = decision.get("operand_refs")
        for ref in operand_refs if isinstance(operand_refs, list) else []:
            validate_fact_ref(ref, f"decision_point {decision_id} operand", source_refs, errors)
        validate_fact_ref(
            decision.get("matched_target"),
            f"decision_point {decision_id} matched_target",
            target_refs,
            errors,
        )
        validate_decision_target_topology(
            decision.get("matched_target"),
            decision.get("node_key"),
            f"decision_point {decision_id} matched_target",
            edges,
            known_nodes,
            errors,
        )
        validate_fact_ref(
            decision.get("unmatched_target"),
            f"decision_point {decision_id} unmatched_target",
            target_refs,
            errors,
        )
        validate_decision_target_topology(
            decision.get("unmatched_target"),
            decision.get("node_key"),
            f"decision_point {decision_id} unmatched_target",
            edges,
            known_nodes,
            errors,
        )
    for rule_key, rule in business_rules.items():
        input_refs = rule.get("input_refs")
        for ref in input_refs if isinstance(input_refs, list) else []:
            validate_fact_ref(ref, f"business_rule {rule_key} input", source_refs, errors)
    covered_db_edges: set[str] = set()
    for operation_id, operation in database_operations.items():
        node_key = operation.get("node_key")
        if node_key not in known_nodes:
            fail(errors, f"database_operation {operation_id}: unknown node_key {node_key!r}")
        edge_id = operation.get("edge_id")
        edge = edges.get(edge_id)
        if edge is None:
            fail(errors, f"database_operation {operation_id}: unknown edge_id {edge_id!r}")
        elif edge.get("type") != "db":
            fail(errors, f"database_operation {operation_id}: edge {edge_id} is not type db")
        elif node_key not in {edge.get("from"), edge.get("to")}:
            fail(errors, f"database_operation {operation_id}: node_key is not on edge {edge_id}")
        else:
            covered_db_edges.add(str(edge_id))
    for config_key, config in configurations.items():
        node_keys = config.get("affected_node_keys")
        for node_key in node_keys if isinstance(node_keys, list) else []:
            if node_key not in known_nodes:
                fail(errors, f"configuration {config_key}: unknown affected node {node_key!r}")
        rule_keys = config.get("affected_rule_keys")
        for rule_key in rule_keys if isinstance(rule_keys, list) else []:
            if rule_key not in business_rules:
                fail(errors, f"configuration {config_key}: unknown affected rule {rule_key!r}")
            else:
                input_refs = business_rules[rule_key].get("input_refs")
                if not isinstance(input_refs, list) or f"config:{config.get('name')}" not in input_refs:
                    fail(
                        errors,
                        f"configuration {config_key}: rule {rule_key!r} lacks reverse config ref",
                    )
    for rule_key, rule in business_rules.items():
        input_refs = rule.get("input_refs")
        for ref in input_refs if isinstance(input_refs, list) else []:
            if not isinstance(ref, str) or not ref.startswith("config:"):
                continue
            config_name = ref.split(":", 1)[1]
            matching = [config for config in configurations.values() if config.get("name") == config_name]
            if matching and not any(
                isinstance(config.get("affected_rule_keys"), list)
                and rule_key in config["affected_rule_keys"]
                for config in matching
            ):
                fail(errors, f"business_rule {rule_key}: config {config_name!r} lacks reverse rule ref")

    if require_analyzed or require_closed:
        open_nodes = sorted(key for key, node in nodes.items() if node.get("state") in OPEN_STATES)
        if open_nodes:
            fail(errors, f"completion audit: open node states remain: {', '.join(open_nodes)}")
        if frontier:
            fail(errors, f"completion audit: frontier is not empty ({len(frontier)} item(s))")
        if any(item != "expanded" for item in coverage):
            fail(errors, "analysis audit: every fragment coverage must be 'expanded'")
        for edge_id, edge in edges.items():
            if edge.get("type") == "db" and edge_id not in covered_db_edges:
                fail(errors, f"analysis audit: db edge {edge_id} lacks a database operation")

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
        pending_configs = sorted(
            key
            for key, config in configurations.items()
            if config.get("current_value_source") == "developer-input-required"
        )
        if pending_configs:
            fail(
                errors,
                "closure audit: developer current values are required for configurations: "
                + ", ".join(pending_configs),
            )
        unresolved_tables = sorted(
            operation_id
            for operation_id, operation in database_operations.items()
            if str(operation.get("table", "")).startswith("unresolved:")
        )
        if unresolved_tables:
            fail(
                errors,
                "closure audit: unresolved database tables remain: "
                + ", ".join(unresolved_tables),
            )

    merged = {
        "root_keys": sorted(set(roots)),
        "entry_root": effective_entry_root,
        "coverage": coverage,
        "nodes": [nodes[key] for key in sorted(nodes)],
        "edges": [edges[key] for key in sorted(edges)],
        "decision_points": [decision_points[key] for key in sorted(decision_points)],
        "key_fields": [key_fields[key] for key in sorted(key_fields)],
        "business_rules": [business_rules[key] for key in sorted(business_rules)],
        "database_operations": [database_operations[key] for key in sorted(database_operations)],
        "key_logs": [key_logs[key] for key in sorted(key_logs)],
        "configurations": [configurations[key] for key in sorted(configurations)],
        "data_flows": data_flows,
        "unresolved": unresolved,
        "frontier": frontier,
    }
    return merged, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fragments", nargs="+", type=Path, help="JSON fragment files")
    parser.add_argument("--output", type=Path, help="write merged JSON to this path")
    parser.add_argument("--entry-root", help="canonical entry node used for reachability audit")
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
        entry_root=args.entry_root,
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
