#!/usr/bin/env python3
"""
Enhanced report formatter for paper-chat-report.

Converts ASCII formulas to LaTeX and generates platform-specific output
optimized for Yuque, Notion, Obsidian, etc.

Usage:
    python3 enhance_report_format.py \
        --input docs/papers/example.md \
        --output docs/papers/example-enhanced.md \
        --platform yuque
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence


PlatformType = Literal["standard", "yuque", "notion", "obsidian"]


@dataclass
class FormulaPattern:
    name: str
    pattern: re.Pattern[str]
    replacement: str
    description: str


# ASCII to LaTeX conversion patterns
FORMULA_PATTERNS: list[FormulaPattern] = [
    # Pattern: L_{xxx} -> \mathcal{L}_{\text{xxx}}
    FormulaPattern(
        name="loss_function",
        pattern=re.compile(r"\bL_\{([^}]+)\}"),
        replacement=r"\\mathcal{L}_{\\text{\1}}",
        description="Loss functions like L_{pretrain}",
    ),
    # Pattern: λ_x -> \lambda_x
    FormulaPattern(
        name="lambda",
        pattern=re.compile(r"λ_?(\w*)"),
        replacement=r"\\lambda_\1",
        description="Lambda coefficients",
    ),
    # Pattern: θ -> \theta
    FormulaPattern(
        name="theta",
        pattern=re.compile(r"[θϴ]"),
        replacement=r"\\theta",
        description="Theta parameter",
    ),
    # Pattern: ẑ/Ẑ -> \hat{z}/\hat{Z}
    FormulaPattern(
        name="z_hat",
        pattern=re.compile(r"ẑ"),
        replacement=r"\\hat{z}",
        description="Z with hat",
    ),
    FormulaPattern(
        name="Z_hat",
        pattern=re.compile(r"Ẑ"),
        replacement=r"\\hat{Z}",
        description="Z uppercase with hat",
    ),
    # Pattern: Σ -> \sum
    FormulaPattern(
        name="summation",
        pattern=re.compile(r"Σ"),
        replacement=r"\\sum",
        description="Summation symbol",
    ),
    # Pattern: ||...||_2 -> \|...\|_2
    FormulaPattern(
        name="l2_norm",
        pattern=re.compile(r"\|\|([^|]+)\|\|_2"),
        replacement=r"\\|\1\\|_2",
        description="L2 norm notation",
    ),
    # Pattern: sg(...) -> \text{sg}(...)
    FormulaPattern(
        name="stop_gradient",
        pattern=re.compile(r"\bsg\(([^)]+)\)"),
        replacement=r"\\text{sg}(\1)",
        description="Stop gradient operator",
    ),
    # Pattern: E_θ -> E_\theta
    FormulaPattern(
        name="E_theta",
        pattern=re.compile(r"\bE_([θϴ])"),
        replacement=r"E_\\theta",
        description="E with theta subscript",
    ),
    # Pattern: C_θ -> C_\theta
    FormulaPattern(
        name="C_theta",
        pattern=re.compile(r"\bC_([θϴ])"),
        replacement=r"C_\\theta",
        description="C with theta subscript",
    ),
    # Pattern: f_θ -> f_\theta
    FormulaPattern(
        name="f_theta",
        pattern=re.compile(r"\bf_([θϴ])"),
        replacement=r"f_\\theta",
        description="f with theta subscript",
    ),
    # Pattern: R_θ -> R_\theta
    FormulaPattern(
        name="R_theta",
        pattern=re.compile(r"\bR_([θϴ])"),
        replacement=r"R_\\theta",
        description="R with theta subscript",
    ),
    # Pattern: V_θ -> V_\theta
    FormulaPattern(
        name="V_theta",
        pattern=re.compile(r"\bV_([θϴ])"),
        replacement=r"V_\\theta",
        description="V with theta subscript",
    ),
    # Pattern: π_θ -> \pi_\theta
    FormulaPattern(
        name="pi_theta",
        pattern=re.compile(r"\bπ_([θϴ])"),
        replacement=r"\\pi_\\theta",
        description="Pi with theta subscript",
    ),
    # Pattern: π -> \pi (standalone)
    FormulaPattern(
        name="pi_standalone",
        pattern=re.compile(r"(?<![a-zA-Z])π(?![a-zA-Z])"),
        replacement=r"\\pi",
        description="Standalone pi",
    ),
]


def looks_like_formula_line(line: str) -> bool:
    """Check if a line looks like it contains a mathematical formula."""
    indicators = [
        r"[_\^]\{[^}]+\}",  # Subscripts/superscripts
        r"[θϴλΣπẑẐ]",        # Greek letters
        r"\|[^|]+\|",        # Norm bars
        r"[=＝]",             # Equal signs with special chars
        r"\\(?:sum|prod|int|frac)",  # LaTeX commands
        r"\b(?:E_|C_|f_|R_|V_|π_)[θϴ]",  # Common ML notation
        r"\b(?:sg|argmax|argmin)\(",    # ML functions
    ]
    combined = re.compile("|".join(f"({p})" for p in indicators))
    return bool(combined.search(line))


def is_in_code_block(lines: list[str], index: int) -> bool:
    """Check if a line is inside a code block."""
    fence_count = 0
    for i in range(index):
        stripped = lines[i].strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            fence_count += 1
    return fence_count % 2 == 1


def convert_ascii_to_latex(text: str) -> str:
    """Convert ASCII formula notation to LaTeX."""
    result = text
    for fp in FORMULA_PATTERNS:
        result = fp.pattern.sub(fp.replacement, result)
    return result


def wrap_inline_math(text: str) -> str:
    """Wrap text in inline math delimiters if it looks like math."""
    stripped = text.strip()
    if not stripped:
        return text
    # Already wrapped
    if stripped.startswith(("$", "\\(")) and stripped.endswith(("$", "\\)")):
        return text
    # Check if it contains math symbols
    if re.search(r"[\\{}^_]|\b(?:sum|int|frac|mathcal|lambda|theta|pi)\b", stripped):
        return f"${stripped}$"
    return text


def is_ascii_box_line(line: str) -> bool:
    """Check if line is part of an ASCII box (like ┌─┐│)."""
    return bool(re.search(r"[│┌┐└┘├┤┬┴┼─═║╔╗╚╝╠╣╦╩╬]", line))


def extract_content_from_ascii_box(lines: list[str]) -> list[str]:
    """Extract actual content from ASCII box lines."""
    content_lines = []
    for line in lines:
        # Remove box drawing characters and leading/trailing spaces
        content = re.sub(r"^[│┌┐└┘├┤┬┴┼─═║╔╗╚╝╠╣╦╩╬\s]+", "", line)
        content = re.sub(r"[│┌┐└┘├┤┬┴┼─═║╔╗╚╝╠╣╦╩╬\s]+$", "", content)
        if content.strip():
            content_lines.append(content)
    return content_lines


def process_formulas_in_text(text: str, platform: PlatformType) -> str:
    """Process and convert formulas in text content."""
    lines = text.split("\n")
    result_lines: list[str] = []

    in_code_block = False
    code_block_lang = ""
    in_ascii_block = False
    in_ascii_box = False
    ascii_buffer: list[str] = []
    ascii_box_buffer: list[str] = []

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Toggle code block state
        if stripped.startswith("```") or stripped.startswith("~~~"):
            # Check if this is a formula block (no language or "text" language)
            if not in_code_block:
                lang_match = re.match(r"^```+\s*(\w*)", stripped)
                code_block_lang = lang_match.group(1).lower() if lang_match else ""
                # If it looks like a formula block (no lang or text), process content
                if code_block_lang in ("", "text"):
                    # Check if next lines look like formulas
                    next_lines = lines[i+1:i+4] if i+1 < len(lines) else []
                    if any(looks_like_formula_line(l) for l in next_lines):
                        in_code_block = True
                        result_lines.append(line)
                        continue
            else:
                in_code_block = False
                code_block_lang = ""
            result_lines.append(line)
            continue

        # Skip real code blocks (with language)
        if in_code_block and code_block_lang not in ("", "text"):
            result_lines.append(line)
            continue

        # Detect ASCII box blocks (like the world model definition boxes)
        if is_ascii_box_line(line):
            if not in_ascii_box:
                in_ascii_box = True
                ascii_box_buffer = []
            ascii_box_buffer.append(line)
            continue
        else:
            if in_ascii_box:
                # Process the ASCII box - extract content and convert
                content_lines = extract_content_from_ascii_box(ascii_box_buffer)
                if content_lines:
                    # Convert to proper LaTeX equations
                    converted = convert_ascii_box_to_latex(content_lines)
                    result_lines.extend(converted)
                else:
                    result_lines.extend(ascii_box_buffer)
                in_ascii_box = False
                ascii_box_buffer = []

        # Detect plain ASCII formula blocks
        if looks_like_formula_line(line) and not stripped.startswith(("|", "#", "-", "*", ">", "`")):
            if not in_ascii_block:
                in_ascii_block = True
                ascii_buffer = []
            ascii_buffer.append(line)
            continue
        else:
            if in_ascii_block:
                # Process the accumulated ASCII formulas
                processed = process_ascii_formula_block(ascii_buffer, platform)
                result_lines.extend(processed)
                in_ascii_block = False
                ascii_buffer = []
            result_lines.append(line)

    # Handle remaining buffers
    if in_ascii_box:
        content_lines = extract_content_from_ascii_box(ascii_box_buffer)
        if content_lines:
            converted = convert_ascii_box_to_latex(content_lines)
            result_lines.extend(converted)
        else:
            result_lines.extend(ascii_box_buffer)

    if in_ascii_block:
        processed = process_ascii_formula_block(ascii_buffer, platform)
        result_lines.extend(processed)

    return "\n".join(result_lines)


def convert_ascii_box_to_latex(content_lines: list[str]) -> list[str]:
    """Convert extracted ASCII box content to LaTeX equations."""
    result: list[str] = []

    # Filter out decorative lines
    formula_lines = [l for l in content_lines if looks_like_formula_line(l)]

    if not formula_lines:
        return result

    # Convert each line to LaTeX
    result.append("$$")
    result.append("\\begin{aligned}")

    for line in formula_lines:
        # Extract label (if any) and formula
        # Pattern: "Label: formula" or just "formula"
        match = re.match(r"^(\w[\w\s]+):\s*(.+)$", line.strip())
        if match:
            label = match.group(1).strip()
            formula = match.group(2).strip()
            converted = convert_ascii_to_latex(formula)
            result.append(f"    \\text{{{label}}}: \\quad {converted} \\\\")
        else:
            converted = convert_ascii_to_latex(line.strip())
            result.append(f"    {converted} \\\\")

    result.append("\\end{aligned}")
    result.append("$$")

    return result


def process_ascii_formula_block(lines: list[str], platform: PlatformType) -> list[str]:
    """Convert an ASCII formula block to proper LaTeX."""
    result: list[str] = []

    # Join lines and process
    text = "\n".join(lines)

    # Check if it's a single formula or multiple
    if len(lines) == 1:
        # Single line formula
        converted = convert_ascii_to_latex(text.strip())
        # If it's complex, use display math
        if len(converted) > 30 or "=" in converted:
            result.append(f"$${converted}$$")
        else:
            result.append(f"${converted}$")
    else:
        # Multi-line formula block
        converted_lines = [convert_ascii_to_latex(line.strip()) for line in lines if line.strip()]

        # Check if they look like aligned equations
        if any("=" in line for line in converted_lines):
            result.append("$$")
            result.append("\\begin{aligned}")
            for cl in converted_lines:
                result.append(f"    {cl} \\\\")
            result.append("\\end{aligned}")
            result.append("$$")
        else:
            result.append("$$")
            result.extend(converted_lines)
            result.append("$$")

    return result


def create_comparison_block(left: str, right: str, platform: PlatformType) -> str:
    """Create a two-column comparison block."""
    if platform == "yuque":
        return f""":::row{{gutter="16"}}
