import pytest
from django.utils import timezone

from listings.models import Comment, FeedEvent, ListingState, PriceChange, Source, SourceListing, SourceRun, TrendReport, Vote
from listings.sql_console import run_query
from listings.sql_queries import CANNED_QUERIES, by_category
from tests.helpers import home_group, make_listing

pytestmark = pytest.mark.django_db


@pytest.fixture
def seeded(owner):
    zillow = Source.objects.create(key="zillow-t", name="Zillow", platform="zillow")
    redfin = Source.objects.create(key="redfin-t", name="Redfin", platform="redfin")
    with_unit = make_listing(price=2600, beds=2, sqft=1000, special_offer="4 weeks free")
    no_unit = make_listing(address_key="937 nw glisan st||97209", address="937 NW Glisan Street, Portland, OR 97209",
                           unit="", price=2650, beds=2, sqft=1000)
    for listing, source in ((with_unit, zillow), (with_unit, redfin), (no_unit, redfin)):
        SourceListing.objects.create(listing=listing, source=source, external_id=f"{source.key}-{listing.pk}",
                                     url="https://example.com/")
    for price in (3000, 2900, 2600):
        PriceChange.objects.create(listing=with_unit, price=price, source="Zillow")
    PriceChange.objects.create(listing=with_unit, price=2600, source="")
    SourceRun.objects.create(source=zillow, ok=True, finished_at=timezone.now())
    SourceRun.objects.create(source=redfin, ok=False, finished_at=timezone.now(), error="blocked")
    FeedEvent.objects.create(listing=with_unit, kind="new_listing", happened_at=timezone.now(), summary="New")
    TrendReport.objects.create(status="done", cost_usd="0.51", input_tokens=1000, group=home_group())
    ListingState.objects.create(group=home_group(), listing=with_unit, status="interested")
    Comment.objects.create(listing=with_unit, group=home_group(), author=owner, author_name="Sam", body="Nice view")
    Vote.objects.create(listing=with_unit, group=home_group(), user=owner, value=1)
    return {"with_unit": with_unit, "no_unit": no_unit}


def canned(title):
    return next(query for query in CANNED_QUERIES if query.title == title)


def rows(title):
    result = run_query(canned(title).sql)
    assert result.error == ""
    return [dict(zip(result.columns, row)) for row in result.rows]


@pytest.mark.parametrize("query", CANNED_QUERIES, ids=lambda query: query.title)
def test_every_canned_query_runs(seeded, query):
    result = run_query(query.sql)
    assert result.error == "", f"{query.title}: {result.error}"
    assert result.columns


def test_every_canned_query_runs_on_an_empty_database():
    for query in CANNED_QUERIES:
        assert run_query(query.sql).error == "", query.title


def test_titles_are_unique():
    titles = [query.title for query in CANNED_QUERIES]
    assert len(titles) == len(set(titles))


def test_categories_in_order():
    assert [category for category, _ in by_category()] == [
        "Listings & market", "Price history", "Scraper health & data quality", "Tracking & costs",
    ]


def test_unit_duplicates_query_finds_the_pair(seeded):
    found = rows("Possible unit-number duplicates")
    assert [(row["listing_id"], row["with_unit_id"]) for row in found] == [(seeded["no_unit"].pk, seeded["with_unit"].pk)]


def test_several_cuts_counts_real_decreases(seeded):
    assert [(row["listing_id"], row["cuts"]) for row in rows("Listings with several price cuts")] == [(seeded["with_unit"].pk, 2)]


def test_biggest_drops_measures_from_the_highest_price(seeded):
    top = rows("Biggest price drops")[0]
    assert (top["listing_id"], top["price_drop"]) == (seeded["with_unit"].pk, 400)


def test_hand_entered_history_is_blank_source_only(seeded):
    assert len(rows("Hand-entered price history")) == 1


def test_median_rent_by_area(seeded):
    assert rows("Median rent by city and quadrant") == [
        {"city": "Portland", "quadrant": "", "listings": 2, "median_price": 2625},
    ]


def test_scrape_runs_by_source(seeded):
    by_source = {row["source"]: row for row in rows("Scrape runs by source (30 days)")}
    assert (by_source["Zillow"]["ok"], by_source["Zillow"]["failed"]) == (1, 0)
    assert (by_source["Redfin"]["ok"], by_source["Redfin"]["failed"]) == (0, 1)


def test_site_overlap(seeded):
    assert rows("Overlap between sites") == [{"site": "Zillow", "also_on": "Redfin", "listings": 1}]


@pytest.fixture
def relisted():
    """A listing with an older, pricier listing period before the current one."""
    listing = make_listing(address_key="1 relisted|2|97209", address="1 Relisted Way #2", unit="2", price=4500)
    history = [
        ("2024-06-21", 6500, "Listed for rent"), ("2024-08-06", 4950, "Price change"),
        ("2024-09-08", 4500, "Price change"), ("2024-09-13", 4500, "Listing removed"),
        ("2026-06-02", 4900, "Listed for rent"), ("2026-09-16", 4500, "Price change"),
    ]
    for day, price, event in history:
        PriceChange.objects.create(listing=listing, price=price, event=event, source="Zillow",
                                   seen_at=timezone.make_aware(timezone.datetime.fromisoformat(day)))
    return listing


def test_biggest_drops_only_count_the_current_listing_period(relisted):
    assert [(row["highest_price"], row["price_drop"]) for row in rows("Biggest price drops")] == [(4900, 400)]


def test_several_cuts_only_count_the_current_listing_period(relisted):
    assert rows("Listings with several price cuts") == []


def test_status_per_group_counts_comments_and_votes(seeded):
    assert [
        (row["listing_id"], row["search_group"], row["status"], row["comments"], row["vote_score"])
        for row in rows("Listings by status, per group")
    ] == [(seeded["with_unit"].pk, home_group().name, "interested", 1, 1)]


def test_recent_comments(seeded):
    assert [(row["search_group"], row["author"], row["body"]) for row in rows("Recent comments")] == [
        (home_group().name, "Sam", "Nice view"),
    ]


def test_trends_costs_name_the_group(seeded):
    assert [row["search_group"] for row in rows("Trends report costs")] == [home_group().name]
