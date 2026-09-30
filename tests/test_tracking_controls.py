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
