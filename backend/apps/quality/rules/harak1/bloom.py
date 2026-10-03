"""Bloom classification by verb matching, with the affective and psychomotor domains (Harak 1 section 6.3)."""

import re

from . import data
from .jsre import WS
from .text import strip_tashkeel, unify_hamza


def _key(verb: str) -> str:
    return unify_hamza(strip_tashkeel(verb))


def _bloom_index() -> dict[str, list[int]]:
    """Normalized verb -> ids of the levels it appears in, ascending."""
    index: dict[str, list[int]] = {}
    for level in data.BLOOM_LEVELS:
        for verb in level["verbs"]:
            levels = index.setdefault(_key(verb), [])
            if level["id"] not in levels:
                levels.append(level["id"])
            levels.sort()
    return index


BLOOM_INDEX = _bloom_index()


def strip_suffixes(word: str, suffixes: list[str]) -> str:
    for suffix in suffixes:
        if len(word) > len(suffix) + 2 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


_NON_LETTER = re.compile(f"[^ء-ي{WS}]")
_SPLIT = re.compile(f"[{WS}]+")
_AN = re.compile("^(?:أن|ان)\\Z")
_PRESENT = re.compile("^[يت][ء-ي]{2,}\\Z")


def extract_verb(text: str) -> str:
    """The first word after "أن", otherwise the first word starting with ي or ت."""
    words = [w for w in _SPLIT.split(_NON_LETTER.sub(" ", strip_tashkeel(text))) if w]
    for i, word in enumerate(words):
        if _AN.search(word) and i + 1 < len(words) and words[i + 1]:
            return words[i + 1]
    return next((w for w in words if _PRESENT.search(w)), "")


_TA = re.compile("^ت")
_DAL_RUN = re.compile("د{2,}")


def lookup_verb(word: str) -> dict | None:
    w = _TA.sub("ي", unify_hamza(word), count=1)
    direct = BLOOM_INDEX.get(w) or (BLOOM_INDEX.get(unify_hamza(word)) if word.startswith("ت") else None)
    if direct:
        return {"levels": direct, "exact": True}
    stem = strip_suffixes(strip_suffixes(w, data.PRONOUN_SUFFIXES), data.VERB_SUFFIXES)
    loose = BLOOM_INDEX.get(stem) or BLOOM_INDEX.get(_TA.sub("ي", stem, count=1))
    if loose:
        return {"levels": loose, "exact": False}
    # Broken PDF fonts turn the kashida into "د" (يبددين = يبين): try without it, with medium confidence.
    if "د" in w:
        for candidate in (_DAL_RUN.sub("", w), _DAL_RUN.sub("دد", w), w.replace("د", "")):
            hit = BLOOM_INDEX.get(candidate) or BLOOM_INDEX.get(_TA.sub("ي", candidate, count=1))
            if hit:
                return {"levels": hit, "exact": False, "repaired": True}
    return None


def level_name(level_id: int) -> str:
    return next((level["name"] for level in data.BLOOM_LEVELS if level["id"] == level_id), "غير محدد")


def _domain_index(domain: str) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for level in data.RAW[domain]["levels"]:
        for verb in level["verbs"]:
            index.setdefault(_key(verb.split(" ")[0]), {"levelId": level["id"], "levelName": level["name"]})
    return index


DOMAIN_INDEX = {domain: _domain_index(domain) for domain in ("affective", "psychomotor")}


def lookup_domain_verb(word: str) -> dict | None:
    w = _TA.sub("ي", unify_hamza(strip_tashkeel(word)), count=1)
    stem = strip_suffixes(strip_suffixes(w, data.PRONOUN_SUFFIXES), data.VERB_SUFFIXES)
    for domain in ("affective", "psychomotor"):
        index = DOMAIN_INDEX[domain]
        hit = index.get(w) or index.get(stem)
        if hit:
            return {"domain": domain, **hit, "exact": w in index}
    return None


def classify_objective(text: str) -> dict:
    """One objective: cognitive level by dictionary, else affective or psychomotor; never guessed."""
    verb = extract_verb(text)
    hit = lookup_verb(verb) if verb else None
    level_id, confidence, domain, level = 0, "low", None, "غير محدد"
    if hit:
        level_id = hit["levels"][0]
        domain = "cognitive"
        level = level_name(level_id)
        confidence = "high" if hit["exact"] and len(hit["levels"]) == 1 else "medium"
    elif verb:
        found = lookup_domain_verb(verb)
        if found:
            domain, level = found["domain"], found["levelName"]
            confidence = "high" if found["exact"] else "medium"
    return {"verb": verb, "level": level, "levelId": level_id, "domain": domain, "confidence": confidence}


def objectives_of(struct: dict):
    """(reference, text) for every objective of a Harak 1 structure, in document order."""
    for ui, unit in enumerate(struct["units"]):
        for li, lesson in enumerate(unit["lessons"]):
            for oi, objective in enumerate(lesson["objectives"]):
                yield {"unit": ui, "lesson": li, "index": oi, "text": objective["text"]}, objective["text"]


def classify_bloom(struct: dict) -> list[dict]:
    return [{"objectiveRef": ref, **classify_objective(text)} for ref, text in objectives_of(struct)]
