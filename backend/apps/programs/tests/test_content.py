import pytest
from django.db import connection, transaction
from django.db.utils import DatabaseError

from apps.accounts.models import Organization, Role
from apps.core.locking import VersionLocked
from apps.programs import content, lifecycle, services
from apps.programs.models import Block, Node, ProgramVersion
from apps.tenancy.context import organization_context

from .factories import member, program

pytestmark = pytest.mark.django_db
S = ProgramVersion.Status


def doc(*texts):
    return {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": t}]} for t in texts]}


@pytest.fixture
def ctx():
    org = Organization.objects.create(name="A", slug="a")
    with organization_context(org):
        owner = member("owner@example.com", Role.AUTHOR)
        version = program(owner).versions.get()
        yield owner, version


def four_level_tree(version, actor):
    root = services.add_node(version, title="برنامج السلامة", actor=actor)
    module = services.add_node(version, title="الوحدة الأولى", parent=root, actor=actor)
    lesson = services.add_node(version, title="الدرس الأول", parent=module, actor=actor)
    activity = services.add_node(version, title="النشاط", parent=lesson, actor=actor)
    return root, module, lesson, activity


def test_nodes_follow_the_template_levels(ctx):
    owner, version = ctx
    root, module, lesson, activity = four_level_tree(version, owner)
    assert [n.level for n in (root, module, lesson, activity)] == [0, 1, 2, 3]
    assert root.node_key != module.node_key
    with pytest.raises(services.ProgramError) as excinfo:
        services.add_node(version, title="أعمق من القالب", parent=activity, actor=owner)
    assert excinfo.value.get_codes() == "node_level_exceeds_template"


def test_siblings_get_increasing_order(ctx):
    owner, version = ctx
    root = services.add_node(version, title="r", actor=owner)
    first = services.add_node(version, title="1", parent=root, actor=owner)
    second = services.add_node(version, title="2", parent=root, actor=owner)
    assert (first.order, second.order) == (1, 2)


def test_parent_must_belong_to_the_same_version(ctx):
    owner, version = ctx
    other = program(owner, title="آخر").versions.get()
    foreign_parent = services.add_node(other, title="x", actor=owner)
    with pytest.raises(services.ProgramError) as excinfo:
        services.add_node(version, title="y", parent=foreign_parent, actor=owner)
    assert excinfo.value.get_codes() == "node_parent_invalid"


def test_blocks_carry_type_content_and_a_stable_hash(ctx):
    owner, version = ctx
    root, module, *_ = four_level_tree(version, owner)
    block = services.add_block(version, node=module, type="objective", content=doc("يصف المتدرب الإجراء"), actor=owner)
    assert block.block_key and block.order == 1
    assert block.content_hash == content.content_hash(doc("يصف المتدرب الإجراء"))
    reordered = {"content": doc("يصف المتدرب الإجراء")["content"], "type": "doc"}
    assert content.content_hash(reordered) == block.content_hash, "key order does not change the hash"

    services.update_block(block, content=doc("يطبّق المتدرب الإجراء"), actor=owner)
    block.refresh_from_db()
    assert block.content_hash == content.content_hash(doc("يطبّق المتدرب الإجراء"))


@pytest.mark.parametrize(
    "bad",
    [
        {"type": "paragraph"},
        {"type": "doc", "content": [{"type": "script", "content": []}]},
        {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": 5}]}]},
        {
            "type": "doc",
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "x", "marks": [{"type": "onclick"}]}]}
            ],
        },
        {"type": "doc", "content": [{"type": "heading", "attrs": {"level": 9}, "content": []}]},
        {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "x",
                            "marks": [{"type": "link", "attrs": {"href": "javascript:alert(1)"}}],
                        }
                    ],
                }
            ],
        },
        "not a dict",
    ],
)
def test_invalid_content_is_rejected(ctx, bad):
    owner, version = ctx
    root = services.add_node(version, title="r", actor=owner)
    with pytest.raises(services.ProgramError) as excinfo:
        services.add_block(version, node=root, type="content", content=bad, actor=owner)
    assert excinfo.value.get_codes() == "content_invalid"


def test_oversized_content_is_rejected(ctx, settings):
    owner, version = ctx
    settings.BLOCK_CONTENT_MAX_BYTES = 200
    root = services.add_node(version, title="r", actor=owner)
    with pytest.raises(services.ProgramError):
        services.add_block(version, node=root, type="content", content=doc("أ" * 200), actor=owner)


