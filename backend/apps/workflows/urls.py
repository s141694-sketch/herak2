from django.urls import path

from . import views

urlpatterns = [
    path("workflow-templates/", views.WorkflowTemplateListView.as_view(), name="workflow-template-list"),
    path("workflow-templates/<int:pk>/", views.WorkflowTemplateDetailView.as_view(), name="workflow-template-detail"),
    path("programs/<int:pk>/workflow/", views.ProgramWorkflowView.as_view(), name="program-workflow"),
    path("program-versions/<int:pk>/submit/", views.SubmitVersionView.as_view(), name="program-version-submit"),
    path("program-versions/<int:pk>/withdraw/", views.WithdrawVersionView.as_view(), name="program-version-withdraw"),
    path("program-versions/<int:pk>/cancel/", views.CancelVersionView.as_view(), name="program-version-cancel"),
    path("program-versions/<int:pk>/workflow/", views.VersionWorkflowView.as_view(), name="program-version-workflow"),
    path("tasks/", views.TaskListView.as_view(), name="task-list"),
    path("tasks/<int:pk>/claim/", views.ClaimTaskView.as_view(), name="task-claim"),
    path("tasks/<int:pk>/release/", views.ReleaseTaskView.as_view(), name="task-release"),
    path("tasks/<int:pk>/decide/", views.DecideTaskView.as_view(), name="task-decide"),
]
