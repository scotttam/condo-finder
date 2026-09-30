import pytest


@pytest.fixture(autouse=True)
def condo_settings(settings):
    settings.REQUEST_DELAY_SECONDS = 0
    settings.TARGET_CITIES = ["Portland", "Lake Oswego", "Beaverton"]
    settings.PUBLIC_URL = ""
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]  # every test logs in; keep it fast


@pytest.fixture
def owner(db):
    """The site admin, Sam, in the owners' group."""
    from tests.helpers import make_user

    return make_user("sam@example.com", "Sam", staff=True)


@pytest.fixture
def client(client, owner):
    """Every page needs a login, so the default test client is logged in as the site admin."""
    client.force_login(owner)
    return client


@pytest.fixture
def anon_client(db):
    from django.test import Client

    return Client()


@pytest.fixture
def member(db):
    """Alex: in the owners' group, not staff."""
    from tests.helpers import make_user

    return make_user("alex@example.com", "Alex")


@pytest.fixture
def member_client(member):
    from django.test import Client

    browser = Client()
    browser.force_login(member)
    return browser
