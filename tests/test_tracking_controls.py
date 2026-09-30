import re

import pytest

from listings.models import Status
from tests.helpers import make_listing

pytestmark = pytest.mark.django_db


def section(content, start):
    begin = content.index(start)
    return content[begin:content.index("</form>", begin)]


def test_status_is_a_row_of_pills_with_the_current_one_selected(client):
    listing = make_listing(status=Status.TOURED)
    pills = section(client.get(f"/listing/{listing.pk}/").content.decode(), f'id="pills-{listing.pk}"')
    for value in ("new", "interested", "toured", "applied", "rejected"):
        assert f'name="status" value="{value}"' in pills
    assert re.search(r'name="status" value="toured"[^>]*checked', pills)
    assert "<select" not in pills


def test_notes_save_while_typing_without_a_save_button(client):
    listing = make_listing()
    tracking = section(client.get(f"/listing/{listing.pk}/").content.decode(), 'id="tracking"')
    assert 'hx-trigger="change, keyup delay:800ms"' in tracking
    assert 'hx-select=".save-state"' in tracking  # only the indicator is swapped, so typing isn't interrupted
    assert 'name="status"' not in tracking
    assert re.sub(r"<noscript>.*?</noscript>", "", tracking, flags=re.S).count("<button") == 0


def test_saving_returns_the_indicator(client):
    listing = make_listing(notes="old")
    response = client.post(f"/listing/{listing.pk}/tracking/", {"notes": "Great light"}, HTTP_HX_REQUEST="true")
    content = response.content.decode()
    assert 'class="save-state saved"' in content and "Saved ✓" in content
    listing.refresh_from_db()
    assert listing.notes == "Great light"