def test_moving_a_subtree_updates_levels_and_refuses_cycles_and_overflow(ctx):
    owner, version = ctx
    root, module, lesson, activity = four_level_tree(version, owner)
    other_module = services.add_node(version, title="الوحدة الثانية", parent=root, actor=owner)

    services.move_node(lesson, parent=other_module, order=1, actor=owner)
    lesson.refresh_from_db()
    activity.refresh_from_db()
    assert (lesson.parent_id, lesson.level, activity.level) == (other_module.pk, 2, 3)

    with pytest.raises(services.ProgramError) as excinfo:
        services.move_node(module, parent=module, order=1, actor=owner)
    assert excinfo.value.get_codes() == "node_move_cycle"
    with pytest.raises(services.ProgramError) as excinfo:
        services.move_node(other_module, parent=lesson, order=1, actor=owner)
    assert excinfo.value.get_codes() == "node_move_cycle"
    # other_module now holds lesson -> activity (three levels below it); under module it would need five.
    with pytest.raises(services.ProgramError) as excinfo:
        services.move_node(other_module, parent=module, order=1, actor=owner)
    assert excinfo.value.get_codes() == "node_level_exceeds_template"


def test_soft_delete_and_restore(ctx):
    owner, version = ctx
    root, module, *_ = four_level_tree(version, owner)
    block = services.add_block(version, node=module, type="content", content=doc("x"), actor=owner)
    services.soft_delete_node(module, actor=owner)
    services.soft_delete_block(block, actor=owner)
    module.refresh_from_db()
    block.refresh_from_db()
    assert module.deleted and block.deleted
    assert Node.objects.filter(pk=module.pk).exists(), "soft delete keeps the row"
    services.restore_node(module, actor=owner)
    services.restore_block(block, actor=owner)
    module.refresh_from_db()
    block.refresh_from_db()
    assert not module.deleted and not block.deleted


def test_a_new_version_copies_the_tree_and_blocks_with_the_same_keys(ctx):
    owner, v1 = ctx
    root, module, lesson, activity = four_level_tree(v1, owner)
    services.add_block(v1, node=lesson, type="objective", content=doc("هدف"), actor=owner)
    deleted = services.add_block(v1, node=module, type="content", content=doc("محذوف"), actor=owner)
    services.soft_delete_block(deleted, actor=owner)

    lifecycle.transition(v1, S.SUBMITTED, actor=owner)
    lifecycle.transition(v1, S.WITHDRAWN, actor=owner)
    v2 = v1.program.versions.get(number=2)

    def snapshot(version):
        nodes = {
            n.node_key: (n.parent.node_key if n.parent else None, n.level, n.order, n.title, n.deleted)
            for n in version.nodes.select_related("parent")
        }
        blocks = {
            b.block_key: (b.node.node_key, b.type, b.content, b.content_hash, b.order, b.deleted)
            for b in version.blocks.select_related("node")
        }
        return nodes, blocks

    assert snapshot(v2) == snapshot(v1)
    assert not set(v2.nodes.values_list("pk", flat=True)) & set(v1.nodes.values_list("pk", flat=True))

    copied_lesson = v2.nodes.get(node_key=lesson.node_key)
    services.update_node(copied_lesson, title="الدرس المعدّل", actor=owner)
    lesson.refresh_from_db()
    assert lesson.title == "الدرس الأول"


def test_locked_versions_reject_node_and_block_changes(ctx):
    owner, version = ctx
    root = services.add_node(version, title="r", actor=owner)
    block = services.add_block(version, node=root, type="content", content=doc("x"), actor=owner)
    lifecycle.transition(version, S.SUBMITTED, actor=owner)
    with pytest.raises(VersionLocked):
        services.add_node(version, title="new", actor=owner)
    with pytest.raises(VersionLocked):
        services.update_block(block, content=doc("y"), actor=owner)
    with pytest.raises(VersionLocked):
        Block.objects.filter(pk=block.pk).update(order=5)
    for sql in (
        "UPDATE programs_node SET title = 'x' WHERE id = %s",
        'UPDATE programs_block SET "order" = 9 WHERE node_id = %s',
    ):
        with pytest.raises(DatabaseError, match="locked"), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(sql, [root.pk])
