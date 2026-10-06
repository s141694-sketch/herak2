"""What a notification says by email, in Arabic and in English (the platform shows its own translations).

An email carries both languages, Arabic first: the member's interface language lives in their browser, not on
the server. Links lead into the platform, which asks for a sign-in (spec 6.5).
"""

from django.conf import settings
from django.utils import timezone

from .models import Notification

E = Notification.Event

TEXTS: dict[str, dict[str, tuple[str, str]]] = {
    E.TASK_ASSIGNED: {
        "ar": (
            "مطلوب منك: {stage} — {program}",
            "وصلت النسخة {number} من «{program}» إلى مرحلة «{stage}». الموعد: {due}.",
        ),
        "en": (
            "Review requested: {stage} — {program}",
            "Review requested: version {number} of “{program}” reached the stage “{stage}”. Due: {due}.",
        ),
    },
    E.VERSION_RETURNED: {
        "ar": ("أُعيدت للتعديل: {program}", "أُعيدت النسخة {number} من «{program}» من مرحلة «{stage}». الملاحظة: {note}"),
        "en": (
            "Returned for changes: {program}",
            "Version {number} of “{program}” was returned at the stage “{stage}”. Note: {note}",
        ),
    },
    E.VERSION_APPROVED: {
        "ar": ("اعتُمدت: {program}", "اعتُمدت النسخة {number} من «{program}»، وأصبحت مقفلة."),
        "en": ("Approved: {program}", "Version {number} of “{program}” was approved and is now locked."),
    },
    E.TASK_DUE_SOON: {
        "ar": ("تذكير: {stage} — {program}", "يحين موعد مرحلة «{stage}» للنسخة {number} من «{program}» في {due}."),
        "en": ("Reminder: {stage} — {program}", "The stage “{stage}” of version {number} of “{program}” is due {due}."),
    },
    E.TASK_DUE: {
        "ar": ("حان الموعد: {stage} — {program}", "حان موعد مرحلة «{stage}» للنسخة {number} من «{program}» ({due})."),
        "en": (
            "Due now: {stage} — {program}",
            "The stage “{stage}” of version {number} of “{program}” is due now ({due}).",
        ),
    },
    E.TASK_OVERDUE: {
        "ar": (
            "تصعيد: تأخرت مرحلة {stage} — {program}",
            "تأخرت مرحلة «{stage}» للنسخة {number} من «{program}» عن موعدها ({due}). المسؤول: {responsible}.",
        ),
        "en": (
            "Escalation: {stage} is late — {program}",
            "The stage “{stage}” of version {number} of “{program}” is past its due time ({due}). "
            "Responsible: {responsible}.",
        ),
    },
}

TEXTS[E.EXPORT_FAILED] = {
    "ar": (
        "تعذّر تصدير: {program}",
        "تعذّر توليد ملفي Word وPDF للنسخة المعتمدة {number} من «{program}» بعد عدة محاولات. الاعتماد قائم، "
        "ويمكن إعادة المحاولة من صفحة النسخة.",
    ),
    "en": (
        "Export failed: {program}",
        "The Word and PDF files of approved version {number} of “{program}” could not be made after several "
        "attempts. The approval stands; try again from the version's page.",
    ),
}

DIGEST = {
    "ar": ("ملخص حراك اليومي", "ما وصلك منذ آخر ملخص:"),
    "en": ("Harak daily digest", "What reached you since the last digest:"),
}


def link(notification: Notification) -> str:
    base = settings.APP_URL.rstrip("/")
    return f"{base}/program-versions/{notification.version_id}" if notification.version_id else f"{base}/tasks"


def _fields(notification: Notification) -> dict:
    p = notification.params
    due = p.get("due_at")
    due_text = timezone.localtime(timezone.datetime.fromisoformat(due)).strftime("%Y-%m-%d %H:%M") if due else "—"
    return {
        "program": p.get("program", ""),
        "number": p.get("number", ""),
        "stage": p.get("stage_name", ""),
        "due": due_text,
        "note": p.get("note", ""),
        "responsible": p.get("responsible", ""),
    }


def subject(notification: Notification) -> str:
    fields = _fields(notification)
    text = " | ".join(TEXTS[notification.event][lang][0].format(**fields) for lang in ("ar", "en"))
    return " ".join(text.split())  # a header is one line: a title with a line break must not lose the email


def lines(notification: Notification, lang: str) -> str:
    return TEXTS[notification.event][lang][1].format(**_fields(notification))


def body(notification: Notification) -> str:
    return "\n\n".join([lines(notification, "ar"), lines(notification, "en"), link(notification)])


def digest_email(notifications: list[Notification]) -> tuple[str, str]:
    title = " | ".join(DIGEST[lang][0] for lang in ("ar", "en"))
    parts = []
    for lang in ("ar", "en"):
        parts.append(DIGEST[lang][1])
        parts.extend(f"- {lines(n, lang)}\n  {link(n)}" for n in notifications)
    return title, "\n\n".join(parts)
