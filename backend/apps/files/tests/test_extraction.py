"""Text from an uploaded curriculum (task 7.1, spec 2.2 production, 7.6, 7.7): PDF with pypdf, Word with
python-docx, and plain text; the type is read from the content, and what cannot be read is refused plainly."""

import io
import zipfile
from pathlib import Path

import pytest
from docx import Document

from apps.files import extraction

FIXTURES = Path(__file__).parent / "fixtures"


def word(*paragraphs, table=None) -> bytes:
    document = Document()
    for text in paragraphs:
        document.add_paragraph(text)
    if table:
        grid = document.add_table(rows=len(table), cols=len(table[0]))
        for r, row in enumerate(table):
            for c, text in enumerate(row):
                grid.cell(r, c).text = text
    document.add_paragraph("الخاتمة")
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def test_a_word_file_gives_its_paragraphs_and_tables_in_reading_order():
    data = word("الوحدة الأولى", "الأهداف", table=[["الهدف", "المستوى"], ["أن يحدد المتدرب المعدات", "تطبيق"]])
    extracted = extraction.extract(data, "منهج.docx")
    assert extracted.kind == "docx"
    lines = [line for line in extracted.text.split("\n") if line]
    assert lines == ["الوحدة الأولى", "الأهداف", "الهدف", "المستوى", "أن يحدد المتدرب المعدات", "تطبيق", "الخاتمة"]


def test_an_arabic_pdf_gives_its_text_in_reading_order():
    extracted = extraction.extract((FIXTURES / "curriculum.pdf").read_bytes(), "curriculum.pdf")
    assert extracted.kind == "pdf"
    text = extracted.text
    assert text.index("الوحدة الأولى: السلامة في الورشة") < text.index("أن يحدد المتدرب معدات الوقاية الشخصية")


def test_plain_text_in_utf8_with_or_without_a_byte_order_mark():
    assert extraction.extract("نص عربي".encode(), "a.txt").text == "نص عربي"
    assert extraction.extract("﻿نص عربي".encode(), "a.txt").text == "نص عربي"


def test_the_type_comes_from_the_content_not_the_name():
    assert extraction.extract(word("نص"), "renamed.pdf").kind == "docx"
    assert extraction.extract((FIXTURES / "curriculum.pdf").read_bytes(), "renamed.docx").kind == "pdf"


@pytest.mark.parametrize(
    "data,name,code",
    [
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 64, "old.doc", "file_type_unsupported"),
        (b"\x89PNG\r\n\x1a\n" + b"\0" * 64, "scan.png", "file_type_unsupported"),
        (b"%PDF-1.7 broken", "broken.pdf", "file_unreadable"),
        ("نص".encode("cp1256"), "legacy.txt", "file_unreadable"),
    ],
)
def test_what_cannot_be_read_is_refused_with_a_reason(data, name, code):
    with pytest.raises(extraction.Refused) as refused:
        extraction.extract(data, name)
    assert refused.value.code == code


def test_a_pdf_locked_with_a_password_is_refused():
    with pytest.raises(extraction.Refused) as refused:
        extraction.extract((FIXTURES / "encrypted.pdf").read_bytes(), "encrypted.pdf")
    assert refused.value.code == "file_encrypted"


def test_a_file_over_the_size_limit_is_refused_before_it_is_read(settings):
    settings.IMPORT_MAX_FILE_BYTES = 1000
    with pytest.raises(extraction.Refused) as refused:
        extraction.extract(b"x" * 1001, "a.txt")
    assert refused.value.code == "file_too_large"


def test_a_pdf_with_too_many_pages_is_refused(settings):
    settings.IMPORT_MAX_PAGES = 0
    with pytest.raises(extraction.Refused) as refused:
        extraction.extract((FIXTURES / "curriculum.pdf").read_bytes(), "curriculum.pdf")
    assert refused.value.code == "file_too_many_pages"


def test_a_word_file_that_would_unpack_to_much_more_than_its_size_is_refused(settings):
    settings.IMPORT_MAX_UNPACKED_BYTES = 10_000
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(word("نص"))) as original, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as bomb:
        for item in original.infolist():
            bomb.writestr(item, original.read(item.filename))
        bomb.writestr("word/media/padding.bin", b"\0" * 50_000)
    with pytest.raises(extraction.Refused) as refused:
        extraction.extract(out.getvalue(), "big.docx")
    assert refused.value.code == "file_too_large"


def test_a_pdf_without_text_gives_no_text():
    """A scanned PDF has pages but no text: the caller then says to paste the text instead."""
    assert extraction.extract((FIXTURES / "scanned.pdf").read_bytes(), "scanned.pdf").text.strip() == ""
