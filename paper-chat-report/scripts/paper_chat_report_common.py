#!/usr/bin/env python3
from __future__ import annotations

import difflib
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Sequence

try:
    import fitz  # type: ignore[import-not-found]
    FITZ_IMPORT_ERROR: ImportError | None = None
except ImportError as exc:  # pragma: no cover
    fitz = None  # type: ignore[assignment]
    FITZ_IMPORT_ERROR = exc


ARXIV_ABS_RE = re.compile(r"^/abs/(?P<id>[^/?#]+)$")
ARXIV_PDF_RE = re.compile(r"^/pdf/(?P<id>[^/?#]+?)(?:\.pdf)?$")
MARKDOWN_HEADING_RE = re.compile(r"^(#{1,6})\s+(?P<title>.+?)\s*$")
TURN_MARKER_RE = re.compile(r"^(#{1,6})\s+(?P<label>.+?)\s*:\s*$")
EQUATION_NUMBER_RE = re.compile(r"^\((\d+)\)$")
ANY_EQUATION_NUMBER_RE = re.compile(r"\((\d+)\)")
FIGURE_CAPTION_RE = re.compile(r"^(Figure|Fig\.)\s*(\d+)\b[:.]?\s*(.*)$", re.IGNORECASE)
TABLE_CAPTION_RE = re.compile(r"^(Table|Tab\.)\s*(\d+)\b[:.]?\s*(.*)$", re.IGNORECASE)
LOSS_TERM_RE = re.compile(r"\bL[A-Za-z][A-Za-z0-9_]*\b")
INLINE_MATH_RE = re.compile(r"(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)")
LATEX_BLOCK_RE = re.compile(r"```(?:latex|tex)\s*(.*?)```", re.DOTALL | re.IGNORECASE)
DOCLING_COMPONENT_HINTS: dict[str, tuple[str, ...]] = {
    "layout": ("docling-layout-heron",),
    "docling_models": ("docling-models",),
    "code_formula": ("CodeFormulaV2",),
}
KNOWN_SECTION_PATTERNS = (
    re.compile(
        r"^(abstract|introduction|related work|background|method|methods|approach|pipeline|implementation|experiments|results|discussion|limitations|conclusion|conclusions|references)$",
        re.IGNORECASE,
    ),
    re.compile(r"^\d+(?:\.\d+)*\.?\s+[A-Z][A-Za-z0-9/-]*(?:[\s:][A-Za-z][A-Za-z0-9,()/:+\-]*){0,14}$"),
    re.compile(r"^[IVXLC]+\.\s+[A-Z][A-Za-z0-9/-]*(?:[\s:][A-Za-z][A-Za-z0-9,()/:+\-]*){0,14}$"),
)
GENERIC_TITLE_PATTERNS = (
    re.compile(r"^(论文精读笔记|文献精读|paper notes|reading notes)$", re.IGNORECASE),
    re.compile(r"^(abstract|introduction|related work|method|methods|experiments|results|conclusion)$", re.IGNORECASE),
    re.compile(r"^(摘要|引言|相关工作|方法|实验|结论|核心贡献|研究问题).*$"),
    re.compile(r"^第?\d+部分.*$"),
)


def normalize_space(value: str) -> str:
    return " ".join(value.split()).strip()


def trim_text(value: str, limit: int = 320) -> str:
    compact = normalize_space(value)
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def slugify(value: str, prefix: str = "paper") -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_only.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if slug:
        return slug
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]
    return f"{prefix}-{digest}"


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def atomic_write_text(path: Path, content: str) -> None:
    ensure_parent(path)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=str(path.parent)) as handle:
        handle.write(content)
        temp_path = Path(handle.name)
    temp_path.replace(path)


