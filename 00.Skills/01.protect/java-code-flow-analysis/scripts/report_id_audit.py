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
DB_OPERATION_ID = r"D\d+"
DB_ANNOTATION_PATTERN = re.compile(
    rf"\[DB\s+({DB_OPERATION_ID})\s+({DB_OPERATION})\s+([A-Za-z0-9_$.*:{{}}-]+)\]"
)


@dataclass(frozen=True)
class NodeIdentity:
    node_id: str
    symbol: str
    action: str
    parent: str | None
    callsite: str
    context: str


def named_section(text: str, title_pattern: str) -> str:
    match = re.search(
        rf"^##\s+[^\n]*(?:{title_pattern})[^\n]*\n(?P<body>.*?)(?=^##\s+|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    return match.group("body") if match else ""


def named_heading_section(text: str, title_pattern: str) -> str:
    match = re.search(
        rf"^#{{2,3}}\s+[^\n]*(?:{title_pattern})[^\n]*\n(?P<body>.*?)(?=^#{{2,3}}\s+|\Z)",
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
        visible_stack: list[tuple[int, str]] = []
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


def normalize_action(value: str) -> str:
    value = DB_ANNOTATION_PATTERN.sub("", value)
    value = re.sub(r"\s*[；;]\s*context=[^；;]+\s*$", "", value)
    return re.sub(r"\s+", " ", value.strip(" `<> "))


def validate_action_quality(node_id: str, action: str, errors: list[str]) -> None:
    match = re.fullmatch(r"(.+?)[；;](.+?)\s*→\s*(.+)", action)
    if not match or any(not part.strip(" `<> ") for part in match.groups()):
        errors.append(
            f"action: {node_id} must use '<action + business object>; "
            "<key input/condition> → <result/effect>'"
        )
        return
    generic = {
        "处理请求",
        "处理数据",
        "执行业务",
        "执行逻辑",
        "调用服务",
        "查询数据",
        "保存数据",
        "返回结果",
        "校验参数",
    }
    if match.group(1).strip(" `<> ") in generic:
        errors.append(f"action: {node_id} uses an overly generic action/object description")


def sequence_actions(section: str) -> dict[str, str]:
    actions: dict[str, str] = {}
    pattern = re.compile(
        rf":\s*({N_ID})\s+(.+?)\s+·\s+({MERMAID_SHORT_SYMBOL})\s*$"
    )
    for fence in FENCE_PATTERN.finditer(section):
        if fence.group("kind").lower() != "mermaid" or "sequenceDiagram" not in fence.group("body"):
            continue
        for line in fence.group("body").splitlines():
            match = pattern.search(line)
            if match:
                actions[match.group(1)] = normalize_action(match.group(2))
    return actions


def tree_actions(section: str) -> dict[str, str]:
    actions: dict[str, str] = {}
    node_pattern = re.compile(
        rf"^[\s│]*(?:(?:├──|└──)\s*)?(?:~~异步~~>\s*)?({N_ID})(?![\d.])"
    )
    for fence in FENCE_PATTERN.finditer(section):
        if fence.group("kind").lower() != "text":
            continue
        for line in fence.group("body").splitlines():
            node_match = node_pattern.match(line)
            if not node_match:
                continue
            symbol_match = SHORT_SYMBOL_PATTERN.search(line[node_match.end() :])
            if not symbol_match:
                continue
            tail = line[node_match.end() + symbol_match.end() :]
            action_match = re.search(r"\s+[—-]\s+(.+?)(?:\s+\{[^{}]*\})?\s*$", tail)
            if action_match:
                actions[node_match.group(1)] = normalize_action(action_match.group(1))
    return actions


def asynchronous_execution_ids(sequence_section: str, tree_section: str) -> tuple[set[str], set[str]]:
    sequence_ids: set[str] = set()
    for fence in FENCE_PATTERN.finditer(sequence_section):
        if fence.group("kind").lower() != "mermaid" or "sequenceDiagram" not in fence.group("body"):
            continue
        for line in fence.group("body").splitlines():
            if "-)" not in line or ":" not in line:
                continue
            match = re.match(rf"^({N_ID})\b", line.split(":", 1)[1].strip())
            if match:
                sequence_ids.add(match.group(1))
    tree_ids: set[str] = set()
    for fence in FENCE_PATTERN.finditer(tree_section):
        if fence.group("kind").lower() != "text":
            continue
        for line in fence.group("body").splitlines():
            if "~~异步~~>" not in line:
                continue
            match = N_ID_PATTERN.search(line)
            if match:
                tree_ids.add(match.group(0))
    return sequence_ids, tree_ids


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
        context_match = re.search(r"[；;]\s*context=([^；;]+)\s*$", identity_cell) or re.search(
            r"[；;]\s*context=([^；;]+)\s*$", parent_cell
        )
        context = context_match.group(1).strip(" `<> ") if context_match else ""
        identity_base = re.sub(r"\s*[；;]\s*context=[^；;]+\s*$", "", identity_cell)
        parent_base = re.sub(r"\s*[；;]\s*context=[^；;]+\s*$", "", parent_cell)
        symbol_match = SHORT_SYMBOL_PATTERN.search(identity_base)
        if not symbol_match:
            errors.append(f"node table: {node_id} lacks Class#method in identity column")
            continue
        symbol = symbol_match.group(0)
        action_parts = re.split(r"\s+[—-]\s+", identity_base, maxsplit=1)
        action = action_parts[1].strip(" `<> ") if len(action_parts) == 2 else ""
        if not action:
            errors.append(f"node table: {node_id} lacks a readable business action")

        if node_id == "N1":
            parent = None
            if "根" not in parent_cell:
                errors.append("node table: N1 parent must be 根")
        else:
            parent_match = N_ID_PATTERN.search(parent_base)
            parent = parent_match.group(0) if parent_match else None
            expected_parent = node_id.rsplit(".", 1)[0]
            if parent != expected_parent:
                errors.append(
                    f"node table: {node_id} parent must be {expected_parent}; got {parent or 'missing'}"
                )
        callsite_source = re.sub(r"^根\s*[；;]?", "", parent_base) if node_id == "N1" else parent_base
        callsite = N_ID_PATTERN.sub("", callsite_source, count=1).strip(" `；;，,<> ")
        if not callsite:
            errors.append(f"node table: {node_id} lacks entry binding/callsite")
        occurrence_key = f"{symbol}@{callsite}[{context}]"
        if occurrence_key in occurrence_keys:
            errors.append(
                f"node table: duplicate call identity for {occurrence_keys[occurrence_key]} and {node_id}"
            )
        occurrence_keys[occurrence_key] = node_id
        records[node_id] = NodeIdentity(node_id, symbol, action, parent, callsite, context)
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


def validate_tree_layout(section: str, errors: list[str]) -> None:
    pattern = re.compile(
        rf"^(?P<prefix>[\s│]*)(?:(?P<connector>├──|└──)\s*)?"
        rf"(?:~~异步~~>\s*)?(?P<id>{N_ID})(?![\d.])"
    )
    for fence in FENCE_PATTERN.finditer(section):
        if fence.group("kind").lower() != "text":
            continue
        for line in fence.group("body").splitlines():
            match = pattern.match(line)
            if not match:
                continue
            node_id = match.group("id")
            connector = match.group("connector")
            if node_id == "N1":
                if connector or match.group("prefix"):
                    errors.append("tree layout: N1 must be the unindented visible root")
                visible_stack = [(0, node_id)]
                continue
            if not connector:
                errors.append(f"tree layout: {node_id} must use a tree connector")
                continue
            depth = node_id.count(".") + 1
            visible_indent = len(match.group("prefix").expandtabs(4))
            minimum_indent = 4 * max(0, depth - 2)
            if visible_indent < minimum_indent:
                errors.append(
                    f"tree layout: {node_id} is too shallow for its encoded hierarchy"
                )
            content_column = visible_indent + 4
            while visible_stack and visible_stack[-1][0] >= content_column:
                visible_stack.pop()
            actual_parent = visible_stack[-1][1] if visible_stack else None
            encoded_parent = node_id.rsplit(".", 1)[0]
            if actual_parent != encoded_parent:
                errors.append(
                    f"tree layout: {node_id} is visually under "
                    f"{actual_parent or 'no parent'}, expected {encoded_parent}"
                )
            visible_stack.append((content_column, node_id))


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
    expected_headers = [
        "日志/节点",
        "稳定日志内容",
        "代码位置",
        "打印条件",
        "事件/时点",
        "能证明 / 不能证明",
        "关联字段",
        "来源/级别/证据与风险",
    ]
    if log_headers and log_headers[0] != expected_headers:
        errors.append("logs: key-log table columns do not match the required order")
    all_log_rows = re.findall(
        r"^\|\s*(L\d+)\s*/\s*([^|]+?)\s*\|",
        log_section,
        re.MULTILINE,
    )
    if all_log_rows and not log_headers:
        errors.append("logs: missing required key-log table header")
    none_found = "目标路径上未发现符合关键日志标准的现有日志" in log_section
    if none_found and all_log_rows:
        errors.append("logs: empty conclusion conflicts with key-log rows")
    if not none_found and not all_log_rows:
        errors.append("logs: require at least one key-log row or the explicit empty conclusion")
    for line in log_section.splitlines():
        if not re.match(r"^\|\s*L\d+\s*/", line):
            continue
        cells = markdown_cells(line)
        if len(cells) != 8:
            errors.append("logs: each key-log row must contain all eight fields")
            continue
        if any(not cell.strip(" `<> ") for cell in cells):
            errors.append(f"logs: {cells[0]} contains empty required fields")
        if not re.search(
            r"\b(?:arrival|decision|handoff|external-result|state-change|failure)\b", cells[4]
        ) or not re.search(
            r"\b(?:before|after-return|after-commit|on-exception|finally)\b", cells[4]
        ):
            errors.append(f"logs: {cells[0]} requires a valid event and timing")
        if not re.search(r"\S+\s*/\s*\S+", cells[5]):
            errors.append(f"logs: {cells[0]} must state proves / does-not-prove")
        if not re.search(r"\b(?:code|aspect|filter|interceptor|wrapper)\b", cells[7]) or not re.search(
            r"\b(?:TRACE|DEBUG|INFO|WARN|ERROR)\b", cells[7]
        ) or not re.search(r"代码已证实|运行已证实|推断|未知", cells[7]):
            errors.append(f"logs: {cells[0]} requires source, level and evidence status")
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


def validate_configurations(
    text: str,
    n_ids: set[str],
    rule_ids: set[str],
    rule_inputs: dict[str, str],
    errors: list[str],
) -> None:
    section = named_section(text, r"配置项汇总|配置与运行时选择")
    if not section:
        errors.append("report: missing configuration summary section")
        return
    if "目标路径上未发现影响业务流程、处理范围或结果的配置项" in section:
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
                "关联编号（N/R）",
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
        if len(cells) != 7:
            errors.append("configurations: each row must contain all seven fields")
            continue
        row_count += 1
        if any(not cell.strip(" `<> ") for cell in cells[:7]):
            errors.append(f"configurations: {cells[0]} contains empty required fields")
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
        referenced_rules = set(re.findall(r"(?<![A-Za-z0-9])R\d+(?!\d)", cells[5]))
        missing_rules = sorted(referenced_rules - rule_ids)
        if missing_rules:
            errors.append(
                f"configurations: {cells[0]} references missing rules: {', '.join(missing_rules)}"
            )
        config_name = cells[0].strip(" `<> ")
        for rule_id in referenced_rules & rule_ids:
            rule_configs = set(
                re.findall(
                    r"(?<![A-Za-z0-9])config:([A-Za-z0-9_.-]+)",
                    rule_inputs.get(rule_id, ""),
                )
            )
            if config_name not in rule_configs:
                errors.append(
                    f"configurations: {config_name} links {rule_id}, but the rule raw input "
                    "does not reference this configuration"
                )
    if row_count == 0:
        errors.append("configurations: table has no configuration rows")
    if pending_current and re.search(r"遍历结论：[^\n]*调用图已闭合", text):
        errors.append("configurations: report cannot claim 调用图已闭合 while current values are pending")


def required_summary_rows(
    text: str,
    title_pattern: str,
    expected_header: list[str],
    row_pattern: str,
    empty_text: str | None,
    label: str,
    errors: list[str],
) -> list[list[str]]:
    section = named_heading_section(text, title_pattern)
    if not section:
        errors.append(f"report: missing {label} section")
        return []
    lines = section.splitlines()
    header_index = next(
        (
            index
            for index, line in enumerate(lines)
            if line.lstrip().startswith("|")
            and markdown_cells(line)
            and markdown_cells(line)[0] == expected_header[0]
        ),
        -1,
    )
    empty_found = bool(empty_text and empty_text in section)
    if empty_found and header_index >= 0:
        errors.append(f"{label}: empty conclusion conflicts with table")
        return []
    if empty_found:
        return []
    if header_index < 0:
        errors.append(f"{label}: missing required table")
        return []
    if markdown_cells(lines[header_index]) != expected_header:
        errors.append(f"{label}: table columns do not match required order")
    rows: list[list[str]] = []
    for line in lines[header_index + 1 :]:
        if not line.lstrip().startswith("|"):
            if rows:
                break
            continue
        cells = markdown_cells(line)
        if not cells or cells[0].startswith("---"):
            continue
        if not re.match(row_pattern, cells[0].strip(" `<> ")):
            continue
        if len(cells) != len(expected_header):
            errors.append(f"{label}: each row must contain all {len(expected_header)} fields")
            continue
        if any(not cell.strip(" `<> ") for cell in cells):
            errors.append(f"{label}: {cells[0]} contains empty required fields")
        rows.append(cells)
    if not rows:
        errors.append(f"{label}: table has no data rows")
    return rows


def validate_reader_guidance(
    text: str, n_ids: set[str], errors: list[str]
) -> tuple[set[str], dict[str, str]]:
    step_rows = required_summary_rows(
        text,
        r"业务步骤导读",
        ["步骤", "关联节点", "业务目的", "输入/前置", "关键处理", "产出/状态变化", "下一步"],
        r"^B\d+\b",
        None,
        "business steps",
        errors,
    )
    step_ids = [
        re.match(r"^(B\d+)\b", row[0].strip(" `<> ")).group(1) for row in step_rows
    ]
    expected_steps = [f"B{index}" for index in range(1, len(step_ids) + 1)]
    if step_ids != expected_steps:
        errors.append(f"business steps: IDs must be unique and contiguous; got {step_ids}")
    known_steps = set(step_ids)
    step_edges: dict[str, set[str]] = {}
    node_step_counts: Counter[str] = Counter()
    for row in step_rows:
        step_id = re.match(r"^(B\d+)\b", row[0].strip(" `<> ")).group(1)
        next_steps = set(re.findall(r"\bB\d+\b", row[6]))
        step_edges[step_id] = next_steps
        missing_steps = sorted(next_steps - known_steps)
        if missing_steps:
            errors.append(
                f"business steps: {row[0]} references missing steps: {', '.join(missing_steps)}"
            )
        for node_id in set(N_ID_PATTERN.findall(row[1])):
            node_step_counts[node_id] += 1
    reachable_steps: set[str] = set()
    frontier = ["B1"] if "B1" in known_steps else []
    while frontier:
        step_id = frontier.pop()
        if step_id in reachable_steps:
            continue
        reachable_steps.add(step_id)
        frontier.extend(step_edges.get(step_id, set()) - reachable_steps)
    unreachable_steps = sorted(known_steps - reachable_steps)
    if unreachable_steps:
        errors.append("business steps: unreachable from B1: " + ", ".join(unreachable_steps))
    missing_step_nodes = sorted(n_ids - set(node_step_counts))
    if missing_step_nodes:
        errors.append("business steps: nodes lack a business step: " + ", ".join(missing_step_nodes))
    duplicate_step_nodes = sorted(
        node_id for node_id, count in node_step_counts.items() if count > 1
    )
    if duplicate_step_nodes:
        errors.append(
            "business steps: nodes belong to multiple steps: " + ", ".join(duplicate_step_nodes)
        )

    field_rows = required_summary_rows(
        text,
        r"关键参数与字段",
        ["参数/字段", "来源", "业务含义", "使用节点", "对流程/结果的作用", "转换/默认值/空值规则", "最终去向", "证据"],
        r"^.+$",
        "目标路径上未发现需要单独说明的关键参数或字段",
        "key fields",
        errors,
    )
    rule_rows = required_summary_rows(
        text,
        r"关键业务逻辑(?:与规则)?|关键业务规则",
        ["逻辑", "关联节点", "适用/触发条件", "输入及来源", "处理规则", "输出", "边界/例外", "业务影响", "代码证据"],
        r"^R\d+\b",
        "目标路径上未发现需要单独说明的关键业务逻辑",
        "business rules",
        errors,
    )
    rule_ids = [
        re.match(r"^(R\d+)\b", row[0].strip(" `<> ")).group(1) for row in rule_rows
    ]
    expected_rules = [f"R{index}" for index in range(1, len(rule_ids) + 1)]
    if rule_ids != expected_rules:
        errors.append(f"business rules: IDs must be unique and contiguous; got {rule_ids}")
    rule_inputs = {
        re.match(r"^(R\d+)\b", row[0].strip(" `<> ")).group(1): row[3]
        for row in rule_rows
    }
    sequence_scope = named_section(text, r"业务时序图|主时序图")
    tree_scope = named_section(text, r"代码调用链|关键调用链")
    for rule_id in rule_ids:
        token = re.compile(rf"(?<![A-Za-z0-9]){re.escape(rule_id)}(?!\d)")
        if not token.search(sequence_scope):
            errors.append(f"business logic: {rule_id} is missing from the sequence diagram")
        if not token.search(tree_scope):
            errors.append(f"business logic: {rule_id} is missing from the call tree")

    decision_rows = required_summary_rows(
        text,
        r"关键分支决策与异常路径|关键分支决策",
        ["决策点", "业务问题", "判定条件与顺序", "条件值来源", "命中路径", "未命中/default/fallback", "业务影响", "证据"],
        rf"^{N_ID}$",
        "目标路径上未发现改变业务结果的关键分支决策",
        "decision points",
        errors,
    )
    for row in decision_rows:
        decision_node = row[0].strip(" `<> ")
        for column, name in ((4, "matched path"), (5, "unmatched/default/fallback path")):
            target_nodes = set(N_ID_PATTERN.findall(row[column]))
            if not target_nodes and not re.search(
                r"(?:result|boundary):\S+", row[column]
            ):
                errors.append(
                    f"decision points: {row[0]} {name} must reference N or explicit result:/boundary:"
                )
            invalid_targets = sorted(
                target for target in target_nodes if not target.startswith(decision_node + ".")
            )
            if invalid_targets:
                errors.append(
                    f"decision points: {row[0]} {name} must reference descendant nodes; "
                    f"got {', '.join(invalid_targets)}"
                )

    referenced_cells = [
        ("business steps", row[0], row[1]) for row in step_rows
    ] + [
        ("key fields", row[0], row[3]) for row in field_rows
    ] + [
        ("business rules", row[0], row[1]) for row in rule_rows
    ] + [
        ("decision points", row[0], row[0] + " " + row[4] + " " + row[5])
        for row in decision_rows
    ]
    for label, item_id, value in referenced_cells:
        refs = set(N_ID_PATTERN.findall(value))
        if not refs:
            errors.append(f"{label}: {item_id} must reference at least one N node")
        missing = sorted(refs - n_ids)
        if missing:
            errors.append(f"{label}: {item_id} references missing nodes: {', '.join(missing)}")

    database_section = named_heading_section(text, r"数据库表操作汇总|核心表操作汇总")
    database_ids = set(re.findall(r"^\|\s*(D\d+)\s*\|", database_section, re.MULTILINE))
    configuration_section = named_section(text, r"配置项汇总|配置与运行时选择")
    configuration_names = {
        cells[0].strip(" `<> ")
        for line in configuration_section.splitlines()
        if line.lstrip().startswith("|")
        and (cells := markdown_cells(line))
        and cells[0] not in {"配置项名称", "---"}
        and not cells[0].startswith("---")
    }
    known_ids = {"B": known_steps, "R": set(rule_ids), "D": database_ids, "N": n_ids}
    token_pattern = re.compile(
        rf"(?<![A-Za-z0-9.])(?:B\d+|R\d+|D\d+|{N_ID})(?![\d.])"
    )
    for label, rows in (
        ("business steps", step_rows),
        ("key fields", field_rows),
        ("business rules", rule_rows),
        ("decision points", decision_rows),
    ):
        for row in rows:
            for token in token_pattern.findall(" ".join(row)):
                prefix = "N" if token.startswith("N") else token[0]
                if token not in known_ids[prefix]:
                    errors.append(f"{label}: {row[0]} references missing ID {token}")
            for config_name in re.findall(
                r"(?<![A-Za-z0-9])config:([A-Za-z0-9_.-]+)", " ".join(row)
            ):
                if config_name not in configuration_names:
                    errors.append(
                        f"{label}: {row[0]} references missing configuration {config_name}"
                    )
    return set(rule_ids), rule_inputs


def database_annotations(section: str, kind: str) -> list[tuple[str, str, str, str]]:
    records: list[tuple[str, str, str, str]] = []
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
            for operation_id, operation, table in DB_ANNOTATION_PATTERN.findall(line):
                records.append((operation_id, node_match.group(1), operation, table))
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
        if re.search(r"^\|\s*操作ID\s*\|\s*节点\s*\|", section, re.MULTILINE):
            errors.append("database: empty conclusion conflicts with operation table")
        return

    lines = section.splitlines()
    header_index = -1
    expected = [
        "操作ID",
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
        if cells and cells[0] == "操作ID" and len(cells) > 2 and cells[1] == "节点":
            header_index = index
            if cells != expected:
                errors.append("database: operation table columns do not match the required order")
            break
    if header_index < 0:
        errors.append("database: missing required operation table")
        return

    summary_records: list[tuple[str, str, str, str]] = []
    for line in lines[header_index + 1 :]:
        if not line.lstrip().startswith("|"):
            if summary_records:
                break
            continue
        cells = markdown_cells(line)
        if not cells or cells[0].startswith("---"):
            continue
        if len(cells) != 9:
            errors.append("database: each operation row must contain all nine fields")
            continue
        operation_id = cells[0].strip(" `<> ")
        node = cells[1].strip(" `<> ")
        table = cells[2].strip(" `<> ")
        operation = cells[3].strip(" `<> ")
        if not re.fullmatch(DB_OPERATION_ID, operation_id):
            errors.append(f"database: invalid operation ID {operation_id!r}")
        if node not in n_ids:
            errors.append(f"database: operation row references missing node {node!r}")
        if not re.fullmatch(DB_OPERATION, operation):
            errors.append(f"database: {node}/{table} has invalid operation {operation!r}")
        if not table:
            errors.append(f"database: {node} has an empty table name")
        if any(not cells[index].strip(" `<> ") for index in range(4, 9)):
            errors.append(f"database: {node}/{table} has empty operation details")
        core_value = cells[8].strip(" `<> ")
        if not re.match(r"^(?:核心|辅助)[；;：:].+$", core_value):
            errors.append(f"database: {node}/{table} core classification requires 核心/辅助 and reason")
        summary_records.append((operation_id, node, operation, table))

    if not summary_records:
        errors.append("database: operation table has no rows")
        return
    if re.search(r"遍历结论：[^\n]*调用图已闭合", text) and any(
        table.startswith("unresolved:") for _, _, _, table in summary_records
    ):
        errors.append("database: report cannot claim 调用图已闭合 with unresolved tables")
    for label, records in (
        ("sequence", sequence_records),
        ("tree", tree_records_found),
        ("summary", summary_records),
    ):
        duplicate_ids = sorted(
            operation_id
            for operation_id, count in Counter(record[0] for record in records).items()
            if count != 1
        )
        if duplicate_ids:
            errors.append(f"database: duplicate {label} operation IDs: {duplicate_ids}")
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
    sequence_action_map = sequence_actions(sequence_section)
    tree_action_map = tree_actions(tree_section)
    sequence_async_ids, tree_async_ids = asynchronous_execution_ids(
        sequence_section, tree_section
    )
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
        expected_action = normalize_action(record.action)
        validate_action_quality(node_id, expected_action, errors)
        if "异步" in record.context:
            if node_id not in sequence_async_ids:
                errors.append(f"async: {node_id} context is asynchronous but sequence does not use -)")
            if node_id not in tree_async_ids:
                errors.append(
                    f"async: {node_id} context is asynchronous but tree lacks ~~异步~~>"
                )
        if sequence_action_map.get(node_id) != expected_action:
            errors.append(
                f"identity: {node_id} sequence action {sequence_action_map.get(node_id)!r} "
                f"!= {expected_action!r}"
            )
        if tree_action_map.get(node_id) != expected_action:
            errors.append(
                f"identity: {node_id} tree action {tree_action_map.get(node_id)!r} "
                f"!= {expected_action!r}"
            )

    validate_hierarchy(sequence_set | tree_set | table_set, errors)
    validate_tree_layout(tree_section, errors)
    x_ids = crosscut_ids(text, sequence_section, errors)
    validate_logs(text, table_set, x_ids, errors)
    rule_ids, rule_inputs = validate_reader_guidance(text, table_set, errors)
    validate_configurations(text, table_set, rule_ids, rule_inputs, errors)
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
