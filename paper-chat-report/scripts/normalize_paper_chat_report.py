#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


TOP_HEADING_RE = re.compile(r"^##\s+(?P<title>.+?)\s*$")
NUMBERED_H3_RE = re.compile(r"^(###)\s+\d+\.\d+\s+(?P<title>.+?)\s*$")

NEW_HEADINGS = [
    "## 0. 阅读入口",
    "## 1. 基本信息",
    "## 2. 研究问题与核心困难",
    "## 3. 核心贡献",
    "## 4. 整体主线",
    "## 5. 方法总览与系统分解",
    "## 6. 方法详解",
    "## 7. 图表与实验解读",
    "## 8. 局限与边界",
    "## 9. 结论",
    "## 10. 参考链接",
]

OLD_TO_NEW_TOP = {
    "## 8. 图表与实验解读": "## 7. 图表与实验解读",
    "## 10. 局限与边界": "## 8. 局限与边界",
    "## 11. 结论": "## 9. 结论",
    "## 12. 参考链接": "## 10. 参考链接",
}


@dataclass
class Section:
    heading: str
    body: str


def parse_sections(text: str) -> tuple[str, list[Section]]:
    lines = text.splitlines()
    preamble: list[str] = []
    sections: list[Section] = []
    current_heading: str | None = None
    current_lines: list[str] = []

    for line in lines:
        if TOP_HEADING_RE.match(line):
            if current_heading is None:
                preamble = current_lines
            else:
                sections.append(Section(heading=current_heading, body="\n".join(current_lines).strip()))
            current_heading = line.strip()
            current_lines = []
            continue
        current_lines.append(line)

    if current_heading is None:
        return ("\n".join(current_lines).rstrip() + "\n") if current_lines else "", []
    sections.append(Section(heading=current_heading, body="\n".join(current_lines).strip()))
    return ("\n".join(preamble).rstrip() + "\n") if preamble else "", sections


def get_body(section_map: dict[str, str], preferred: str, fallback: str | None = None) -> str:
    if preferred in section_map:
        return section_map[preferred]
    if fallback and fallback in section_map:
        return section_map[fallback]
    return ""


def append_subsection(body: str, heading: str, content: str) -> str:
    content = content.strip()
    if not content:
        return body.strip()
    base = body.strip()
    if base:
        return f"{base}\n\n{heading}\n\n{content}".rstrip()
    return f"{heading}\n\n{content}".rstrip()


def renumber_h3_block(body: str, prefix: int) -> str:
    lines = body.splitlines()
    counter = 0
    result: list[str] = []
    for line in lines:
        match = NUMBERED_H3_RE.match(line.strip())
        if not match:
            result.append(line)
            continue
        counter += 1
        result.append(f"### {prefix}.{counter} {match.group('title')}")
    return "\n".join(result).rstrip()


