import pytest
from django.contrib.auth import get_user_model

from accounts.groups import owners_group
from accounts.models import Profile, SearchGroup
from tests.helpers import make_user

pytestmark = pytest.mark.django_db


def test_pages_need_a_login(anon_client):
    response = anon_client.get("/feed/")
    assert response.status_code == 302 and response.url == "/login/?next=/feed/"


def test_login_page_is_public_and_shows_no_nav(anon_client):
    content = anon_client.get("/login/").content.decode()
    assert '<input type="email" name="username"' in content
    assert 'href="/feed/"' not in content and 'action="/logout/"' not in content


def test_log_in_with_email_in_any_case(anon_client):
    make_user("alex@example.com", "Alex")
    response = anon_client.post("/login/", {"username": " Alex@Example.com ", "password": "pw"})
    assert response.status_code == 302 and response.url == "/"
    assert anon_client.get("/feed/").status_code == 200


def test_wrong_password_says_so(anon_client):
    make_user("alex@example.com", "Alex")
    content = anon_client.post("/login/", {"username": "alex@example.com", "password": "nope"}).content.decode()
    assert '<p class="form-error">That email and password do not match an account.</p>' in content


def test_htmx_request_without_a_login_redirects_the_whole_page(anon_client):
    response = anon_client.get("/feed/", HTTP_HX_REQUEST="true", HTTP_HX_CURRENT_URL="http://testserver/feed/?tab=new")
    assert response.status_code == 200 and response.content == b""
    assert response["HX-Redirect"] == "/login/?next=%2Ffeed%2F"


def test_log_out(client):
    assert client.post("/logout/").status_code == 302
    assert client.get("/").status_code == 302


def test_nav_shows_who_is_logged_in(client):
    content = client.get("/").content.decode()
    assert '<span class="muted whoami">Sam</span>' in content
    assert '<form method="post" action="/logout/">' in content


def test_account_made_outside_the_app_gets_its_own_group(anon_client):
    user = get_user_model().objects.create_user("old-admin", "boss@example.com", "pw")
    anon_client.force_login(user)
    assert anon_client.get("/").status_code == 200
    profile = Profile.objects.get(user=user)
    assert profile.display_name == "boss" and profile.group.name == "boss's search"
    assert profile.group != owners_group()


def test_admin_login_page_is_public(anon_client):
    assert anon_client.get("/admin/login/").status_code == 200


def test_the_owners_group_exists_after_migrating():
    assert SearchGroup.objects.order_by("pk").first().name == "Our search"
