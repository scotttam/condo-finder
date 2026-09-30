from urllib.parse import parse_qs, urlencode

import pytest
from bs4 import BeautifulSoup
from django.urls import reverse

from listings.models import SavedQuery

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff_client(client):
    """The conftest client: Sam, the site admin."""
    return client


def soup(response):
    return BeautifulSoup(response.content, "html.parser")


def test_save_creates_and_redirects_to_it(staff_client):
    response = staff_client.post("/sql/save/", {"name": "Cheap ones", "sql": "  SELECT 1  "})
    saved = SavedQuery.objects.get()
    assert (saved.name, saved.sql) == ("Cheap ones", "SELECT 1")
    assert response["Location"] == "/sql/?" + urlencode({"q": "SELECT 1", "saved": saved.pk})


def test_save_with_pk_updates(staff_client):
    saved = SavedQuery.objects.create(name="Old", sql="SELECT 1")
    staff_client.post("/sql/save/", {"name": "New", "sql": "SELECT 2", "pk": saved.pk})
    saved.refresh_from_db()
    assert (saved.name, saved.sql) == ("New", "SELECT 2")
    assert SavedQuery.objects.count() == 1


def test_save_as_new_keeps_the_original(staff_client):
    saved = SavedQuery.objects.create(name="Old", sql="SELECT 1")
    staff_client.post("/sql/save/", {"name": "Copy", "sql": "SELECT 2", "pk": saved.pk, "as_new": "1"})
    assert sorted(SavedQuery.objects.values_list("name", "sql")) == [("Copy", "SELECT 2"), ("Old", "SELECT 1")]


@pytest.mark.parametrize("data", [{"name": "", "sql": "SELECT 1"}, {"name": "Blank", "sql": "   "}])
def test_invalid_save_is_refused_with_a_message(staff_client, data):
    response = staff_client.post("/sql/save/", data, follow=True)
    assert not SavedQuery.objects.exists()
    assert "Give the query a name and some SQL" in soup(response).select_one("ul.messages").get_text()


def test_save_unknown_pk_is_404(staff_client):
    assert staff_client.post("/sql/save/", {"name": "X", "sql": "SELECT 1", "pk": 999}).status_code == 404


def test_delete(staff_client):
    saved = SavedQuery.objects.create(name="Gone", sql="SELECT 3")
    response = staff_client.post(f"/sql/saved/{saved.pk}/delete/")
    assert not SavedQuery.objects.exists()
    assert response["Location"] == "/sql/?" + urlencode({"q": "SELECT 3"})


def test_delete_requires_post(staff_client):
    saved = SavedQuery.objects.create(name="Stays", sql="SELECT 3")
    assert staff_client.get(f"/sql/saved/{saved.pk}/delete/").status_code == 405
    assert SavedQuery.objects.exists()


def test_anonymous_cannot_save_or_delete(anon_client):
    saved = SavedQuery.objects.create(name="Stays", sql="SELECT 3")
    save = anon_client.post("/sql/save/", {"name": "X", "sql": "SELECT 1"})
    delete = anon_client.post(f"/sql/saved/{saved.pk}/delete/")
    assert save["Location"].startswith(reverse("login"))
    assert delete["Location"].startswith(reverse("login"))
    assert list(SavedQuery.objects.values_list("name", flat=True)) == ["Stays"]


def test_members_who_are_not_staff_cannot_save_or_delete(member_client):
    saved = SavedQuery.objects.create(name="Stays", sql="SELECT 3")
    assert member_client.post("/sql/save/", {"name": "X", "sql": "SELECT 1"}).status_code == 403
    assert member_client.post(f"/sql/saved/{saved.pk}/delete/").status_code == 403
    assert list(SavedQuery.objects.values_list("name", flat=True)) == ["Stays"]


def test_page_without_saved_offers_plain_save(staff_client):
    page = soup(staff_client.get("/sql/"))
    form = page.select_one("form#sql-save")
    assert form["action"] == "/sql/save/"
    assert form.select_one("input[name=pk]") is None
    assert form.find("button", string="Save") is not None
    assert page.select_one("form.sql-delete") is None


def test_loaded_saved_query_offers_update_copy_and_delete(staff_client):
    saved = SavedQuery.objects.create(name="Mine", sql="SELECT 7 AS n")
    page = soup(staff_client.get("/sql/?" + urlencode({"q": saved.sql, "saved": saved.pk})))
    form = page.select_one("form#sql-save")
    assert form.select_one("input[name=pk]")["value"] == str(saved.pk)
    assert form.select_one("input[name=name]")["value"] == "Mine"
    assert form.find("button", string="Save changes") is not None
    assert form.find("button", string="Save as new")["name"] == "as_new"
    assert page.select_one("form.sql-delete")["action"] == f"/sql/saved/{saved.pk}/delete/"
    assert page.select_one("form#sql-form input[name=saved]")["value"] == str(saved.pk)


def test_saved_list_links_to_each_query(staff_client):
    saved = SavedQuery.objects.create(name="Mine", sql="SELECT 7 AS n")
    sidebar = soup(staff_client.get("/sql/")).find("summary", string="Saved").parent
    href = sidebar.find("a", string="Mine")["href"]
    assert href.startswith("?")
    assert parse_qs(href[1:]) == {"q": ["SELECT 7 AS n"], "saved": [str(saved.pk)]}


def test_bad_saved_param_is_ignored(staff_client):
    assert staff_client.get("/sql/?saved=abc").status_code == 200
    assert staff_client.get("/sql/?saved=999").status_code == 200
