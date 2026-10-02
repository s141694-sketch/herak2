from django.apps import AppConfig


class TenancyTestAppConfig(AppConfig):
    """Test-only models exercising the tenancy layer. Installed in the test settings only."""

    name = "apps.tenancy.tests.testapp"
    label = "tenancy_testapp"
