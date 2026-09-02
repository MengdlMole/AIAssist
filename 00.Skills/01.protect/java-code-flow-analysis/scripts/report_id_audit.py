#!/usr/bin/env python3
"""Audit readable call identities across a Java flow-analysis report."""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path


N_ID = r"N\d+(?:\.\d+)*"
N_ID_PATTERN = re.compile(rf"(?<![A-Za-z0-9.]){N_ID}(?![\d.])")
SHORT_SYMBOL = r"[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*#[A-Za-z_$][\w$]*"
SHORT_SYMBOL_PATTERN = re.compile(SHORT_SYMBOL)
MERMAID_SHORT_SYMBOL = (
    r"[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*(?:#35;|#)[A-Za-z_$][\w$]*"
)
FENCE_PATTERN = re.compile(r"```(?P<kind>\w+)\s*\n(?P<body>.*?)```", re.DOTALL)
DB_OPERATION = r"(?:SELECT_LOCK|SELECT|INSERT|UPDATE|DELETE|UPSERT|MERGE|CALL)"
DB_ANNOTATION_PATTERN = re.compile(rf"\[DB\s+({DB_OPERATION})\s+([A-Za-z0-9_$.*:-]+)\]")


@dataclass(frozen=True)
class NodeIdentity:
    node_id: str
    symbol: str
    action: str
    parent: str | None
    callsite: str


