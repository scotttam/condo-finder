import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

BEFORE = [("listings", "0008_listingstate")]
AFTER = [("listings", "0009_move_status_to_owners_group")]


def migrate(targets):
    executor = MigrationExecutor(connection)
    executor.migrate(targets)
    return MigrationExecutor(connection).loader.project_state(targets).apps


@pytest.mark.django_db(transaction=True)
def test_statuses_move_to_the_owners_group():
    apps = migrate(BEFORE)
    Listing = apps.get_model("listings", "Listing")
    liked = Listing.objects.create(address_key="a", address="1 A St", street="1 A St", city="Portland", status="interested")
    Listing.objects.create(address_key="b", address="2 B St", street="2 B St", city="Portland")
    try:
        apps = migrate(AFTER)
        State = apps.get_model("listings", "ListingState")
        SearchGroup = apps.get_model("accounts", "SearchGroup")
        owners = SearchGroup.objects.order_by("pk").first()
        assert list(State.objects.values_list("group_id", "listing_id", "status")) == [(owners.pk, liked.pk, "interested")]
        assert State.objects.get().status_at is not None
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())  # leave the schema fully migrated
