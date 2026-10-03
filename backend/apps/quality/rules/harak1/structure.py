"""Turning curriculum text into units, lessons and sections, and the completeness summary (Harak 1 6.2 and 6.5)."""

import re
from dataclasses import dataclass

from . import data
from .jsre import DOT, NS, WS, D, S, js_len, js_round, js_trim
from .text import count_words, strip_tashkeel, unify_hamza

SECTION_TYPES = ["objectives", "activities", "assessments", "references"]
_NUM = f"[{D}٠-٩]"
_SEP = f"[{WS}.\\-–)]"


@dataclass(frozen=True)
class Pattern:
    type: str
    heading: re.Pattern | None
    item: re.Pattern | None
    numbered: bool
    heading_source: str | None
    item_source: str | None
    #: A ``(?=.{0,N}$)`` lookahead counts UTF-16 code units; Python checks it in code.
    max_length: int | None = None

    def matches(self, line: str, kind: str) -> bool:
        pattern = self.heading if kind == "heading" else self.item
        if pattern is None or not pattern.search(line):
            return False
        return self.max_length is None or js_len(line) <= self.max_length


STRUCTURE_PATTERNS = [
    Pattern(
        "unit",
        re.compile(f"^(?:الوحدة|وحدة|الفصل|الباب){S}*(?:رقم{S}*)?{_NUM}*{S}*[:\\-–—]?{S}*{NS}"),
        None,
        False,
        "^(?:الوحدة|وحدة|الفصل|الباب)\\s*(?:رقم\\s*)?[\\d٠-٩]*\\s*[:\\-–—]?\\s*\\S",
        None,
    ),
    Pattern(
        "lesson",
        re.compile(f"^(?:الدرس|درس|المحاضرة|الورشة){S}*(?:رقم{S}*)?{_NUM}*{S}*[:\\-–—]?{S}*[ء-ي{D}٠-٩]"),
        None,
        False,
        "^(?:الدرس|درس|المحاضرة|الورشة)\\s*(?:رقم\\s*)?[\\d٠-٩]*\\s*[:\\-–—]?\\s*[ء-ي\\d٠-٩]",
        None,
    ),
    Pattern(
        "lesson",
        re.compile(f"^(?!{_NUM})(?={DOT}*\\Z)(?={DOT}*{S}الدرس{S}+(?:ال[ء-ي]+|{_NUM}+))(?={DOT}*[:\\-–—])"),
        None,
        False,
        "^(?![\\d٠-٩])(?=.{0,70}$)(?=.*\\sالدرس\\s+(?:ال[ء-ي]+|[\\d٠-٩]+))(?=.*[:\\-–—])",
        None,
        max_length=70,
    ),
    Pattern(
        "lesson",
        re.compile(f"^{_NUM}{{1,2}}{S}*[.\\-–)]{_SEP}*(?!(?:أن|ان){S}|[يت][ء-ي]{{2,}}(?![ء-ي]))[ء-ي{D}٠-٩]"),
        None,
        True,
        "^[\\d٠-٩]{1,2}\\s*[\\.\\-–)][\\s.\\-–)]*(?!(?:أن|ان)\\s|[يت][ء-ي]{2,}(?![ء-ي]))[ء-ي\\d٠-٩]",
        None,
    ),
    Pattern(
        "objectives",
        re.compile(
            "^(?:الأهداف|الاهداف|أهداف التعلم|اهداف التعلم|نواتج التعلم|أهداف الدرس|اهداف الدرس|الأهداف السلوكية"
            f"|الاهداف السلوكية|الأهداف الخاصة|نتاجات التعلم){S}*:?{S}*\\Z"
            "|يتوقع من (?:المتدرب|الطالب|المتعلم|الدارس)|^بعد (?:نهاية|انتهاء|دراسة) (?:هذا )?(?:الدرس|الوحدة)"
        ),
        None,
        False,
        "^(?:الأهداف|الاهداف|أهداف التعلم|اهداف التعلم|نواتج التعلم|أهداف الدرس|اهداف الدرس|الأهداف السلوكية"
        "|الاهداف السلوكية|الأهداف الخاصة|نتاجات التعلم)\\s*:?\\s*$"
        "|يتوقع من (?:المتدرب|الطالب|المتعلم|الدارس)|^بعد (?:نهاية|انتهاء|دراسة) (?:هذا )?(?:الدرس|الوحدة)",
        None,
    ),
    Pattern(
        "activities",
        re.compile(f"^(?:الأنشطة|الانشطة|أنشطة|انشطة|التطبيقات|نشاط|تطبيق){S}*:?{S}*\\Z"),
        re.compile("^(?:نشاط|تطبيق)(?![ء-ي])"),
        False,
        "^(?:الأنشطة|الانشطة|أنشطة|انشطة|التطبيقات|نشاط|تطبيق)\\s*:?\\s*$",
        "^(?:نشاط|تطبيق)(?![ء-ي])",
    ),
    Pattern(
        "assessments",
        re.compile(f"^(?:التقويم|تقويم|التقييم|أسئلة|اسئلة|الأسئلة|الاسئلة|اختبار|الاختبار){S}*:?{S}*\\Z"),
        re.compile("^(?:التقويم|تقويم|أسئلة|اسئلة|اختبار)(?![ء-ي])"),
        False,
        "^(?:التقويم|تقويم|التقييم|أسئلة|اسئلة|الأسئلة|الاسئلة|اختبار|الاختبار)\\s*:?\\s*$",
        "^(?:التقويم|تقويم|أسئلة|اسئلة|اختبار)(?![ء-ي])",
    ),
    Pattern(
        "references",
        re.compile(f"^(?:المراجع|مراجع|مصادر|المصادر|مصادر التعلم){S}*:?{S}*\\Z"),
        None,
        False,
        "^(?:المراجع|مراجع|مصادر|المصادر|مصادر التعلم)\\s*:?\\s*$",
        None,
    ),
]