def named_section(text: str, title_pattern: str) -> str:
    match = re.search(
        rf"^##\s+[^\n]*(?:{title_pattern})[^\n]*\n(?P<body>.*?)(?=^##\s+|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    return match.group("body") if match else ""


def named_heading_section(text: str, title_pattern: str) -> str:
    match = re.search(
        rf"^##{{2,3}}\s+[^\n]*(?:{title_pattern})[^\n]*\n(?P<body>.*?)(?=^##{{2,3}}\s+|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    return match.group("body") if match else ""


def markdown_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def validate_mermaid_entities(text: str, errors: list[str]) -> None:
    for fence in FENCE_PATTERN.finditer(text):
        if fence.group("kind").lower() != "mermaid":
            continue
        if re.search(r"#(?!35;)", fence.group("body")):
            errors.append("mermaid: literal '#' is forbidden; use '#35;'")


def sequence_records(section: str, errors: list[str]) -> tuple[list[str], dict[str, str]]:
    references: list[str] = []
    definitions: list[tuple[str, str]] = []
    definition_pattern = re.compile(
        rf":\s*({N_ID})\s+(.+?)\s+·\s+({MERMAID_SHORT_SYMBOL})\s*$"
    )
    for fence in FENCE_PATTERN.finditer(section):
        if fence.group("kind").lower() != "mermaid":
            continue
        body = fence.group("body")
        if "sequenceDiagram" not in body:
            continue
        references.extend(N_ID_PATTERN.findall(body))
        for line in body.splitlines():
            if not re.search(r"(?:->>|-->>|-\))", line):
                continue
            message = line.split(":", 1)[1].strip() if ":" in line else ""
            if not re.match(rf"^{N_ID}\b", message):
                continue
            match = definition_pattern.search(line)
            if not match:
                errors.append(
                    "sequence: first-call message must be "
                    f"'<ID> <action> · <Class#35;method>': {line.strip()}"
                )
                continue
            definitions.append((match.group(1), match.group(3).replace("#35;", "#")))

    counts = Counter(node_id for node_id, _ in definitions)
    duplicates = sorted(node_id for node_id, count in counts.items() if count != 1)
    if duplicates:
        errors.append("sequence: each ID needs one first-call message: " + ", ".join(duplicates))
    symbols = {node_id: symbol for node_id, symbol in definitions}
    undefined_refs = sorted(set(references) - set(symbols))
    if undefined_refs:
        errors.append("sequence: referenced IDs lack a first-call message: " + ", ".join(undefined_refs))
    return references, symbols


def tree_records(section: str, errors: list[str]) -> tuple[list[str], dict[str, str]]:
    ids: list[str] = []
    symbols: dict[str, str] = {}
    label_pattern = re.compile(
        rf"^[\s│]*(?:(?:├──|└──)\s*)?(?:~~异步~~>\s*)?({N_ID})(?![\d.])"
    )
    for fence in FENCE_PATTERN.finditer(section):
        if fence.group("kind").lower() != "text":
            continue
        for line in fence.group("body").splitlines():
            label = label_pattern.match(line)
            if not label:
                continue
            node_id = label.group(1)
            ids.append(node_id)
            symbol = SHORT_SYMBOL_PATTERN.search(line[label.end() :])
            if not symbol:
                errors.append(f"tree: {node_id} lacks readable Class#method")
            else:
                symbols[node_id] = symbol.group(0)
    return ids, symbols


def node_table_records(section: str, errors: list[str]) -> tuple[list[str], dict[str, NodeIdentity]]:
    lines = section.splitlines()
    header_index = -1
    for index, line in enumerate(lines):
        if not line.lstrip().startswith("|"):
            continue
        cells = markdown_cells(line)
        if len(cells) >= 3 and cells[0] == "节点" and "短符号" in cells[1] and "父节点" in cells[2]:
            header_index = index
            break
    if header_index < 0:
        errors.append("node table: missing required identity columns (节点/短符号/父节点)")
        return [], {}

    ids: list[str] = []
    records: dict[str, NodeIdentity] = {}
    occurrence_keys: dict[str, str] = {}
    row_pattern = re.compile(rf"^{N_ID}$")
    for line in lines[header_index + 1 :]:
        if not line.lstrip().startswith("|"):
            if ids:
                break
            continue
        cells = markdown_cells(line)
        if len(cells) < 3 or not row_pattern.fullmatch(cells[0]):
            continue
        node_id = cells[0]
        ids.append(node_id)
        identity_cell, parent_cell = cells[1], cells[2]
        symbol_match = SHORT_SYMBOL_PATTERN.search(identity_cell)
        if not symbol_match:
            errors.append(f"node table: {node_id} lacks Class#method in identity column")
            continue
        symbol = symbol_match.group(0)
        action_parts = re.split(r"\s+[—-]\s+", identity_cell, maxsplit=1)
        action = action_parts[1].strip(" `<> ") if len(action_parts) == 2 else ""
        if not action:
            errors.append(f"node table: {node_id} lacks a readable business action")

        if node_id == "N1":
            parent = None
            if "根" not in parent_cell:
                errors.append("node table: N1 parent must be 根")
        else:
            parent_match = N_ID_PATTERN.search(parent_cell)
            parent = parent_match.group(0) if parent_match else None
            expected_parent = node_id.rsplit(".", 1)[0]
            if parent != expected_parent:
                errors.append(
                    f"node table: {node_id} parent must be {expected_parent}; got {parent or 'missing'}"
                )
        callsite_source = re.sub(r"^根\s*[；;]?", "", parent_cell) if node_id == "N1" else parent_cell
        callsite = N_ID_PATTERN.sub("", callsite_source, count=1).strip(" `；;，,<> ")
        if not callsite:
            errors.append(f"node table: {node_id} lacks entry binding/callsite")
        occurrence_key = f"{symbol}@{callsite}"
        if occurrence_key in occurrence_keys:
            errors.append(
                f"node table: duplicate call identity for {occurrence_keys[occurrence_key]} and {node_id}"
            )
        occurrence_keys[occurrence_key] = node_id
        records[node_id] = NodeIdentity(node_id, symbol, action, parent, callsite)
    return ids, records


def validate_hierarchy(ids: set[str], errors: list[str]) -> None:
    if "N1" not in ids:
        errors.append("hierarchy: root N1 is missing")
    extra_roots = sorted(item for item in ids if "." not in item and item != "N1")
    if extra_roots:
        errors.append("hierarchy: only N1 may be a root: " + ", ".join(extra_roots))
    children: dict[str, list[int]] = defaultdict(list)
    for item in sorted(ids):
        if "." not in item:
            continue
        parent, child = item.rsplit(".", 1)
        if parent not in ids:
            errors.append(f"hierarchy: {item} has missing parent {parent}")
        children[parent].append(int(child))
    for parent, indexes in sorted(children.items()):
        actual = sorted(indexes)
        expected = list(range(1, len(actual) + 1))
        if actual != expected:
            errors.append(f"hierarchy: children of {parent} must be contiguous from 1; got {actual}")


def crosscut_ids(text: str, sequence_section: str, errors: list[str]) -> set[str]:
    crosscut_section = named_heading_section(text, r"横切链|横切前置链")
    rows = re.findall(r"^\|\s*(X\d+)\s*\|\s*([^|]+)\|", crosscut_section, re.MULTILINE)
    counts = Counter(node_id for node_id, _ in rows)
    duplicates = sorted(node_id for node_id, count in counts.items() if count != 1)
    if duplicates:
        errors.append("crosscut: duplicate X IDs: " + ", ".join(duplicates))
    for node_id, identity in rows:
        if "—" not in identity or not identity.strip(" `<> "):
            errors.append(f"crosscut: {node_id} needs a readable short identity and action")
    defined = set(counts)
    referenced: set[str] = set()
    for fence in FENCE_PATTERN.finditer(sequence_section):
        if fence.group("kind").lower() == "mermaid" and "sequenceDiagram" in fence.group("body"):
            referenced.update(re.findall(r"(?<![A-Za-z0-9])X\d+(?!\d)", fence.group("body")))
    missing = sorted(referenced - defined)
    if missing:
        errors.append("crosscut: sequence references missing X nodes: " + ", ".join(missing))
    return defined


def validate_logs(text: str, n_ids: set[str], x_ids: set[str], errors: list[str]) -> None:
    log_section = named_section(text, r"关键日志")
    log_headers = [
        markdown_cells(line)
        for line in log_section.splitlines()
        if line.lstrip().startswith("|") and markdown_cells(line)[0] == "日志/节点"
    ]
    expected_front = ["日志/节点", "稳定日志内容", "代码位置", "打印条件"]
    if log_headers and log_headers[0][:4] != expected_front:
        errors.append("logs: first columns must be 日志/节点, 稳定日志内容, 代码位置, 打印条件")
    all_log_rows = re.findall(
        r"^\|\s*(L\d+)\s*/\s*([^|]+?)\s*\|",
        log_section,
        re.MULTILINE,
    )
    if all_log_rows and not log_headers:
        errors.append("logs: missing required key-log table header")
    allowed_target = re.compile(rf"^(?:{N_ID}|X\d+|边界|来源未知)$")
    log_rows: list[tuple[str, str]] = []
    for log_id, raw_target in all_log_rows:
        target = raw_target.strip()
        if not allowed_target.fullmatch(target):
            errors.append(
                f"logs: {log_id} target must be N/X/边界/来源未知; got {target!r}"
            )
            continue
        log_rows.append((log_id, target))
    duplicates = sorted(
        log_id
        for log_id, count in Counter(log_id for log_id, _ in all_log_rows).items()
        if count != 1
    )
    if duplicates:
        errors.append("logs: duplicate log IDs: " + ", ".join(duplicates))
    for log_id, target in log_rows:
        if target.startswith("N") and target not in n_ids:
            errors.append(f"logs: {log_id} references missing node {target}")
        if target.startswith("X") and target not in x_ids:
            errors.append(f"logs: {log_id} references missing crosscut node {target}")


def validate_configurations(text: str, n_ids: set[str], errors: list[str]) -> None:
    section = named_section(text, r"配置项汇总|配置与运行时选择")
    if not section:
        errors.append("report: missing configuration summary section")
        return
    if "目标路径上未发现影响流程走向的配置项" in section:
        if re.search(r"^\|\s*配置项名称\s*\|", section, re.MULTILINE):
            errors.append("configurations: empty conclusion conflicts with a configuration table")
        return
    lines = section.splitlines()
    header_index = -1
    for index, line in enumerate(lines):
        if not line.lstrip().startswith("|"):
            continue
        cells = markdown_cells(line)
        if cells and cells[0] == "配置项名称":
            header_index = index
            expected = [
                "配置项名称",
                "说明",
                "作用",
                "默认值",
                "当前值（开发者填写）",
                "关联编号（时序图/调用树）",
                "声明/读取证据",
            ]
            if cells != expected:
                errors.append("configurations: table columns do not match the required order")
            break
    if header_index < 0:
        errors.append("configurations: missing required table")
        return
    row_count = 0
    pending_current = False
    for line in lines[header_index + 1 :]:
        if not line.lstrip().startswith("|"):
            if row_count:
                break
            continue
        cells = markdown_cells(line)
        if not cells or cells[0].startswith("---"):
            continue
        if len(cells) < 7:
            errors.append("configurations: each row must contain all seven fields")
            continue
        row_count += 1
        current = cells[4].strip(" `<> ")
        pending_current = pending_current or current == "待开发者填写"
        if current != "待开发者填写" and not re.match(r"^开发者提供[:：]", current):
            errors.append(
                f"configurations: {cells[0]} current value must be 待开发者填写 or 开发者提供：<值>"
            )
        refs = set(N_ID_PATTERN.findall(cells[5]))
        if not refs:
            errors.append(f"configurations: {cells[0]} must reference at least one N node")
        missing = sorted(refs - n_ids)
        if missing:
            errors.append(
                f"configurations: {cells[0]} references missing nodes: {', '.join(missing)}"
            )
    if row_count == 0:
        errors.append("configurations: table has no configuration rows")
    if pending_current and re.search(r"遍历结论：[^\n]*调用图已闭合", text):
        errors.append("configurations: report cannot claim 调用图已闭合 while current values are pending")


def database_annotations(section: str, kind: str) -> list[tuple[str, str, str]]:
    records: list[tuple[str, str, str]] = []
    for fence in FENCE_PATTERN.finditer(section):
        if fence.group("kind").lower() != kind:
            continue
        body = fence.group("body")
        if kind == "mermaid" and "sequenceDiagram" not in body:
            continue
        for line in body.splitlines():
            if kind == "mermaid":
                message = line.split(":", 1)[1].strip() if ":" in line else ""
                node_match = re.match(rf"^({N_ID})\b", message)
            else:
                node_match = re.match(
                    rf"^[\s│]*(?:(?:├──|└──)\s*)?(?:~~异步~~>\s*)?({N_ID})(?![\d.])",
                    line,
                )
            if not node_match:
                continue
            for operation, table in DB_ANNOTATION_PATTERN.findall(line):
                records.append((node_match.group(1), operation, table))
    return records


def validate_database_operations(
    text: str,
    sequence_section: str,
    tree_section: str,
    n_ids: set[str],
    errors: list[str],
) -> None:
    section = named_heading_section(text, r"数据库表操作汇总|核心表操作汇总")
    if not section:
        errors.append("report: missing database operation summary section")
        return
    sequence_records = database_annotations(sequence_section, "mermaid")
    tree_records_found = database_annotations(tree_section, "text")
    none_found = "目标路径上未发现数据库表操作" in section
    if none_found:
        if sequence_records or tree_records_found:
            errors.append("database: empty conclusion conflicts with DB annotations")
        if re.search(r"^\|\s*节点\s*\|\s*表\s*\|", section, re.MULTILINE):
            errors.append("database: empty conclusion conflicts with operation table")
        return

    lines = section.splitlines()
    header_index = -1
    expected = [
        "节点",
        "表",
        "操作",
        "业务目的",
        "条件/关键字段",
        "事务/结果影响",
        "SQL/映射证据",
        "核心性/理由",
    ]
    for index, line in enumerate(lines):
        if not line.lstrip().startswith("|"):
            continue
        cells = markdown_cells(line)
        if cells and cells[0] == "节点" and len(cells) > 1 and cells[1] == "表":
            header_index = index
            if cells != expected:
                errors.append("database: operation table columns do not match the required order")
            break
    if header_index < 0:
        errors.append("database: missing required operation table")
        return

    summary_records: list[tuple[str, str, str]] = []
    for line in lines[header_index + 1 :]:
        if not line.lstrip().startswith("|"):
            if summary_records:
                break
            continue
        cells = markdown_cells(line)
        if not cells or cells[0].startswith("---"):
            continue
        if len(cells) < 8:
            errors.append("database: each operation row must contain all eight fields")
            continue
        node = cells[0].strip(" `<> ")
        table = cells[1].strip(" `<> ")
        operation = cells[2].strip(" `<> ")
        if node not in n_ids:
            errors.append(f"database: operation row references missing node {node!r}")
        if not re.fullmatch(DB_OPERATION, operation):
            errors.append(f"database: {node}/{table} has invalid operation {operation!r}")
        if not table:
            errors.append(f"database: {node} has an empty table name")
        if any(not cells[index].strip(" `<> ") for index in range(3, 8)):
            errors.append(f"database: {node}/{table} has empty operation details")
        core_value = cells[7].strip(" `<> ")
        if not re.match(r"^(?:核心|辅助)[；;：:].+$", core_value):
            errors.append(f"database: {node}/{table} core classification requires 核心/辅助 and reason")
        summary_records.append((node, operation, table))

    if not summary_records:
        errors.append("database: operation table has no rows")
        return
    for label, records in (
        ("sequence", sequence_records),
        ("tree", tree_records_found),
        ("summary", summary_records),
    ):
        duplicates = sorted(item for item, count in Counter(records).items() if count != 1)
        if duplicates:
            errors.append(f"database: duplicate {label} annotations: {duplicates}")
    sequence_set, tree_set, summary_set = (
        set(sequence_records),
        set(tree_records_found),
        set(summary_records),
    )
    if sequence_set != tree_set:
        errors.append(
            "database: sequence/tree annotations differ: "
            f"sequence-only={sorted(sequence_set - tree_set)}, tree-only={sorted(tree_set - sequence_set)}"
        )
    if tree_set != summary_set:
        errors.append(
            "database: tree/summary operations differ: "
            f"tree-only={sorted(tree_set - summary_set)}, summary-only={sorted(summary_set - tree_set)}"
        )


def audit(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"cannot read {path}: {exc}"]
    errors: list[str] = []
    sequence_section = named_section(text, r"业务时序图|主时序图")
    tree_section = named_section(text, r"代码调用链|关键调用链")
    node_section = named_section(text, r"关键代码节点")
    log_section = named_section(text, r"关键日志")
    for section, label in (
        (sequence_section, "business sequence diagram"),
        (tree_section, "code call tree"),
        (node_section, "key code nodes"),
    ):
        if not section:
            errors.append(f"report: missing {label} section")
    if not log_section:
        errors.append("report: missing key logs section")

    if re.search(r"^\s*autonumber\b", sequence_section, re.MULTILINE | re.IGNORECASE):
        errors.append("sequence: Mermaid autonumber is forbidden")
    validate_mermaid_entities(text, errors)
    sequence_refs, sequence_symbols = sequence_records(sequence_section, errors)
    tree_ids, tree_symbols = tree_records(tree_section, errors)
    table_ids, node_records = node_table_records(node_section, errors)

    for label, ids in (("tree", tree_ids), ("node table", table_ids)):
        duplicates = sorted(item for item, count in Counter(ids).items() if count != 1)
        if duplicates:
            errors.append(f"{label}: duplicate IDs: " + ", ".join(duplicates))
    sequence_set = set(sequence_symbols)
    tree_set = set(tree_ids)
    table_set = set(table_ids)
    if sequence_set != tree_set:
        errors.append(
            "sequence/tree ID sets differ: "
            f"sequence-only={sorted(sequence_set - tree_set)}, tree-only={sorted(tree_set - sequence_set)}"
        )
    if tree_set != table_set:
        errors.append(
            "tree/node-table ID sets differ: "
            f"tree-only={sorted(tree_set - table_set)}, table-only={sorted(table_set - tree_set)}"
        )
    for node_id in sorted(sequence_set & tree_set & table_set):
        record = node_records.get(node_id)
        if not record:
            continue
        if sequence_symbols.get(node_id) != record.symbol:
            errors.append(
                f"identity: {node_id} sequence symbol {sequence_symbols.get(node_id)!r} != {record.symbol!r}"
            )
        if tree_symbols.get(node_id) != record.symbol:
            errors.append(f"identity: {node_id} tree symbol {tree_symbols.get(node_id)!r} != {record.symbol!r}")

    validate_hierarchy(sequence_set | tree_set | table_set, errors)
    x_ids = crosscut_ids(text, sequence_section, errors)
    validate_logs(text, table_set, x_ids, errors)
    validate_configurations(text, table_set, errors)
    validate_database_operations(text, sequence_section, tree_section, table_set, errors)
    if not sequence_refs:
        errors.append("sequence: no call IDs found")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="generated Markdown report")
    args = parser.parse_args()
    errors = audit(args.report)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"OK: readable call identities are aligned in {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
