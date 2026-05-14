#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Sequence


REQUIRED_HEADINGS = [
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
STALE_HEADINGS = [
    "## 7. 关键机制与公式速查",
    "## 8. 图表与实验解读",
    "## 9. 相关工作与定位",
    "## 10. 局限与边界",
    "## 11. 结论",
    "## 12. 参考链接",
    "## 13. 建议插图",
]
PLACEHOLDER_PATTERNS = [
    re.compile(r"\bTODO\b", re.IGNORECASE),
    re.compile(r"\bTBD\b", re.IGNORECASE),
    re.compile(r"在这里"),
    re.compile(r"待补"),
    re.compile(r"待写"),
]
TRANSCRIPT_LEAK_PATTERNS = [
    re.compile(r"^\s*####\s+.+said:\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"\bYou said\b", re.IGNORECASE),
    re.compile(r"\bChatGPT said\b", re.IGNORECASE),
    re.compile(r"\bClaude said\b", re.IGNORECASE),
    re.compile(r"\bGemini said\b", re.IGNORECASE),
]
TABLE_SEPARATOR_RE = re.compile(r"^\|\s*[-: ]+\|\s*[-|: ]+$")
NUMBERED_SUBHEADING_RE = re.compile(r"^###\s+(?P<number>\d+\.\d+)\b")
SECTION_SUBHEADING_PREFIX = {
    "## 2. 研究问题与核心困难": "2.",
    "## 6. 方法详解": "6.",
    "## 7. 图表与实验解读": "7.",
    "## 8. 局限与边界": "8.",
}


def count_cjk(text: str) -> int:
    return sum(1 for char in text if "\u4e00" <= char <= "\u9fff")


def has_markdown_table(text: str) -> bool:
    lines = text.splitlines()
    for idx in range(len(lines) - 1):
        if "|" not in lines[idx]:
            continue
        if TABLE_SEPARATOR_RE.match(lines[idx + 1].strip()):
            return True
    return False


def has_math(text: str) -> bool:
    if "```latex" in text or "```tex" in text or "$$" in text:
        return True
    return bool(re.search(r"\$[^$\n]{3,}\$", text))


def extract_section_block(text: str, heading: str) -> list[str]:
    lines = text.splitlines()
    capture = False
    bucket: list[str] = []
    for line in lines:
        if line.strip() == heading:
            capture = True
            continue
        if capture and line.startswith("## "):
            break
        if capture:
            bucket.append(line)
    return bucket


def validate_report(report_path: Path) -> dict[str, object]:
    report_path = report_path.resolve()
    if not report_path.exists():
        return {
            "passed": False,
            "issues": [f"report not found: {report_path}"],
            "warnings": [],
            "stats": {},
        }

    text = report_path.read_text(encoding="utf-8")
    issues: list[str] = []
    warnings: list[str] = []

    for heading in REQUIRED_HEADINGS:
        if heading not in text:
            issues.append(f"missing heading: {heading}")
    for heading in STALE_HEADINGS:
        if heading in text:
            issues.append(f"stale heading detected: {heading}")
    for pattern in PLACEHOLDER_PATTERNS:
        if pattern.search(text):
            issues.append(f"placeholder text detected: /{pattern.pattern}/")
    for pattern in TRANSCRIPT_LEAK_PATTERNS:
        if pattern.search(text):
            issues.append(f"transcript marker leaked into report: /{pattern.pattern}/")
    for heading, expected_prefix in SECTION_SUBHEADING_PREFIX.items():
        if heading not in text:
            continue
        for line in extract_section_block(text, heading):
            match = NUMBERED_SUBHEADING_RE.match(line.strip())
            if not match:
                continue
            number = match.group("number")
            if not number.startswith(expected_prefix):
                issues.append(
                    f"subheading numbering mismatch under {heading}: expected prefix {expected_prefix}, got {number}"
                )

    char_count = len(text)
    cjk_count = count_cjk(text)
    if char_count < 3200:
        warnings.append("report is short; likely not detailed enough for a teaching-style paper report")
    if cjk_count < 300:
        issues.append("report contains too little Chinese content")
    if not has_markdown_table(text):
        issues.append("report is missing a markdown table")
    if not has_math(text):
        issues.append("report is missing markdown math or a latex block")
    if "http://" not in text and "https://" not in text:
        issues.append("report is missing reference links")
    if "[[FIG:" not in text and "[[TAB:" not in text:
        warnings.append("report does not contain figure/table placement markers")

    return {
        "passed": not issues,
        "issues": issues,
        "warnings": warnings,
        "stats": {
            "char_count": char_count,
            "cjk_count": cjk_count,
            "line_count": len(text.splitlines()),
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the final markdown report produced by paper-chat-report.")
    parser.add_argument("--report", required=True, help="Path to docs/papers/<slug>.md")
    parser.add_argument("--json", action="store_true", help="Print JSON payload")
    parser.add_argument("--require-pass", action="store_true", help="Exit 2 if validation fails")
    args = parser.parse_args(argv)

    payload = validate_report(Path(args.report))
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"passed: {payload['passed']}")
        print(f"issues: {len(payload['issues'])}")
        for issue in payload["issues"]:
            print(f"- {issue}")
        if payload["warnings"]:
            print(f"warnings: {len(payload['warnings'])}")
            for warning in payload["warnings"]:
                print(f"- {warning}")
        print(f"stats: {payload['stats']}")

    if args.require_pass and not payload["passed"]:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
