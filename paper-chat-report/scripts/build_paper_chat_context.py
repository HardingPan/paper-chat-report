#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence

from paper_chat_report_common import atomic_write_text, read_json, trim_text


SECTION_HEADING_RE = re.compile(r"^(#{1,6})\s+(?P<title>.+?)\s*$")


def normalize_space(value: str) -> str:
    return " ".join(value.split()).strip()


def extract_markdown_section(text: str, title: str) -> str:
    lines = text.splitlines()
    capture = False
    target_level = None
    bucket: list[str] = []
    for line in lines:
        match = SECTION_HEADING_RE.match(line.strip())
        if match:
            current_title = normalize_space(match.group("title"))
            current_level = len(match.group(1))
            if capture and current_level <= (target_level or current_level):
                break
            if current_title == title:
                capture = True
                target_level = current_level
                continue
        if capture:
            bucket.append(line)
    return "\n".join(bucket).strip()


def resolve_skill_root() -> Path:
    """根据当前脚本位置解析 skill 根目录，支持多宿主（agents/codex/claude）"""
    # 当前脚本所在目录: .../scripts/
    scripts_dir = Path(__file__).parent.resolve()
    # 向上两级到 skill 根目录
    return scripts_dir.parent


def find_contract_path() -> Path | None:
    # 优先从当前 skill 根目录查找
    skill_root = resolve_skill_root()
    local_candidate = skill_root / "references" / "report-contract.md"
    if local_candidate.exists():
        return local_candidate
    # 回退到全局路径（兼容旧用法）
    candidates = [
        Path.home() / ".agents" / "skills" / "paper-chat-report" / "references" / "report-contract.md",
        Path.home() / ".codex" / "skills" / "paper-chat-report" / "references" / "report-contract.md",
        Path.home() / ".claude" / "skills" / "paper-chat-report" / "references" / "report-contract.md",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def choose_report_path(manifest: dict[str, Any], source: dict[str, Any], analysis_dir: Path) -> Path:
    report_path = manifest.get("report_path") or source.get("report_path")
    if report_path:
        return Path(str(report_path))
    slug = manifest.get("slug") or analysis_dir.name
    root = analysis_dir.parents[3]
    return root / "docs" / "papers" / f"{slug}.md"


def load_equation_cards(path: Path) -> list[dict[str, Any]]:
    payload = read_json(path)
    cards = payload.get("equation_cards", [])
    return cards if isinstance(cards, list) else []


def select_primary_equations(cards: list[dict[str, Any]], limit: int = 6) -> list[dict[str, Any]]:
    def priority(card: dict[str, Any]) -> tuple[int, int]:
        source_score = 30 if card.get("source") == "paper" else 20
        role = str(card.get("role", "other"))
        role_score = {"method": 20, "problem": 5, "evidence": 5, "other": 0}.get(role, 0)
        eq_id = str(card.get("eq", "999")).replace("dialogue-", "999")
        try:
            eq_num = int(eq_id)
        except ValueError:
            eq_num = 999
        return (source_score + role_score, -eq_num)

    return sorted(cards, key=priority, reverse=True)[:limit]


def build_context_markdown(
    *,
    manifest: dict[str, Any],
    source: dict[str, Any],
    section_map: dict[str, Any],
    teaching_map_text: str,
    equation_cards: list[dict[str, Any]],
    contract_text: str,
    analysis_dir: Path,
) -> str:
    title = str(manifest.get("title") or source.get("candidate_title") or analysis_dir.name)
    report_path = choose_report_path(manifest, source, analysis_dir)
    problem_framing = extract_markdown_section(teaching_map_text, "Problem Framing")
    method_story = extract_markdown_section(teaching_map_text, "Method Story")
    evidence_cards = extract_markdown_section(teaching_map_text, "Evidence Cards")
    report_focus = extract_markdown_section(teaching_map_text, "Report Drafting Focus")
    equation_section = extract_markdown_section(teaching_map_text, "Equation Cards")
    primary_equations = select_primary_equations(equation_cards)

    assistant_turns = int(section_map.get("assistant_turns", 0))
    parsed_sections = int(len(section_map.get("sections", []))) if isinstance(section_map.get("sections", []), list) else 0

    dialogue_path = source.get('dialogue_path', manifest.get('dialogue_path', ''))

    lines: list[str] = [
        f"# {title} - 成稿上下文",
        "",
        "## Target Output",
        "",
        f"- 输出文件：`{report_path}`",
        f"- 工作目录：`{analysis_dir}`",
        f"- Dialogue Source: `{dialogue_path}`",
        f"- Paper Source: `{(source.get('paper_source') or {}).get('display_source', 'unresolved')}`",
        "",
        "## Required Inputs",
        "",
        f"- `manifest.json`: `{analysis_dir / 'manifest.json'}`",
        f"- `source.json`: `{analysis_dir / 'source.json'}`",
        f"- `dialogue-cleaned.md`: `{analysis_dir / 'dialogue-cleaned.md'}`",
        f"- `dialogue-section-map.json`: `{analysis_dir / 'dialogue-section-map.json'}`",
        f"- `teaching-map.md`: `{analysis_dir / 'teaching-map.md'}`",
        f"- `equation-cards.json`: `{analysis_dir / 'equation-cards.json'}`",
        f"- `paper.struct.md`: `{analysis_dir / 'paper.struct.md'}`",
        f"- `paper.txt`: `{analysis_dir / 'paper.txt'}`",
        "",
        "## Dialogue Signal Summary",
        "",
        f"- 总 turn 数：{manifest.get('dialogue_turn_count', section_map.get('total_turns', 0))}",
        f"- assistant turn 数：{assistant_turns}",
        f"- 解析出的助手章节数：{parsed_sections}",
        "",
        "## Non-Negotiables",
        "",
        "- 最终稿必须是 standalone 文档，而不是 transcript 改写版。",
        "- 中文为主，英文术语保留。",
        "- 对话用来继承解释逻辑，原论文用来做事实纠偏。",
        "- 不能保留 `You said` / `ChatGPT said` / `Claude said` / `Gemini said`。",
        "- 方法解释优先，公式要嵌入方法小节。",
        "- 顶层结构按 `0/1/2/3/4/5/6/7/8/9/10` 写，不要沿用旧版 `8/10/12` 编号。",
        "- 相关工作整合到 `2.2 研究现状与局限`，不要单列 `相关工作与定位`。",
        "- 不要创建独立的 `关键机制与公式速查` 或 `建议插图` 章节。",
        "- 图表位置在正文中用 `[[FIG:n|...]]` / `[[TAB:n|...]]` 标记，而不是文末集中列出。",
        f"- **阅读源对话文件** `{dialogue_path}`，识别用户追问环节并整合洞见。",
        "",
        "## Problem Framing",
        "",
        problem_framing or "- 需要回看 teaching-map.md 的 Problem Framing 部分。",
        "",
        "## Method Story",
        "",
        method_story or "- 需要回看 teaching-map.md 的 Method Story 部分。",
        "",
        "## Evidence To Cite",
        "",
        evidence_cards or "- 需要回看 teaching-map.md 的 Evidence Cards 部分。",
        "",
        "## Primary Equations To Weave Into Method",
        "",
    ]

    if primary_equations:
        for card in primary_equations:
            lines.append(f"### Eq. ({card['eq']})")
            lines.append("")
            lines.append(f"- Source: `{card.get('source', 'unknown')}`")
            lines.append(f"- Section: `{card.get('section', 'unknown')}`")
            lines.append(f"- Role: `{card.get('role', 'other')}`")
            lines.append("")
            lines.append("```text")
            lines.append(trim_text(str(card.get("preferred_excerpt", "")).strip(), limit=1200))
            lines.append("```")
            lines.append("")
    elif equation_section:
        lines.append(equation_section)
        lines.append("")
    else:
        lines.append("- 未识别到稳定公式卡片，需要回看原论文。")
        lines.append("")

    lines.extend(
        [
            "## Final Writing Checklist",
            "",
            report_focus or "- 需要回看 teaching-map.md 的 Report Drafting Focus 部分。",
            "- 检查 `## 7. 图表与实验解读`、`## 8. 局限与边界`、`## 9. 结论`、`## 10. 参考链接` 是否按新版编号落位。",
            "- 检查子节编号是否和父节一致，例如 `7.1/7.2/7.3` 必须属于第 7 节。",
            "- 写完后运行 `validate_paper_chat_report.py` 做结构和 transcript 泄漏校验。",
            "",
            "## Contract Reminder",
            "",
            trim_text(contract_text, limit=1800) if contract_text else "- report-contract.md 缺失，需按 skill 默认结构写作。",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def build_context(analysis_dir: Path) -> dict[str, Any]:
    analysis_dir = analysis_dir.resolve()
    manifest_path = analysis_dir / "manifest.json"
    source_path = analysis_dir / "source.json"
    section_map_path = analysis_dir / "dialogue-section-map.json"
    teaching_map_path = analysis_dir / "teaching-map.md"
    equation_cards_path = analysis_dir / "equation-cards.json"
    report_context_path = analysis_dir / "report-context.md"

    manifest = read_json(manifest_path)
    source = read_json(source_path)
    section_map = read_json(section_map_path)
    if not manifest:
        raise FileNotFoundError(f"manifest.json not found or invalid: {manifest_path}")
    if not teaching_map_path.exists():
        raise FileNotFoundError(f"teaching-map.md not found: {teaching_map_path}")
    if not equation_cards_path.exists():
        raise FileNotFoundError(f"equation-cards.json not found: {equation_cards_path}")

    contract_path = find_contract_path()
    contract_text = contract_path.read_text(encoding="utf-8") if contract_path and contract_path.exists() else ""
    teaching_map_text = teaching_map_path.read_text(encoding="utf-8")
    equation_cards = load_equation_cards(equation_cards_path)
    content = build_context_markdown(
        manifest=manifest,
        source=source,
        section_map=section_map,
        teaching_map_text=teaching_map_text,
        equation_cards=equation_cards,
        contract_text=contract_text,
        analysis_dir=analysis_dir,
    )
    atomic_write_text(report_context_path, content)
    return {
        "analysis_dir": str(analysis_dir),
        "report_context_path": str(report_context_path),
        "report_path": str(choose_report_path(manifest, source, analysis_dir)),
        "equation_count": len(equation_cards),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a condensed report writing context for paper-chat-report.")
    parser.add_argument("--analysis-dir", required=True, help="paper-chat-report analysis directory")
    parser.add_argument("--json", action="store_true", help="Print JSON payload")
    args = parser.parse_args(argv)

    payload = build_context(Path(args.analysis_dir))
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for key, value in payload.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
