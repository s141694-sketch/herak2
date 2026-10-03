"""Rules over a version's tree: Harak 1's objective rules on objective blocks, completeness of leaf nodes,
alignment links, and the mandatory coverage of every target competency by an assessment (spec 5.2, D36)."""

import random

from apps.quality.rules import program
from apps.quality.rules.program import BlockRow, CompetencyRow, LinkRow, NodeRow, Snapshot

GOOD_OBJECTIVE = "أن يطبق المتدرب إجراء العزل والإقفال باستخدام قائمة التحقق بدقة"


def tree(*, blocks=(), links=(), targets=(), competencies=None, nodes=None):
    nodes = nodes or (
        NodeRow("root", None, 0, "البرنامج", False),
        NodeRow("m1", "root", 0, "الوحدة الأولى", False),
    )
    competencies = competencies or (
        CompetencyRow("c1", "EL-01", "عزل الدوائر الكهربائية وإقفالها قبل الصيانة"),
        CompetencyRow("c2", "FA-01", "تقديم الإسعافات الأولية للمصابين"),
    )
    return Snapshot(tuple(nodes), tuple(blocks), tuple(links), tuple(targets), tuple(competencies))


def block(key, node, type_, text="", deleted=False, order=0):
    return BlockRow(key, node, type_, text, f"hash-{key}-{text}", deleted, order)


def kinds(findings, **where):
    return sorted(
        (f.kind, f.node_key, f.block_key, f.competency_key)
        for f in findings
        if all(getattr(f, k) == v for k, v in where.items())
    )


def complete_leaf(**extra):
    return tree(
        blocks=(
            block("o1", "m1", "objective", GOOD_OBJECTIVE),
            block("a1", "m1", "assessment", "اختبار عملي"),
            block("t1", "m1", "activity", "تطبيق"),
            block("r1", "m1", "reference", "دليل"),
        ),
        links=(
            LinkRow("objective_competency", "o1", None, "c1"),
            LinkRow("assessment_objective", "a1", "o1", None),
        ),
        targets=("c1",),
        **extra,
    )


def test_an_empty_program_reports_what_its_only_node_lacks():
    _, findings = program.analyze(tree(nodes=(NodeRow("root", None, 0, "ب", False),)))
    assert kinds(findings) == [
        ("node_missing_activity", "root", None, None),
        ("node_missing_assessment", "root", None, None),
        ("node_missing_objective", "root", None, None),
        ("node_missing_reference", "root", None, None),
    ]
    assert {f.severity for f in findings if f.kind in ("node_missing_objective", "node_missing_assessment")} == {
        "warning"
    }
    assert {f.severity for f in findings if f.kind in ("node_missing_activity", "node_missing_reference")} == {"info"}


def test_a_complete_aligned_leaf_has_no_warnings_and_its_objective_is_classified():
    objectives, findings = program.analyze(complete_leaf())
    assert [f for f in findings if f.severity != "info"] == []
    [result] = objectives
    assert (result.block_key, result.verb, result.level_id, result.domain, result.confidence) == (
        "o1",
        "يطبق",
        3,
        "cognitive",
        "high",
    )
    assert result.components == {
        "an": True,
        "verb": True,
        "learner": True,
        "content": True,
        "condition": True,
        "criterion": True,
    }


def test_only_leaves_are_checked_for_completeness():
    _, findings = program.analyze(complete_leaf())
    assert not [f for f in findings if f.node_key == "root" and f.kind.startswith("node_missing")]


def test_a_target_competency_no_assessment_reaches_is_critical():
    snapshot = complete_leaf()
    snapshot = Snapshot(snapshot.nodes, snapshot.blocks, snapshot.links, ("c1", "c2"), snapshot.competencies)
    _, findings = program.analyze(snapshot)
    [critical] = [f for f in findings if f.severity == "critical"]
    assert (critical.kind, critical.node_key, critical.competency_key, critical.confidence) == (
        "competency_not_assessed",
        "root",
        "c2",
        "high",
    )
    assert critical.params == {"has_objective": False}


def test_coverage_follows_higher_objectives():
    snapshot = tree(
        nodes=(
            NodeRow("root", None, 0, "ب", False),
            NodeRow("m1", "root", 0, "و", False),
            NodeRow("l1", "m1", 0, "د", False),
        ),
        blocks=(
            block("parent", "m1", "objective", GOOD_OBJECTIVE),
            block("child", "l1", "objective", "أن يذكر المتدرب خطوات العزل"),
            block("a1", "l1", "assessment", "اختبار"),
        ),
        links=(
            LinkRow("objective_competency", "parent", None, "c1"),
            LinkRow("objective_parent", "child", "parent", None),
            LinkRow("assessment_objective", "a1", "child", None),
        ),
        targets=("c1",),
    )
    _, findings = program.analyze(snapshot)
    assert not [f for f in findings if f.kind == "competency_not_assessed"]
    assert not [f for f in findings if f.kind == "objective_not_aligned"]


