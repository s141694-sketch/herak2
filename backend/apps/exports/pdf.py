"""PDF from the Word file (task 7.4; D78): LibreOffice without a screen converts the very file of task 7.3, so the
two say the same thing. Each conversion has its own LibreOffice profile (conversions may run side by side) and a
time limit."""

import os
import shutil
import signal
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
            said = _run(command, settings.EXPORT_PDF_SECONDS)
        except subprocess.TimeoutExpired as exc:
            raise ConversionFailed(f"LibreOffice took too long (over {settings.EXPORT_PDF_SECONDS} s)") from exc
        made = folder / "program.pdf"
        if not made.exists():
            raise ConversionFailed(f"LibreOffice made no PDF: {said.strip()[:500]}")
        return made.read_bytes()


def _run(command: list[str], timeout: int) -> str:
    """Runs LibreOffice in a process group of its own and stops the whole group when it is done or out of time:
    soffice is a script whose soffice.bin would outlive it (phase 7 review, D81). Returns what it said."""
    process = subprocess.Popen(  # noqa: S603 - fixed arguments, no shell
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True
    )
    try:
        said, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _stop(process)
        raise
    _stop(process)  # anything it left running
    return said or ""


def _stop(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass  # the group has ended
    process.wait()
