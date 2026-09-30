import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True)
def test_rolling_back_removes_group_activity_before_its_columns_go():
    from accounts.groups import owners_group
    from listings.models import FeedEvent
    from tests.helpers import make_listing

    listing = make_listing()
    FeedEvent.objects.create(listing=listing, kind="new_listing", summary="scraped", happened_at=listing.first_seen_at)
    FeedEvent.objects.create(listing=listing, kind="comment", summary="Sam: private", happened_at=listing.first_seen_at,
                             group=owners_group())
    executor = MigrationExecutor(connection)
    try:
        executor.migrate([("listings", "0017_trends_to_owners_group")])
        with connection.cursor() as cursor:
            cursor.execute("SELECT summary FROM listings_feedevent")
            assert [row[0] for row in cursor.fetchall()] == ["scraped"]
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
