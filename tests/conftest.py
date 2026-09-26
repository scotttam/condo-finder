import pytest


@pytest.fixture(autouse=True)
def condo_settings(settings):
    settings.REQUEST_DELAY_SECONDS = 0
    settings.NTFY_TOPIC = ""
    settings.TARGET_CITIES = ["Portland", "Lake Oswego", "Beaverton"]
    settings.SITE_URL = "http://testserver"
