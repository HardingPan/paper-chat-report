#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from paper_chat_report_common import (
    maybe_write,
    parse_role_marked_dialogue,
    read_pdfinfo,
    resolve_source,
    write_json,
    extract_candidate_title_from_dialogue,
    extract_text_with_fitz,
    choose_best_title,
    slugify,
)


def build_report_stub(title: str, source: str, dialogue_source: str) -> str:
    return f"""# {title}

> 三句话总结：
>
> 1. 论文在解决什么问题？
> 2. 核心方法到底是怎么工作的？
> 3. 最重要的实验或结果说明了什么？

## 0. 阅读入口

- Dialogue Source: {dialogue_source}
- Paper Source: {source}
- Keywords:
- Core Insight:

## 1. 基本信息

| 项目 | 内容 |
| --- | --- |
| Title | {title} |
| Dialogue Source | {dialogue_source} |
| Paper Source | {source} |
| Venue / Year |  |
| Project / Code |  |

### 符号说明（可选）

| 符号 | 含义 |
| --- | --- |
|  |  |

## 2. 研究问题与核心困难

### 2.1 问题背景

### 2.2 研究现状与局限

> 相关工作整合在这里，从“为什么现有方法还不够”来写，而不是单列一章。

### 2.3 核心研究问题

## 3. 核心贡献

## 4. 整体主线

> 先讲清楚整篇方法的主流程，不要按 transcript 顺序堆信息。

## 5. 方法总览与系统分解

| 模块 / Stage | 固定量 / 输入 | 优化变量 / 关键操作 | 输出 | 作用 |
| --- | --- | --- | --- | --- |
|  |  |  |  |  |

## 6. 方法详解

### 6.1 问题形式化 / 建模

### 6.2 关键模块设计

### 6.3 训练 / 学习过程

```latex
% 用原文核对后的关键公式放在这里，并直接解释每一项的职责
```

### 6.4 推理 / 部署过程

| 阶段 | 固定量 | 优化变量 / 推断对象 | 关键约束 / 关键操作 | 输出 |
| --- | --- | --- | --- | --- |
|  |  |  |  |  |

## 7. 图表与实验解读

### 7.1 关键图

[[FIG:1|在正文中说明这张图最值得看的信息]]

### 7.2 关键表

[[TAB:1|在正文中说明这张表最能支撑什么结论]]

### 7.3 实验设计与证据

## 8. 局限与边界

### 8.1 明确局限

### 8.2 适用边界

### 8.3 潜在改进方向

## 9. 结论

## 10. 参考链接
"""


def build_teaching_map_stub(title: str) -> str:
    return f"""# {title} - 教学地图

## Source

## Dialogue Inventory

## Paper Resolution

## Problem Framing

## Method Story

## Evidence Cards

## Equation Cards

## Report Drafting Focus
"""


def build_report_context_stub(title: str) -> str:
    return f"""# {title} - 成稿上下文

## Target Output

## Required Inputs

## Dialogue Signal Summary

## Non-Negotiables

## Problem Framing

## Method Story

## Evidence To Cite

## Primary Equations To Weave Into Method

## Final Writing Checklist
"""


def choose_initial_title(dialogue_path: Path, source: str | None) -> dict[str, Any]:
    dialogue_text = dialogue_path.read_text(encoding="utf-8")
    turns = parse_role_marked_dialogue(dialogue_text)
    title_info = extract_candidate_title_from_dialogue(turns, dialogue_path=dialogue_path)
    chosen_title = str(title_info.get("title", dialogue_path.stem))
    resolved_source: dict[str, Any] | None = None

    if source:
        resolved_source = resolve_source(source)
        if resolved_source["source_type"] == "local_pdf":
            pdfinfo_payload = read_pdfinfo(Path(resolved_source["pdf_path"]))
            fitz_payload = extract_text_with_fitz(Path(resolved_source["pdf_path"]))
            chosen_title = choose_best_title(
                resolved_source,
                pdfinfo_payload,
                fitz_payload,
                fallback_title=chosen_title,
            )

    return {
        "title": chosen_title,
        "title_candidates": title_info.get("candidates", []),
        "turns": turns,
        "resolved_source": resolved_source,
    }