OBJECTIVE_LINE_SOURCE = "^(?:[\\d٠-٩]{1,2}\\s*[\\.\\-–)][\\s.\\-–)]*)?(?:(?:أن|ان)\\s+\\S|[يت][ء-ي]{2,}(?![ء-ي]))"
OBJECTIVE_LINE = re.compile(f"^(?:{_NUM}{{1,2}}{S}*[.\\-–)]{_SEP}*)?(?:(?:أن|ان){S}+{NS}|[يت][ء-ي]{{2,}}(?![ء-ي]))")
OBJECTIVE_LINE_LOOSE_SOURCE = "^[\\d٠-٩]{1,2}(?:\\s|[\\.\\-–)]).*(?:^|\\s)(?:أن|ان)\\s+[يت][ء-ي]{2,}"
OBJECTIVE_LINE_LOOSE = re.compile(f"^{_NUM}{{1,2}}(?:{S}|[.\\-–)]){DOT}*(?:^|{S})(?:أن|ان){S}+[يت][ء-ي]{{2,}}")


def match_pattern(line: str, type_: str, kind: str = "heading") -> Pattern | None:
    for pattern in STRUCTURE_PATTERNS:
        if pattern.type == type_ and pattern.matches(line, kind):
            return pattern
    return None


def new_lesson(title: str, page: int, implicit: bool = False) -> dict:
    return {
        "title": title,
        "page": page,
        "implicit": implicit,
        "objectives": [],
        "activities": [],
        "assessments": [],
        "references": [],
    }


def _lesson_is_empty(lesson: dict) -> bool:
    return all(not lesson[t] for t in SECTION_TYPES)


_NOT_TITLE_CHAR = re.compile(f"[^ء-ي{D}٠-٩]")


def _title_key(title: str) -> str:
    return "".join(sorted(_NOT_TITLE_CHAR.sub("", unify_hamza(strip_tashkeel(title)))))


_TRAILING_COLON = re.compile(f"{S}*:{S}*\\Z")
_LESSON_WORD = re.compile("^(?:الدرس|درس)")
_ENDS_WITH_COLON = re.compile(f"[:：]{S}*\\Z")
_STARTS_NUMBERED = re.compile(f"^{_NUM}{{1,2}}{S}*[.\\-–)]")
_AN_LINE = re.compile(f"^(?:أن|ان){S}")

NO_UNITS = 'لم تُكتشف وحدات؛ عومل الملف كله كوحدة واحدة بعنوان "المستند".'
NO_UNITS_NOR_LESSONS = 'لم تُكتشف وحدات ولا دروس؛ عومل الملف كله كوحدة واحدة بعنوان "المستند".'


