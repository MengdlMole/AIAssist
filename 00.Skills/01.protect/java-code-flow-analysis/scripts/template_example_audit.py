#!/usr/bin/env python3
"""Extract and validate the canonical report/Flow Pack example."""

from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

from report_id_audit import audit_flow_pack, audit_markdown


SKILL_DIR = Path(__file__).resolve().parent.parent
TEMPLATE = SKILL_DIR / "references" / "report-template.md"


def extract(pattern: str, text: str, label: str) -> str:
    match = re.search(pattern, text, flags=re.DOTALL)
    if not match:
        raise ValueError(f"cannot find {label} in {TEMPLATE}")
    return match.group(1).strip() + "\n"


def main() -> int:
    text = TEMPLATE.read_text(encoding="utf-8")
    try:
        tree = extract(r"## 3\. 树形调用链.*?```text\n(.*?)\n```", text, "call tree example")
        flow_pack = extract(r"## Flow Pack 规范.*?```jsonl\n(.*?)\n```", text, "Flow Pack example")
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    markdown = "\n".join([
        "# 模板契约示例",
        "",
        "## 流程概述",
        "模板示例的最小可校验说明。",
        "",
        "## 树形调用链",
        "",
        "```text",
        tree.rstrip(),
        "```",
        "",
        "## 分阶段说明",
        "模板示例覆盖订单创建和异步库存处理。",
        "",
    ])

    with tempfile.TemporaryDirectory(prefix="flow-template-audit-") as temp_dir:
        temp = Path(temp_dir)
        report_path = temp / "example.md"
        pack_path = temp / "example.flow.jsonl"
        report_path.write_text(markdown, encoding="utf-8")
        pack_path.write_text(flow_pack, encoding="utf-8")
        _, nodes, tag_refs, errors = audit_markdown(report_path)
        errors.extend(audit_flow_pack(pack_path, nodes, tag_refs))

        duplicate_records = [json.loads(line) for line in flow_pack.splitlines()]
        duplicate_records.append(next(record for record in duplicate_records if record.get("type") == "edge"))
        pack_path.write_text(
            "\n".join(json.dumps(record, ensure_ascii=False) for record in duplicate_records) + "\n",
            encoding="utf-8",
        )
        duplicate_errors = audit_flow_pack(pack_path, nodes, tag_refs)
        if not any("duplicate edge identity" in error for error in duplicate_errors):
            errors.append("regression: duplicate edge identity was not rejected")

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"OK: canonical template example passes report_id_audit: {TEMPLATE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
