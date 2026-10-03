"""Objective wording quality: the six components, the common errors and the knowledge dimension (Harak 1 B6)."""

import re

from . import data
from .bloom import lookup_verb, objectives_of
from .jsre import NS, WS, D, S, js_trim, split_ws
from .text import normalize_arabic, strip_tashkeel, unify_hamza

#: Harak 1's JavaScript sources of the patterns below, kept to detect changes on Harak 1's side.
JS_SOURCES = {
    "learner": (
        "(?:المتدرب|المتدربة|المتدربون|المتدربين|الطالب|الطالبة|الطلاب|الطلبة|المتعلم|المتعلمة|"
        "المتعلمون|المتعلمين|الدارس|الدارسون|التلميذ|التلاميذ|الضابط|الجندي)"
    ),
    "condition": (
        "(?:باستخدام|باستعمال|بدون الرجوع|دون الرجوع|دون مساعدة|بعد (?:قراءة|مشاهدة|عرض|دراسة|"
        "الاطلاع)|في ضوء|على ضوء|حسب|وفق|وفقًا|من خلال|اعتمادًا على|معتمدًا على|بالاعتماد على|"
        "بمساعدة|بالرجوع إلى|عند (?:إعطائه|تزويده|عرض)|إذا أُعطي|معطًى)"
    ),
    "criterion": (
        "(?:بدقة|بدون أخطاء|بلا أخطاء|دون أخطاء|بنسبة|على الأقل|على الأكثر|خلال (?:\\S+ )?(?:دقائق|"
        "دقيقة|ساعة|ساعات)|في (?:\\S+ )?(?:دقائق|دقيقة)|بشكل (?:صحيح|جيد|سليم|كامل)|صحيحًا|صحيحة|"
        "وافيًا|وافية|مميزًا|كاملًا|بطلاقة|مقبولًا|بإتقان|بكفاءة|بنجاح|100 ?%|\\d+ ?%|[٠-٩]+ ?%)"
    ),
    "teacherSubject": (
        "^(?:[\\d٠-٩]{1,2}\\s*[\\.\\-–)][\\s.\\-–)]*)?(?:أن|ان)\\s+\\S+\\s+(?:الموجه|المعلم|المدرب|المدرس|"
        "المحاضر|المعلمة|المدربة)(?![ء-ي])"
    ),
    "process": "(?:يعرف|يتعلم|يتعرف على|يعلم)\\s+(?:\\S+\\s+)?(?:كيفية|كيف|طريقة)",
    "topic": ("^(?:[\\d٠-٩]{1,2}\\s*[\\.\\-–)][\\s.\\-–)]*)?(?:أن|ان)\\s+(?:يدرس|يتناول|يتعرض|يأخذ|يقرأ عن|يتطرق)"),
}

_NUMBERING = f"(?:[{D}٠-٩]{{1,2}}{S}*[.\\-–)][{WS}.\\-–)]*)"

LEARNER = re.compile(JS_SOURCES["learner"])
CONDITION = re.compile(JS_SOURCES["condition"])
CRITERION = re.compile(
    "(?:بدقة|بدون أخطاء|بلا أخطاء|دون أخطاء|بنسبة|على الأقل|على الأكثر"
    f"|خلال (?:{NS}+ )?(?:دقائق|دقيقة|ساعة|ساعات)|في (?:{NS}+ )?(?:دقائق|دقيقة)"
    "|بشكل (?:صحيح|جيد|سليم|كامل)|صحيحًا|صحيحة|وافيًا|وافية|مميزًا|كاملًا|بطلاقة|مقبولًا|بإتقان|بكفاءة|بنجاح"
    f"|100 ?%|[{D}]+ ?%|[٠-٩]+ ?%)"
)
TEACHER_SUBJECT = re.compile(
    f"^{_NUMBERING}?(?:أن|ان){S}+{NS}+{S}+(?:الموجه|المعلم|المدرب|المدرس|المحاضر|المعلمة|المدربة)(?![ء-ي])"
)
PROCESS = re.compile(f"(?:يعرف|يتعلم|يتعرف على|يعلم){S}+(?:{NS}+{S}+)?(?:كيفية|كيف|طريقة)")
TOPIC = re.compile(f"^{_NUMBERING}?(?:أن|ان){S}+(?:يدرس|يتناول|يتعرض|يأخذ|يقرأ عن|يتطرق)")

