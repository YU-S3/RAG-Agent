from pathlib import Path
from unittest.mock import patch

from app.cli import _read_text_from_file
from app.rag.file_parser import read_text_from_file


def run() -> None:
    pdf = Path("eval/tmp_parse.pdf")
    pdf.parent.mkdir(parents=True, exist_ok=True)
    pdf.write_text("dummy", encoding="utf-8")
    with patch("app.rag.file_parser._read_pdf_text_layout", return_value="pdf layout ok"):
        assert read_text_from_file(pdf) == "pdf layout ok"

    docx = Path("eval/tmp_parse.docx")
    docx.write_text("dummy", encoding="utf-8")
    with patch("app.rag.file_parser._read_docx_text", return_value="docx ok"):
        assert read_text_from_file(docx) == "docx ok"

    doc = Path("eval/tmp_parse.doc")
    doc.write_text("dummy", encoding="utf-8")
    with patch("app.rag.file_parser._read_doc_text", return_value="doc ok"):
        assert read_text_from_file(doc) == "doc ok"

    txt = Path("eval/tmp_parse.txt")
    txt.write_text("txt ok", encoding="utf-8")
    assert read_text_from_file(txt) == "txt ok"
    assert _read_text_from_file(txt) == "txt ok"


if __name__ == "__main__":
    run()
