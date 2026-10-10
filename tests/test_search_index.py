import pytest
from django.db import connection

from listings.models import Listing
from listings.search_index import Keywords, parse
from tests.helpers import make_listing

pytestmark = pytest.mark.django_db


def matches(fts):
    with connection.cursor() as cursor:
        cursor.execute("SELECT rowid FROM listing_search WHERE listing_search MATCH %s", [fts])
        return {row[0] for row in cursor.fetchall()}


def in_sync():
    with connection.cursor() as cursor:  # raises if the index and listings_listing disagree
        cursor.execute("INSERT INTO listing_search(listing_search, rank) VALUES ('integrity-check', 1)")


@pytest.mark.parametrize("text, expected", [
    ("balcony", Keywords('("balcony")', "")),
    ('"walk in closet"', Keywords('("walk in closet")', "")),
    ("pearl balcony OR terrace", Keywords('("pearl") AND ("balcony" OR "terrace")', "")),
    ("-studio", Keywords("", '"studio"')),
    ("pearl -studio -\"no pets\"", Keywords('("pearl")', '"studio" OR "no pets"')),
    ("balc*", Keywords('("balc"*)', "")),
    ('"unbalanced phrase', Keywords('("unbalanced phrase")', "")),
    ("two-bedroom", Keywords('("two bedroom")', "")),
    ("pearl AND balcony", Keywords('("pearl") AND ("balcony")', "")),
])
def test_parse(text, expected):
    assert parse(text) == expected


@pytest.mark.parametrize("text", ["", "   ", "OR", "-", "***", '""', '"" -""', "OR OR", "- -"])
def test_nothing_to_search_for(text):
    assert parse(text) is None


@pytest.mark.parametrize("text", ['"unbalanced', "AND NOT", "(paren", "col:umn", "^start", "NEAR(a b)", "a OR", "OR a",
                                  "café", "<script>", "50%", "a\"b\"c", "-\"", "*a", "😀 balcony"])
def test_messy_queries_never_raise(text):
    make_listing(address_key="k", title="Balcony views")
    keywords = parse(text)
    if keywords and keywords.include:
        matches(keywords.include)
    if keywords and keywords.exclude:
        matches(keywords.exclude)


def test_index_follows_inserts_updates_and_deletes():
    row = make_listing(address_key="a", title="Pearl loft", description="Big balcony", neighborhood="Pearl")
    assert matches('"balcony"') == {row.pk}
    row.description = "Rooftop deck"
    row.save()
    assert matches('"balcony"') == set() and matches('"rooftop"') == {row.pk}
    Listing.objects.filter(pk=row.pk).update(title="Sunny condo")  # QuerySet.update skips save(); the trigger doesn't
    assert matches('"sunny"') == {row.pk} and matches('"loft"') == set()
    in_sync()
    row.delete()
    assert matches('"rooftop"') == set()
    in_sync()


def test_stemming_and_accents():
    row = make_listing(address_key="a", description="Two balconies near the café")
    assert matches('"balcony"') == {row.pk}
    assert matches('"cafe"') == {row.pk}


@pytest.mark.django_db(transaction=True)
def test_migration_indexes_existing_listings():
    from django.db.migrations.executor import MigrationExecutor

    def migrate(target):
        MigrationExecutor(connection).migrate(target)
        return MigrationExecutor(connection).loader.project_state(target).apps

    apps = migrate([("listings", "0022_listing_effective_price")])
    old = apps.get_model("listings", "Listing").objects.create(
        address_key="k", address="1 A St", street="1 A St", city="Portland", description="Wraparound terrace")
    try:
        migrate([("listings", "0023_listing_search")])
        assert matches('"terrace"') == {old.pk}
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
