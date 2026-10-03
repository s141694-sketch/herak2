"""Harak 1's rule data (verb dictionaries, suffixes, stop words, thresholds) and the indexes built from it."""

import json
import re
from pathlib import Path

RAW = json.loads((Path(__file__).with_name("data.json")).read_text(encoding="utf-8"))

BLOOM_LEVELS: list[dict] = RAW["bloomLevels"]
PRONOUN_SUFFIXES: list[str] = RAW["pronounSuffixes"]
VERB_SUFFIXES: list[str] = RAW["verbSuffixes"]
STOP_WORDS: frozenset[str] = frozenset(RAW["stopWords"])
MATCH_THRESHOLDS: dict[str, float] = RAW["matchThresholds"]
DOMAIN_NAMES: dict[str, str] = RAW["domainNames"]
DIMENSIONS: list[dict] = RAW["dimensions"]
UNMEASURABLE_VERBS: list[str] = RAW["unmeasurableVerbs"]
READER: dict = RAW["reader"]

#: Diacritics and tatweel: U+0610-U+061A, U+064B-U+065F, U+0670, U+06D6-U+06ED, U+0640.
TASHKEEL_SOURCE = "[ؐ-ًؚ-ٰٟۖ-ۭـ]"
TASHKEEL = re.compile(TASHKEEL_SOURCE)
#: Any character of the Arabic block.
ARABIC_CHAR_SOURCE = "[؀-ۿ]"
ARABIC_CHAR = re.compile(ARABIC_CHAR_SOURCE)
