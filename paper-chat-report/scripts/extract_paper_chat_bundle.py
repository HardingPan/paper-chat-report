#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence

from build_paper_chat_context import build_context
from paper_chat_report_common import (
    INLINE_MATH_RE,
    LATEX_BLOCK_RE,
    LOSS_TERM_RE,
    atomic_write_text,
    choose_best_title,
    collect_pdf_bundle,
    download_file,
    extract_candidate_title_from_dialogue,
    normalize_space,
    parse_role_marked_dialogue,
    read_json,
    render_cleaned_dialogue,
    resolve_paper_source,
    slugify,
    trim_text,
    write_json,
)


SECTION_HEADING_RE = re.compile(r"^(#{1,6})\s+(?P<title>.+?)\s*$")


def split_markdown_sections(text: str) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        match = SECTION_HEADING_RE.match(line.strip())
        if match:
            if current is not None:
                current["body"] = "\n".join(current["lines"]).strip()
                sections.append(current)
            current = {
                "title": normalize_space(match.group("title")),
                "level": len(match.group(1)),
                "lines": [],
            }
            continue
        if current is not None:
            current["lines"].append(line)
    if current is not None:
        current["body"] = "\n".join(current["lines"]).strip()
        sections.append(current)
    return sections


def classify_dialogue_section(title: str, body: str) -> str:
    """简单分类对话片段，主要用于索引"""
    lowered = f"{normalize_space(title)} {normalize_space(body[:400])}".lower()
    if any(token in lowered for token in ("标题", "基本信息", "关键词", "paper info", "核心关键词")):
        return "metadata"
    if any(token in lowered for token in ("问题", "背景", "动机", "难题", "challenge", "introduction", "研究问题")):
        return "problem"
    if any(token in lowered for token in ("方法", "机制", "pipeline", "framework", "approach", "algorithm", "planning", "world model", "dynamics", "核心思想")):
        return "method"
    if any(token in lowered for token in ("贡献", "innovation", "insight", "contribution")):
        return "contribution"
    if any(token in lowered for token in ("实验", "结果", "evaluation", "benchmark", "ablation", "effect", "实验结论")):
        return "evidence"
    if any(token in lowered for token in ("related work", "相关工作", "preliminar")):
        return "related"
    if any(token in lowered for token in ("局限", "conclusion", "discussion", "总结")):
        return "conclusion"
    return "other"


def extract_equations_from_text(text: str) -> list[str]:
    equations: list[str] = []
    for match in LATEX_BLOCK_RE.finditer(text):
        equation = normalize_space(match.group(1))
        if equation:
            equations.append(equation)
    for match in INLINE_MATH_RE.finditer(text):
        equation = normalize_space(match.group(1))
        if equation and len(equation) >= 3:
            equations.append(equation)
    for raw_line in text.splitlines():
        compact = normalize_space(raw_line)
        if "=" in compact and (LOSS_TERM_RE.search(compact) or "\\" in compact or "_" in compact):
            equations.append(compact)
    deduped: list[str] = []
    seen: set[str] = set()
    for equation in equations:
        key = re.sub(r"\s+", "", equation)
        if key and key not in seen:
            seen.add(key)
            deduped.append(equation)
    return deduped[:8]


def choose_section_excerpt(body: str, limit: int = 220) -> str:
    candidates: list[str] = []
    for raw_line in body.splitlines():
        line = normalize_space(raw_line)
        if not line:
            continue
        if line.startswith(("|", "![", "<img", "```", ">", "* * *")):
            continue
        if len(line) < 15 and not any(char.isdigit() for char in line):
            continue
        candidates.append(line)
        if len(candidates) >= 3:
            break
    if not candidates:
        return trim_text(body, limit=limit)
    return trim_text(" ".join(candidates), limit=limit)


