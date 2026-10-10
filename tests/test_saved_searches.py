import pytest
from django.test import Client

from accounts.groups import new_group
from listings.models import SavedSearch
from tests.helpers import home_group, make_listing, make_user

pytestmark = pytest.mark.django_db


def save(browser, name="Pearl 2bd", query="q=balcony&zips=97209&page=3", **extra):
    return browser.post("/search/saved/", {"name": name, "query": query, "columns": "address,price", **extra})


def test_saving_a_search_shares_it_with_the_group(client, member_client):
    response = save(client)
    saved = SavedSearch.objects.get()
    assert (saved.group, saved.name, saved.query, saved.by) == (home_group(), "Pearl 2bd", "q=balcony&zips=97209", "Sam")
    assert response.status_code == 302 and response["Location"] == f"/search/?q=balcony&zips=97209&saved={saved.pk}"
    content = member_client.get("/search/").content.decode()
    assert f'<a href="/search/?q=balcony&amp;zips=97209&amp;saved={saved.pk}">Pearl 2bd</a>' in content
    assert "by Sam" in content


def test_other_groups_cant_see_or_touch_it(client):
    save(client)
    saved = SavedSearch.objects.get()
    outsider = make_user("o@example.com", "Olive", group=new_group("Other"))
    browser = Client()
    browser.force_login(outsider)
    assert "Pearl 2bd" not in browser.get("/search/").content.decode()
    for action in ("update", "rename", "delete"):
        assert browser.post(f"/search/saved/{saved.pk}/{action}/", {"name": "x", "query": "q="}).status_code == 404
    assert SavedSearch.objects.get().name == "Pearl 2bd"


def test_columns_are_saved_only_when_asked(client):
    save(client, name="With columns", with_columns="on")
    assert SavedSearch.objects.get(name="With columns").query == "q=balcony&zips=97209&cols=address%2Cprice"
    save(client, name="Without", query="q=&cols=address,zip")
    assert SavedSearch.objects.get(name="Without").query == "q="


def test_rename_update_and_delete(client, member_client):
    save(client)
    saved = SavedSearch.objects.get()
    member_client.post(f"/search/saved/{saved.pk}/rename/", {"name": "Pearl, 2 bed"})
    member_client.post(f"/search/saved/{saved.pk}/update/", {"query": "q=terrace&saved=9", "columns": "address"})
    saved.refresh_from_db()
    assert (saved.name, saved.query) == ("Pearl, 2 bed", "q=terrace")
    member_client.post(f"/search/saved/{saved.pk}/delete/")
    assert not SavedSearch.objects.exists()


def test_a_name_is_required_and_a_huge_query_is_refused(client):
    save(client, name="  ")
    save(client, query="q=" + "x" * 5000)
    assert not SavedSearch.objects.exists()


def test_opening_a_saved_search_shows_its_controls_and_keeps_it_while_filtering(client):
    make_listing(address_key="a", description="balcony")
    save(client)
    saved = SavedSearch.objects.get()
    content = client.get(saved.get_absolute_url()).content.decode()
    assert "Viewing “Pearl 2bd”" in content
    assert f'<input type="hidden" name="saved" value="{saved.pk}">' in content
    assert f'action="/search/saved/{saved.pk}/update/"' in content


def test_a_saved_search_link_from_another_group_is_ignored(client):
    other = SavedSearch.objects.create(group=new_group("Other"), name="Theirs", query="q=")
    assert "Viewing" not in client.get(f"/search/?q=&saved={other.pk}").content.decode()
