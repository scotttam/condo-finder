import pytest
from django.db import connection

from listings.filters import apply_filters
from listings.forms import ListingFilterForm
from listings.models import Listing
from listings.search_index import Keywords, highlights, parse
from tests.helpers import home_group, make_listing

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


def searched(q, **data):
    form = ListingFilterForm({"q": q, **data})
    assert form.is_valid(), form.errors
    return list(apply_filters(Listing.objects.all(), form.cleaned_data, home_group()).values_list("address_key", flat=True))


def test_keyword_search_filters_and_ranks_title_matches_first():
    make_listing(address_key="desc", price=2000, description="Quiet unit. " * 20 + "Small balcony.")
    make_listing(address_key="title", price=3000, title="Balcony views over the Pearl")
    make_listing(address_key="none", price=2500, description="Garden level")
    assert searched("balcony") == ["title", "desc"]
    assert searched("balcony", sort="price") == ["desc", "title"]  # a chosen sort wins


def test_or_phrase_prefix_and_exclude():
    make_listing(address_key="pb", description="Pearl loft with balcony")
    make_listing(address_key="pt", description="Pearl flat with terrace")
    make_listing(address_key="b", description="Balcony in Sellwood")
    make_listing(address_key="studio", description="Pearl studio with balcony")
    assert set(searched("pearl balcony OR terrace")) == {"pb", "pt", "studio"}
    assert set(searched("pearl balcony OR terrace -studio")) == {"pb", "pt"}
    assert set(searched('"loft with"')) == {"pb"}
    assert set(searched("balc*")) == {"pb", "b", "studio"}


def test_exclude_only_keeps_everything_else_sorted_by_price():
    make_listing(address_key="studio", price=2000, description="Studio")
    make_listing(address_key="b", price=3000, description="Two bedroom")
    make_listing(address_key="a", price=2500, description="One bedroom")
    assert searched("-studio") == ["a", "b"]


def test_keywords_and_filters_combine():
    make_listing(address_key="cheap", price=2000, description="balcony")
    make_listing(address_key="dear", price=4000, description="balcony")
    assert searched("balcony", max_price=3000) == ["cheap"]


def test_highlights_mark_matches():
    row = make_listing(address_key="a", title="Pearl loft", description="A sunny unit with a big balcony and views.")
    marks = highlights([row.pk], "balcony pearl")[row.pk]
    assert "<mark>Pearl</mark>" in marks["title"]
    assert "<mark>balcony</mark>" in marks["snippet"]


def test_highlights_escape_listing_text():
    row = make_listing(address_key="a", description='<script>alert("x")</script> balcony <b>bold</b>')
    snippet = str(highlights([row.pk], "balcony")[row.pk]["snippet"])
    assert "<script>" not in snippet and "&lt;script&gt;" in snippet
    assert "<b>" not in snippet and "<mark>balcony</mark>" in snippet


def test_no_highlights_without_keywords():
    row = make_listing(address_key="a", description="balcony")
    assert highlights([row.pk], "") == {} and highlights([row.pk], "-balcony") == {}