def maybe_write(path: Path, content: str, force: bool) -> bool:
    if path.exists() and not force:
        return False
    ensure_parent(path)
    path.write_text(content, encoding="utf-8")
    return True


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return raw if isinstance(raw, dict) else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def run_command(command: Sequence[str]) -> dict[str, Any]:
    try:
        proc = subprocess.run(command, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return {"available": False, "returncode": None, "stdout": "", "stderr": "command not found"}
    return {
        "available": True,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def sanitize_extracted_text(raw_text: str) -> str:
    return raw_text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")


def normalize_pdf_text(raw_text: str) -> str:
    text = sanitize_extracted_text(raw_text)
    if "\f" not in text:
        return text.strip() + "\n"
    pages = [page.strip() for page in text.split("\f")]
    chunks: list[str] = []
    for index, page in enumerate(pages, start=1):
        if page:
            chunks.append(f"=== Page {index} ===\n{page}")
    return "\n\n".join(chunks).strip() + "\n"


def resolve_source(source: str) -> dict[str, Any]:
    raw = source.strip()
    if not raw:
        raise ValueError("Paper source is required.")

    candidate = Path(raw).expanduser()
    if candidate.exists():
        resolved = candidate.resolve()
        if resolved.suffix.lower() != ".pdf":
            raise ValueError(f"Only PDF files are supported for local paths: {resolved}")
        return {
            "source_type": "local_pdf",
            "original_source": raw,
            "pdf_path": str(resolved),
            "display_source": str(resolved),
        }

    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"Unsupported source: {source}")

    abs_match = ARXIV_ABS_RE.match(parsed.path)
    if parsed.netloc in {"arxiv.org", "www.arxiv.org"} and abs_match:
        arxiv_id = abs_match.group("id")
        return {
            "source_type": "arxiv_abs_url",
            "original_source": raw,
            "arxiv_id": arxiv_id,
            "abs_url": f"https://arxiv.org/abs/{arxiv_id}",
            "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}.pdf",
            "display_source": f"arXiv:{arxiv_id}",
        }

    pdf_match = ARXIV_PDF_RE.match(parsed.path)
    if parsed.netloc in {"arxiv.org", "www.arxiv.org"} and pdf_match:
        arxiv_id = pdf_match.group("id")
        return {
            "source_type": "arxiv_pdf_url",
            "original_source": raw,
            "arxiv_id": arxiv_id,
            "abs_url": f"https://arxiv.org/abs/{arxiv_id}",
            "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}.pdf",
            "display_source": f"arXiv:{arxiv_id}",
        }

    if parsed.path.lower().endswith(".pdf"):
        return {
            "source_type": "remote_pdf_url",
            "original_source": raw,
            "pdf_url": raw,
            "display_source": raw,
        }

    raise ValueError(f"Unsupported paper source: {source}")


def download_file(url: str, destination: Path) -> Path:
    ensure_parent(destination)
    request = urllib.request.Request(url, headers={"User-Agent": "paper-chat-report-skill/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response, destination.open("wb") as handle:
        shutil.copyfileobj(response, handle)
    return destination


def read_pdfinfo(pdf_path: Path) -> dict[str, Any]:
    result = run_command(["pdfinfo", str(pdf_path)])
    payload: dict[str, Any] = {
        "available": result["available"],
        "used": False,
        "title": "",
        "author": "",
        "pages": None,
        "raw": "",
        "error": "",
    }
    if not result["available"]:
        payload["error"] = "pdfinfo not available"
        return payload
    if result["returncode"] != 0:
        payload["error"] = result["stderr"].strip() or "pdfinfo failed"
        return payload
    payload["used"] = True
    payload["raw"] = result["stdout"]
    for line in result["stdout"].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key == "title":
            payload["title"] = value
        elif key == "author":
            payload["author"] = value
        elif key == "pages":
            try:
                payload["pages"] = int(value)
            except ValueError:
                payload["pages"] = None
    return payload


def extract_text_with_pdftotext(pdf_path: Path) -> dict[str, Any]:
    result = run_command(["pdftotext", "-layout", "-enc", "UTF-8", str(pdf_path), "-"])
    payload: dict[str, Any] = {
        "available": result["available"],
        "used": False,
        "text": "",
        "error": "",
    }
    if not result["available"]:
        payload["error"] = "pdftotext not available"
        return payload
    if result["returncode"] != 0:
        payload["error"] = result["stderr"].strip() or "pdftotext failed"
        return payload
    payload["used"] = True
    payload["text"] = normalize_pdf_text(result["stdout"])
    return payload


def extract_text_with_fitz(pdf_path: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "available": fitz is not None,
        "used": False,
        "text": "",
        "page_count": 0,
        "metadata": {
            "title": "",
            "author": "",
            "subject": "",
            "keywords": "",
        },
        "version": "",
        "error": "",
    }
    if fitz is None:
        detail = str(FITZ_IMPORT_ERROR) if FITZ_IMPORT_ERROR else "PyMuPDF import failed"
        payload["error"] = f"PyMuPDF not installed: {detail}"
        return payload

    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:  # pragma: no cover
        payload["error"] = f"{type(exc).__name__}: {exc}"
        return payload

    try:
        pages: list[str] = []
        for page_number, page in enumerate(doc, start=1):
            text = sanitize_extracted_text(page.get_text("text")).strip()
            if text:
                pages.append(f"=== Page {page_number} ===\n{text}")
        metadata = doc.metadata or {}
        payload.update(
            {
                "used": True,
                "text": ("\n\n".join(pages).strip() + "\n") if pages else "",
                "page_count": doc.page_count,
                "metadata": {
                    "title": str(metadata.get("title", "")).strip(),
                    "author": str(metadata.get("author", "")).strip(),
                    "subject": str(metadata.get("subject", "")).strip(),
                    "keywords": str(metadata.get("keywords", "")).strip(),
                },
                "version": str(fitz.version[0]),
            }
        )
        return payload
    except Exception as exc:  # pragma: no cover
        payload["error"] = f"{type(exc).__name__}: {exc}"
        return payload
    finally:
        doc.close()


def candidate_docling_artifacts_paths(explicit: str | Path | None = None) -> list[Path]:
    candidates: list[Path] = []
    raw_candidates: list[str | Path | None] = [
        explicit,
        os.environ.get("PAPER_CHAT_REPORT_DOCLING_ARTIFACTS"),
        Path.home() / ".cache" / "docling" / "models",
    ]
    for raw in raw_candidates:
        if not raw:
            continue
        candidate = Path(raw).expanduser()
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates


def resolve_docling_artifacts_path(explicit: str | Path | None = None, must_exist: bool = True) -> Path | None:
    for candidate in candidate_docling_artifacts_paths(explicit=explicit):
        if not must_exist or candidate.exists():
            return candidate
    return None


def inspect_docling_runtime(artifacts_path: str | Path | None = None) -> dict[str, Any]:
    configured_path = resolve_docling_artifacts_path(explicit=artifacts_path, must_exist=False)
    resolved_path = resolve_docling_artifacts_path(explicit=artifacts_path, must_exist=True)
    disabled = env_flag("PAPER_CHAT_REPORT_DISABLE_DOCLING")
    try:
        version = importlib.metadata.version("docling")
        installed = True
    except importlib.metadata.PackageNotFoundError:
        version = ""
        installed = False

    available_components: list[str] = []
    missing_components: list[str] = []
    artifacts_exists = resolved_path is not None and resolved_path.exists()
    if artifacts_exists and resolved_path is not None:
        lowered_names = {child.name.lower() for child in resolved_path.iterdir()}
        for component, hints in DOCLING_COMPONENT_HINTS.items():
            if any(hint.lower() in name for hint in hints for name in lowered_names):
                available_components.append(component)
            else:
                missing_components.append(component)
    else:
        missing_components = list(DOCLING_COMPONENT_HINTS.keys())

    notes: list[str] = []
    if disabled:
        notes.append("docling disabled by PAPER_CHAT_REPORT_DISABLE_DOCLING")
    if installed and not artifacts_exists:
        notes.append("local docling artifacts path not found; conversion may still work if docling manages its own cache")
    if installed and artifacts_exists and missing_components:
        notes.append("some local docling artifact groups are missing; formula enrichment may degrade")

    return {
        "disabled": disabled,
        "installed": installed,
        "version": version,
        "artifacts_path": str(configured_path) if configured_path else None,
        "artifacts_exists": artifacts_exists,
        "models_ready": installed and artifacts_exists and not missing_components,
        "available_components": available_components,
        "missing_components": missing_components,
        "notes": notes,
    }


def try_docling_markdown(pdf_path: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "available": False,
        "used": False,
        "markdown": "",
        "title": "",
        "error": "",
        "runtime": inspect_docling_runtime(),
    }
    runtime = payload["runtime"]
    if runtime["disabled"]:
        payload["error"] = "docling disabled by PAPER_CHAT_REPORT_DISABLE_DOCLING"
        return payload
    try:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption
    except ImportError:
        payload["error"] = "docling not installed"
        return payload

    payload["available"] = True
    try:
        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_formula_enrichment = True
        pipeline_options.do_code_enrichment = False
        pipeline_options.do_picture_classification = False
        pipeline_options.do_picture_description = False
        if runtime["artifacts_exists"] and runtime["artifacts_path"]:
            pipeline_options.artifacts_path = runtime["artifacts_path"]
        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
            }
        )
        result = converter.convert(str(pdf_path))
        document = result.document
        payload["used"] = True
        payload["markdown"] = document.export_to_markdown().strip() + "\n"
        payload["title"] = str(getattr(document, "name", "") or "").strip()
        return payload
    except Exception as exc:  # pragma: no cover
        payload["error"] = f"{type(exc).__name__}: {exc}"
        return payload


def compute_text_quality(text: str) -> dict[str, Any]:
    non_whitespace = len(re.sub(r"\s+", "", text))
    word_count = len(re.findall(r"\b\w+\b", text))
    line_count = sum(1 for line in text.splitlines() if line.strip())
    sufficient = non_whitespace >= 500 and word_count >= 80 and line_count >= 20
    return {
        "non_whitespace_chars": non_whitespace,
        "word_count": word_count,
        "line_count": line_count,
        "sufficient": sufficient,
    }


def extract_sections_from_markdown(text: str) -> list[str]:
    headings: list[str] = []
    seen: set[str] = set()
    for raw_line in text.splitlines():
        match = MARKDOWN_HEADING_RE.match(raw_line.strip())
        if not match:
            continue
        title = normalize_space(match.group("title"))
        lowered = title.lower()
        if title and lowered not in seen:
            seen.add(lowered)
            headings.append(title)
        if len(headings) >= 40:
            break
    return headings


def extract_sections(text: str) -> list[str]:
    markdown_headings = extract_sections_from_markdown(text)
    if markdown_headings:
        return markdown_headings[:30]
    headings: list[str] = []
    seen: set[str] = set()
    for raw_line in text.splitlines():
        line = normalize_space(raw_line)
        if len(line) < 3 or len(line) > 140:
            continue
        if line.endswith((".", ",")) or len(line.split()) > 12:
            continue
        if not any(pattern.match(line) for pattern in KNOWN_SECTION_PATTERNS):
            continue
        lowered = line.lower()
        if lowered not in seen:
            seen.add(lowered)
            headings.append(line)
        if len(headings) >= 30:
            break
    return headings


def build_context_snippet(lines: list[str], line_index: int, before: int = 4, after: int = 2) -> str:
    start = max(0, line_index - before)
    end = min(len(lines), line_index + after + 1)
    chunk = [line.strip() for line in lines[start:end] if line.strip()]
    return "\n".join(chunk[:12]).strip()


def nearest_section(lines: list[str], line_index: int) -> str:
    for idx in range(line_index, -1, -1):
        line = normalize_space(lines[idx])
        if line and any(pattern.match(line) for pattern in KNOWN_SECTION_PATTERNS):
            return line
    return ""


def looks_like_equation_line(line: str) -> bool:
    compact = normalize_space(line)
    if not compact:
        return False
    indicators = ("=", "Σ", "∑", "||", "∥", "\\sum", " min ", " max ", " arg")
    padded = f" {compact} "
    if any(token in compact for token in indicators[:5]):
        return True
    if any(token in padded for token in indicators[5:]):
        return True
    return bool(LOSS_TERM_RE.search(compact))


def has_recent_equation_line(lines: list[str], line_index: int, max_nonempty_lines: int = 4) -> bool:
    seen = 0
    for idx in range(line_index - 1, -1, -1):
        line = lines[idx].strip()
        if not line:
            continue
        seen += 1
        if looks_like_equation_line(line):
            return True
        if seen >= max_nonempty_lines:
            return False
    return False


def extract_equation_anchors(text: str) -> list[dict[str, Any]]:
    anchors: list[dict[str, Any]] = []
    seen: set[str] = set()
    lines = sanitize_extracted_text(text).splitlines()
    for idx, raw_line in enumerate(lines):
        line = raw_line.strip()
        eq_number = ""
        if match := EQUATION_NUMBER_RE.match(line):
            eq_number = match.group(1)
        else:
            for inline_match in ANY_EQUATION_NUMBER_RE.finditer(line):
                body = line[:inline_match.start()].strip()
                if body and looks_like_equation_line(body):
                    eq_number = inline_match.group(1)
                    break
                if not body and line.startswith(f"({inline_match.group(1)})") and has_recent_equation_line(lines, idx):
                    eq_number = inline_match.group(1)
                    break
        if eq_number and eq_number not in seen:
            seen.add(eq_number)
            anchors.append(
                {
                    "eq": eq_number,
                    "section": nearest_section(lines, idx),
                    "snippet": build_context_snippet(lines, idx, before=8, after=3),
                    "loss_terms": [],
                }
            )
    return anchors


def extract_caption_anchors(text: str, pattern: re.Pattern[str], key: str) -> list[dict[str, Any]]:
    anchors: list[dict[str, Any]] = []
    lines = sanitize_extracted_text(text).splitlines()
    for idx, raw_line in enumerate(lines):
        line = normalize_space(raw_line)
        match = pattern.match(line)
        if match:
            anchors.append(
                {
                    key: match.group(2),
                    "section": nearest_section(lines, idx),
                    "caption": match.group(3).strip() or line,
                    "snippet": build_context_snippet(lines, idx, before=0, after=2),
                }
            )
    return anchors


def extract_loss_terms(text: str) -> list[str]:
    terms: set[str] = set()
    for line in sanitize_extracted_text(text).splitlines():
        found = LOSS_TERM_RE.findall(line)
        if found and ("=" in line or (len(found) >= 2 and line.lstrip().startswith("L"))):
            terms.update(found)
    return sorted(term for term in terms if len(term) > 2)[:40]


def choose_best_title(
    source_info: dict[str, Any],
    pdfinfo_payload: dict[str, Any],
    fitz_payload: dict[str, Any],
    docling_payload: dict[str, Any] | None = None,
    fallback_title: str = "",
) -> str:
    def normalized_key(value: str) -> str:
        return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", value).lower())

    def filename_like(candidate: str) -> bool:
        if source_info["source_type"] != "local_pdf":
            return False
        stem = Path(source_info["pdf_path"]).stem
        return normalized_key(candidate) == normalized_key(stem)

    candidates = [
        fitz_payload.get("metadata", {}).get("title", ""),
        pdfinfo_payload.get("title", ""),
        (docling_payload or {}).get("title", ""),
        fallback_title,
    ]
    for candidate in candidates:
        title = str(candidate or "").strip()
        if title and title.lower() != "untitled" and not filename_like(title):
            return title
    if source_info["source_type"] == "local_pdf":
        return Path(source_info["pdf_path"]).stem
    return str(source_info.get("display_source", fallback_title or "Paper"))


def collect_pdf_bundle(pdf_path: Path, prefer_docling: bool = True) -> dict[str, Any]:
    pdfinfo_payload = read_pdfinfo(pdf_path)
    pdftotext_payload = extract_text_with_pdftotext(pdf_path)
    fitz_payload = extract_text_with_fitz(pdf_path)
    docling_payload = try_docling_markdown(pdf_path) if prefer_docling else {
        "available": False,
        "used": False,
        "markdown": "",
        "title": "",
        "error": "docling disabled",
        "runtime": inspect_docling_runtime(),
    }

    pdftotext_quality = compute_text_quality(pdftotext_payload.get("text", ""))
    fitz_quality = compute_text_quality(fitz_payload.get("text", ""))
    preferred_text = pdftotext_payload.get("text", "")
    preferred_source = "pdftotext"
    preferred_quality = pdftotext_quality
    if not preferred_text or fitz_quality["non_whitespace_chars"] > pdftotext_quality["non_whitespace_chars"]:
        preferred_text = fitz_payload.get("text", "")
        preferred_source = "fitz"
        preferred_quality = fitz_quality
    if not preferred_text and docling_payload.get("markdown"):
        preferred_text = str(docling_payload["markdown"])
        preferred_source = "docling"
        preferred_quality = compute_text_quality(preferred_text)

    warnings: list[str] = []
    if pdftotext_payload.get("error"):
        warnings.append(pdftotext_payload["error"])
    if pdfinfo_payload.get("error"):
        warnings.append(pdfinfo_payload["error"])
    if fitz_payload.get("error"):
        warnings.append(f"fitz: {fitz_payload['error']}")
    if docling_payload.get("error"):
        warnings.append(f"docling: {docling_payload['error']}")

    equation_anchors = extract_equation_anchors(preferred_text)
    figure_anchors = extract_caption_anchors(preferred_text, FIGURE_CAPTION_RE, "figure")
    table_anchors = extract_caption_anchors(preferred_text, TABLE_CAPTION_RE, "table")
    loss_terms = extract_loss_terms(preferred_text)
    for anchor in equation_anchors:
        anchor["loss_terms"] = [term for term in loss_terms if term in anchor["snippet"]]

    return {
        "pdfinfo": pdfinfo_payload,
        "pdftotext": pdftotext_payload,
        "fitz": fitz_payload,
        "docling": docling_payload,
        "preferred_text": preferred_text,
        "preferred_text_source": preferred_source,
        "structured_text_source": "docling" if docling_payload.get("used") else preferred_source,
        "readability": preferred_quality,
        "sections": extract_sections(docling_payload.get("markdown", "") or preferred_text),
        "equation_anchors": equation_anchors,
        "figure_anchors": figure_anchors,
        "table_anchors": table_anchors,
        "loss_terms": loss_terms,
        "warnings": warnings,
    }


def classify_speaker_label(label: str) -> str | None:
    lowered = normalize_space(label).lower()
    if not lowered:
        return None
    if any(token in lowered for token in ("you said", "user", "me said", "i said")):
        return "user"
    if any(token in lowered for token in ("assistant", "chatgpt", "claude", "gemini", "gpt", "copilot")):
        return "assistant"
    if "system" in lowered:
        return "system"
    return None


def clean_turn_content(content: str) -> str:
    cleaned_lines: list[str] = []
    for raw_line in sanitize_extracted_text(content).splitlines():
        line = raw_line.rstrip()
        compact = normalize_space(line)
        if compact in {"PDF", "Markdown"}:
            continue
        if re.fullmatch(r"\d+/\d+", compact):
            continue
        if compact in {"* * *", "---", "***"}:
            continue
        cleaned_lines.append(line)
    text = "\n".join(cleaned_lines).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def parse_role_marked_dialogue(text: str) -> list[dict[str, Any]]:
    turns: list[dict[str, Any]] = []
    current_label = ""
    current_role = ""
    current_lines: list[str] = []

    def flush() -> None:
        if not current_label:
            return
        raw_content = sanitize_extracted_text("\n".join(current_lines)).strip()
        cleaned = clean_turn_content(raw_content)
        if not raw_content and not cleaned:
            return
        turns.append(
            {
                "turn_index": len(turns) + 1,
                "speaker_label": current_label,
                "role": current_role or "unknown",
                "content": raw_content,
                "cleaned_content": cleaned,
            }
        )

    for raw_line in sanitize_extracted_text(text).splitlines():
        stripped = raw_line.strip()
        marker_match = TURN_MARKER_RE.match(stripped)
        role = classify_speaker_label(marker_match.group("label")) if marker_match else None
        if marker_match and role:
            flush()
            current_label = marker_match.group("label")
            current_role = role
            current_lines = []
            continue
        if not current_label and not stripped:
            continue
        if not current_label:
            current_label = "Unknown"
            current_role = "unknown"
        current_lines.append(raw_line)
    flush()
    if turns:
        return turns
    cleaned = clean_turn_content(text)
    return [
        {
            "turn_index": 1,
            "speaker_label": "Unknown",
            "role": "unknown",
            "content": sanitize_extracted_text(text).strip(),
            "cleaned_content": cleaned,
        }
    ]


def render_cleaned_dialogue(turns: Sequence[dict[str, Any]]) -> str:
    lines = ["# Cleaned Dialogue", ""]
    for turn in turns:
        lines.append(f"## Turn {turn['turn_index']} | {turn['role']} | {turn['speaker_label']}")
        lines.append("")
        lines.append(str(turn.get("cleaned_content", "")).strip())
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def clean_title_candidate(raw: str) -> str:
    value = sanitize_extracted_text(raw).strip().strip("`")
    value = re.sub(r"^#+\s*", "", value)
    value = value.strip("*_> -")
    value = re.sub(r"\s+", " ", value).strip()
    if value.lower().endswith(".pdf"):
        value = clean_filename_title(value)
    value = re.sub(r"\s+\((?:[^()]*et al\.?,?\s*\d{4}|[A-Z][A-Za-z]+ et al\.?,?\s*\d{4})\)\s*$", "", value)
    value = re.sub(r"\s{2,}", " ", value).strip(" :：-")
    return value.strip()


def clean_filename_title(raw: str) -> str:
    stem = Path(raw).name
    if stem.lower().endswith(".pdf"):
        stem = stem[:-4]
    stem = stem.replace("_", " ")
    parts = [part.strip() for part in stem.split(" - ") if part.strip()]
    if len(parts) >= 3 and re.fullmatch(r"\d{4}", parts[1]):
        stem = " - ".join(parts[2:])
    elif len(parts) >= 2 and re.fullmatch(r"\d{4}", parts[-2]):
        stem = parts[-1]
    return clean_title_candidate(stem)


def title_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).lower()
    normalized = re.sub(r"\bet al\b", "", normalized)
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", normalized)