def build_dialogue_section_map(turns: list[dict[str, Any]], title: str) -> dict[str, Any]:
    """构建对话章节映射，供 AI 参考索引"""
    sections: list[dict[str, Any]] = []
    assistant_turns = 0

    for turn in turns:
        if turn["role"] != "assistant":
            continue
        assistant_turns += 1
        raw_sections = split_markdown_sections(str(turn.get("cleaned_content", "")))
        if not raw_sections:
            raw_sections = [{"title": f"Turn {turn['turn_index']}", "level": 2, "body": str(turn.get("cleaned_content", ""))}]

        for index, section in enumerate(raw_sections, start=1):
            role = classify_dialogue_section(section["title"], section.get("body", ""))
            equations = extract_equations_from_text(section.get("body", ""))
            sections.append(
                {
                    "turn_index": turn["turn_index"],
                    "section_index": index,
                    "speaker_label": turn["speaker_label"],
                    "title": section["title"],
                    "level": int(section.get("level", 2)),
                    "role": role,
                    "excerpt": choose_section_excerpt(section.get("body", "")),
                    "body": section.get("body", ""),
                    "equations": equations,
                }
            )

    role_counts: dict[str, int] = {}
    for section in sections:
        role_counts[section["role"]] = role_counts.get(section["role"], 0) + 1

    return {
        "paper_title": title,
        "total_turns": len(turns),
        "assistant_turns": assistant_turns,
        "sections": sections,
        "role_counts": role_counts,
    }


def role_cards(section_map: dict[str, Any], role: str, limit: int = 4) -> list[dict[str, Any]]:
    sections = section_map.get("sections", [])
    if not isinstance(sections, list):
        return []
    return [section for section in sections if section.get("role") == role][:limit]


def role_lines(section_map: dict[str, Any], role: str, prefix: str) -> list[str]:
    cards = role_cards(section_map, role)
    if not cards:
        return [f"- {prefix}：未从对话中稳定提取。"]
    return [f"- [{prefix}] {card['title']}: {card['excerpt']}" for card in cards]


def derive_equation_cards(section_map: dict[str, Any], paper_bundle: dict[str, Any] | None) -> dict[str, Any]:
    cards: list[dict[str, Any]] = []
    eq_index = 1
    for section in section_map.get("sections", []):
        equations = section.get("equations", [])
        if not isinstance(equations, list):
            continue
        for equation in equations:
            cards.append(
                {
                    "eq": f"dialogue-{eq_index}",
                    "source": "dialogue",
                    "section": section.get("title", ""),
                    "role": section.get("role", "other"),
                    "loss_terms": LOSS_TERM_RE.findall(equation),
                    "preferred_excerpt": equation,
                }
            )
            eq_index += 1

    if paper_bundle:
        for anchor in paper_bundle.get("equation_anchors", []):
            section_title = str(anchor.get("section", ""))
            role = "method"
            lowered = section_title.lower()
            if any(token in lowered for token in ("experiment", "evaluation", "result")):
                role = "evidence"
            cards.append(
                {
                    "eq": str(anchor.get("eq", "")),
                    "source": "paper",
                    "section": section_title,
                    "role": role,
                    "loss_terms": anchor.get("loss_terms", []),
                    "preferred_excerpt": anchor.get("snippet", ""),
                }
            )

    deduped: dict[tuple[str, str], dict[str, Any]] = {}
    for card in cards:
        key = (str(card.get("source", "")), str(card.get("eq", "")))
        deduped[key] = card
    final_cards = list(deduped.values())
    return {
        "equation_cards": final_cards,
        "counts": {
            "dialogue": sum(1 for card in final_cards if card.get("source") == "dialogue"),
            "paper": sum(1 for card in final_cards if card.get("source") == "paper"),
        },
    }


