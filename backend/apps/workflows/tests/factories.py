from apps.workflows import services


def two_stage_template(admin, *, approver, name="مسار الاعتماد", default=True, first_resubmit="same_stage"):
    """Stage 1: any reviewer claims it (2 work days). Stage 2: one approver (1 work day)."""
    return services.save_template(
        None,
        actor=admin,
        name=name,
        is_default=default,
        stages=[
            {"name": "مراجعة فنية", "assignee_role": "reviewer", "due_work_days": 2, "resubmit": first_resubmit},
            {"name": "اعتماد", "assignee_user": approver.pk, "due_work_days": 1, "resubmit": "same_stage"},
        ],
    )


def one_stage_template(actor, *, role="reviewer", due_work_days=3):
    """The organization's default: one stage any holder of ``role`` claims."""
    return services.save_template(
        None,
        actor=actor,
        name="مراجعة واحدة",
        is_default=True,
        stages=[{"name": "مراجعة", "assignee_role": role, "due_work_days": due_work_days}],
    )
