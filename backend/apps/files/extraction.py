"""Text from an uploaded curriculum (task 7.1; D76, D80). The type is read from the content, not the name: PDF with
pypdf (it kept the Arabic reading order where pdfminer.six reversed it), Word with python-docx (paragraphs and tables
in the order of the document), and UTF-8 text. What cannot be read is refused with a reason the author is told, and
pasting the text stays open (spec 7.7). Harak 1's reader then takes the text as it takes pasted text.

A file is read in a child process with a time limit and a memory limit (D80): a few kilobytes of PDF or Word can be
made to take minutes or gigabytes to parse, and must not hold a web worker. Anything the parsers raise is a file
that could not be read.

    python -m apps.files.extraction   reads {"name", "limits"} on stdin's first line, then the file; writes JSON
"""

import io
import json
import os
import resource
import signal
import subprocess
import sys
import zipfile
from dataclasses import dataclass

from django.conf import settings

PDF_MAGIC = b"%PDF-"
ZIP_MAGIC = b"PK\x03\x04"


class Refused(Exception):
    """The file is not read; ``code`` says why (import_file_too_large, file_type_unsupported, file_unreadable,
    file_encrypted, file_too_many_pages, file_text_too_long)."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code


@dataclass(frozen=True)
class Extracted:
    kind: str  # pdf, docx or txt
    text: str


def extract(data: bytes, name: str) -> Extracted:
    from apps.agents.importing import MAX_TEXT_CHARS

    if len(data) > settings.IMPORT_MAX_FILE_BYTES:
        raise Refused("import_file_too_large", f"{len(data)} bytes")
    limits = {
        "pages": settings.IMPORT_MAX_PAGES,
        "unpacked": settings.IMPORT_MAX_UNPACKED_BYTES,
        "chars": MAX_TEXT_CHARS,
    }
    header = json.dumps({"name": name, "limits": limits}).encode() + b"\n"
    seconds, memory = settings.IMPORT_EXTRACT_SECONDS, settings.IMPORT_EXTRACT_MEMORY_MB * 1024 * 1024

    def limited():
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
        resource.setrlimit(resource.RLIMIT_CPU, (seconds + 1, seconds + 1))

    child = subprocess.Popen(
        [sys.executable, "-m", "apps.files.extraction"],
        cwd=settings.BASE_DIR,
        env={"PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8"},  # nothing of the server's own settings
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        preexec_fn=limited,
        start_new_session=True,
    )
    try:
        out, _ = child.communicate(header + data, timeout=seconds)
    except subprocess.TimeoutExpired:
        os.killpg(child.pid, signal.SIGKILL)
        child.wait()
        raise Refused("file_unreadable", f"not read within {seconds} s") from None
    try:
        result = json.loads(out)
    except ValueError:
        raise Refused("file_unreadable", f"the reader stopped (exit {child.returncode})") from None
    if "refused" in result:
        raise Refused(result["refused"], result.get("detail", ""))
    return Extracted(result["kind"], result["text"])


def read(data: bytes, name: str, limits: dict) -> Extracted:
    """Reads the file in this process: only ever called in the child (see ``extract``)."""
    if data.startswith(PDF_MAGIC):
        extracted = Extracted("pdf", _pdf(data, limits))
    elif data.startswith(ZIP_MAGIC):
        extracted = Extracted("docx", _docx(data, limits))
    else:
        extracted = Extracted("txt", _text(data, name))
    if len(extracted.text) > limits["chars"]:
        raise Refused("file_text_too_long", f"more than {limits['chars']} characters")
    return extracted


def _pdf(data: bytes, limits: dict) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted and not reader.decrypt(""):
        raise Refused("file_encrypted")  # a password to open it: Harak does not ask for it
    if len(reader.pages) > limits["pages"]:
        raise Refused("file_too_many_pages", f"{len(reader.pages)} pages")
    texts, length = [], 0
    for page in reader.pages:
        text = (page.extract_text() or "").strip()
        length += len(text)
        if length > limits["chars"]:  # longer than an import takes: no need to read the rest
            raise Refused("file_text_too_long", f"more than {limits['chars']} characters")
        texts.append(text)
    return "\n\n".join(texts)


def _docx(data: bytes, limits: dict) -> str:
    from docx import Document
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    with zipfile.ZipFile(io.BytesIO(data)) as package:
        if "word/document.xml" not in package.namelist():
            raise Refused("file_type_unsupported", "a zip that is not a Word document")
        # A small file that unpacks to a huge one would tie up the server (a "zip bomb").
        if sum(entry.file_size for entry in package.infolist()) > limits["unpacked"]:
            raise Refused("import_file_too_large", "unpacks to more than allowed")
    document = Document(io.BytesIO(data))
    lines: list[str] = []
    for item in document.iter_inner_content():
        if isinstance(item, Paragraph):
            lines.append(item.text)
        elif isinstance(item, Table):
            # Cells as written in the file: python-docx's row.cells lays out spans and merges, one entry per column
            # spanned, which a crafted span makes millions long.
            for row in item._tbl.iterchildren(qn("w:tr")):
                for cell in row.iterchildren(qn("w:tc")):
                    lines.extend(Paragraph(p, item).text for p in cell.iter(qn("w:p")))
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


def _child() -> None:
    header = sys.stdin.buffer.readline()
    data = sys.stdin.buffer.read()
    request = json.loads(header)
    try:
        extracted = read(data, request["name"], request["limits"])
        result = {"kind": extracted.kind, "text": extracted.text}
    except Refused as refused:
        result = {"refused": refused.code, "detail": str(refused)}
    except Exception as exc:  # noqa: BLE001 - whatever a parser raises, the file could not be read
        result = {"refused": "file_unreadable", "detail": f"{type(exc).__name__}: {exc}"[:500]}
    sys.stdout.write(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    _child()
