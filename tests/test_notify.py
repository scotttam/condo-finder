import itertools
from decimal import Decimal

import httpx
import pytest

from listings import notify
from listings.models import PropertyType, Status
from tests.helpers import make_listing

pytestmark = pytest.mark.django_db

_keys = itertools.count()


def good(**overrides):
    fields = dict(price=3200, beds=2, baths=Decimal("2"), sqft=1100, parking_spaces=2,
                  has_washer_dryer=True, has_ac=None, has_outdoor_space=True, property_type=PropertyType.CONDO)
    fields.update(overrides)
    return make_listing(address_key=f"key-{next(_keys)}", **fields)


@pytest.fixture
def pushes(monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "send_push", lambda title, message, url="", tags=None: sent.append((title, message, url)) or True)
    return sent


def test_criteria_accepts_unknowns():
    assert notify.matches_alert_criteria(good(parking_spaces=None, has_washer_dryer=None))


@pytest.mark.parametrize("overrides", [
    {"beds": 1}, {"baths": Decimal("1.5")}, {"price": 6000}, {"price": None},
    {"property_type": PropertyType.APARTMENT}, {"parking_spaces": 1},
    {"has_washer_dryer": False}, {"has_ac": False}, {"has_outdoor_space": False},
])
def test_criteria_rejects_known_failures(overrides):
    assert not notify.matches_alert_criteria(good(**overrides))


def test_summarize():
    listing = good(parking_spaces=None)
    assert notify.summarize(listing) == "$3,200 · 2bd/2ba · 1,100 sqft · parking ? · Portland"


def test_alert_new_listings_only_matches(pushes):
    listing = good()
    assert notify.alert_new_listings([listing, good(beds=1)]) == 1
    title, message, url = pushes[0]
    assert title == "New: 937 NW Glisan Street"
    assert url == f"http://testserver/listing/{listing.pk}/"


def test_alert_new_listings_caps_individual_pushes(pushes):
    listings = [good(sqft=1000 + i) for i in range(8)]
    notify.alert_new_listings(listings)
    assert len(pushes) == notify.MAX_INDIVIDUAL_ALERTS + 1
    assert pushes[-1][0] == "3 more new matches"


def test_alert_price_drops_only_for_interested(pushes):
    interested = good(status=Status.INTERESTED)
    ignored = good(sqft=999)
    assert notify.alert_price_drops([(interested, 3400, 3200), (ignored, 3400, 3200)]) == 1
    assert pushes[0][0] == "Price drop: 937 NW Glisan Street"
    assert pushes[0][1].startswith("$3,400 → $3,200")


def test_send_push_disabled_without_topic():
    assert notify.send_push("t", "m") is False


def test_send_push_posts_json(settings, monkeypatch):
    settings.NTFY_TOPIC = "condo-topic"
    calls = []

    def fake_post(url, json, timeout):
        calls.append((url, json))
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(notify.httpx, "post", fake_post)
    assert notify.send_push("Title — ok", "Body", url="http://x/1", tags=["house"]) is True
    assert calls == [("https://ntfy.sh", {"topic": "condo-topic", "title": "Title — ok", "message": "Body", "click": "http://x/1", "tags": ["house"]})]
