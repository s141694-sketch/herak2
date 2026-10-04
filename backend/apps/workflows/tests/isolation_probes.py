from apps.accounts.models import Role, User
from apps.programs.tests.factories import member
from apps.programs.tests.isolation_probes import _program, _version
from apps.tenancy.isolation import Probe, register
from apps.workflows import services
from apps.workflows.models import StageTask


def _admin(org):
    return member(f"wf-{org.slug}-{User.objects.count()}@example.com", Role.ADMIN)


def _template(org):
    return services.save_template(
        None,
        actor=_admin(org),
        name=f"wf-{org.slug}",
        stages=[{"name": "s", "assignee_role": "admin", "due_work_days": 1}],
    )


def _task(org):
    """An open task for the admin role, in a submitted version of this organization."""
    template = _template(org)
    version = _version(org)
    services.choose_template(version.program, template, actor=version.program.owner)
    services.submit(version, actor=version.program.owner, role=Role.AUTHOR)
    return StageTask.objects.get(instance__version=version)


register(Probe(route="workflow-template-list", kind="list", make=_template))
register(Probe(route="workflow-template-detail", kind="detail", make=_template))
register(Probe(route="program-workflow", kind="detail", make=_program))
register(Probe(route="program-version-submit", kind="action", make=_version))
register(Probe(route="program-version-withdraw", kind="action", make=lambda org: _task(org).instance.version))
register(Probe(route="program-version-cancel", kind="action", make=_version))
register(Probe(route="program-version-workflow", kind="nested", make=lambda org: _task(org).instance.version))
register(Probe(route="task-list", kind="list", make=_task))
register(Probe(route="task-claim", kind="action", make=_task))
register(Probe(route="task-release", kind="action", make=_task))
register(Probe(route="task-decide", kind="action", make=_task))
