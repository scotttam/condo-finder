import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

BEFORE = [("listings", "0016_trends_per_group")]
AFTER = [("listings", "0017_trends_to_owners_group")]


def migrate(targets):
    MigrationExecutor(connection).migrate(targets)
    return MigrationExecutor(connection).loader.project_state(targets).apps


@pytest.mark.django_db(transaction=True)
def test_existing_reports_and_priorities_move_to_the_owners_group():
    apps = migrate(BEFORE)
    TrendReport = apps.get_model("listings", "TrendReport")
    SearchPriorities = apps.get_model("listings", "SearchPriorities")
    SearchGroup = apps.get_model("accounts", "SearchGroup")
    owners = SearchGroup.objects.order_by("pk").first() or SearchGroup.objects.create(name="Our search")
    report = TrendReport.objects.create(status="done")
    SearchPriorities.objects.create(pk=1, text="Near a park")
    try:
        apps = migrate(AFTER)
        assert apps.get_model("listings", "TrendReport").objects.get(pk=report.pk).group_id == owners.pk
        assert apps.get_model("listings", "SearchPriorities").objects.get().group_id == owners.pk
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
