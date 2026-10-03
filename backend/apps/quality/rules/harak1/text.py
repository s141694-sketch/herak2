"""Arabic normalization, lexical similarity and the plain-text reader (Harak 1 sections 6.1 and 6.4)."""

import re
import unicodedata

from . import data
from .jsre import WS, D, from_units, js_trim, split_ws, to_units

# ---------- shared Arabic normalization ----------


def strip_tashkeel(text: str) -> str:
    return data.TASHKEEL.sub("", text)


_HAMZA = re.compile("[أإآ]")


def unify_hamza(text: str) -> str:
    return _HAMZA.sub("ا", text)


_NOT_WORD = re.compile(f"[^ء-ي٠-٩{D}{WS}]")
_DEFINITE = re.compile("^(?:و|ف|ب|ك|ل)?ال")


def normalize_arabic(text: str | None) -> str:
    """Hamza, ta marbuta, alef maqsura, diacritics, the article and punctuation, for lexical matching."""
    t = unify_hamza(strip_tashkeel(text or "")).replace("ة", "ه").replace("ى", "ي")
    t = _NOT_WORD.sub(" ", t)
    words = (_DEFINITE.sub("", w, count=1) for w in split_ws(t))
    return " ".join(w for w in words if w)


def token_set(text: str) -> dict[str, None]:
    """Normalized words of two letters or more, without stop words, in first-seen order (an ordered set)."""
    words = normalize_arabic(text).split(" ")
    return dict.fromkeys(w for w in words if len(w) >= 2 and w not in data.STOP_WORDS)


def jaccard(a, b) -> float:
    if not a or not b:
        return 0
    inter = sum(1 for w in a if w in b)
    return inter / (len(a) + len(b) - inter)


def count_words(text: str) -> int:
    return len([w for w in normalize_arabic(text).split(" ") if w])


# ---------- reader (6.1), plain-text path ----------


class ReaderError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def count_arabic_chars(text: str) -> int:
    return len(data.ARABIC_CHAR.findall(text))


def count_common_words(text: str) -> int:
    common = data.READER["commonWords"]
    return sum(1 for w in split_ws(text) if w in common)


def reverse_lines(text: str) -> str:
    """Reverse the characters of each line (code points, as ``Array.from``), keeping line order."""
    return "\n".join(line[::-1] for line in text.split("\n"))


def detect_reversed(text: str) -> bool:
    return count_common_words(reverse_lines(text)) > count_common_words(text)


_CRLF = re.compile("\r\n?")
_BLANKS = re.compile("[ \t\xa0]+")
_HAS_CONTENT = re.compile(f"[ء-ي٠-٩A-Za-z{D}]")
_MANY_NEWLINES = re.compile("\n{2,}")


def normalize_text(text: str | None) -> str:
    """NFKC, one kind of line break, single spaces, trimmed lines, no runs of blank lines."""
    t = unicodedata.normalize("NFKC", text or "")
    t = _BLANKS.sub(" ", _CRLF.sub("\n", t))
    lines = (js_trim(line) for line in t.split("\n"))
    t = "\n".join(line if _HAS_CONTENT.search(line) else "" for line in lines)
    return js_trim(_MANY_NEWLINES.sub("\n\n", t))


_LEADING_NEWLINES = re.compile("^\n+")


def paginate_text(text: str, page_size: int | None = None) -> list[str]:
    """Cut long text into pages at line breaks where possible; sizes count UTF-16 code units."""
    size = data.READER["txtPageSize"] if page_size is None else page_size
    rest = to_units(text)
    pages = []
    while len(rest) > size:
        cut = rest.rfind("\n", 0, size + 1)
        if cut < size / 2:
            cut = size
        pages.append(from_units(rest[:cut]))
        rest = _LEADING_NEWLINES.sub("", rest[cut:], count=1)
    pages.append(from_units(rest))
    return pages


_EXTENSION = re.compile("\\.([a-z0-9]+)\\Z", re.IGNORECASE)


def file_extension(file_name: str | None) -> str:
    match = _EXTENSION.search(file_name or "")
    return match.group(1).lower() if match else ""


def read_text_document(file_name: str, content: str) -> dict:
    """Harak 1's ``readDocument`` for text already extracted from a file (TXT path)."""
    file_type = file_extension(file_name)
    if file_type not in data.READER["supportedTypes"]:
        raise ReaderError(
            "UNSUPPORTED_TYPE",
            f'الصيغة "{file_type or "غير معروفة"}" غير مدعومة. الصيغ المقبولة: PDF نصي، DOCX، TXT.',
        )
    warnings = []
    pages = [normalize_text(page) for page in paginate_text(content)]
    if sum(count_arabic_chars(page) for page in pages) < data.READER["minArabicChars"]:
        raise ReaderError("NO_TEXT", "الملف فارغ أو لا يحوي نصًا عربيًا كافيًا للتحليل.")
    if detect_reversed("\n".join(pages)):
        pages = [normalize_text(reverse_lines(page)) for page in pages]
        warnings.append(
            {"code": "REVERSED_TEXT_FIXED", "message": "كان النص العربي مقلوبًا وقُلب تلقائيًا؛ راجع النتائج."}
        )
    return {
        "meta": {"fileName": file_name, "fileType": file_type, "pageCount": len(pages), "warnings": warnings},
        "pages": [{"index": i, "text": page} for i, page in enumerate(pages)],
    }
