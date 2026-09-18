#!/usr/bin/env python3
"""Validate a readable Java flow report and its optional JSONL Flow Pack."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


NODE_ID = re.compile(r"^N\d+(?:\.\d+)*$")
FACT_ID = re.compile(r"^[SRDMLCUX]\d+$")
TREE_NODE = re.compile(
    r"(?P<id>N\d+(?:\.\d+)*)\s+(?P<labels>(?:\[[^\]]+\]\s*)*)"
    r"(?P<symbol>[\w.$<>]+#[\w$<>]+(?:\([^)]*\))?)\s*[—-]\s*(?P<action>.+)$"
)
TAG_REF = re.compile(r"\[(?:R:|DB:|MQ:|LOG:|CFG:|U:)([RDMLCU]\d+)\]")
HEADING = re.compile(r"^##\s+")

TYPE_PREFIX = {
    "stage": "S",
    "node": "N",
    "crosscut": "X",
    "decision": "R",
    "rule": "R",
    "sink": None,
    "log": "L",
    "config": "C",
    "unknown": "U",
}
ALLOWED_TYPES = {
    "flow",
    "stage",
    "node",
    "crosscut",
    "edge",
    "decision",
    "rule",
    "sink",
    "lineage",
    "log",
    "config",
    "unknown",
    "transaction",
    "retry",
}
COVERAGE = {"main-path", "key-paths-covered", "static-scope-complete", "partial"}


def section(text: str, title_fragment: str) -> str:
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.startswith("## ") and title_fragment in line:
            start = index + 1
            break
    if start is None:
        return ""
    end = len(lines)
    for index in range(start, len(lines)):
        if HEADING.match(lines[index]):
            end = index
            break
    return "\n".join(lines[start:end])


def clean_action(value: str) -> str:
    value = re.sub(r"\s*\{(?:代码已证实|运行已证实|推断|未知|配置绑定已证实)\}\s*$", "", value)
    return re.sub(r"\s+", " ", value).strip()


def parse_tree(text: str, errors: list[str]) -> dict[str, dict[str, str]]:
    tree = section(text, "树形调用链")
    if not tree:
        errors.append("markdown: missing '树形调用链' section")
        return {}

    nodes: dict[str, dict[str, str]] = {}
    for raw_line in tree.splitlines():
        line = raw_line.strip().lstrip("│├└─~ ")
        match = TREE_NODE.search(line)
        if not match:
            continue
        node_id = match.group("id")
        if node_id in nodes:
            errors.append(f"markdown: duplicate tree node {node_id}")
            continue
        nodes[node_id] = {
            "symbol": match.group("symbol"),
            "action": clean_action(match.group("action")),
            "line": raw_line,
        }

    if not nodes:
        errors.append("markdown: no readable N nodes found in call tree")
        return nodes
    if "N1" not in nodes:
        errors.append("markdown: call tree has no N1 root")
    for node_id in nodes:
        if "." in node_id:
            parent = node_id.rsplit(".", 1)[0]
            if parent not in nodes:
                errors.append(f"markdown: {node_id} is missing parent {parent}")
    return nodes


def mermaid_blocks(text: str) -> list[str]:
    return re.findall(r"```mermaid\s*\n(.*?)```", text, flags=re.DOTALL)


def audit_markdown(path: Path) -> tuple[str, dict[str, dict[str, str]], set[str], list[str]]:
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")
    for required in ("流程概述", "树形调用链", "分阶段说明"):
        if not section(text, required):
            errors.append(f"markdown: missing or empty '{required}' section")
    nodes = parse_tree(text, errors)
    tree_text = section(text, "树形调用链")
    tag_refs = set(TAG_REF.findall(tree_text))

    for index, block in enumerate(mermaid_blocks(text), start=1):
        if re.search(r"#(?!35;)", block):
            errors.append(f"markdown: Mermaid block {index} contains raw '#'; use '#35;'")
    return text, nodes, tag_refs, errors


def load_flow_pack(path: Path, errors: list[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            value = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            errors.append(f"flow-pack:{line_number}: invalid JSON: {exc.msg}")
            continue
        if not isinstance(value, dict):
            errors.append(f"flow-pack:{line_number}: record must be an object")
            continue
        record_type = value.get("type")
        if record_type not in ALLOWED_TYPES:
            errors.append(f"flow-pack:{line_number}: unknown type {record_type!r}")
            continue
        value["_line"] = line_number
        records.append(value)
    if not records:
        errors.append("flow-pack: no records")
    elif records[0].get("type") != "flow":
        errors.append("flow-pack: first record must have type 'flow'")
    return records


def is_target(value: Any, nodes: set[str]) -> bool:
    if not isinstance(value, str):
        return False
    return value in nodes or value.startswith("result:") or value.startswith("boundary:")


def audit_flow_pack(
    path: Path,
    markdown_nodes: dict[str, dict[str, str]],
    markdown_tag_refs: set[str],
) -> list[str]:
    errors: list[str] = []
    records = load_flow_pack(path, errors)
    if not records:
        return errors

    by_type: dict[str, list[dict[str, Any]]] = {}
    ids: dict[str, dict[str, Any]] = {}
    for record in records:
        record_type = str(record["type"])
        by_type.setdefault(record_type, []).append(record)
        if record_type not in TYPE_PREFIX:
            continue
        record_id = record.get("id")
        if not isinstance(record_id, str):
            errors.append(f"flow-pack:{record['_line']}: {record_type} requires string id")
            continue
        expected = TYPE_PREFIX[record_type]
        if record_type == "sink":
            if not re.fullmatch(r"[DM]\d+", record_id):
                errors.append(f"flow-pack:{record['_line']}: sink id must use D or M prefix")
        elif expected == "N":
            if not NODE_ID.fullmatch(record_id):
                errors.append(f"flow-pack:{record['_line']}: invalid node id {record_id!r}")
        elif expected and not re.fullmatch(expected + r"\d+", record_id):
            errors.append(f"flow-pack:{record['_line']}: {record_type} id must use {expected} prefix")
        if record_id in ids:
            errors.append(f"flow-pack:{record['_line']}: duplicate id {record_id}")
        else:
            ids[record_id] = record

    node_records = {record.get("id"): record for record in by_type.get("node", []) if isinstance(record.get("id"), str)}
    node_ids = set(node_records)
    if not node_ids:
        errors.append("flow-pack: at least one node record is required")
    if not by_type.get("stage"):
        errors.append("flow-pack: at least one stage record is required")

    flow_record = records[0] if records and records[0].get("type") == "flow" else {}
    for field in ("id", "name", "intent", "trigger", "baseline"):
        if not isinstance(flow_record.get(field), str) or not flow_record[field].strip():
            errors.append(f"flow-pack: flow.{field} must be non-empty")
    scope = flow_record.get("scope")
    if not isinstance(scope, dict) or any(
        not isinstance(scope.get(field), str) or not scope[field].strip()
        for field in ("scenario", "included", "excluded")
    ):
        errors.append("flow-pack: flow.scope requires scenario/included/excluded")
    coverage = flow_record.get("coverage")
    if coverage not in COVERAGE:
        errors.append("flow-pack: flow.coverage is invalid")
    frontier_count = flow_record.get("frontier_count")
    unresolved_count = flow_record.get("unresolved_count")
    if not isinstance(frontier_count, int) or frontier_count < 0:
        errors.append("flow-pack: flow.frontier_count must be a non-negative integer")
    elif frontier_count > 0 and coverage != "partial":
        errors.append("flow-pack: non-empty frontier requires coverage=partial")
    elif frontier_count == 0 and coverage == "partial":
        errors.append("flow-pack: coverage=partial requires a non-empty frontier")
    unknown_count = len(by_type.get("unknown", []))
    if not isinstance(unresolved_count, int) or unresolved_count < 0:
        errors.append("flow-pack: flow.unresolved_count must be a non-negative integer")
    elif unresolved_count != unknown_count:
        errors.append("flow-pack: flow.unresolved_count must equal unknown record count")
    if flow_record.get("entry") not in node_ids:
        errors.append("flow-pack: flow.entry must reference a node")
    ends = flow_record.get("end")
    if not isinstance(ends, list) or not ends:
        errors.append("flow-pack: flow.end must be a non-empty list")
    else:
        for endpoint in ends:
            if endpoint not in node_ids and endpoint not in ids and not is_target(endpoint, node_ids):
                errors.append(f"flow-pack: flow.end references unknown endpoint {endpoint!r}")
    markdown_ids = set(markdown_nodes)
    if node_ids != markdown_ids:
        missing_pack = sorted(markdown_ids - node_ids)
        missing_markdown = sorted(node_ids - markdown_ids)
        if missing_pack:
            errors.append("identity: Markdown nodes missing from Flow Pack: " + ", ".join(missing_pack))
        if missing_markdown:
            errors.append("identity: Flow Pack nodes missing from Markdown tree: " + ", ".join(missing_markdown))

    for node_id, record in node_records.items():
        parent = record.get("parent")
        expected_parent = node_id.rsplit(".", 1)[0] if "." in node_id else None
        if parent != expected_parent:
            errors.append(f"flow-pack: {node_id} parent {parent!r} != {expected_parent!r}")
        markdown_node = markdown_nodes.get(node_id)
        if markdown_node:
            symbol = record.get("symbol")
            action = record.get("action")
            if symbol != markdown_node["symbol"]:
                errors.append(f"identity: {node_id} symbol differs between Markdown and Flow Pack")
            if clean_action(str(action or "")) != markdown_node["action"]:
                errors.append(f"identity: {node_id} action differs between Markdown and Flow Pack")

    for record in by_type.get("stage", []):
        stage_nodes = record.get("nodes")
        if not isinstance(stage_nodes, list) or not stage_nodes:
            errors.append(f"flow-pack:{record['_line']}: stage requires non-empty nodes")
        else:
            for node_id in stage_nodes:
                if node_id not in node_ids:
                    errors.append(f"flow-pack:{record['_line']}: stage references unknown node {node_id}")

    for record in by_type.get("edge", []):
        if record.get("from") not in node_ids or not is_target(record.get("to"), node_ids):
            errors.append(f"flow-pack:{record['_line']}: edge has unknown from/to")

    for record_type in ("crosscut", "decision", "rule", "sink", "log", "config", "transaction", "retry"):
        for record in by_type.get(record_type, []):
            at = record.get("at")
            if isinstance(at, list):
                invalid = [value for value in at if value not in node_ids]
                if invalid:
                    errors.append(f"flow-pack:{record['_line']}: unknown at nodes {invalid}")
            elif at not in node_ids:
                errors.append(f"flow-pack:{record['_line']}: unknown at node {at!r}")
            if record_type == "decision":
                for side in ("yes", "no"):
                    if side in record and not is_target(record[side], node_ids):
                        errors.append(f"flow-pack:{record['_line']}: decision {side} has unknown target")

    for record in by_type.get("lineage", []):
        path_value = record.get("path")
        if not isinstance(path_value, list) or len(path_value) < 2:
            errors.append(f"flow-pack:{record['_line']}: lineage path needs at least source and destination")

    pack_fact_ids = {record_id for record_id in ids if FACT_ID.fullmatch(record_id) and not record_id.startswith("S")}
    missing_facts = sorted(markdown_tag_refs - pack_fact_ids)
    if missing_facts:
        errors.append("identity: Markdown tree references undefined Flow Pack facts: " + ", ".join(missing_facts))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="developer-facing Markdown report")
    parser.add_argument("--flow-pack", type=Path, help="JSONL Flow Pack generated from the same facts")
    args = parser.parse_args()

    _, nodes, tag_refs, errors = audit_markdown(args.report)
    if args.flow_pack:
        errors.extend(audit_flow_pack(args.flow_pack, nodes, tag_refs))
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    suffix = f" and {args.flow_pack}" if args.flow_pack else ""
    print(f"OK: report identities are consistent in {args.report}{suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
