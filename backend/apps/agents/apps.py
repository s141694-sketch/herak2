from django.apps import AppConfig


class AgentsConfig(AppConfig):
    name = "apps.agents"
    label = "agents"
    verbose_name = "AI agents"

    def ready(self):
        from . import classification  # noqa: F401 - registers the agent for evaluation
