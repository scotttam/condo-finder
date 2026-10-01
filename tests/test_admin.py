import pytest
from bs4 import BeautifulSoup

from listings.models import PriceChange
from tests.helpers import make_listing

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_client(client, django_user_model):
    client.force_login(django_user_model.objects.create_superuser("admin", "admin@example.com", "pw"))
    return client


def change_form_data(admin_client, listing):
    """The listing's admin change form as the browser would submit it, unedited."""
    soup = BeautifulSoup(admin_client.get(f"/admin/listings/listing/{listing.pk}/change/").content, "html.parser")
    form = soup.find("form", id="listing_form")
    data = {}
    for field in form.find_all(["input", "select", "textarea"]):
        name = field.get("name")
        if not name or field.get("type") in ("submit", "button", "file"):
            continue
        if field.get("type") == "checkbox":
            if field.has_attr("checked"):
                data[name] = field.get("value", "on")
        elif field.name == "select":
            selected = field.find("option", selected=True)
            data[name] = selected.get("value", "") if selected else ""
        elif field.name == "textarea":
            data[name] = field.text
        else:
            data[name] = field.get("value", "")
    return data


def test_admin_can_add_a_price_history_entry(admin_client):
    listing = make_listing(price=3000)
    PriceChange.objects.create(listing=listing, price=3000)
    data = change_form_data(admin_client, listing)
    prefix = "price_changes"
    total = int(data[f"{prefix}-TOTAL_FORMS"])
    data.update({
        f"{prefix}-TOTAL_FORMS": str(total + 1),
        f"{prefix}-{total}-price": "2850",
        f"{prefix}-{total}-seen_at_0": "2026-09-20",
        f"{prefix}-{total}-seen_at_1": "10:00:00",
        f"{prefix}-{total}-listing": str(listing.pk),
    })
    response = admin_client.post(f"/admin/listings/listing/{listing.pk}/change/", data)
    assert response.status_code == 302, response.content.decode()[:2000]
    assert sorted(listing.price_changes.values_list("price", flat=True)) == [2850, 3000]


def test_admin_change_page_offers_editable_price_inputs(admin_client):
    listing = make_listing(price=3000)
    PriceChange.objects.create(listing=listing, price=3000)
    content = admin_client.get(f"/admin/listings/listing/{listing.pk}/change/").content.decode()
    assert 'name="price_changes-0-price"' in content
    assert 'name="price_changes-__prefix__-price"' in content  # template row used by "Add another"


def test_source_links_are_read_only_without_an_add_row(admin_client):
    listing = make_listing()
    content = admin_client.get(f"/admin/listings/listing/{listing.pk}/change/").content.decode()
    assert 'name="source_listings-__prefix__-' not in content  # no "Add another" row that could only save nothing


def test_source_name_and_enabled_are_editable_in_admin(admin_client):
    from listings.models import Source

    source = Source.objects.create(key="k", name="A Source", platform="appfolio")
    soup = BeautifulSoup(admin_client.get(f"/admin/listings/source/{source.pk}/change/").content, "html.parser")
    assert soup.find("input", attrs={"name": "name"}) is not None
    assert soup.find("input", attrs={"name": "is_enabled"}) is not None
    # key and platform are code-driven, shown read-only (no form input).
    assert soup.find("input", attrs={"name": "key"}) is None
    assert soup.find("select", attrs={"name": "platform"}) is None and soup.find("input", attrs={"name": "platform"}) is None


def test_admin_can_disable_a_source(admin_client):
    from listings.models import Source

    source = Source.objects.create(key="k2", name="Toggle", platform="appfolio")
    data = {"name": "Toggle", "_save": "Save"}  # is_enabled checkbox unchecked = disabled
    admin_client.post(f"/admin/listings/source/{source.pk}/change/", data)
    source.refresh_from_db()
    assert source.is_enabled is False