def test_an_objective_aligned_to_a_target_but_never_assessed_says_so():
    snapshot = tree(
        blocks=(block("o1", "m1", "objective", GOOD_OBJECTIVE),),
        links=(LinkRow("objective_competency", "o1", None, "c1"),),
        targets=("c1",),
    )
    _, findings = program.analyze(snapshot)
    [critical] = [f for f in findings if f.kind == "competency_not_assessed"]
    assert critical.params == {"has_objective": True}


def test_unaligned_objectives_and_assessments_are_warnings():
    snapshot = tree(blocks=(block("o1", "m1", "objective", GOOD_OBJECTIVE), block("a1", "m1", "assessment", "س")))
    _, findings = program.analyze(snapshot)
    assert kinds(findings, severity="warning") == [
        ("assessment_not_aligned", "m1", "a1", None),
        ("objective_not_aligned", "m1", "o1", None),
    ]


def test_deleted_nodes_hide_their_whole_subtree():
    snapshot = tree(
        nodes=(
            NodeRow("root", None, 0, "ب", False),
            NodeRow("gone", "root", 0, "و", True),
            NodeRow("under", "gone", 0, "د", False),
        ),
        blocks=(block("o1", "under", "objective", "أن يفهم المتدرب"),),
    )
    objectives, findings = program.analyze(snapshot)
    assert objectives == []
    assert {f.node_key for f in findings} == {"root"}


def test_a_link_to_a_deleted_block_is_reported_on_the_live_end():
    snapshot = tree(
        blocks=(
            block("o1", "m1", "objective", GOOD_OBJECTIVE, deleted=True),
            block("a1", "m1", "assessment", "اختبار"),
        ),
        links=(LinkRow("assessment_objective", "a1", "o1", None),),
    )
    _, findings = program.analyze(snapshot)
    assert ("link_to_deleted", "m1", "a1", None) in kinds(findings)
    assert ("assessment_not_aligned", "m1", "a1", None) in kinds(findings)


def test_harak1_objective_problems_become_findings():
    snapshot = tree(
        blocks=(
            block("vague", "m1", "objective", "أن يفهم المتدرب أهمية السلامة"),
            block("teacher", "m1", "objective", "أن يشرح المدرب للمتدربين قواعد السلامة"),
            block("two", "m1", "objective", "أن يذكر المتدرب أنواع الحرائق ويشرح طرق إطفائها"),
            block("unknown", "m1", "objective", "أن يتأمل المتدرب تجربته"),
            block("none", "m1", "objective", "معرفة أنواع الصمامات"),
        )
    )
    objectives, findings = program.analyze(snapshot)
    by_block = {}
    for f in findings:
        by_block.setdefault(f.block_key, set()).add(f.kind)
    assert "objective_unmeasurable" in by_block["vague"]
    assert "objective_teacher_activity" in by_block["teacher"]
    assert "objective_multi" in by_block["two"]
    assert "objective_unclassified" in by_block["unknown"]
    assert "objective_unclassified" in by_block["none"]
    unclassified = next(f for f in findings if f.block_key == "unknown" and f.kind == "objective_unclassified")
    assert (unclassified.severity, unclassified.confidence, unclassified.params) == ("info", "low", {"verb": "يتأمل"})
    missing = next(f for f in findings if f.block_key == "vague" and f.kind == "objective_components_missing")
    assert missing.params == {"missing": ["condition", "criterion"]}
    assert {o.block_key: o.domain for o in objectives}["unknown"] is None


def test_unaligned_objectives_get_possible_competency_matches():
    snapshot = tree(blocks=(block("o1", "m1", "objective", "أن يعزل المتدرب الدوائر الكهربائية ويقفلها قبل الصيانة"),))
    _, findings = program.analyze(snapshot)
    [match] = [f for f in findings if f.kind == "possible_competency_match"]
    assert (match.competency_key, match.severity, match.confidence) == ("c1", "info", "medium")
    # Shared words after normalization: الدوائر، الكهربائية، الصيانة = 3 of 9.
    assert match.params == {"score": 0.33}
    _, aligned = program.analyze(complete_leaf())
    assert not [f for f in aligned if f.kind == "possible_competency_match"]


def test_results_do_not_depend_on_row_order_and_fingerprints_are_stable():
    snapshot = complete_leaf()
    shuffled = list(snapshot.blocks)
    random.Random(7).shuffle(shuffled)
    other = Snapshot(
        tuple(reversed(snapshot.nodes)),
        tuple(shuffled),
        tuple(reversed(snapshot.links)),
        snapshot.targets,
        snapshot.competencies,
    )
    assert program.analyze(snapshot) == program.analyze(other)
    _, findings = program.analyze(snapshot)
    assert len({f.fingerprint for f in findings}) == len(findings)
    assert all(len(f.fingerprint) == 64 for f in findings)


def test_every_kind_has_a_severity():
    assert set(program.SEVERITY.values()) == {"critical", "warning", "info"}
    assert [k for k, v in program.SEVERITY.items() if v == "critical"] == ["competency_not_assessed"]
