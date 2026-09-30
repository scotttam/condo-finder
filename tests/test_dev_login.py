import pytest

pytestmark = pytest.mark.django_db
SWITCH = '<div class="dev-switch"'


def test_production_has_no_quick_login(anon_client, member, settings):
    settings.DEBUG = False
    assert SWITCH not in anon_client.get("/login/").content.decode()
    assert anon_client.post("/dev/login-as/", {"user": member.pk}).status_code == 404
    assert anon_client.get("/").status_code == 302  # still logged out


def test_dev_login_page_logs_in_with_one_click(anon_client, owner, member, settings):
    settings.DEBUG = True
    content = anon_client.get("/login/?next=/feed/").content.decode()
    assert SWITCH in content
    assert f'<button type="submit" name="user" value="{member.pk}" class="link">Alex</button>' in content
    response = anon_client.post("/dev/login-as/", {"user": member.pk, "next": "/feed/"})
    assert response.status_code == 302 and response.url == "/feed/"
    assert anon_client.get("/feed/").wsgi_request.user == member


def test_dev_header_switches_accounts_and_stays_on_the_page(client, member, settings):
    settings.DEBUG = True
    content = client.get("/feed/").content.decode()
    assert f'<button type="submit" name="user" value="{member.pk}" class="link">Alex</button>' in content
    assert '<input type="hidden" name="next" value="/feed/">' in content
    response = client.post("/dev/login-as/", {"user": member.pk, "next": "/feed/"})
    assert response.url == "/feed/"
    assert client.get("/").wsgi_request.user == member


def test_dev_switch_ignores_an_offsite_next(client, member, settings):
    settings.DEBUG = True
    assert client.post("/dev/login-as/", {"user": member.pk, "next": "https://evil.example.com/"}).url == "/"