def looks_like_generic_title(value: str) -> bool:
    compact = clean_title_candidate(value)
    if not compact:
        return True
    if any(pattern.match(compact) for pattern in GENERIC_TITLE_PATTERNS):
        return True
    if len(compact) < 6:
        return True
    return False


def add_title_candidate(bucket: list[dict[str, Any]], title: str, source: str, score: int) -> None:
    cleaned = clean_title_candidate(title)
    if not cleaned or looks_like_generic_title(cleaned):
        return
    bucket.append({"title": cleaned, "source": source, "score": score, "key": title_key(cleaned)})


def extract_title_candidates_from_turns(turns: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for turn in turns:
        content = str(turn.get("cleaned_content", "") or turn.get("content", ""))
        lines = sanitize_extracted_text(content).splitlines()

        for raw_line in lines:
            compact = raw_line.strip()
            if compact.lower().endswith(".pdf") and compact.upper() != "PDF":
                add_title_candidate(candidates, clean_filename_title(compact), "filename", 80)

        for index, raw_line in enumerate(lines):
            compact = raw_line.strip()
            if re.search(r"(?:\*\*)?标题(?:\*\*)?\s*[:：]\s*", compact):
                after = re.split(r"[:：]", compact, maxsplit=1)[1].strip()
                if clean_title_candidate(after):
                    add_title_candidate(candidates, after, "title_field", 100)
                else:
                    for follow in lines[index + 1 :]:
                        if follow.strip():
                            add_title_candidate(candidates, follow, "title_field_follow", 95)
                            break

        for raw_line in lines:
            compact = raw_line.strip()
            if compact.startswith(("_", "*")) and compact.endswith(("_", "*")) and len(compact) > 10:
                add_title_candidate(candidates, compact, "emphasis_line", 70)

        for raw_line in lines:
            match = MARKDOWN_HEADING_RE.match(raw_line.strip())
            if not match:
                continue
            title = match.group("title")
            if "(" in title and ")" in title:
                add_title_candidate(candidates, title, "heading_with_author", 75)
            else:
                add_title_candidate(candidates, title, "heading", 60)

    deduped: dict[str, dict[str, Any]] = {}
    for item in candidates:
        key = item["key"]
        existing = deduped.get(key)
        if existing is None or (item["score"], len(item["title"])) > (existing["score"], len(existing["title"])):
            deduped[key] = item
    ranked = sorted(deduped.values(), key=lambda item: (item["score"], len(item["title"])), reverse=True)
    return [{"title": item["title"], "source": item["source"], "score": item["score"]} for item in ranked]


def extract_candidate_title_from_dialogue(turns: Sequence[dict[str, Any]], dialogue_path: Path | None = None) -> dict[str, Any]:
    candidates = extract_title_candidates_from_turns(turns)
    if candidates:
        return {"title": candidates[0]["title"], "candidates": candidates}
    fallback = dialogue_path.stem if dialogue_path is not None else "paper-chat-report"
    return {"title": fallback, "candidates": []}


def extract_pdf_mentions_from_turns(turns: Sequence[dict[str, Any]], base_dir: Path | None = None) -> list[dict[str, Any]]:
    mentions: list[dict[str, Any]] = []
    for turn in turns:
        for raw_line in sanitize_extracted_text(str(turn.get("content", ""))).splitlines():
            compact = raw_line.strip().strip("`")
            if not compact.lower().endswith(".pdf") or compact.upper() == "PDF":
                continue
            candidates: list[Path] = []
            direct = Path(compact).expanduser()
            if direct.is_absolute():
                candidates.append(direct)
            if base_dir is not None:
                candidates.append(base_dir / compact)
                candidates.append(base_dir / Path(compact).name)
            resolved_path = None
            for candidate in candidates:
                expanded = candidate.expanduser()
                if expanded.exists() and expanded.suffix.lower() == ".pdf":
                    resolved_path = expanded.resolve()
                    break
            mentions.append(
                {
                    "raw": compact,
                    "resolved_path": str(resolved_path) if resolved_path else None,
                    "turn_index": turn["turn_index"],
                    "role": turn["role"],
                }
            )
    return mentions


def title_similarity(left: str, right: str) -> float:
    left_key = title_key(left)
    right_key = title_key(right)
    if not left_key or not right_key:
        return 0.0
    return difflib.SequenceMatcher(a=left_key, b=right_key).ratio()


def fetch_text(url: str, accept: str = "text/plain") -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "paper-chat-report-skill/1.0", "Accept": accept})
    with urllib.request.urlopen(request, timeout=30) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def search_arxiv_by_title(title: str) -> dict[str, Any] | None:
    query = urllib.parse.quote(f'ti:"{title}"')
    url = f"https://export.arxiv.org/api/query?search_query={query}&start=0&max_results=5"
    try:
        xml_text = fetch_text(url, accept="application/atom+xml")
    except Exception:
        return None
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    best: dict[str, Any] | None = None
    best_score = 0.0
    for entry in root.findall("atom:entry", ns):
        entry_id = entry.findtext("atom:id", default="", namespaces=ns).strip()
        entry_title = normalize_space(entry.findtext("atom:title", default="", namespaces=ns))
        if not entry_id or not entry_title:
            continue
        score = title_similarity(title, entry_title)
        if score < 0.78 or score <= best_score:
            continue
        arxiv_id = entry_id.rstrip("/").split("/")[-1]
        best = {
            "source_type": "arxiv_search_match",
            "original_source": title,
            "arxiv_id": arxiv_id,
            "abs_url": f"https://arxiv.org/abs/{arxiv_id}",
            "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}.pdf",
            "display_source": f"arXiv:{arxiv_id}",
            "resolved_title": entry_title,
            "resolved_via": "arxiv_title_search",
            "title_similarity": round(score, 4),
        }
        best_score = score
    return best


