import re

import pytest

from tests.helpers import FIXTURES

SECRET_PATTERNS = {
    "Google API key": r"AIza[0-9A-Za-z_-]{30,}",
    "Mapbox token": r"\b(?:pk|sk)\.eyJ[A-Za-z0-9._-]{20,}",
    "key= URL parameter": r"[?&](?:amp;)?key=[A-Za-z0-9_-]{20,}",
}


@pytest.mark.parametrize("path", sorted(FIXTURES.iterdir()), ids=lambda p: p.name)
def test_fixture_contains_no_api_keys(path):
    text = path.read_text(encoding="utf-8", errors="ignore")
    for label, pattern in SECRET_PATTERNS.items():
        assert not re.search(pattern, text), f"{path.name} contains a {label}; redact it before committing"