def build_teaching_map_markdown(
    *,
    title: str,
    dialogue_path: Path,
    paper_source: dict[str, Any] | None,
    section_map: dict[str, Any],
    equation_cards: dict[str, Any],
    paper_bundle: dict[str, Any] | None,
) -> str:
    lines: list[str] = [
        f"# {title} - 教学地图",
        "",
        "## Source",
        "",
        f"- Dialogue: `{dialogue_path}`",
        f"- Paper Source: `{(paper_source or {}).get('display_source', 'unresolved')}`",
        "",
        "## Dialogue Inventory",
        "",
        f"- 总 turn 数：{section_map.get('total_turns', 0)}",
        f"- assistant turn 数：{section_map.get('assistant_turns', 0)}",
        f"- 解析出的章节数：{len(section_map.get('sections', []))}",
        "",
        "## Paper Resolution",
        "",
    ]

    if paper_source:
        lines.append(f"- 解析方式：`{paper_source.get('resolved_via', paper_source.get('source_type', 'unknown'))}`")
        lines.append(f"- 解析后的来源：`{paper_source.get('display_source', paper_source.get('original_source', ''))}`")
    else:
        lines.append("- 原论文未稳定解析，只能基于对话先整理骨架。")

    if paper_bundle:
        lines.extend(
            [
                f"- 文本主来源：`{paper_bundle.get('preferred_text_source', 'unknown')}`",
                f"- 可读性：`{'sufficient' if paper_bundle.get('readability', {}).get('sufficient') else 'insufficient'}`",
                f"- 论文章节线索：{', '.join(paper_bundle.get('sections', [])[:8]) or 'n/a'}",
            ]
        )

    lines.extend(["", "## Problem Framing", ""])
    lines.extend(role_lines(section_map, "problem", "对话"))
    if paper_bundle:
        problem_sections = [section for section in paper_bundle.get("sections", []) if "intro" in section.lower() or "abstract" in section.lower()]
        if problem_sections:
            lines.append(f"- [论文] {', '.join(problem_sections[:3])}")

    lines.extend(["", "## Method Story", ""])
    lines.extend(role_lines(section_map, "method", "对话"))
    lines.extend(role_lines(section_map, "contribution", "对话 - 贡献"))
    if paper_bundle:
        method_sections = [section for section in paper_bundle.get("sections", []) if any(token in section.lower() for token in ("method", "approach", "pipeline", "framework", "3."))]
        if method_sections:
            lines.append(f"- [论文] {', '.join(method_sections[:4])}")

    lines.extend(["", "## Evidence Cards", ""])
    lines.extend(role_lines(section_map, "evidence", "对话"))
    if paper_bundle:
        evidence_sections = [section for section in paper_bundle.get("sections", []) if any(token in section.lower() for token in ("experiment", "evaluation", "result", "4."))]
        if evidence_sections:
            lines.append(f"- [论文] {', '.join(evidence_sections[:4])}")
        figure_count = len(paper_bundle.get("figure_anchors", []))
        table_count = len(paper_bundle.get("table_anchors", []))
        if figure_count or table_count:
            lines.append(f"- [论文] figures={figure_count}, tables={table_count}")

    lines.extend(["", "## Equation Cards", ""])
    cards = equation_cards.get("equation_cards", [])
    if cards:
        for card in cards[:8]:
            lines.append(
                f"- Eq. ({card['eq']}) [{card.get('source', 'unknown')}] {card.get('section', 'unknown')}: {trim_text(str(card.get('preferred_excerpt', '')), 160)}"
            )
    else:
        lines.append("- 未识别到稳定公式卡片。")

    lines.extend(
        [
            "",
            "## Report Drafting Focus",
            "",
            "- 把对话里的解释逻辑重写为独立报告，不保留 transcript 结构。",
            "- 对话作为解释材料，原论文作为事实纠偏来源；若冲突以原论文为准。",
            "- 方法部分优先解释阶段协作、关键变量、关键约束和执行顺序。",
            "- 公式要嵌进方法小节，而不是从对话里生搬硬套成单独公式堆栈。",
            "- 实验部分只选最能支撑 claim 的图表和结果。",
            "- **自己阅读源对话文件**，识别用户的追问环节，将追问解答中的洞见整合到主干叙述。",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def resolve_pdf_path(out_dir: Path, paper_source: dict[str, Any]) -> Path:
    source_type = str(paper_source.get("source_type", ""))
    if source_type == "local_pdf":
        return Path(str(paper_source["pdf_path"]))
    pdf_url = str(paper_source.get("pdf_url", "")).strip()
    if not pdf_url:
        raise ValueError("resolved paper source does not contain a downloadable PDF URL")
    destination = out_dir / "paper.pdf"
    download_file(pdf_url, destination)
    return destination


def extract_bundle(dialogue: str, out_dir: Path, source: str | None = None) -> tuple[dict[str, Any], int]:
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest.json"
    source_path = out_dir / "source.json"
    dialogue_source_path = out_dir / "dialogue-source.md"
    dialogue_normalized_path = out_dir / "dialogue-normalized.json"
    dialogue_cleaned_path = out_dir / "dialogue-cleaned.md"
    dialogue_section_map_path = out_dir / "dialogue-section-map.json"
    teaching_map_path = out_dir / "teaching-map.md"
    equation_cards_path = out_dir / "equation-cards.json"
    paper_text_path = out_dir / "paper.txt"
    paper_struct_path = out_dir / "paper.struct.md"

    manifest = read_json(manifest_path)
    source_payload = read_json(source_path)

    dialogue_path = Path(dialogue).expanduser().resolve()
    if not dialogue_path.exists():
        raise FileNotFoundError(f"Dialogue markdown not found: {dialogue_path}")
    dialogue_text = dialogue_path.read_text(encoding="utf-8")
    turns = parse_role_marked_dialogue(dialogue_text)
    title_info = extract_candidate_title_from_dialogue(turns, dialogue_path=dialogue_path)
    title = str(manifest.get("title") or title_info.get("title") or dialogue_path.stem)
    if not manifest.get("slug"):
        manifest["slug"] = slugify(title, prefix="paper-chat")
    manifest["title"] = title
    manifest["dialogue_path"] = str(dialogue_path)
    manifest["dialogue_turn_count"] = len(turns)

    atomic_write_text(dialogue_source_path, dialogue_text)
    atomic_write_text(dialogue_cleaned_path, render_cleaned_dialogue(turns))
    write_json(dialogue_normalized_path, {"turns": turns})

    section_map = build_dialogue_section_map(turns, title)
    write_json(dialogue_section_map_path, section_map)

    requested_source = source or source_payload.get("requested_source")
    paper_source = resolve_paper_source(
        explicit_source=requested_source,
        turns=turns,
        dialogue_path=dialogue_path,
        preferred_title=title,
    )
    source_payload = {
        **source_payload,
        "dialogue_path": str(dialogue_path),
        "requested_source": requested_source,
        "candidate_title": title,
        "title_candidates": title_info.get("candidates", []),
        "paper_source": paper_source,
    }
    write_json(source_path, source_payload)

    paper_bundle: dict[str, Any] | None = None
    exit_code = 0
    if paper_source is None:
        manifest["status"] = "paper_unresolved"
        manifest["paper_resolved"] = False
        manifest["extracted"] = False
        manifest["warnings"] = ["original paper source could not be resolved"]
        equation_cards = derive_equation_cards(section_map, None)
        write_json(equation_cards_path, equation_cards)
        teaching_map = build_teaching_map_markdown(
            title=title,
            dialogue_path=dialogue_path,
            paper_source=None,
            section_map=section_map,
            equation_cards=equation_cards,
            paper_bundle=None,
        )
        atomic_write_text(teaching_map_path, teaching_map)
        write_json(manifest_path, manifest)
        build_context(out_dir)
        payload = {
            "status": manifest["status"],
            "analysis_dir": str(out_dir),
            "manifest_path": str(manifest_path),
            "source_path": str(source_path),
            "dialogue_section_map_path": str(dialogue_section_map_path),
            "teaching_map_path": str(teaching_map_path),
            "equation_cards_path": str(equation_cards_path),
            "report_context_path": str(out_dir / "report-context.md"),
            "error": "original paper source could not be resolved",
        }
        return payload, 2

    pdf_path = resolve_pdf_path(out_dir, paper_source)
    paper_bundle = collect_pdf_bundle(pdf_path)
    paper_source["pdf_path"] = str(pdf_path)
    source_payload["paper_source"] = paper_source
    write_json(source_path, source_payload)

    chosen_title = choose_best_title(
        paper_source,
        paper_bundle["pdfinfo"],
        paper_bundle["fitz"],
        paper_bundle["docling"],
        fallback_title=title,
    )
    manifest["title"] = chosen_title
    source_payload["candidate_title"] = chosen_title
    write_json(source_path, source_payload)

    atomic_write_text(paper_text_path, paper_bundle["preferred_text"])
    if paper_bundle["docling"].get("used") and paper_bundle["docling"].get("markdown"):
        atomic_write_text(paper_struct_path, str(paper_bundle["docling"]["markdown"]))
    elif paper_struct_path.exists():
        paper_struct_path.unlink()

    equation_cards = derive_equation_cards(section_map, paper_bundle)
    write_json(equation_cards_path, equation_cards)
    teaching_map = build_teaching_map_markdown(
        title=chosen_title,
        dialogue_path=dialogue_path,
        paper_source=paper_source,
        section_map=section_map,
        equation_cards=equation_cards,
        paper_bundle=paper_bundle,
    )
    atomic_write_text(teaching_map_path, teaching_map)

    manifest["paper_resolved"] = True
    manifest["paper_text_path"] = str(paper_text_path)
    manifest["paper_struct_path"] = str(paper_struct_path)
    manifest["paper_pdf_path"] = str(pdf_path)
    manifest["preferred_text_source"] = paper_bundle["preferred_text_source"]
    manifest["structured_text_source"] = paper_bundle["structured_text_source"]
    manifest["readability"] = paper_bundle["readability"]
    manifest["sections"] = paper_bundle["sections"]
    manifest["equation_anchors"] = paper_bundle["equation_anchors"]
    manifest["figure_anchors"] = paper_bundle["figure_anchors"]
    manifest["table_anchors"] = paper_bundle["table_anchors"]
    manifest["loss_terms"] = paper_bundle["loss_terms"]
    manifest["parser_provenance"] = {
        "pdfinfo": paper_bundle["pdfinfo"],
        "pdftotext": paper_bundle["pdftotext"],
        "fitz": paper_bundle["fitz"],
        "docling": paper_bundle["docling"],
    }
    manifest["warnings"] = paper_bundle["warnings"]
    manifest["extracted"] = bool(paper_bundle["readability"].get("sufficient"))
    manifest["status"] = "extracted" if manifest["extracted"] else "extraction_failed"
    write_json(manifest_path, manifest)
    build_context(out_dir)

    payload = {
        "status": manifest["status"],
        "analysis_dir": str(out_dir),
        "manifest_path": str(manifest_path),
        "source_path": str(source_path),
        "dialogue_normalized_path": str(dialogue_normalized_path),
        "dialogue_cleaned_path": str(dialogue_cleaned_path),
        "dialogue_section_map_path": str(dialogue_section_map_path),
        "teaching_map_path": str(teaching_map_path),
        "equation_cards_path": str(equation_cards_path),
        "paper_text_path": str(paper_text_path),
        "paper_struct_path": str(paper_struct_path),
        "report_context_path": str(out_dir / "report-context.md"),
    }
    if not manifest["extracted"]:
        payload["error"] = "paper text quality is insufficient for a stable report"
        exit_code = 2
    return payload, exit_code


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract dialogue and paper artifacts for paper-chat-report.")
    parser.add_argument("--dialogue", required=True, help="Path to a role-labeled markdown export")
    parser.add_argument("--out-dir", required=True, help="Analysis output directory")
    parser.add_argument("--source", help="Optional original paper source")
    parser.add_argument("--json", action="store_true", help="Print JSON payload")
    args = parser.parse_args(argv)

    payload, exit_code = extract_bundle(dialogue=args.dialogue, out_dir=Path(args.out_dir), source=args.source)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for key, value in payload.items():
            print(f"{key}: {value}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
