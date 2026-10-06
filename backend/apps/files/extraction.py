"""Text from an uploaded curriculum (task 7.1; D76). The type is read from the content, not the name: PDF with pypdf
(it kept the Arabic reading order where pdfminer.six reversed it), Word with python-docx (paragraphs and tables in
the order of the document), and UTF-8 text. What cannot be read is refused with a reason the author is told, and
pasting the text stays open (spec 7.7). Harak 1's reader then takes the text as it takes pasted text."""

import io
import zipfile
from dataclasses import dataclass

from django.conf import settings
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from pypdf import PdfReader
from pypdf.errors import PyPdfError

PDF_MAGIC = b"%PDF-"
ZIP_MAGIC = b"PK\x03\x04"


class Refused(Exception):
    """The file is not read; ``code`` says why (file_too_large, file_type_unsupported, file_unreadable,
    file_encrypted, file_too_many_pages)."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code


@dataclass(frozen=True)
class Extracted:
    kind: str  # pdf, docx or txt
    text: str


def extract(data: bytes, name: str) -> Extracted:
    if len(data) > settings.IMPORT_MAX_FILE_BYTES:
        raise Refused("file_too_large", f"{len(data)} bytes")
    if data.startswith(PDF_MAGIC):
        return Extracted("pdf", _pdf(data))
    if data.startswith(ZIP_MAGIC):
        return Extracted("docx", _docx(data))
    return Extracted("txt", _text(data, name))


def _pdf(data: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise Refused("file_encrypted")  # a password to open it: Harak does not ask for it
        if len(reader.pages) > settings.IMPORT_MAX_PAGES:
            raise Refused("file_too_many_pages", f"{len(reader.pages)} pages")
        return "\n\n".join((page.extract_text() or "").strip() for page in reader.pages)
    except Refused:
        raise
    except (PyPdfError, ValueError, KeyError, TypeError, OSError) as exc:
        raise Refused("file_unreadable", str(exc)) from exc


def _docx(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as package:
            entries = package.infolist()
            if "word/document.xml" not in package.namelist():
                raise Refused("file_type_unsupported", "a zip that is not a Word document")
            # A small file that unpacks to a huge one would tie up the server (a "zip bomb").
            if sum(entry.file_size for entry in entries) > settings.IMPORT_MAX_UNPACKED_BYTES:
                raise Refused("file_too_large", "unpacks to more than allowed")
        document = Document(io.BytesIO(data))
    except Refused:
        raise
    except (zipfile.BadZipFile, KeyError, ValueError, OSError) as exc:
        raise Refused("file_unreadable", str(exc)) from exc
    lines: list[str] = []
    for item in document.iter_inner_content():
        if isinstance(item, Paragraph):
            lines.append(item.text)
        elif isinstance(item, Table):
            for row in item.rows:
                seen = set()
                for cell in row.cells:  # a merged cell is given once per row
                    if id(cell._tc) not in seen:
                        seen.add(id(cell._tc))
                        lines.extend(paragraph.text for paragraph in cell.paragraphs)
    return "\n".join(lines)


def _text(data: bytes, name: str) -> str:
    if not name.lower().endswith(".txt"):
        raise Refused("file_type_unsupported", name)
    try:
        if data.startswith((b"\xff\xfe", b"\xfe\xff")):
            return data.decode("utf-16")
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise Refused("file_unreadable", "the text is not in UTF-8") from exc
