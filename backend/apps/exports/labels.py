"""What an exported file says besides the program's own content, in Arabic and in English. The files are written
in Arabic (D77): a program carries no language of its own, and Harak's programs are written in Arabic."""

LANGUAGE = "ar"

TEXTS: dict[str, dict[str, str]] = {
    "ar": {
        "objective": "الأهداف",
        "content": "المحتوى",
        "activity": "الأنشطة",
        "assessment": "التقويم",
        "reference": "المراجع",
        "target_role": "الدور الوظيفي المستهدف: {role}",
        "version": "النسخة {number}",
        "approved": "اعتمدها {name} في {date}",
        "page": "صفحة",
    },
    "en": {
        "objective": "Objectives",
        "content": "Content",
        "activity": "Activities",
        "assessment": "Assessment",
        "reference": "References",
        "target_role": "Target role: {role}",
        "version": "Version {number}",
        "approved": "Approved by {name} on {date}",
        "page": "Page",
    },
}


def label(key: str, **values) -> str:
    return TEXTS[LANGUAGE][key].format(**values)