def structure(doc: dict) -> dict:
    """Harak 1's ``structure``: units, lessons and their sections from the document's lines."""
    warnings: list[dict] = []
    units: list[dict] = []
    orphan: list[str] = []
    state = {"unit": None, "lesson": None, "section": None}

    lines = []
    for page in doc["pages"]:
        for raw in page["text"].split("\n"):
            line = js_trim(raw)
            if line:
                lines.append((line, page["index"]))

    def open_unit(title, page, implicit=False):
        state["unit"] = {"title": title, "pageStart": page, "implicit": implicit, "lessons": []}
        units.append(state["unit"])
        state["lesson"] = None
        state["section"] = None

    def open_lesson(title, page, implicit=False):
        lesson = state["lesson"]
        # An empty implicit lesson (opened by an earlier section heading) is replaced and keeps its open section.
        if lesson and lesson["implicit"] and _lesson_is_empty(lesson):
            state["unit"]["lessons"].pop()
        else:
            state["section"] = None
        state["lesson"] = new_lesson(title, page, implicit)
        state["unit"]["lessons"].append(state["lesson"])

    def ensure_unit(page):
        if not state["unit"]:
            open_unit("المستند", page, True)
            warnings.append({"code": "NO_UNITS_DETECTED", "message": NO_UNITS})

    def ensure_lesson(page):
        if not state["lesson"]:
            open_lesson(state["unit"]["title"], page, True)

    for line, page in lines:
        if match_pattern(line, "unit"):
            open_unit(_TRAILING_COLON.sub("", line, count=1), page)
            continue

        lesson_pattern = match_pattern(line, "lesson")
        unit = state["unit"]
        has_explicit_lessons = bool(unit) and any(
            not each["implicit"] and not each.get("numbered") for each in unit["lessons"]
        )
        if lesson_pattern and (
            not lesson_pattern.numbered
            or (unit and state["section"] is None and js_len(line) < 80 and not has_explicit_lessons)
        ):
            ensure_unit(page)
            title = _TRAILING_COLON.sub("", line, count=1)
            lesson = state["lesson"]
            # Repeating the current lesson's title (at the start of its content, say) opens no new lesson.
            if lesson and not lesson["implicit"] and _title_key(title) == _title_key(lesson["title"]):
                if _LESSON_WORD.search(title) and not _LESSON_WORD.search(lesson["title"]):
                    lesson["title"] = title
                state["section"] = None
                continue
            open_lesson(title, page)
            state["lesson"]["numbered"] = lesson_pattern.numbered
            continue

        section_type = next((t for t in SECTION_TYPES if match_pattern(line, t)), None)
        if section_type:
            ensure_unit(page)
            ensure_lesson(page)
            state["section"] = section_type
            continue

        if not state["unit"]:
            orphan.append(line)
            continue
        ensure_lesson(page)
        lesson = state["lesson"]

        # A line that is itself an activity or an assessment is filed there, even outside its section.
        item_type = next((t for t in ("activities", "assessments") if match_pattern(line, t, "item")), None)
        if item_type:
            lesson[item_type].append({"text": line, "page": page})
            state["section"] = item_type
            continue

        section = state["section"]
        if section == "objectives":
            last = lesson["objectives"][-1] if lesson["objectives"] else None
            if OBJECTIVE_LINE.search(line) or OBJECTIVE_LINE_LOOSE.search(line):
                lesson["objectives"].append({"text": line, "page": page})
            elif _ENDS_WITH_COLON.search(line) or _STARTS_NUMBERED.search(line) or not last or js_len(line) > 120:
                state["section"] = None
                orphan.append(line)
            else:
                last["text"] += " " + line  # a wrapped line continues the previous objective
        elif section:
            lesson[section].append({"text": line, "page": page})
        else:
            orphan.append(line)

    if not units:
        warnings.append({"code": "NO_UNITS_DETECTED", "message": NO_UNITS_NOR_LESSONS})
        lesson = new_lesson("المستند", 0, True)
        for line, page in lines:
            if _AN_LINE.search(line):
                lesson["objectives"].append({"text": line, "page": page})
        return {
            "units": [{"title": "المستند", "pageStart": 0, "implicit": True, "lessons": [lesson]}],
            "orphanText": "",
            "warnings": warnings,
        }

    return {"units": units, "orphanText": "\n".join(orphan), "warnings": warnings}


def summarize(struct: dict, bloom: list[dict], doc: dict | None) -> tuple[list[dict], dict]:
    """Completeness of every lesson and the document statistics."""
    completeness = []
    lessons = objectives = 0
    for ui, unit in enumerate(struct["units"]):
        for li, lesson in enumerate(unit["lessons"]):
            lessons += 1
            objectives += len(lesson["objectives"])
            completeness.append(
                {
                    "lessonRef": {"unit": ui, "lesson": li, "unitTitle": unit["title"], "title": lesson["title"]},
                    "hasObjectives": bool(lesson["objectives"]),
                    "hasActivities": bool(lesson["activities"]),
                    "hasAssessment": bool(lesson["assessments"]),
                    "hasReferences": bool(lesson["references"]),
                }
            )

    dist = {level["name"]: 0 for level in data.BLOOM_LEVELS}
    dist["غير محدد"] = 0
    for b in bloom:
        key = (
            b["level"]
            if b["domain"] == "cognitive"
            else (data.DOMAIN_NAMES[b["domain"]] if b["domain"] else "غير محدد")
        )
        dist[key] = dist.get(key, 0) + 1
    total = len(bloom) or 1
    distribution = {key: js_round((count / total) * 1000) / 10 for key, count in dist.items()}

    domains = {"cognitive": 0, "affective": 0, "psychomotor": 0, "none": 0}
    for b in bloom:
        domains[b["domain"] or "none"] += 1
    words = sum(count_words(page["text"]) for page in doc["pages"]) if doc else 0
    stats = {
        "units": len(struct["units"]),
        "lessons": lessons,
        "objectives": objectives,
        "words": words,
        "pages": doc["meta"]["pageCount"] if doc else 0,
        "bloomDistribution": distribution,
        "bloomCounts": dist,
        "domainCounts": domains,
    }
    return completeness, stats
