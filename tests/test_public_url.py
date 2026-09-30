import pytest
from django.test import Client

from condofinder.settings import web_security
from tests.helpers import make_listing, status_of

HOST = "mac-mini.tail1234.ts.net"


def test_local_development_is_open_and_uses_plain_cookies():
    assert web_security("") == {"ALLOWED_HOSTS": ["*"], "CSRF_TRUSTED_ORIGINS": [],
                                "SESSION_COOKIE_SECURE": False, "CSRF_COOKIE_SECURE": False}


def test_public_https_url_locks_hosts_and_cookies():
    assert web_security(f"https://{HOST}") == {
        "ALLOWED_HOSTS": [HOST, "localhost", "127.0.0.1"], "CSRF_TRUSTED_ORIGINS": [f"https://{HOST}"],
        "SESSION_COOKIE_SECURE": True, "CSRF_COOKIE_SECURE": True,
    }


@pytest.mark.django_db
def test_status_posts_pass_csrf_on_the_public_url(owner, settings):
    settings.ALLOWED_HOSTS = [HOST, "testserver"]
    settings.CSRF_TRUSTED_ORIGINS = [f"https://{HOST}"]
    listing = make_listing()
    browser = Client(enforce_csrf_checks=True)
    browser.force_login(owner)
    browser.get("/", HTTP_HOST=HOST, secure=True)
    token = browser.cookies["csrftoken"].value
    response = browser.post(
        f"/listing/{listing.pk}/status/", {"status": "interested"}, secure=True,
        HTTP_HOST=HOST, HTTP_ORIGIN=f"https://{HOST}", HTTP_X_CSRFTOKEN=token, HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    assert status_of(listing) == "interested"


@pytest.mark.django_db
def test_unknown_hosts_are_refused(settings, anon_client):
    settings.ALLOWED_HOSTS = [HOST]
    assert anon_client.get("/login/", HTTP_HOST="evil.example.com").status_code == 400
