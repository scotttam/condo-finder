import importlib

import pytest
from django.apps import apps

from tests.helpers import make_listing

backfill = importlib.import_module("listings.migrations.0002_listing_quadrant").backfill_quadrants


@pytest.mark.django_db
def test_backfill_sets_quadrant_for_existing_listings():
    pearl = make_listing()
    beaverton = make_listing(address_key="bv", street="4775 SW Franklin Ave", city="Beaverton")
    kept = make_listing(address_key="kept", street="1 SE Main St", overrides={"quadrant": "NE"})
    backfill(apps, None)
    pearl.refresh_from_db()
    beaverton.refresh_from_db()
    kept.refresh_from_db()
    assert (pearl.quadrant, beaverton.quadrant, kept.quadrant) == ("NW", "", "NE")
