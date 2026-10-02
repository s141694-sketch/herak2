"""Builders shared by program tests. Must be called inside an organization context."""

from apps.accounts.models import Membership, Role, User
from apps.competencies import services as competency_services
from apps.programs import services
from apps.structures import services as structure_services

FOUR_LEVELS = [
    {"name_ar": "برنامج", "name_en": "Program"},
    {"name_ar": "وحدة", "name_en": "Module"},
    {"name_ar": "درس", "name_en": "Lesson"},
    {"name_ar": "نشاط", "name_en": "Activity"},
]


def member(email: str, role: str = Role.AUTHOR) -> User:
    user = User.objects.create_user(email=email, password="x" * 12, full_name=email.split("@")[0])
    Membership.objects.create(user=user, role=role)
    return user


def published_template(actor, levels=FOUR_LEVELS):
    version = structure_services.create_template(name="قالب", actor=actor, levels=levels).versions.get()
    return structure_services.publish_version(version, actor=actor)


def published_framework(actor, codes=("C-1", "C-2", "C-3")):
    version = competency_services.create_framework(name="إطار", actor=actor).versions.get()
    for code in codes:
        competency_services.add_competency(version, code=code, title=f"كفاية {code}")
    return competency_services.publish_version(version, actor=actor)


def program(owner, *, title="برنامج السلامة", template=None, framework=None, targets=None):
    template = template or published_template(owner)
    framework = framework or published_framework(owner)
    if targets is None:
        targets = list(framework.competencies.values_list("pk", flat=True)[:2])
    return services.create_program(
        title=title,
        target_role="فني سلامة",
        owner=owner,
        template_version=template,
        framework_version=framework,
        target_ids=targets,
    )