def search_semantic_scholar_open_pdf(title: str) -> dict[str, Any] | None:
    params = urllib.parse.urlencode(
        {
            "query": title,
            "limit": 5,
            "fields": "title,year,url,venue,openAccessPdf,externalIds",
        }
    )
    url = f"https://api.semanticscholar.org/graph/v1/paper/search?{params}"
    try:
        payload = json.loads(fetch_text(url, accept="application/json"))
    except Exception:
        return None
    data = payload.get("data", [])
    if not isinstance(data, list):
        return None
    best: dict[str, Any] | None = None
    best_score = 0.0
    for item in data:
        item_title = normalize_space(str(item.get("title", "")))
        pdf_payload = item.get("openAccessPdf") or {}
        pdf_url = str(pdf_payload.get("url", "")).strip()
        if not item_title or not pdf_url:
            continue
        score = title_similarity(title, item_title)
        if score < 0.84 or score <= best_score:
            continue
        best = {
            "source_type": "semantic_scholar_open_pdf",
            "original_source": title,
            "pdf_url": pdf_url,
            "display_source": str(item.get("url") or pdf_url),
            "landing_url": str(item.get("url", "")).strip(),
            "resolved_title": item_title,
            "resolved_via": "semantic_scholar_open_pdf",
            "title_similarity": round(score, 4),
            "year": item.get("year"),
            "venue": item.get("venue"),
        }
        best_score = score
    return best


def resolve_paper_source(
    *,
    explicit_source: str | None,
    turns: Sequence[dict[str, Any]],
    dialogue_path: Path,
    preferred_title: str = "",
) -> dict[str, Any] | None:
    if explicit_source:
        payload = resolve_source(explicit_source)
        payload["resolved_via"] = "explicit_source"
        return payload

    mentions = extract_pdf_mentions_from_turns(turns, base_dir=dialogue_path.parent)
    for mention in mentions:
        if mention["resolved_path"]:
            payload = resolve_source(str(mention["resolved_path"]))
            payload["resolved_via"] = "dialogue_local_pdf_hint"
            payload["dialogue_pdf_hint"] = mention["raw"]
            return payload

    if env_flag("PAPER_CHAT_REPORT_DISABLE_REMOTE_RESOLVE"):
        return None

    title_info = extract_candidate_title_from_dialogue(turns, dialogue_path=dialogue_path)
    title = preferred_title or str(title_info.get("title", "")).strip()
    if not title:
        return None

    arxiv_match = search_arxiv_by_title(title)
    if arxiv_match:
        return arxiv_match
    semantic_match = search_semantic_scholar_open_pdf(title)
    if semantic_match:
        return semantic_match
    return None
