from pathlib import Path
from statistics import median
from typing import Any


ALLOWED_UPLOAD_SUFFIXES = {".txt", ".md", ".markdown", ".pdf", ".doc", ".docx"}


def _group_words_to_lines(words: list[dict[str, Any]], y_tol: float) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    for w in words:
        text = str(w.get("text", "")).strip()
        if not text:
            continue
        top = float(w.get("top", 0.0))
        bottom = float(w.get("bottom", top))
        x0 = float(w.get("x0", 0.0))
        x1 = float(w.get("x1", x0))
        target = None
        for line in lines:
            if abs(top - float(line["top"])) <= y_tol:
                target = line
                break
        if target is None:
            target = {"top": top, "bottom": bottom, "words": []}
            lines.append(target)
        target["top"] = min(float(target["top"]), top)
        target["bottom"] = max(float(target["bottom"]), bottom)
        target["words"].append({"x0": x0, "x1": x1, "text": text})
    for line in lines:
        line["words"].sort(key=lambda item: float(item["x0"]))
        line["text"] = " ".join(str(item["text"]).strip() for item in line["words"] if str(item["text"]).strip())
        line["x0"] = min(float(item["x0"]) for item in line["words"]) if line["words"] else 0.0
        line["x1"] = max(float(item["x1"]) for item in line["words"]) if line["words"] else 0.0
        line["x_center"] = (float(line["x0"]) + float(line["x1"])) / 2.0
    lines = [line for line in lines if str(line.get("text", "")).strip()]
    lines.sort(key=lambda row: (float(row["top"]), float(row["x0"])))
    return lines


def _order_lines_by_layout(lines: list[dict[str, Any]], page_width: float) -> list[str]:
    if not lines:
        return []
    mid_x = page_width / 2.0 if page_width > 0 else 300.0
    left = [ln for ln in lines if float(ln.get("x_center", 0.0)) <= mid_x]
    right = [ln for ln in lines if float(ln.get("x_center", 0.0)) > mid_x]
    cross = [ln for ln in lines if float(ln.get("x0", 0.0)) < mid_x < float(ln.get("x1", 0.0))]
    two_col = len(left) >= 6 and len(right) >= 6 and len(cross) <= max(2, len(lines) // 5)
    if two_col:
        left.sort(key=lambda row: (float(row["top"]), float(row["x0"])))
        right.sort(key=lambda row: (float(row["top"]), float(row["x0"])))
        ordered = left + right
    else:
        ordered = sorted(lines, key=lambda row: (float(row["top"]), float(row["x0"])))
    return [str(row.get("text", "")).strip() for row in ordered if str(row.get("text", "")).strip()]


def _read_pdf_text_layout(file_path: Path) -> str:
    try:
        import pdfplumber
    except Exception:
        return ""
    rows: list[str] = []
    try:
        with pdfplumber.open(str(file_path)) as pdf:
            for page in pdf.pages:
                words = page.extract_words(
                    keep_blank_chars=False,
                    use_text_flow=False,
                    x_tolerance=2,
                    y_tolerance=2,
                )
                if not words:
                    continue
                heights = [max(1.0, float(w.get("bottom", 0.0)) - float(w.get("top", 0.0))) for w in words]
                y_tol = max(2.0, min(8.0, median(heights) * 0.6))
                lines = _group_words_to_lines(words, y_tol=y_tol)
                ordered = _order_lines_by_layout(lines, page_width=float(getattr(page, "width", 0.0) or 0.0))
                if ordered:
                    rows.append("\n".join(ordered))
        return "\n\n".join(rows).strip()
    except Exception:
        return ""


def _read_pdf_text_fallback(file_path: Path) -> str:
    try:
        from pypdf import PdfReader
    except Exception:
        return ""
    try:
        reader = PdfReader(str(file_path))
        chunks: list[str] = []
        for page in reader.pages:
            chunks.append(page.extract_text() or "")
        return "\n".join(chunks).strip()
    except Exception:
        return ""


def _read_pdf_text(file_path: Path) -> str:
    layout_text = _read_pdf_text_layout(file_path)
    if layout_text:
        return layout_text
    return _read_pdf_text_fallback(file_path)


def _read_pdf_text_with_meta(file_path: Path) -> tuple[str, dict[str, Any]]:
    layout_text = _read_pdf_text_layout(file_path)
    if layout_text:
        return layout_text, {"file_type": "pdf", "pdf_parser": "pdfplumber_layout", "layout_used": True}
    fallback = _read_pdf_text_fallback(file_path)
    if fallback:
        return fallback, {"file_type": "pdf", "pdf_parser": "pypdf_fallback", "layout_used": False}
    return "", {"file_type": "pdf", "pdf_parser": "none", "layout_used": False}


def _read_docx_text(file_path: Path) -> str:
    try:
        from docx import Document
    except Exception:
        return ""
    try:
        doc = Document(str(file_path))
        rows = [p.text for p in doc.paragraphs if p.text and p.text.strip()]
        return "\n".join(rows).strip()
    except Exception:
        return ""


def _read_doc_text(file_path: Path) -> str:
    data = file_path.read_bytes()
    for encoding in ("utf-16le", "utf-8", "gb18030", "latin1"):
        try:
            text = data.decode(encoding, errors="ignore")
        except Exception:
            continue
        cleaned = text.replace("\x00", " ").strip()
        if len(cleaned) >= 40:
            return cleaned
    return ""


def read_text_from_file(file_path: Path) -> str:
    text, _ = read_text_with_meta(file_path)
    return text


def read_text_with_meta(file_path: Path) -> tuple[str, dict[str, Any]]:
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        return _read_pdf_text_with_meta(file_path)
    if suffix == ".docx":
        return _read_docx_text(file_path), {"file_type": "docx", "parser": "python-docx"}
    if suffix == ".doc":
        return _read_doc_text(file_path), {"file_type": "doc", "parser": "binary-decode"}
    return file_path.read_text(encoding="utf-8", errors="ignore").strip(), {"file_type": "text", "parser": "utf-8"}