_LEADING_NUMBER = re.compile(f"^[{D}٠-٩]{{1,2}}{S}*[.\\-–)][{WS}.\\-–)]*")
_AN_PREFIX = re.compile(f"^(?:أن|ان){S}")
_AN_AND_VERB = re.compile(f"^(?:أن|ان){S}+{NS}+{S}*")
_PUNCT = re.compile("[.،:]")
_VERB_TOKEN = re.compile("^(?:و|ثم)?[يت][ء-ي]{2,}\\Z")
_CONJUNCTION = re.compile("^(?:و|ثم)")
_THEN_VERB = re.compile(f"{S}ثم{S}+[يت][ء-ي]{{2,}}")
_TA = re.compile("^ت")


def objective_body(text: str) -> str:
    return js_trim(_LEADING_NUMBER.sub("", strip_tashkeel(text), count=1))


def guess_dimension(text: str) -> dict | None:
    """Knowledge dimension by keywords; a low-confidence guess by design."""
    t = normalize_arabic(text)
    best, best_hits = None, 0
    for dimension in data.DIMENSIONS:
        hits = sum(1 for keyword in dimension["keywords"] if normalize_arabic(keyword) in t)
        if hits > best_hits:
            best, best_hits = dimension, hits
    return {"id": best["id"], "name": best["name"], "confidence": "low"} if best else None


def check_objective(text: str, classified: dict) -> dict:
    """Components present, error codes and score of one objective, given its Bloom classification."""
    verb = classified.get("verb") or ""
    domain = classified.get("domain")
    body = objective_body(text)
    words = split_ws(body)
    verb_norm = _TA.sub("ي", unify_hamza(strip_tashkeel(verb)), count=1)
    learner = LEARNER.search(body)
    after_learner = js_trim(body[learner.end() :]) if learner else _AN_AND_VERB.sub("", body, count=1)
    components = {
        "an": bool(_AN_PREFIX.search(body)),
        "verb": bool(verb) and bool(domain),
        "learner": bool(learner),
        "content": len([w for w in split_ws(_PUNCT.sub("", after_learner)) if w]) >= 2,
        "condition": bool(CONDITION.search(body)),
        "criterion": bool(CRITERION.search(body)),
    }
    errors = []
    plain = strip_tashkeel(text)
    if TEACHER_SUBJECT.search(plain):
        errors.append("teacher-activity")
    if PROCESS.search(body):
        errors.append("process")
    if TOPIC.search(plain):
        errors.append("topic")
    verb_tokens = [w for w in words if _VERB_TOKEN.search(w) and lookup_verb(_CONJUNCTION.sub("", w, count=1))]
    if _THEN_VERB.search(body):
        errors.append("multi")
    elif len([w for w in verb_tokens if w.startswith("و")]) >= 1 and len(verb_tokens) >= 2:
        errors.append("multi")
    if verb_norm in data.UNMEASURABLE_VERBS or (verb and not domain):
        errors.append("unmeasurable")
    return {
        "components": components,
        "score": sum(1 for present in components.values() if present),
        "errors": errors,
        "dimension": guess_dimension(body) if domain == "cognitive" else None,
    }


def check_objectives(struct: dict, bloom: list[dict]) -> list[dict]:
    by_ref = {(b["objectiveRef"]["unit"], b["objectiveRef"]["lesson"], b["objectiveRef"]["index"]): b for b in bloom}
    out = []
    for ref, text in objectives_of(struct):
        classified = by_ref.get((ref["unit"], ref["lesson"], ref["index"]), {})
        out.append({"objectiveRef": ref, **check_objective(text, classified)})
    return out


def taxonomy_matrix(bloom: list[dict], quality: list[dict]) -> dict:
    """Bloom level x knowledge dimension counts for cognitive objectives (keys as strings, like Harak 1's JSON)."""
    dims = [d["id"] for d in data.DIMENSIONS] + ["none"]
    matrix = {str(level["id"]): dict.fromkeys(dims, 0) for level in data.BLOOM_LEVELS}
    for i, q in enumerate(quality):
        b = bloom[i] if i < len(bloom) else None
        if not b or b["domain"] != "cognitive":
            continue
        matrix[str(b["levelId"])][q["dimension"]["id"] if q["dimension"] else "none"] += 1
    return {"dims": dims, "matrix": matrix}