def normalize_report_text(text: str) -> tuple[str, dict[str, object]]:
    preamble, sections = parse_sections(text)
    section_map = {section.heading: section.body for section in sections}
    changes: list[str] = []

    section2 = get_body(section_map, "## 2. 研究问题与核心困难")
    old_related = get_body(section_map, "## 9. 相关工作与定位")
    if old_related:
        section2 = append_subsection(section2, "#### 补充：相关工作定位（自动归并）", old_related)
        changes.append("merged old related-work section into section 2")

    section6 = get_body(section_map, "## 6. 方法详解")
    old_equation = get_body(section_map, "## 7. 关键机制与公式速查")
    if old_equation:
        section6 = append_subsection(section6, "### 6.5 机制与公式补充（自动归并）", old_equation)
        changes.append("merged old equation-summary section into section 6")

    section7 = get_body(section_map, "## 7. 图表与实验解读", "## 8. 图表与实验解读")
    if "## 8. 图表与实验解读" in section_map and "## 7. 图表与实验解读" not in section_map:
        changes.append("renamed top-level section 8 -> 7 for evidence section")

    old_fig_suggestions = get_body(section_map, "## 13. 建议插图")
    if old_fig_suggestions:
        section7 = append_subsection(section7, "#### 补充：图表关注清单（自动归并）", old_fig_suggestions)
        changes.append("merged old figure-suggestion section into section 7")

    section8 = get_body(section_map, "## 8. 局限与边界", "## 10. 局限与边界")
    if "## 10. 局限与边界" in section_map and "## 8. 局限与边界" not in section_map:
        changes.append("renamed top-level section 10 -> 8 for limitation section")

    section9 = get_body(section_map, "## 9. 结论", "## 11. 结论")
    if "## 11. 结论" in section_map and "## 9. 结论" not in section_map:
        changes.append("renamed top-level section 11 -> 9 for conclusion section")

    section10 = get_body(section_map, "## 10. 参考链接", "## 12. 参考链接")
    if "## 12. 参考链接" in section_map and "## 10. 参考链接" not in section_map:
        changes.append("renamed top-level section 12 -> 10 for reference section")

    bodies = {
        "## 0. 阅读入口": get_body(section_map, "## 0. 阅读入口"),
        "## 1. 基本信息": get_body(section_map, "## 1. 基本信息"),
        "## 2. 研究问题与核心困难": renumber_h3_block(section2, 2),
        "## 3. 核心贡献": get_body(section_map, "## 3. 核心贡献"),
        "## 4. 整体主线": get_body(section_map, "## 4. 整体主线"),
        "## 5. 方法总览与系统分解": get_body(section_map, "## 5. 方法总览与系统分解"),
        "## 6. 方法详解": renumber_h3_block(section6, 6),
        "## 7. 图表与实验解读": renumber_h3_block(section7, 7),
        "## 8. 局限与边界": renumber_h3_block(section8, 8),
        "## 9. 结论": get_body(section_map, "## 9. 结论", "## 11. 结论"),
        "## 10. 参考链接": get_body(section_map, "## 10. 参考链接", "## 12. 参考链接"),
    }

    for old_heading, new_heading in OLD_TO_NEW_TOP.items():
        if old_heading in section_map and new_heading not in section_map:
            changes.append(f"mapped {old_heading} -> {new_heading}")

    rendered: list[str] = []
    if preamble.strip():
        rendered.append(preamble.rstrip())
        rendered.append("")
    for heading in NEW_HEADINGS:
        body = bodies.get(heading, "").strip()
        if not body:
            continue
        rendered.append(heading)
        rendered.append("")
        rendered.append(body)
        rendered.append("")

    normalized = "\n".join(rendered).rstrip() + "\n"
    return normalized, {
        "changed": normalized != text,
        "changes": changes,
        "kept_sections": [heading for heading in NEW_HEADINGS if bodies.get(heading, "").strip()],
    }


def normalize_report(report: Path, output: Path | None = None, in_place: bool = False) -> dict[str, object]:
    report = report.resolve()
    if not report.exists():
        raise FileNotFoundError(f"report not found: {report}")
    text = report.read_text(encoding="utf-8")
    normalized, summary = normalize_report_text(text)

    if in_place:
        target = report
    elif output is not None:
        target = output.resolve()
    else:
        target = report.with_name(report.stem + "-normalized" + report.suffix)

    target.write_text(normalized, encoding="utf-8")
    return {
        "report": str(report),
        "output": str(target),
        **summary,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Normalize old paper-chat-report markdown structure to the latest contract.")
    parser.add_argument("--report", required=True, help="Path to the markdown report")
    parser.add_argument("--output", help="Optional output path")
    parser.add_argument("--in-place", action="store_true", help="Rewrite the report file in place")
    parser.add_argument("--json", action="store_true", help="Print JSON payload")
    args = parser.parse_args(argv)

    if args.output and args.in_place:
        raise SystemExit("Use either --output or --in-place, not both.")

    payload = normalize_report(
        report=Path(args.report),
        output=Path(args.output) if args.output else None,
        in_place=args.in_place,
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for key, value in payload.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
