"""JavaScript string and regex semantics that Harak 1's rules depend on.

Harak 1 runs in a browser, so its rules use ECMAScript behaviour that differs
from Python in small ways that change results on real Arabic text:

- ``\\s`` is a fixed set of whitespace and line terminators (no U+001C-U+001F
  or U+0085, but U+FEFF), and ``trim()`` strips exactly that set;
- ``\\d`` is ASCII 0-9 only, while Python's matches Arabic-Indic digits too;
- ``.`` stops at four line terminators, not only ``\\n``;
- ``$`` without the m flag is the end of input, while Python's also matches
  before a final newline;
- string lengths and indexes count UTF-16 code units;
- ``Math.round`` rounds halves up, while Python's ``round`` rounds to even.

The rule modules build their patterns from the pieces below, so each pattern
reads like its JavaScript source with these differences made explicit.
"""

import math
import re

#: Contents of a character class equal to ECMAScript's ``\\s``.
WS = "\\t\\n\\x0b\\x0c\\r \\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000\\ufeff"
#: ``\\s``, ``\\S`` and ``.`` (no s flag) as Python pattern fragments.
S = f"[{WS}]"
NS = f"[^{WS}]"
DOT = "[^\\n\\r\\u2028\\u2029]"
#: ECMAScript ``\\d``.
D = "0-9"

_WS_CHARS = frozenset("\t\n\x0b\x0c\r \xa0     　﻿") | frozenset(chr(c) for c in range(0x2000, 0x200B))
_SPLIT_WS = re.compile(f"{S}+")


def js_trim(text: str) -> str:
    """``String.prototype.trim``."""
    start, end = 0, len(text)
    while start < end and text[start] in _WS_CHARS:
        start += 1
    while end > start and text[end - 1] in _WS_CHARS:
        end -= 1
    return text[start:end]


def split_ws(text: str) -> list[str]:
    """``text.split(/\\s+/)``: empty strings at either end are kept, as in JavaScript."""
    return _SPLIT_WS.split(text)


def js_round(value: float) -> int:
    """``Math.round`` for the non-negative values the rules produce."""
    return math.floor(value + 0.5)


def js_len(text: str) -> int:
    """``text.length``: UTF-16 code units."""
    return len(text) + sum(1 for ch in text if ord(ch) > 0xFFFF)


def to_units(text: str) -> str:
    """Spell astral characters as surrogate pairs, so indexes and slices count UTF-16 code units."""
    if all(ord(ch) <= 0xFFFF for ch in text):
        return text
    out = []
    for ch in text:
        code = ord(ch)
        if code > 0xFFFF:
            code -= 0x10000
            out.append(chr(0xD800 + (code >> 10)))
            out.append(chr(0xDC00 + (code & 0x3FF)))
        else:
            out.append(ch)
    return "".join(out)


_PAIR = re.compile("[\\ud800-\\udbff][\\udc00-\\udfff]")


def from_units(text: str) -> str:
    """Join surrogate pairs back into characters; a lone surrogate stays, as it would in JavaScript."""
    return _PAIR.sub(lambda m: chr(0x10000 + ((ord(m.group()[0]) - 0xD800) << 10) + (ord(m.group()[1]) - 0xDC00)), text)
