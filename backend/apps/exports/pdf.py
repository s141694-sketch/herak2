"""PDF from the Word file (task 7.4; D78): LibreOffice without a screen converts the very file of task 7.3, so the
two say the same thing. Each conversion has its own LibreOffice profile (conversions may run side by side) and a
time limit."""

import shutil
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings


class ConversionFailed(Exception):
    pass


def from_word(docx: bytes) -> bytes:
    soffice = shutil.which(settings.EXPORT_SOFFICE)
    if soffice is None:
        raise ConversionFailed(f"LibreOffice ({settings.EXPORT_SOFFICE}) is not installed on this server")
    with tempfile.TemporaryDirectory(prefix="harak2-export-") as work:
        folder = Path(work)
        source = folder / "program.docx"
        source.write_bytes(docx)
        command = [
            soffice,
            "--headless",
            "--norestore",
            "--nolockcheck",
            f"-env:UserInstallation={(folder / 'profile').as_uri()}",
            "--convert-to",
            "pdf",
            "--outdir",
            str(folder),
            str(source),
        ]
        try:
            finished = subprocess.run(  # noqa: S603 - fixed arguments, no shell
                command, capture_output=True, text=True, timeout=settings.EXPORT_PDF_SECONDS, check=False
            )
        except subprocess.TimeoutExpired as exc:
            raise ConversionFailed(f"LibreOffice took too long (over {settings.EXPORT_PDF_SECONDS} s)") from exc
        made = folder / "program.pdf"
        if not made.exists():
            raise ConversionFailed(f"LibreOffice made no PDF: {(finished.stderr or finished.stdout).strip()[:500]}")
        return made.read_bytes()
