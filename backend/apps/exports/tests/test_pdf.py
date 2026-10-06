"""The PDF of an approved version (task 7.4; D78): made by LibreOffice from the very Word file of task 7.3, so the
two say the same thing. Where LibreOffice is not installed the conversion tests are skipped, except in CI, which
installs it and sets HARAK_REQUIRE_SOFFICE so that a missing LibreOffice fails instead."""

import io
import os
import shutil
import subprocess

import pytest
from django.conf import settings
from pypdf import PdfReader

from apps.exports import pdf, word
from apps.tenancy.context import organization_context

from .test_word import world  # noqa: F401 - the world fixture

pytestmark = pytest.mark.django_db
needs_soffice = pytest.mark.skipif(
    not shutil.which(settings.EXPORT_SOFFICE) and not os.environ.get("HARAK_REQUIRE_SOFFICE"),
    reason="needs LibreOffice (soffice); CI installs it",
)


@needs_soffice
def test_the_pdf_is_the_word_file_converted_and_reads_in_the_trees_order(world):  # noqa: F811
    with organization_context(world["org"]):
        made = pdf.from_word(word.build(world["version"]))
    assert made.startswith(b"%PDF-")
    reader = PdfReader(io.BytesIO(made))
    assert len(reader.pages) >= 2  # the cover, then the tree
    # pypdf drops the spaces between Arabic words set in some fonts (DejaVu Sans here): the order is compared
    # without them.
    text = "".join("".join(page.extract_text() for page in reader.pages).split())
    order = ["برنامج السلامة المهنية", "الوحدة الأولى: السلامة", "الدرس الأول: المعدات", "الوحدة الثانية: الإسعاف"]
    positions = [text.index("".join(heading.split())) for heading in order]
    assert positions == sorted(positions)


def test_a_conversion_that_takes_too_long_fails_plainly(monkeypatch):
    def slow(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="soffice", timeout=1)

    monkeypatch.setattr(pdf.subprocess, "run", slow)
    with pytest.raises(pdf.ConversionFailed, match="too long"):
        pdf.from_word(b"PK")


def test_without_libreoffice_the_conversion_fails_plainly(settings):
    settings.EXPORT_SOFFICE = "/nonexistent/soffice"
    with pytest.raises(pdf.ConversionFailed, match="LibreOffice"):
        pdf.from_word(b"PK")


def test_a_conversion_that_makes_no_pdf_fails_plainly(monkeypatch):
    monkeypatch.setattr(pdf.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "", "boom"))
    monkeypatch.setattr(pdf.shutil, "which", lambda name: "/usr/bin/soffice")
    with pytest.raises(pdf.ConversionFailed, match="no PDF"):
        pdf.from_word(b"PK")
