import pytest

from apps.accounts.models import Organization, Role
from apps.core.locking import VersionLocked
from apps.programs import lifecycle, services
from apps.programs.models import AlignmentLink, ProgramVersion
from apps.tenancy.context import organization_context

from .factories import member, program, published_framework

pytestmark = pytest.mark.django_db
S = ProgramVersion.Status
K = AlignmentLink.Kind


@pytest.fixture
def ctx():
    org = Organization.objects.create(name="A", slug="a")
    with organization_context(org):
        owner = member("owner@example.com", Role.AUTHOR)
        version = program(owner).versions.get()
        root = services.add_node(version, title="البرنامج", actor=owner)
        module = services.add_node(version, title="الوحدة", parent=root, actor=owner)
        other_module = services.add_node(version, title="وحدة أخرى", parent=root, actor=owner)
        blocks = {
            "program_objective": services.add_block(version, node=root, type="objective", actor=owner),
            "objective": services.add_block(version, node=module, type="objective", actor=owner),
            "sibling_objective": services.add_block(version, node=other_module, type="objective", actor=owner),
            "assessment": services.add_block(version, node=module, type="assessment", actor=owner),
            "content": services.add_block(version, node=module, type="content", actor=owner),
        }
        competency = version.framework_version.competencies.first()
        yield owner, version, blocks, competency


def test_the_three_kinds_of_links(ctx):
    owner, version, b, competency = ctx
    a = services.link(version, kind=K.OBJECTIVE_COMPETENCY, source=b["objective"], competency=competency, actor=owner)
    c = services.link(version, kind=K.ASSESSMENT_OBJECTIVE, source=b["assessment"], target=b["objective"], actor=owner)
    d = services.link(
        version, kind=K.OBJECTIVE_PARENT, source=b["objective"], target=b["program_objective"], actor=owner
    )
    assert {link.kind for link in version.alignment_links.all()} == {
        K.OBJECTIVE_COMPETENCY,
        K.ASSESSMENT_OBJECTIVE,
        K.OBJECTIVE_PARENT,
    }
    assert (a.target_competency, c.target_block, d.target_block) == (competency, b["objective"], b["program_objective"])


@pytest.mark.parametrize(
    "kind,source,target",
    [
        (K.OBJECTIVE_COMPETENCY, "content", None),
        (K.ASSESSMENT_OBJECTIVE, "objective", "objective"),
        (K.ASSESSMENT_OBJECTIVE, "assessment", "content"),
        (K.OBJECTIVE_PARENT, "objective", "sibling_objective"),
        (K.OBJECTIVE_PARENT, "program_objective", "objective"),
        (K.OBJECTIVE_PARENT, "objective", "objective"),
    ],
)
def test_links_must_connect_the_right_block_types(ctx, kind, source, target):
    owner, version, b, competency = ctx
    with pytest.raises(services.ProgramError) as excinfo:
        services.link(
            version,
            kind=kind,
            source=b[source],
            target=b[target] if target else None,
            competency=competency if kind == K.OBJECTIVE_COMPETENCY else None,
            actor=owner,
        )
    assert excinfo.value.get_codes() == "link_invalid"


def test_competency_must_come_from_the_version_framework(ctx):
    owner, version, b, _ = ctx
    foreign = published_framework(owner, codes=("Z-9",)).competencies.get()
    with pytest.raises(services.ProgramError):
        services.link(version, kind=K.OBJECTIVE_COMPETENCY, source=b["objective"], competency=foreign, actor=owner)


def test_duplicate_links_are_refused(ctx):
    owner, version, b, competency = ctx
    services.link(version, kind=K.OBJECTIVE_COMPETENCY, source=b["objective"], competency=competency, actor=owner)
    with pytest.raises(services.ProgramError) as excinfo:
        services.link(version, kind=K.OBJECTIVE_COMPETENCY, source=b["objective"], competency=competency, actor=owner)
    assert excinfo.value.get_codes() == "link_exists"


def test_links_are_copied_to_a_new_version_by_key_and_locked_with_their_version(ctx):
    owner, v1, b, competency = ctx
    services.link(v1, kind=K.OBJECTIVE_COMPETENCY, source=b["objective"], competency=competency, actor=owner)
    services.link(v1, kind=K.ASSESSMENT_OBJECTIVE, source=b["assessment"], target=b["objective"], actor=owner)
    lifecycle.transition(v1, S.SUBMITTED, actor=owner)
    with pytest.raises(VersionLocked):
        services.unlink(v1.alignment_links.first(), actor=owner)
    lifecycle.transition(v1, S.WITHDRAWN, actor=owner)
    v2 = v1.program.versions.get(number=2)

    def keys(version):
        return {
            (
                link.kind,
                link.source.block_key,
                link.target_block.block_key if link.target_block else None,
                link.target_competency.competency_key if link.target_competency else None,
            )
            for link in version.alignment_links.select_related("source", "target_block", "target_competency")
        }

    assert keys(v2) == keys(v1)
    assert all(link.source.version_id == v2.pk for link in v2.alignment_links.select_related("source"))
    services.unlink(v2.alignment_links.first(), actor=owner)
    assert v1.alignment_links.count() == 2
