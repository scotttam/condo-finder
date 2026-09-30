import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

BEFORE = [("listings", "0012_comment")]
AFTER = [("listings", "0013_notes_to_comments")]


def migrate(targets):
    MigrationExecutor(connection).migrate(targets)
    return MigrationExecutor(connection).loader.project_state(targets).apps


@pytest.mark.django_db(transaction=True)
def test_notes_become_the_owners_first_comment():
    apps = migrate(BEFORE)
    Listing = apps.get_model("listings", "Listing")
    SearchGroup = apps.get_model("accounts", "SearchGroup")
    Profile = apps.get_model("accounts", "Profile")
    User = apps.get_model("auth", "User")
    owners = SearchGroup.objects.order_by("pk").first() or SearchGroup.objects.create(name="Our search")
    scott = User.objects.create(username="scott@example.com", email="scott@example.com", is_staff=True)
    Profile.objects.create(user=scott, group=owners, display_name="Scott")
    noted = Listing.objects.create(address_key="a", address="1 A St", street="1 A St", city="Portland", notes="  Big deck.  ")
    Listing.objects.create(address_key="b", address="2 B St", street="2 B St", city="Portland", notes="   ")
    try:
        apps = migrate(AFTER)
        Comment = apps.get_model("listings", "Comment")
        comment = Comment.objects.get()
        assert (comment.listing_id, comment.group_id, comment.author_id) == (noted.pk, owners.pk, scott.pk)
        assert comment.body == "Big deck." and comment.author_name == "Scott"
        assert comment.created_at == Listing.objects.get(pk=noted.pk).updated_at
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