def initialize_artifacts(root: Path, dialogue: str, source: str | None = None, force: bool = False) -> dict[str, Any]:
    if not root.exists():
        raise FileNotFoundError(f"Repository root not found: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Repository root is not a directory: {root}")

    dialogue_path = Path(dialogue).expanduser().resolve()
    if not dialogue_path.exists():
        raise FileNotFoundError(f"Dialogue markdown not found: {dialogue_path}")

    title_payload = choose_initial_title(dialogue_path, source)
    title = str(title_payload["title"])
    slug = slugify(title, prefix="paper-chat")
    turns = title_payload["turns"]
    resolved_source = title_payload["resolved_source"]

    papers_dir = root / "docs" / "papers"
    analysis_dir = root / ".tmp" / "analysis" / "paper-chat-report" / slug
    papers_dir.mkdir(parents=True, exist_ok=True)
    analysis_dir.mkdir(parents=True, exist_ok=True)

    report_path = papers_dir / f"{slug}.md"
    manifest_path = analysis_dir / "manifest.json"
    source_path = analysis_dir / "source.json"
    dialogue_source_path = analysis_dir / "dialogue-source.md"
    dialogue_normalized_path = analysis_dir / "dialogue-normalized.json"
    dialogue_cleaned_path = analysis_dir / "dialogue-cleaned.md"
    dialogue_section_map_path = analysis_dir / "dialogue-section-map.json"
    teaching_map_path = analysis_dir / "teaching-map.md"
    equation_cards_path = analysis_dir / "equation-cards.json"
    report_context_path = analysis_dir / "report-context.md"

    paper_source_display = ""
    if resolved_source:
        paper_source_display = str(resolved_source.get("display_source", resolved_source.get("original_source", "")))
    elif source:
        paper_source_display = source
    else:
        paper_source_display = "auto-resolve pending"

    report_written = maybe_write(
        report_path,
        build_report_stub(title, paper_source_display, str(dialogue_path)),
        force=force,
    )
    teaching_map_written = maybe_write(teaching_map_path, build_teaching_map_stub(title), force=force)
    report_context_written = maybe_write(report_context_path, build_report_context_stub(title), force=force)
    maybe_write(dialogue_source_path, dialogue_path.read_text(encoding="utf-8"), force=force)
    if force or not dialogue_normalized_path.exists():
        dialogue_normalized_path.write_text(json.dumps({"turns": turns}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if force or not dialogue_cleaned_path.exists():
        from paper_chat_report_common import render_cleaned_dialogue

        dialogue_cleaned_path.write_text(render_cleaned_dialogue(turns), encoding="utf-8")
    if force or not dialogue_section_map_path.exists():
        dialogue_section_map_path.write_text(json.dumps({"sections": []}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if force or not equation_cards_path.exists():
        equation_cards_path.write_text(json.dumps({"equation_cards": []}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    source_payload = {
        "dialogue_path": str(dialogue_path),
        "requested_source": source,
        "candidate_title": title,
        "title_candidates": title_payload.get("title_candidates", []),
        "paper_source": resolved_source,
        "report_path": str(report_path),
        "analysis_dir": str(analysis_dir),
    }
    manifest_payload = {
        "slug": slug,
        "title": title,
        "dialogue_path": str(dialogue_path),
        "report_path": str(report_path),
        "analysis_dir": str(analysis_dir),
        "dialogue_source_path": str(dialogue_source_path),
        "dialogue_normalized_path": str(dialogue_normalized_path),
        "dialogue_cleaned_path": str(dialogue_cleaned_path),
        "dialogue_section_map_path": str(dialogue_section_map_path),
        "teaching_map_path": str(teaching_map_path),
        "equation_cards_path": str(equation_cards_path),
        "report_context_path": str(report_context_path),
        "paper_text_path": str(analysis_dir / "paper.txt"),
        "paper_struct_path": str(analysis_dir / "paper.struct.md"),
        "paper_pdf_path": str(analysis_dir / "paper.pdf"),
        "source_json_path": str(source_path),
        "status": "initialized",
        "paper_resolved": bool(resolved_source),
        "extracted": False,
        "warnings": [],
        "parser_provenance": {},
        "sections": [],
        "dialogue_turn_count": len(turns),
    }

    if force or not source_path.exists():
        write_json(source_path, source_payload)
    if force or not manifest_path.exists():
        write_json(manifest_path, manifest_payload)

    return {
        "slug": slug,
        "title": title,
        "report_path": str(report_path),
        "analysis_dir": str(analysis_dir),
        "manifest_path": str(manifest_path),
        "source_path": str(source_path),
        "dialogue_source_path": str(dialogue_source_path),
        "dialogue_normalized_path": str(dialogue_normalized_path),
        "dialogue_cleaned_path": str(dialogue_cleaned_path),
        "dialogue_section_map_path": str(dialogue_section_map_path),
        "teaching_map_path": str(teaching_map_path),
        "equation_cards_path": str(equation_cards_path),
        "report_context_path": str(report_context_path),
        "report_written": report_written,
        "teaching_map_written": teaching_map_written,
        "report_context_written": report_context_written,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Initialize output artifacts for paper-chat-report.")
    parser.add_argument("--root", required=True, help="Repository root where docs/papers and .tmp live")
    parser.add_argument("--dialogue", required=True, help="Path to a role-labeled markdown export")
    parser.add_argument("--source", help="Optional original paper source (local PDF / arXiv / direct PDF URL)")
    parser.add_argument("--force", action="store_true", help="Overwrite existing stubs and metadata")
    parser.add_argument("--json", action="store_true", help="Print JSON payload")
    args = parser.parse_args(argv)

    payload = initialize_artifacts(
        root=Path(args.root).expanduser().resolve(),
        dialogue=args.dialogue,
        source=args.source,
        force=args.force,
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for key, value in payload.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
