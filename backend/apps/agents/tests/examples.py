"""Inputs and hand-written answers the agent tests replay (see recordings.py)."""

from apps.agents import alignment, classification, drafting

ISOLATION = alignment.Competency("EL-01", "عزل الدوائر الكهربائية وإقفالها قبل الصيانة")
FIRST_AID = alignment.Competency("FA-01", "تقديم الإسعافات الأولية للمصابين")


def EXAMPLES():
    return [
        (
            classification.SPEC,
            classification.payload("أن يتأمل المتدرب تجربته في الموقع"),
            {
                "domain": "affective",
                "level_id": 3,
                "verb": "يتأمل",
                "confidence": "medium",
                "explanation": "التأمل في الخبرة سلوك وجداني يقيّم فيه المتدرب تجربته.",
            },
        ),
        (
            classification.SPEC,
            classification.payload("أن يحدد المتدرب مواقع مخارج الطوارئ على المخطط"),
            {
                "domain": "cognitive",
                "level_id": 1,
                "verb": "يحدد",
                "confidence": "high",
                "explanation": "تحديد المواقع على المخطط استرجاع وتعرّف، أي مستوى التذكر.",
            },
        ),
        (
            classification.SPEC,
            classification.payload("معرفة أنواع الصمامات"),
            {
                "domain": "unclear",
                "level_id": 0,
                "verb": "",
                "confidence": "low",
                "explanation": "الهدف بلا سلوك ملاحظ؛ يحتاج فعلًا قابلًا للقياس.",
            },
        ),
        (
            alignment.CHECK,
            alignment.check_payload("أن يطبق المتدرب إجراء العزل والإقفال على لوحة كهربائية", ISOLATION),
            {"verdict": "aligned", "confidence": "high", "explanation": "تطبيق العزل والإقفال هو جوهر الكفاية."},
        ),
        (
            alignment.CHECK,
            alignment.check_payload("أن يعدد المتدرب أنواع طفايات الحريق", ISOLATION),
            {"verdict": "misaligned", "confidence": "high", "explanation": "طفايات الحريق لا تتصل بعزل الدوائر."},
        ),
        (
            alignment.SUGGEST,
            alignment.suggest_payload(FIRST_AID),
            {
                "objective": "أن يقدم المتدرب الإسعافات الأولية لمصاب بنزيف وفق دليل الإسعاف خلال دقيقتين",
                "confidence": "medium",
                "explanation": "يجعل الكفاية سلوكًا ملاحظًا بشرط ومعيار.",
            },
        ),
        (
            drafting.REWRITE,
            drafting.rewrite_payload("أن يفهم المتدرب أهمية الإسعافات", [FIRST_AID]),
            {
                "objective": "أن يقدم المتدرب الإسعافات الأولية لمصاب بنزيف وفق دليل الإسعاف خلال دقيقتين",
                "confidence": "medium",
                "explanation": "استبدلت «يفهم» بفعل ملاحظ وأضفت شرطًا ومعيارًا مع بقاء موضوع الإسعافات.",
            },
        ),
        (
            drafting.OUTLINE,
            drafting.outline_payload("برنامج السلامة", "فني", ["وحدة", "درس"], [FIRST_AID, ISOLATION]),
            {
                "nodes": [
                    {"ref": "n1", "parent": "", "title": "السلامة في موقع العمل"},
                    {"ref": "n2", "parent": "n1", "title": "الإسعافات الأولية"},
                    {"ref": "n3", "parent": "n1", "title": "عزل الدوائر الكهربائية"},
                ],
                "objectives": [
                    {
                        "node": "n2",
                        "competency": "FA-01",
                        "text": "أن يقدم المتدرب الإسعافات الأولية لمصاب بنزيف وفق دليل الإسعاف خلال دقيقتين",
                    },
                    {
                        "node": "n3",
                        "competency": "EL-01",
                        "text": "أن يطبق المتدرب إجراء العزل والإقفال على لوحة كهربائية",
                    },
                ],
                "confidence": "medium",
                "explanation": "وحدة واحدة بدرسين، لكل كفاية درس وهدف.",
            },
        ),
    ]