:::col{{span="12"}}
{left}
:::
:::col{{span="12"}}
{right}
:::
:::
"""
    elif platform == "notion":
        # Notion doesn't have native column markdown, use table
        return f"""| {left.strip().split(chr(10))[0]} | {right.strip().split(chr(10))[0]} |
| --- | --- |
| {left.replace(chr(10), "<br>")} | {right.replace(chr(10), "<br>")} |
"""
    else:
        # Standard: HTML table
        return f"""<table>
<tr>
<td width="50%" valign="top">

{left}

</td>
<td width="50%" valign="top">

{right}

</td>
</tr>
</table>
"""


def create_collapsible_block(title: str, content: str, platform: PlatformType) -> str:
    """Create a collapsible block."""
    if platform == "yuque":
        return f""":::toggle{{title="{title}"}}
{content}
:::
"""
    else:
        # Standard HTML details (works in Notion too)
        return f"""<details>
<summary>{title}</summary>

{content}

</details>
"""


def highlight_text(text: str, color: str, platform: PlatformType) -> str:
    """Add color highlight to text."""
    color_map = {
        "blue": "#1677ff",
        "green": "#52c41a",
        "red": "#ff4d4f",
        "orange": "#fa8c16",
        "purple": "#722ed1",
    }
    hex_color = color_map.get(color, color)

    if platform == "yuque":
        return f'<span style="color:{hex_color}">**{text}**</span>'
    elif platform == "notion":
        # Notion limited support, use bold
        return f"**{text}**"
    else:
        return f"**{text}**"


def enhance_section_headers(text: str, platform: PlatformType) -> str:
    """Enhance section headers with collapsible wrappers for long sections."""
    # Pattern: ## N. Title (section headers)
    section_pattern = re.compile(r"^(## \d+\. .+)$", re.MULTILINE)

    def wrap_section(match: re.Match[str]) -> str:
        header = match.group(1)
        # For long sections, we could add collapsible hints
        # For now, just return as-is
        return header

    return section_pattern.sub(wrap_section, text)


def post_process_tables(text: str, platform: PlatformType) -> str:
    """Post-process tables for better platform compatibility."""
    # Convert certain comparison tables to multi-column layouts
    # Pattern: tables with exactly 2 rows (header + 1 data) and 2 columns

    if platform in ("yuque", "notion"):
        # These platforms handle markdown tables well
        return text

    return text


# Semantic image marker pattern: [[FIG:n|description]] or [[TAB:n|description]]
SEMANTIC_MARKER_RE = re.compile(
    r"\[\[(FIG|TAB):(\d+)\|([^\]]+)\]\]",
    re.IGNORECASE
)


def convert_semantic_markers(text: str, platform: PlatformType) -> str:
    """Convert semantic image markers to platform-specific format.

    Syntax: [[FIG:n|description]] or [[TAB:n|description]]

    Platform outputs:
    - yuque: <span style="color:#ff6b6b">[插入图n：description]</span>
    - notion: Callout block (or HTML span)
    - standard: 🔴 **[插入图n：description]**
    """
    def replace_marker(match: re.Match[str]) -> str:
        marker_type = match.group(1).upper()  # FIG or TAB
        number = match.group(2)
        description = match.group(3).strip()

        type_name = "图" if marker_type == "FIG" else "表"

        if platform == "yuque":
            # Yuque supports HTML span with color
            return f'<span style="color:#ff6b6b">**[插入{type_name}{number}：{description}]**</span>'
        elif platform == "notion":
            # Notion supports HTML in markdown import
            return f'<span style="color:#ff6b6b">**[插入{type_name}{number}：{description}]**</span>'
        elif platform == "obsidian":
            # Obsidian callout format
            return f"> [!important] 插入{type_name}{number}\n> {description}"
        else:
            # Standard markdown with emoji
            return f"🔴 **[插入{type_name}{number}：{description}]**"

    return SEMANTIC_MARKER_RE.sub(replace_marker, text)


def enhance_report(
    input_path: Path,
    output_path: Path,
    platform: PlatformType,
) -> dict[str, object]:
    """Main entry point: enhance a report for a specific platform."""
    content = input_path.read_text(encoding="utf-8")

    # Step 1: Convert ASCII formulas to LaTeX
    content = process_formulas_in_text(content, platform)

    # Step 2: Enhance section headers
    content = enhance_section_headers(content, platform)

    # Step 3: Post-process tables
    content = post_process_tables(content, platform)

    # Step 4: Convert semantic image markers
    content = convert_semantic_markers(content, platform)

    # Step 4: Add platform-specific header
    header = f"""<!--
Platform: {platform}
Enhanced by paper-chat-report
Original: {input_path.name}
-->

"""
    content = header + content

    # Write output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")

    return {
        "input": str(input_path),
        "output": str(output_path),
        "platform": platform,
        "chars_processed": len(content),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Enhance paper report with platform-specific formatting"
    )
    parser.add_argument(
        "--input", "-i",
        required=True,
        help="Input markdown report path",
    )
    parser.add_argument(
        "--output", "-o",
        required=True,
        help="Output enhanced report path",
    )
    parser.add_argument(
        "--platform", "-p",
        choices=["standard", "yuque", "notion", "obsidian"],
        default="standard",
        help="Target platform (default: standard)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON result",
    )
    args = parser.parse_args(argv)

    payload = enhance_report(
        input_path=Path(args.input).expanduser().resolve(),
        output_path=Path(args.output).expanduser().resolve(),
        platform=args.platform,  # type: ignore
    )

    if args.json:
        import json
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for key, value in payload.items():
            print(f"{key}: {value}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
