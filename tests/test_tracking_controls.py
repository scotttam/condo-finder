import re

import pytest

from listings.models import Status
from tests.helpers import make_listing

pytestmark = pytest.mark.django_db


def test_status_is_a_row_of_pills_with_the_current_one_selected(client):
    listing = make_listing(status=Status.TOURED)
    content = client.get(f"/listing/{listing.pk}/").content.decode()
    tracking = content[content.index('id="tracking"'):content.index("</form>", content.index('id="tracking"'))]
    for value in ("new", "interested", "toured", "applied", "rejected"):
        assert f'name="status" value="{value}"' in tracking
    assert re.search(r'name="status" value="toured"[^>]*checked', tracking)
    assert "<select" not in tracking


def test_saves_on_change_and_while_typing_without_a_save_button(client):
    listing = make_listing()
    content = client.get(f"/listing/{listing.pk}/").content.decode()
    tracking = content[content.index('id="tracking"'):content.index("</form>", content.index('id="tracking"'))]
    assert 'hx-trigger="change, keyup delay:800ms"' in tracking
    assert 'hx-select=".save-state"' in tracking  # only the indicator is swapped, so typing isn't interrupted
    assert re.sub(r"<noscript>.*?</noscript>", "", tracking, flags=re.S).count("<button") == 0


def test_saving_returns_the_indicator(client):
    listing = make_listing(notes="old")
    response = client.post(f"/listing/{listing.pk}/tracking/", {"status": "interested", "notes": "Great light"}, HTTP_HX_REQUEST="true")
    content = response.content.decode()
    assert 'class="save-state saved"' in content and "Saved ✓" in content
    listing.refresh_from_db()
    assert (listing.status, listing.notes) == (Status.INTERESTED, "Great light")
