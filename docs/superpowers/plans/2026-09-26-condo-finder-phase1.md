# Condo Finder Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A self-hosted Django app that scrapes Portland-area property-manager sites (AppFolio + Nesthub platforms), stores/merges listings in SQLite, and lets two people browse, map, filter and track condos, with push alerts.

**Architecture:** One Django project (`condofinder`) with one app (`listings`). Scrapers are plain classes that return `ScrapedListing` dataclasses; `ingest` normalizes addresses, dedupes into `Listing` rows, extracts features by regex, tracks price history and off-market status. A `runner` orchestrates scrape → ingest → alerts → geocode, triggered by an in-process APScheduler job or a "Scrape now" button. UI is server-rendered Django templates with HTMX for inline edits and Leaflet for the map.

**Tech Stack:** Python 3.12+, Django 5.2+, SQLite (WAL), httpx, BeautifulSoup4, APScheduler 3.x, gunicorn, WhiteNoise, python-dotenv, pytest + pytest-django, uv for env management. HTMX and Leaflet from CDN.

**Spec:** `docs/superpowers/specs/2026-09-26-condo-finder-design.md`

## Global Constraints

- Target cities default: `Portland,Lake Oswego,Beaverton` (setting `TARGET_CITIES`).
- Store only listings in a target city with beds ≥ 2.
- Feature fields (`parking_spaces`, `has_washer_dryer`, `has_ac`, `has_outdoor_space`) are tri-state: `None` = unknown; unknown is never hidden by default.
- Off-market after `OFF_MARKET_AFTER_MISSES = 3` missed successful runs of that source.
- Health push after `HEALTH_ALERT_AFTER_FAILURES = 3` consecutive failures, or immediately on 0 results after a non-zero run.
- Scrape schedule default `SCRAPE_HOURS = "7,11,15,19,23"`, timezone `America/Los_Angeles`.
- Alert max price default `5000`; UI default max price `5000`.
- Polite scraping: `REQUEST_DELAY_SECONDS` default `1.5` between requests per scraper; Nominatim ≤ 1 req/s with identifying User-Agent.
- Scheduler starts only when env `CONDOFINDER_SCHEDULER=1`.
- gunicorn: exactly 1 worker (gthread, 4 threads), bind `0.0.0.0:8000`.
- No login; LAN-only.
- Run all commands from the project root `/Users/scotttam/Claude/Projects/condo-finder`.

## File Structure

```
pyproject.toml, uv.lock, manage.py, .gitignore, .env.example, README.md
condofinder/settings.py, urls.py, wsgi.py, asgi.py
listings/
  apps.py            – starts scheduler when CONDOFINDER_SCHEDULER=1
  models.py          – Source, SourceRun, Listing, SourceListing, PriceChange
  admin.py
  parsing.py         – price / int / beds-baths string parsers
  extract.py         – parking, W/D, AC, outdoor, property-type extraction
  address.py         – address parsing, normalization, dedupe key, city filter
  scrapers/base.py   – ScrapedListing, Fetcher (polite HTTP), Scraper base, is_candidate
  scrapers/appfolio.py
  scrapers/nesthub.py
  scrapers/registry.py – SOURCES config + build_scraper
  ingest.py          – upsert/dedupe/price history/off-market
  geocode.py         – Nominatim geocoding
  notify.py          – ntfy push, alert criteria, alert senders
  runner.py          – run_source / run_all / background run / health
  scheduler.py       – APScheduler setup
  forms.py           – ListingFilterForm, TrackingForm, default filter data
  filters.py         – apply_filters(queryset, cleaned_data)
  views.py, urls.py
  templates/listings/*.html
  management/commands/scrape.py
deploy/gunicorn.conf.py, deploy/com.condofinder.web.plist.template, deploy/install.sh
tests/ (helpers.py, conftest.py, fixtures/*.html, test_*.py)
```

---

### Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml` (via uv), `manage.py`, `condofinder/*` (via startproject), `listings/*` (via startapp), `.gitignore`, `tests/__init__.py`, `tests/conftest.py`, `tests/helpers.py`, `tests/test_smoke.py`, `listings/urls.py`
- Modify: `condofinder/settings.py` (replace), `condofinder/urls.py` (replace)

**Interfaces:**
- Produces: settings constants `SITE_URL, TARGET_CITIES, SCRAPE_HOURS, ALERT_MAX_PRICE, DEFAULT_MAX_PRICE, REQUEST_DELAY_SECONDS, NTFY_SERVER, NTFY_TOPIC, NOMINATIM_EMAIL, OFF_MARKET_AFTER_MISSES, HEALTH_ALERT_AFTER_FAILURES`; `tests.helpers.load_fixture(name) -> str`, `tests.helpers.FakeFetcher(pages: dict, default: str|None)` with `.get(url) -> str` and `.requested: list[str]`.

- [ ] **Step 1: Create the uv project and Django skeleton**

```bash
uv init --bare --name condo-finder
uv add django httpx beautifulsoup4 "apscheduler>=3.10,<4" gunicorn whitenoise python-dotenv
uv add --dev pytest pytest-django
uv run django-admin startproject condofinder .
uv run python manage.py startapp listings
mkdir -p tests/fixtures
touch tests/__init__.py
```

- [ ] **Step 2: Append pytest config to `pyproject.toml`**

```toml
[tool.pytest.ini_options]
DJANGO_SETTINGS_MODULE = "condofinder.settings"
pythonpath = ["."]
testpaths = ["tests"]
python_files = ["test_*.py"]
```

- [ ] **Step 3: Replace `condofinder/settings.py`**

```python
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_list(name, default):
    return [part.strip() for part in os.environ.get(name, default).split(",") if part.strip()]


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-insecure-change-me")
DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"
ALLOWED_HOSTS = ["*"]  # LAN-only app

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "listings",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "condofinder.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "condofinder.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        "OPTIONS": {
            "timeout": 20,
            "transaction_mode": "IMMEDIATE",
            "init_command": "PRAGMA journal_mode=WAL;",
        },
    }
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "America/Los_Angeles"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {"listings": {"handlers": ["console"], "level": "INFO"}},
}

# --- Condo finder ---
SITE_URL = os.environ.get("SITE_URL", "http://localhost:8000").rstrip("/")
TARGET_CITIES = env_list("TARGET_CITIES", "Portland,Lake Oswego,Beaverton")
SCRAPE_HOURS = os.environ.get("SCRAPE_HOURS", "7,11,15,19,23")
ALERT_MAX_PRICE = int(os.environ.get("ALERT_MAX_PRICE", "5000"))
DEFAULT_MAX_PRICE = int(os.environ.get("DEFAULT_MAX_PRICE", "5000"))
REQUEST_DELAY_SECONDS = float(os.environ.get("REQUEST_DELAY_SECONDS", "1.5"))
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
NOMINATIM_EMAIL = os.environ.get("NOMINATIM_EMAIL", "")
OFF_MARKET_AFTER_MISSES = 3
HEALTH_ALERT_AFTER_FAILURES = 3
```

- [ ] **Step 4: Replace `condofinder/urls.py` and create `listings/urls.py`**

`condofinder/urls.py`:
```python
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("listings.urls")),
]
```

`listings/urls.py` (routes are added in Task 11):
```python
urlpatterns = []
```

- [ ] **Step 5: Create `.gitignore`**

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
db.sqlite3*
staticfiles/
logs/
.env
```

- [ ] **Step 6: Create test helpers**

`tests/helpers.py`:
```python
from pathlib import Path

import httpx

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeFetcher:
    """Stands in for scrapers.base.Fetcher; serves canned HTML by URL."""

    def __init__(self, pages, default=None):
        self.pages = pages
        self.default = default
        self.requested = []

    def get(self, url):
        self.requested.append(url)
        if url in self.pages:
            return self.pages[url]
        if self.default is not None:
            return self.default
        raise httpx.HTTPError(f"no fake page for {url}")
```

`tests/conftest.py`:
```python
import pytest


@pytest.fixture(autouse=True)
def condo_settings(settings):
    settings.REQUEST_DELAY_SECONDS = 0
    settings.NTFY_TOPIC = ""
    settings.TARGET_CITIES = ["Portland", "Lake Oswego", "Beaverton"]
    settings.SITE_URL = "http://testserver"
```

- [ ] **Step 7: Write the smoke test**

`tests/test_smoke.py`:
```python
import pytest


@pytest.mark.django_db
def test_admin_login_page_renders(client):
    response = client.get("/admin/login/")
    assert response.status_code == 200
```

- [ ] **Step 8: Run tests**

Run: `uv run pytest -q`
Expected: `1 passed`

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "chore: scaffold Django project with uv and pytest"
```

---

### Task 2: Models and admin

**Files:**
- Modify: `listings/models.py`, `listings/admin.py`
- Create: migration via makemigrations; `tests/test_models.py`
- Modify: `tests/helpers.py` (add `make_listing`)

**Interfaces:**
- Produces: `PropertyType`, `Status` (TextChoices); models `Source(key, name, platform, last_success_at, last_count, last_error, last_error_at, consecutive_failures)`, `SourceRun(source, started_at, finished_at, ok, count, new_count, error)`, `Listing(address_key, address, street, unit, city, zip_code, neighborhood, latitude, longitude, geocoded_at, title, description, price, beds, baths, sqft, parking_spaces, has_washer_dryer, has_ac, has_outdoor_space, property_type, available, photo_url, overrides, status, notes, is_active, first_seen_at, last_seen_at, updated_at)` with `.price_per_sqft`, `.days_on_market`, `.get_absolute_url()` (reverses `listing_detail`), `SourceListing(listing, source, external_id, url, is_active, missed_runs, first_seen_at, last_seen_at)`, `PriceChange(listing, price, seen_at)`. Related names: `listing.source_listings`, `listing.price_changes`, `source.runs`, `source.source_listings`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/helpers.py`:
```python
def make_listing(**overrides):
    from listings.models import Listing

    fields = dict(
        address_key="937 nw glisan st|435|97209",
        address="937 NW Glisan Street #435, Portland, OR 97209",
        street="937 NW Glisan Street",
        unit="435",
        city="Portland",
        zip_code="97209",
    )
    fields.update(overrides)
    return Listing.objects.create(**fields)
```

`tests/test_models.py`:
```python
from datetime import timedelta

import pytest
from django.utils import timezone

from listings.models import PropertyType, Status
from tests.helpers import make_listing

pytestmark = pytest.mark.django_db


def test_listing_defaults():
    listing = make_listing()
    assert listing.status == Status.NEW
    assert listing.property_type == PropertyType.UNKNOWN
    assert listing.is_active is True
    assert listing.overrides == {}
    assert listing.has_ac is None


def test_price_per_sqft():
    assert make_listing(price=2800, sqft=1105).price_per_sqft == 2.53


def test_price_per_sqft_missing_sqft():
    assert make_listing(price=2800).price_per_sqft is None


def test_days_on_market_active_listing_counts_to_now():
    listing = make_listing(first_seen_at=timezone.now() - timedelta(days=5))
    assert listing.days_on_market == 5


def test_days_on_market_off_market_listing_counts_to_last_seen():
    now = timezone.now()
    listing = make_listing(
        first_seen_at=now - timedelta(days=10),
        last_seen_at=now - timedelta(days=3),
        is_active=False,
    )
    assert listing.days_on_market == 7
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_models.py -q`
Expected: FAIL with `ImportError: cannot import name 'PropertyType'`

- [ ] **Step 3: Write `listings/models.py`**

```python
from django.db import models
from django.urls import reverse
from django.utils import timezone


class PropertyType(models.TextChoices):
    CONDO = "condo", "Condo"
    TOWNHOME = "townhome", "Townhome"
    HOUSE = "house", "House"
    APARTMENT = "apartment", "Apartment"
    OTHER = "other", "Other"
    UNKNOWN = "unknown", "Unknown"


class Status(models.TextChoices):
    NEW = "new", "New"
    INTERESTED = "interested", "Interested"
    TOURED = "toured", "Toured"
    APPLIED = "applied", "Applied"
    REJECTED = "rejected", "Rejected"


class Source(models.Model):
    key = models.SlugField(unique=True)
    name = models.CharField(max_length=100)
    platform = models.CharField(max_length=30)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_count = models.IntegerField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    last_error_at = models.DateTimeField(null=True, blank=True)
    consecutive_failures = models.IntegerField(default=0)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class SourceRun(models.Model):
    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name="runs")
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    ok = models.BooleanField(default=False)
    count = models.IntegerField(default=0)
    new_count = models.IntegerField(default=0)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at"]


class Listing(models.Model):
    address_key = models.CharField(max_length=255, unique=True)
    address = models.CharField(max_length=255)
    street = models.CharField(max_length=255)
    unit = models.CharField(max_length=50, blank=True)
    city = models.CharField(max_length=100)
    zip_code = models.CharField(max_length=10, blank=True)
    neighborhood = models.CharField(max_length=100, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    geocoded_at = models.DateTimeField(null=True, blank=True)

    title = models.CharField(max_length=300, blank=True)
    description = models.TextField(blank=True)
    price = models.IntegerField(null=True, blank=True)
    beds = models.PositiveSmallIntegerField(null=True, blank=True)
    baths = models.DecimalField(max_digits=3, decimal_places=1, null=True, blank=True)
    sqft = models.IntegerField(null=True, blank=True)
    parking_spaces = models.IntegerField(null=True, blank=True)
    has_washer_dryer = models.BooleanField(null=True, blank=True)
    has_ac = models.BooleanField(null=True, blank=True)
    has_outdoor_space = models.BooleanField(null=True, blank=True)
    property_type = models.CharField(
        max_length=20, choices=PropertyType.choices, default=PropertyType.UNKNOWN
    )
    available = models.CharField(max_length=100, blank=True)
    photo_url = models.URLField(max_length=500, blank=True)
    overrides = models.JSONField(
        default=dict,
        blank=True,
        help_text='Manual corrections that survive re-scrapes, e.g. {"parking_spaces": 2, "has_ac": true}',
    )

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    notes = models.TextField(blank=True)

    is_active = models.BooleanField(default=True)
    first_seen_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-first_seen_at"]

    def __str__(self):
        return self.address

    def get_absolute_url(self):
        return reverse("listing_detail", args=[self.pk])

    @property
    def price_per_sqft(self):
        if self.price and self.sqft:
            return round(self.price / self.sqft, 2)
        return None

    @property
    def days_on_market(self):
        end = timezone.now() if self.is_active else self.last_seen_at
        return (end - self.first_seen_at).days


class SourceListing(models.Model):
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="source_listings")
    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name="source_listings")
    external_id = models.CharField(max_length=200)
    url = models.URLField(max_length=500)
    is_active = models.BooleanField(default=True)
    missed_runs = models.IntegerField(default=0)
    first_seen_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["source", "external_id"], name="unique_source_external_id")
        ]


class PriceChange(models.Model):
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="price_changes")
    price = models.IntegerField()
    seen_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["seen_at"]
```

- [ ] **Step 4: Write `listings/admin.py`**

```python
from django.contrib import admin

from .models import Listing, PriceChange, Source, SourceListing, SourceRun


class SourceListingInline(admin.TabularInline):
    model = SourceListing
    extra = 0
    readonly_fields = ("source", "external_id", "url", "is_active", "missed_runs", "first_seen_at", "last_seen_at")


class PriceChangeInline(admin.TabularInline):
    model = PriceChange
    extra = 0
    readonly_fields = ("price", "seen_at")


@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    list_display = ("address", "price", "beds", "baths", "parking_spaces", "property_type", "status", "is_active", "first_seen_at")
    list_filter = ("status", "property_type", "city", "is_active")
    search_fields = ("address", "title", "neighborhood")
    inlines = [SourceListingInline, PriceChangeInline]


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ("name", "platform", "last_success_at", "last_count", "consecutive_failures")


@admin.register(SourceRun)
class SourceRunAdmin(admin.ModelAdmin):
    list_display = ("source", "started_at", "ok", "count", "new_count")
    list_filter = ("source", "ok")
```

- [ ] **Step 5: Make migrations and run tests**

Run: `uv run python manage.py makemigrations listings && uv run pytest -q`
Expected: migration `0001_initial.py` created; all tests pass.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: add listing, source, and price history models"
```

---

### Task 3: Text parsing and feature extraction

**Files:**
- Create: `listings/parsing.py`, `listings/extract.py`, `tests/test_parsing.py`, `tests/test_extract.py`

**Interfaces:**
- Consumes: `PropertyType` from Task 2.
- Produces: `parse_price(text) -> int|None`, `parse_int(text) -> int|None`, `parse_beds_baths(text) -> tuple[int|None, Decimal|None]`, `WORD_NUMBERS: dict`; `extract_parking(text) -> int|None`, `has_washer_dryer(text) -> bool|None`, `has_ac(text) -> bool|None`, `has_outdoor_space(text) -> bool|None`, `classify_property_type(hint: str, text: str) -> str (PropertyType value)`.

- [ ] **Step 1: Write the failing tests**

`tests/test_parsing.py`:
```python
from decimal import Decimal

import pytest

from listings.parsing import parse_beds_baths, parse_int, parse_price


@pytest.mark.parametrize(
    "text,expected",
    [("$2,800", 2800), ("$1,625/mo.", 1625), ("RENT $ 3100", 3100), ("Call for price", None), ("", None), (None, None)],
)
def test_parse_price(text, expected):
    assert parse_price(text) == expected


@pytest.mark.parametrize("text,expected", [("1,105", 1105), ("Square Feet: 925", 925), ("", None)])
def test_parse_int(text, expected):
    assert parse_int(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("2 bd / 2 ba", (2, Decimal("2"))),
        ("Beds: 2 Baths: 1.0", (2, Decimal("1.0"))),
        ("3 bedrooms, 2.5 baths", (3, Decimal("2.5"))),
        ("Studio / 1 ba", (0, Decimal("1"))),
        ("", (None, None)),
    ],
)
def test_parse_beds_baths(text, expected):
    assert parse_beds_baths(text) == expected
```

`tests/test_extract.py`:
```python
import pytest

from listings.extract import (
    classify_property_type,
    extract_parking,
    has_ac,
    has_outdoor_space,
    has_washer_dryer,
)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Amenities: 1 Reserved Parking Space, Concierge", 1),
        ("Attached 2-car garage", 2),
        ("two car garage plus driveway", 2),
        ("Double garage", 2),
        ("Includes 2 assigned spaces in secure garage", 2),
        ("Garage parking for 2 cars", 2),
        ("Tandem parking in building garage", 2),
        ("Off-street parking", 1),
        ("One garage space", 1),
        ("Ample street parking", 0),
        ("No parking available", 0),
        ("Beautiful 2 bedroom unit with 2 bathrooms", None),
    ],
)
def test_extract_parking(text, expected):
    assert extract_parking(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("In-unit washer/dryer", True),
        ("Appliances: Dishwasher, Washer/Dryer", True),
        ("W/D included", True),
        ("Washer and dryer in unit", True),
        ("Shared laundry on site", False),
        ("No washer or dryer", False),
        ("Hardwood floors", None),
    ],
)
def test_has_washer_dryer(text, expected):
    assert has_washer_dryer(text) is expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Central air conditioning", True),
        ("Ductless mini-split heat pump", True),
        ("High efficiency heating & cooling systems", True),
        ("A/C in bedrooms", True),
        ("No air conditioning", False),
        ("Gas fireplace", None),
    ],
)
def test_has_ac(text, expected):
    assert has_ac(text) is expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Private balcony with views", True),
        ("Fenced backyard", True),
        ("Covered patio", True),
        ("Rooftop deck", True),
        ("No balcony", False),
        ("Granite counters", None),
    ],
)
def test_has_outdoor_space(text, expected):
    assert has_outdoor_space(text) is expected


@pytest.mark.parametrize(
    "hint,text,expected",
    [
        ("Condo", "", "condo"),
        ("Townhouse", "", "townhome"),
        ("Single Family Home", "", "house"),
        ("Apartment", "Nice unit", "apartment"),
        ("Apartment", "South facing condo in the Pearl", "condo"),
        ("", "937 Condos - 2 bed/2 bath", "condo"),
        ("", "HOA covers water", "condo"),
        ("", "End-unit townhome", "townhome"),
        ("", "Visit our leasing office", "apartment"),
        ("", "Charming craftsman bungalow", "house"),
        ("Other", "Spacious unit", "other"),
        ("Duplex", "", "other"),
        ("", "Spacious unit", "unknown"),
    ],
)
def test_classify_property_type(hint, text, expected):
    assert classify_property_type(hint, text) == expected
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_parsing.py tests/test_extract.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'listings.parsing'`

- [ ] **Step 3: Write `listings/parsing.py`**

```python
import re
from decimal import Decimal

WORD_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "single": 1, "double": 2}


def parse_price(text):
    match = re.search(r"\$\s*(\d[\d,]*)", text or "")
    return int(match.group(1).replace(",", "")) if match else None


def parse_int(text):
    match = re.search(r"\d[\d,]*", text or "")
    return int(match.group(0).replace(",", "")) if match else None


def parse_beds_baths(text):
    lowered = (text or "").lower()
    beds = 0 if "studio" in lowered else None
    # "Beds: 2" label form first, so "Beds: 2 Baths: 1" isn't misread as "2 baths".
    match = re.search(r"\b(?:beds?|bedrooms?):\s*(\d+(?:\.\d+)?)", lowered) or re.search(
        r"(\d+(?:\.\d+)?)\s*(?:bd|beds?|bedrooms?|br)\b", lowered
    )
    if match:
        beds = int(float(match.group(1)))
    match = re.search(r"\b(?:baths?|bathrooms?):\s*(\d+(?:\.\d+)?)", lowered) or re.search(
        r"(\d+(?:\.\d+)?)\s*(?:ba|baths?|bathrooms?)\b", lowered
    )
    baths = Decimal(match.group(1)) if match else None
    return beds, baths
```

- [ ] **Step 4: Write `listings/extract.py`**

```python
"""Keyword/regex extraction of features from free listing text. None means unknown."""

import re

from .models import PropertyType
from .parsing import WORD_NUMBERS

_NUM = r"(\d|one|two|three|four|single|double)"
_QUALIFIER = r"(?:(?:reserved|assigned|deeded|covered|secured?|garage|off[\s-]street|underground|dedicated|private|tandem)\s+)"
_PARKING_COUNT_PATTERNS = [
    rf"\b{_NUM}[\s-]*(?:car|vehicle)\s+(?:attached\s+|detached\s+|tandem\s+)?(?:garage|parking|carport)",
    rf"\b{_NUM}\s+garage\b",
    rf"\b{_NUM}\s+{_QUALIFIER}*parking\b",
    rf"\b{_NUM}\s+{_QUALIFIER}+(?:spaces?|spots?|stalls?)\b",
    rf"\bparking\s+for\s+{_NUM}\b",
]
_PARKING_POSITIVE = (
    r"\b(?:garage|carport|driveway|w/\s?parking|with parking"
    r"|(?:off[\s-]street|assigned|reserved|covered|secured?|underground|deeded|private|gated) parking"
    r"|parking (?:space|spot|stall|included|available))"
)
_PARKING_NONE = r"\bno (?:off[\s-]street )?parking\b|\bparking (?:is )?not included"

_WD_NONE = r"\bno (?:in[\s-]unit )?(?:washer|w/d|laundry)"
_WD_YES = (
    r"in[\s-](?:unit|home)\s+(?:washer|laundry|w/d)|washer\s*(?:/|&|and|-)\s*dryer"
    r"|\bw/d\b|laundry in (?:unit|home)|stackable"
)
_WD_SHARED = r"(?:shared|coin[\s-]op(?:erated)?|common|on[\s-]?site|community) laundry|laundry (?:room|facilities|facility)"

_AC_NONE = r"\bno (?:air[\s-]conditioning|a/c|ac)\b"
_AC_YES = r"air[\s-]condition|\ba/c\b|\bac\b|central air|ductless|mini[\s-]splits?|heat pump|cooling"

_OUTDOOR_NONE = r"\bno (?:balcony|patio|deck|yard|outdoor space)"
_OUTDOOR_YES = r"balcon|patio|\bdecks?\b|\byard\b|back ?yard|terrace|porch|veranda|lanai"

_TYPE_HINTS = [
    ("condo", PropertyType.CONDO),
    ("town", PropertyType.TOWNHOME),
    ("single family", PropertyType.HOUSE),
    ("house", PropertyType.HOUSE),
    ("apartment", PropertyType.APARTMENT),
    ("plex", PropertyType.OTHER),
    ("loft", PropertyType.OTHER),
    ("other", PropertyType.OTHER),
]
_TYPE_TEXT_RULES = [
    (r"\bcondo(?:minium)?s?\b|\bhoa\b", PropertyType.CONDO),
    (r"\btown\s?(?:home|house)s?\b", PropertyType.TOWNHOME),
    (
        r"leasing office|apartment homes|apartment community|our community|resident portal"
        r"|community amenities|\bapartments\b",
        PropertyType.APARTMENT,
    ),
    (r"single[\s-]family|\bhouse\b|\bbungalow\b|\bcraftsman\b|\branch[\s-]style\b", PropertyType.HOUSE),
]


def _to_int(word):
    return int(word) if word.isdigit() else WORD_NUMBERS[word]


def extract_parking(text):
    lowered = (text or "").lower()
    counts = [_to_int(m.group(1)) for p in _PARKING_COUNT_PATTERNS for m in re.finditer(p, lowered)]
    if re.search(r"\btandem\b", lowered):
        counts.append(2)
    if counts:
        return max(counts)
    if re.search(_PARKING_NONE, lowered):
        return 0
    if re.search(_PARKING_POSITIVE, lowered):
        return 1
    if re.search(r"\bstreet parking\b", lowered):  # checked after "off-street parking"
        return 0
    return None


def _tri_state(text, none_pattern, yes_pattern, no_pattern=None):
    lowered = (text or "").lower()
    if re.search(none_pattern, lowered):
        return False
    if re.search(yes_pattern, lowered):
        return True
    if no_pattern and re.search(no_pattern, lowered):
        return False
    return None


def has_washer_dryer(text):
    return _tri_state(text, _WD_NONE, _WD_YES, _WD_SHARED)


def has_ac(text):
    return _tri_state(text, _AC_NONE, _AC_YES)


def has_outdoor_space(text):
    return _tri_state(text, _OUTDOOR_NONE, _OUTDOOR_YES)


def _type_from_hint(hint):
    lowered = (hint or "").lower()
    for needle, property_type in _TYPE_HINTS:
        if needle in lowered:
            return property_type
    return None


def _type_from_text(text):
    lowered = (text or "").lower()
    for pattern, property_type in _TYPE_TEXT_RULES:
        if re.search(pattern, lowered):
            return property_type
    return PropertyType.UNKNOWN


def classify_property_type(hint, text):
    hinted = _type_from_hint(hint)
    from_text = _type_from_text(text)
    # Property managers often label individually owned condos as "Apartment".
    if hinted == PropertyType.APARTMENT and from_text == PropertyType.CONDO:
        return PropertyType.CONDO
    if hinted and hinted != PropertyType.OTHER:
        return hinted
    if from_text != PropertyType.UNKNOWN:
        return from_text
    return hinted or PropertyType.UNKNOWN
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_parsing.py tests/test_extract.py -q`
Expected: all pass. If a regex case fails, adjust the pattern in `extract.py` (not the test) until it passes.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: add text parsing and feature extraction"
```

---

### Task 4: Address normalization

**Files:**
- Create: `listings/address.py`, `tests/test_address.py`

**Interfaces:**
- Produces: `ParsedAddress(street, unit, city, state, zip_code)` with `.key` (dedupe key) and `.display`; `parse_address(raw) -> ParsedAddress|None`; `normalize_street(street) -> str`; `is_target_city(city) -> bool`.

- [ ] **Step 1: Write the failing tests**

`tests/test_address.py`:
```python
import pytest

from listings.address import is_target_city, parse_address


def test_parse_appfolio_address_with_hash_unit():
    parsed = parse_address("937 NW Glisan Street #435, Portland, OR 97209")
    assert parsed.street == "937 NW Glisan Street"
    assert parsed.unit == "435"
    assert parsed.city == "Portland"
    assert parsed.state == "OR"
    assert parsed.zip_code == "97209"
    assert parsed.key == "937 nw glisan st|435|97209"
    assert parsed.display == "937 NW Glisan Street #435, Portland, OR 97209"


@pytest.mark.parametrize(
    "raw,street,unit",
    [
        ("4775 SW FRANKLIN AVE APT 321, Beaverton, OR 97005", "4775 SW FRANKLIN AVE", "321"),
        ("13000 NW Cornell Road Unit 15, Portland, OR 97229", "13000 NW Cornell Road", "15"),
        ("515 S Tamarind Ave - 515, Portland, OR 97220", "515 S Tamarind Ave", "515"),
        ("2655 NE 205th Ave Unit 303-A, Portland, OR 97024", "2655 NE 205th Ave", "303-A"),
        ("123 Main St, Unit 4, Portland, OR 97201", "123 Main St", "4"),
        (" 2908 NE Skidmore St, Portland, OR 97211", "2908 NE Skidmore St", ""),
    ],
)
def test_parse_units(raw, street, unit):
    parsed = parse_address(raw)
    assert (parsed.street, parsed.unit) == (street, unit)


def test_zip_plus_four_and_country_suffix():
    parsed = parse_address("4775 SW Franklin Ave, Beaverton, OR 97005-2943, US")
    assert parsed.zip_code == "97005"
    assert parsed.city == "Beaverton"


def test_multiword_city_is_title_cased():
    assert parse_address("16849 Lakeridge Drive, LAKE OSWEGO, OR 97034").city == "Lake Oswego"


def test_equivalent_addresses_share_key():
    a = parse_address("937 NW Glisan St. #435, Portland, OR 97209")
    b = parse_address("937 Northwest Glisan Street Unit 435, Portland, OR 97209")
    assert a.key == b.key


def test_unparseable_address_returns_none():
    assert parse_address("Contact us for address") is None
    assert parse_address("") is None


def test_is_target_city():
    assert is_target_city("Portland")
    assert is_target_city("lake oswego")
    assert not is_target_city("Gresham")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_address.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'listings.address'`

- [ ] **Step 3: Write `listings/address.py`**

```python
import re
from dataclasses import dataclass

from django.conf import settings

_ABBREVIATIONS = {
    "street": "st", "avenue": "ave", "boulevard": "blvd", "road": "rd", "drive": "dr",
    "lane": "ln", "court": "ct", "place": "pl", "terrace": "ter", "parkway": "pkwy",
    "highway": "hwy", "circle": "cir", "north": "n", "south": "s", "east": "e", "west": "w",
    "northwest": "nw", "northeast": "ne", "southwest": "sw", "southeast": "se",
}
_ADDRESS_RE = re.compile(
    r"^(?P<street>.+?),\s*(?P<city>[A-Za-z .'-]+?),\s*(?P<state>[A-Za-z]{2})\.?\s*"
    r"(?P<zip>\d{5})?(?:-\d{4})?(?:\s*,?\s*(?:US|USA))?$"
)
_UNIT_RE = re.compile(
    r"(?:\s*#\s*|\s+(?:apt\.?|apartment|unit|suite|ste\.?)\s*#?\s*|\s+-\s+)(?P<unit>[A-Za-z0-9-]+)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedAddress:
    street: str
    unit: str
    city: str
    state: str
    zip_code: str

    @property
    def key(self):
        return "|".join([normalize_street(self.street), self.unit.lower(), self.zip_code or self.city.lower()])

    @property
    def display(self):
        unit = f" #{self.unit}" if self.unit else ""
        return f"{self.street}{unit}, {self.city}, {self.state} {self.zip_code}".strip()


def normalize_street(street):
    words = re.sub(r"[.,]", " ", street.lower()).split()
    return " ".join(_ABBREVIATIONS.get(word, word) for word in words)


def parse_address(raw):
    text = " ".join((raw or "").split())
    match = _ADDRESS_RE.match(text)
    if not match:
        return None
    street = match["street"].strip()
    unit = ""
    unit_match = _UNIT_RE.search(street)
    if unit_match:
        unit = unit_match["unit"]
        street = street[: unit_match.start()].rstrip(" ,")
    return ParsedAddress(
        street=street,
        unit=unit,
        city=match["city"].strip().title(),
        state=match["state"].upper(),
        zip_code=match["zip"] or "",
    )


def is_target_city(city):
    return (city or "").strip().lower() in {c.lower() for c in settings.TARGET_CITIES}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_address.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: add address parsing and dedupe keys"
```

---

### Task 5: Scraper base + AppFolio scraper

**Files:**
- Create: `listings/scrapers/__init__.py` (empty), `listings/scrapers/base.py`, `listings/scrapers/appfolio.py`, `tests/test_appfolio.py`
- Create fixtures: `tests/fixtures/appfolio_list.html`, `tests/fixtures/appfolio_detail.html`

**Interfaces:**
- Consumes: `parse_price, parse_int, parse_beds_baths` (Task 3); `parse_address, is_target_city` (Task 4).
- Produces: `ScrapedListing(external_id, url, address, price=None, beds=None, baths=None, sqft=None, title="", description="", amenities="", property_type_hint="", available="", photo_url="")` with `.full_text`; `Fetcher(delay=None, client=None).get(url) -> str`; `Scraper(key, name, fetcher=None, **options)` with `.scrape() -> list[ScrapedListing]`, `.options`, `.fetcher`; `is_candidate(item) -> bool`; `appfolio.parse_list(html, base_url)`, `appfolio.parse_detail(html) -> dict(description, amenities)`, `AppFolioScraper` (option `subdomain`). Scrapers return **all** parsed listings; only candidates are enriched with detail pages.

- [ ] **Step 1: Save fixtures**

Copy the pages captured on 2026-09-26 from the session scratchpad:
```bash
S=/private/tmp/claude-501/-Users-scotttam-Claude-Projects-condo-finder/b09fbf2e-ae09-4499-b55a-1a31fd020e8a/scratchpad
cp $S/pearl.html tests/fixtures/appfolio_list.html
cp $S/af_detail.html tests/fixtures/appfolio_detail.html
```
If the scratchpad is gone, download fresh copies (and update the expected values in Step 2 to match the first listing on the page):
```bash
curl -sL -A "Mozilla/5.0" https://pearlpropertymanagement.appfolio.com/listings -o tests/fixtures/appfolio_list.html
# open the file, take the first /listings/detail/<uuid> link, then:
curl -sL -A "Mozilla/5.0" "https://pearlpropertymanagement.appfolio.com/listings/detail/<uuid>" -o tests/fixtures/appfolio_detail.html
```

- [ ] **Step 2: Write the failing tests**

`tests/test_appfolio.py`:
```python
from decimal import Decimal

from listings.scrapers.appfolio import AppFolioScraper, parse_detail, parse_list
from listings.scrapers.base import ScrapedListing, is_candidate
from tests.helpers import FakeFetcher, load_fixture

BASE = "https://pearlpropertymanagement.appfolio.com"
FIRST_ID = "320665de-4759-4508-afa2-bb7567932ef4"


def test_parse_list_extracts_cards():
    items = parse_list(load_fixture("appfolio_list.html"), BASE)
    assert len(items) == 7
    first = items[0]
    assert first.external_id == FIRST_ID
    assert first.url == f"{BASE}/listings/detail/{FIRST_ID}"
    assert first.address == "937 NW Glisan Street #435, Portland, OR 97209"
    assert first.price == 2800
    assert first.beds == 2
    assert first.baths == Decimal("2")
    assert first.sqft == 1105
    assert first.available == "NOW"
    assert "937 Condos" in first.title
    assert first.photo_url.startswith("https://images.cdn.appfolio.com/")


def test_parse_detail_gets_full_description_and_amenities():
    detail = parse_detail(load_fixture("appfolio_detail.html"))
    assert "south facing 2 bedroom, 2 bath condo" in detail["description"]
    assert "1 Reserved Parking Space" in detail["amenities"]
    assert "Washer/Dryer" in detail["amenities"]


def test_is_candidate():
    ok = ScrapedListing(external_id="1", url="u", address="1 Main St, Portland, OR 97201", beds=2)
    assert is_candidate(ok)
    assert not is_candidate(ScrapedListing(external_id="2", url="u", address="1 Main St, Portland, OR 97201", beds=1))
    assert not is_candidate(ScrapedListing(external_id="3", url="u", address="1 Main St, Gresham, OR 97030", beds=3))


def test_scraper_fetches_details_only_for_candidates():
    fetcher = FakeFetcher({f"{BASE}/listings": load_fixture("appfolio_list.html")}, default=load_fixture("appfolio_detail.html"))
    scraper = AppFolioScraper(key="pearl", name="Pearl", fetcher=fetcher, subdomain="pearlpropertymanagement")
    items = scraper.scrape()
    assert len(items) == 7
    candidates = [i for i in items if is_candidate(i)]
    assert len(fetcher.requested) == 1 + len(candidates)
    assert all("Amenities" in i.amenities for i in candidates)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_appfolio.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'listings.scrapers'`

- [ ] **Step 4: Write `listings/scrapers/__init__.py` (empty) and `listings/scrapers/base.py`**

```python
import logging
import time
from dataclasses import dataclass
from decimal import Decimal

import httpx
from django.conf import settings

from ..address import is_target_city, parse_address

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)


@dataclass
class ScrapedListing:
    external_id: str
    url: str
    address: str
    price: int | None = None
    beds: int | None = None
    baths: Decimal | None = None
    sqft: int | None = None
    title: str = ""
    description: str = ""
    amenities: str = ""
    property_type_hint: str = ""
    available: str = ""
    photo_url: str = ""

    @property
    def full_text(self):
        return "\n".join(part for part in (self.title, self.description, self.amenities) if part)


class Fetcher:
    """Polite HTTP GET: waits `delay` seconds between requests."""

    def __init__(self, delay=None, client=None):
        self.delay = settings.REQUEST_DELAY_SECONDS if delay is None else delay
        self.client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=30
        )
        self._last_request = 0.0

    def get(self, url):
        wait = self.delay - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        try:
            response = self.client.get(url)
        finally:
            self._last_request = time.monotonic()
        response.raise_for_status()
        return response.text


class Scraper:
    platform = ""

    def __init__(self, key, name, fetcher=None, **options):
        self.key = key
        self.name = name
        self.fetcher = fetcher or Fetcher()
        self.options = options

    def scrape(self):
        raise NotImplementedError


def is_candidate(item):
    """Worth a detail-page fetch and storing: target city and 2+ beds (or beds unknown)."""
    parsed = parse_address(item.address)
    return parsed is not None and is_target_city(parsed.city) and (item.beds is None or item.beds >= 2)
```

- [ ] **Step 5: Write `listings/scrapers/appfolio.py`**

```python
import logging
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from ..parsing import parse_beds_baths, parse_int, parse_price
from .base import ScrapedListing, Scraper, is_candidate

log = logging.getLogger(__name__)

DETAIL_SECTIONS = ("amenities", "appliances", "utilities included", "pet policy")


def _text(element, separator=" "):
    return element.get_text(separator, strip=True) if element else ""


def parse_list(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for card in soup.select("div.js-listing-item"):
        link = card.select_one(".js-listing-title a") or card.select_one("a[href*='/listings/detail/']")
        if link is None:
            continue
        href = link["href"]
        facts = {
            _text(label).lower(): _text(value)
            for label, value in zip(card.select(".detail-box__label"), card.select(".detail-box__value"))
        }
        beds, baths = parse_beds_baths(facts.get("bed / bath", ""))
        image = card.select_one("img.js-listing-image")
        items.append(
            ScrapedListing(
                external_id=href.rstrip("/").rsplit("/", 1)[-1],
                url=urljoin(base_url, href),
                address=_text(card.select_one(".js-listing-address")),
                price=parse_price(facts.get("rent", "")),
                beds=beds,
                baths=baths,
                sqft=parse_int(facts.get("square feet", "")),
                title=_text(link),
                description=_text(card.select_one(".js-listing-description"), "\n"),
                available=facts.get("available", ""),
                photo_url=(image.get("data-original") or "") if image else "",
            )
        )
    return items


def parse_detail(html):
    soup = BeautifulSoup(html, "html.parser")
    sections = {}
    for heading in soup.select("h3"):
        items = heading.find_next_sibling("ul")
        if items is not None:
            sections[_text(heading).lower()] = [_text(li) for li in items.select("li")]
    amenities = [
        f"{name.title()}: {', '.join(sections[name])}" for name in DETAIL_SECTIONS if sections.get(name)
    ]
    return {
        "description": _text(soup.select_one(".listing-detail__description"), "\n"),
        "amenities": "\n".join(amenities),
    }


class AppFolioScraper(Scraper):
    platform = "appfolio"

    def scrape(self):
        base_url = f"https://{self.options['subdomain']}.appfolio.com"
        items = parse_list(self.fetcher.get(f"{base_url}/listings"), base_url)
        for item in items:
            if not is_candidate(item):
                continue
            try:
                detail = parse_detail(self.fetcher.get(item.url))
            except httpx.HTTPError as exc:
                log.warning("AppFolio detail fetch failed for %s: %s", item.url, exc)
                continue
            item.description = detail["description"] or item.description
            item.amenities = detail["amenities"]
        return items
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_appfolio.py -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: add scraper base and AppFolio scraper"
```

---

### Task 6: Nesthub scraper + source registry

**Files:**
- Create: `listings/scrapers/nesthub.py`, `listings/scrapers/registry.py`, `tests/test_nesthub.py`
- Create fixtures: `tests/fixtures/nesthub_list.html`, `tests/fixtures/nesthub_detail.html`

**Interfaces:**
- Consumes: `ScrapedListing, Scraper, is_candidate` (Task 5); parsers (Task 3).
- Produces: `nesthub.parse_list(html, base_url)`, `nesthub.parse_detail(html) -> dict(sqft, property_type_hint, description, amenities, available)`, `NesthubScraper` (option `list_url`); `registry.SOURCES: list[dict]` (keys `key, name, platform` + platform options), `registry.build_scraper(config, fetcher=None) -> Scraper`.

- [ ] **Step 1: Save fixtures**

```bash
S=/private/tmp/claude-501/-Users-scotttam-Claude-Projects-condo-finder/b09fbf2e-ae09-4499-b55a-1a31fd020e8a/scratchpad
cp $S/uptown.html tests/fixtures/nesthub_list.html
cp $S/nh_detail.html tests/fixtures/nesthub_detail.html
```
Fallback: `curl -sL -A "Mozilla/5.0" https://www.uptownpm.com/portland-homes-for-rent -o tests/fixtures/nesthub_list.html`, then fetch one `/_system/listings/<id>/<slug>` detail page, and update expected values in Step 2.

- [ ] **Step 2: Write the failing tests**

`tests/test_nesthub.py`:
```python
from decimal import Decimal

from listings.scrapers.nesthub import NesthubScraper, parse_detail, parse_list
from listings.scrapers.registry import SOURCES, build_scraper
from tests.helpers import FakeFetcher, load_fixture

BASE = "https://www.uptownpm.com"
LIST_URL = f"{BASE}/portland-homes-for-rent"


def test_parse_list_extracts_cards():
    items = parse_list(load_fixture("nesthub_list.html"), BASE)
    assert len(items) == 19
    item = next(i for i in items if i.external_id == "13")
    assert item.url == f"{BASE}/_system/listings/13/4775-SW-FRANKLIN-AVE-APT-321-Beaverton-OR-97005-2943-US"
    assert item.address == "4775 SW FRANKLIN AVE APT 321, Beaverton, OR 97005"
    assert item.price == 1625
    assert item.beds == 2
    assert item.baths == Decimal("1")
    assert item.property_type_hint == "Apartment"
    assert item.available == "Immediately"
    assert item.title.startswith("Spacious NEW Construction")
    assert item.photo_url.startswith(f"{BASE}/_system/listings/images/")


def test_parse_detail():
    detail = parse_detail(load_fixture("nesthub_detail.html"))
    assert detail["sqft"] == 925
    assert detail["property_type_hint"] == "Apartment"
    assert detail["description"].startswith("Modern new construction")
    assert "Amenities:" not in detail["description"]
    assert "washer/dryer (included)" in detail["amenities"]
    assert detail["available"] == "Immediately"


def test_scraper_enriches_candidates():
    fetcher = FakeFetcher({LIST_URL: load_fixture("nesthub_list.html")}, default=load_fixture("nesthub_detail.html"))
    scraper = NesthubScraper(key="uptown", name="Uptown", fetcher=fetcher, list_url=LIST_URL)
    items = scraper.scrape()
    assert len(items) == 19
    item = next(i for i in items if i.external_id == "13")
    assert item.sqft == 925
    assert "washer/dryer" in item.amenities


def test_registry_builds_every_source():
    keys = [config["key"] for config in SOURCES]
    assert len(keys) == len(set(keys))
    for config in SOURCES:
        scraper = build_scraper(config, fetcher=FakeFetcher({}))
        assert scraper.key == config["key"]
        assert scraper.platform == config["platform"]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_nesthub.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'listings.scrapers.nesthub'`

- [ ] **Step 4: Write `listings/scrapers/nesthub.py`**

```python
import json
import logging
import re
from decimal import Decimal
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from ..parsing import parse_int, parse_price
from .base import ScrapedListing, Scraper, is_candidate

log = logging.getLogger(__name__)


def _text(element):
    return " ".join(element.get_text(" ", strip=True).split()) if element else ""


def parse_list(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for card in soup.select("div.nhw-list__item"):
        link = card.find("a", href=True)
        if link is None:
            continue
        href = link["href"]
        id_match = re.search(r"/_system/listings/(\d+)", href)
        details = _text(card.select_one(".nhw-list__details")).lower()
        beds = re.search(r"beds?:\s*(\d+)", details)
        baths = re.search(r"baths?:\s*(\d+(?:\.\d+)?)", details)
        image = card.select_one("img[data-src]")
        title = (image.get("alt") or "").removesuffix(" property image").strip() if image else ""
        items.append(
            ScrapedListing(
                external_id=id_match.group(1) if id_match else href,
                url=urljoin(base_url, href),
                address=_text(card.select_one(".nhw-list__location")),
                price=parse_price(_text(card.select_one(".nhw-list__price"))),
                beds=int(beds.group(1)) if beds else (0 if "studio" in details else None),
                baths=Decimal(baths.group(1)) if baths else None,
                title=title,
                property_type_hint=_text(card.select_one(".nhw-list__prop-type")),
                available=_text(card.select_one(".nhw-list__availability")).removeprefix("Available:").strip(),
                photo_url=urljoin(base_url, image["data-src"]) if image else "",
            )
        )
    return items


def parse_detail(html):
    soup = BeautifulSoup(html, "html.parser")
    sub_details = {}
    for row in soup.select(".sub-detail"):
        label, value = row.select_one(".sub-detail__label"), row.select_one(".sub-detail__value")
        if label and value:
            sub_details[_text(label).rstrip(":").lower()] = _text(value)
    description = ""
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or "", strict=False)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("description"):
            description = data["description"]
            break
    amenities = ""
    if "Amenities:" in description:
        description, rest = description.split("Amenities:", 1)
        amenities = f"Amenities: {rest.strip()}"
    return {
        "sqft": parse_int(_text(soup.select_one(".key-detail.sqft .value"))),
        "property_type_hint": sub_details.get("building type", ""),
        "description": description.strip(),
        "amenities": amenities,
        "available": sub_details.get("date available", ""),
    }


class NesthubScraper(Scraper):
    platform = "nesthub"

    def scrape(self):
        list_url = self.options["list_url"]
        parts = urlsplit(list_url)
        items = parse_list(self.fetcher.get(list_url), f"{parts.scheme}://{parts.netloc}")
        for item in items:
            if not is_candidate(item):
                continue
            try:
                detail = parse_detail(self.fetcher.get(item.url))
            except httpx.HTTPError as exc:
                log.warning("Nesthub detail fetch failed for %s: %s", item.url, exc)
                continue
            item.sqft = detail["sqft"] or item.sqft
            item.property_type_hint = detail["property_type_hint"] or item.property_type_hint
            item.description = detail["description"] or item.description
            item.amenities = detail["amenities"]
            item.available = detail["available"] or item.available
        return items
```

- [ ] **Step 5: Write `listings/scrapers/registry.py`**

```python
from .appfolio import AppFolioScraper
from .nesthub import NesthubScraper

PLATFORMS = {"appfolio": AppFolioScraper, "nesthub": NesthubScraper}

# To add a property manager, append one entry. AppFolio needs its <subdomain>.appfolio.com;
# Nesthub needs the site's listings page URL.
SOURCES = [
    {"key": "pearl", "name": "Pearl Property Management", "platform": "appfolio", "subdomain": "pearlpropertymanagement"},
    {"key": "living-room", "name": "Living Room Realty", "platform": "appfolio", "subdomain": "livingroomproperty"},
    {"key": "tmg", "name": "The Management Group", "platform": "appfolio", "subdomain": "tmgoregon"},
    {"key": "mainlander", "name": "Mainlander", "platform": "appfolio", "subdomain": "mainlander"},
    {"key": "propm", "name": "PropM (AppFolio)", "platform": "appfolio", "subdomain": "propmhomes"},
    {"key": "utopia", "name": "Utopia Management", "platform": "appfolio", "subdomain": "utopiamanagement"},
    {"key": "uptown", "name": "Uptown Properties", "platform": "nesthub", "list_url": "https://www.uptownpm.com/portland-homes-for-rent"},
    {"key": "propm-site", "name": "PropM (website)", "platform": "nesthub", "list_url": "https://www.propmhomes.com/portland-homes-for-rent"},
]


def build_scraper(config, fetcher=None):
    options = {k: v for k, v in config.items() if k not in ("key", "name", "platform")}
    return PLATFORMS[config["platform"]](key=config["key"], name=config["name"], fetcher=fetcher, **options)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_nesthub.py -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: add Nesthub scraper and source registry"
```

---

### Task 7: Ingest (dedupe, price history, off-market)

**Files:**
- Create: `listings/ingest.py`, `tests/test_ingest.py`
- Modify: `tests/helpers.py` (add `scraped`, `make_source`)

**Interfaces:**
- Consumes: models (Task 2), extractors (Task 3), `parse_address, is_target_city` (Task 4), `ScrapedListing` (Task 5).
- Produces: `ingest(source: Source, items: list[ScrapedListing], now=None) -> IngestResult(seen, skipped, new_listings: list[Listing], price_drops: list[tuple[Listing, int, int]])`; `OVERRIDABLE_FIELDS`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/helpers.py`:
```python
def scraped(**overrides):
    from decimal import Decimal

    from listings.scrapers.base import ScrapedListing

    fields = dict(
        external_id="a1",
        url="https://example.com/a1",
        address="937 NW Glisan Street #435, Portland, OR 97209",
        price=2800,
        beds=2,
        baths=Decimal("2"),
        sqft=1105,
        title="Pearl condo",
        description="2 bed 2 bath condo. 1 reserved parking space. In-unit washer/dryer. Balcony.",
    )
    fields.update(overrides)
    return ScrapedListing(**fields)


def make_source(key="pearl"):
    from listings.models import Source

    return Source.objects.get_or_create(key=key, defaults={"name": key.title(), "platform": "appfolio"})[0]
```

`tests/test_ingest.py`:
```python
from datetime import timedelta

import pytest
from django.utils import timezone

from listings.ingest import ingest
from listings.models import Listing, PriceChange, SourceListing
from tests.helpers import make_source, scraped

pytestmark = pytest.mark.django_db


def test_creates_listing_with_extracted_features():
    result = ingest(make_source(), [scraped()])
    assert result.seen == 1 and len(result.new_listings) == 1
    listing = Listing.objects.get()
    assert listing.address_key == "937 nw glisan st|435|97209"
    assert listing.street == "937 NW Glisan Street"
    assert listing.price == 2800
    assert listing.parking_spaces == 1
    assert listing.has_washer_dryer is True
    assert listing.has_outdoor_space is True
    assert listing.has_ac is None
    assert listing.property_type == "condo"
    assert PriceChange.objects.get().price == 2800
    assert SourceListing.objects.get().url == "https://example.com/a1"


def test_skips_other_cities_and_small_units():
    result = ingest(make_source(), [
        scraped(external_id="x", address="1 Main St, Gresham, OR 97030"),
        scraped(external_id="y", beds=1),
        scraped(external_id="z", beds=None),
        scraped(external_id="w", address="call for address"),
    ])
    assert result.skipped == 4
    assert Listing.objects.count() == 0


def test_merges_same_unit_across_sources():
    ingest(make_source("pearl"), [scraped()])
    result = ingest(make_source("zillow"), [scraped(external_id="z9", url="https://zillow.example/z9",
                                                     address="937 Northwest Glisan St Unit 435, Portland, OR 97209")])
    assert result.new_listings == []
    assert Listing.objects.count() == 1
    assert Listing.objects.get().source_listings.count() == 2


def test_price_drop_is_recorded_and_reported():
    source = make_source()
    ingest(source, [scraped(price=3000)])
    result = ingest(source, [scraped(price=2750)])
    listing = Listing.objects.get()
    assert [p.price for p in listing.price_changes.all()] == [3000, 2750]
    assert result.price_drops == [(listing, 3000, 2750)]


def test_price_increase_recorded_not_reported():
    source = make_source()
    ingest(source, [scraped(price=2800)])
    result = ingest(source, [scraped(price=2900)])
    assert result.price_drops == []
    assert PriceChange.objects.count() == 2


def test_unchanged_price_adds_no_history():
    source = make_source()
    ingest(source, [scraped()])
    ingest(source, [scraped()])
    assert PriceChange.objects.count() == 1


def test_goes_off_market_after_three_missed_runs_and_can_return():
    source = make_source()
    other = scraped(external_id="b2", address="100 SW Main St, Portland, OR 97204")
    ingest(source, [scraped(), other])
    for _ in range(2):
        ingest(source, [other])
    assert Listing.objects.get(street="937 NW Glisan Street").is_active is True
    ingest(source, [other])
    gone = Listing.objects.get(street="937 NW Glisan Street")
    assert gone.is_active is False
    ingest(source, [scraped(), other])
    gone.refresh_from_db()
    assert gone.is_active is True
    assert gone.source_listings.get().missed_runs == 0


def test_listing_stays_active_while_another_source_has_it():
    pearl, zillow = make_source("pearl"), make_source("zillow")
    other = scraped(external_id="b2", address="100 SW Main St, Portland, OR 97204")
    ingest(pearl, [scraped(), other])
    ingest(zillow, [scraped(external_id="z1")])
    for _ in range(3):
        ingest(pearl, [other])
    assert Listing.objects.get(street="937 NW Glisan Street").is_active is True


def test_empty_run_does_not_mark_missing():
    source = make_source()
    ingest(source, [scraped()])
    for _ in range(3):
        ingest(source, [])
    assert Listing.objects.get().is_active is True


def test_manual_overrides_survive_rescrape():
    source = make_source()
    ingest(source, [scraped()])
    Listing.objects.update(overrides={"parking_spaces": 2, "has_ac": True})
    ingest(source, [scraped()])
    listing = Listing.objects.get()
    assert listing.parking_spaces == 2
    assert listing.has_ac is True


def test_known_feature_not_erased_by_source_without_info():
    ingest(make_source("pearl"), [scraped()])
    ingest(make_source("other"), [scraped(external_id="o1", description="Nice place", title="")])
    assert Listing.objects.get().has_washer_dryer is True


def test_first_seen_is_kept_and_last_seen_updates():
    source = make_source()
    earlier = timezone.now() - timedelta(days=2)
    ingest(source, [scraped()], now=earlier)
    ingest(source, [scraped()])
    listing = Listing.objects.get()
    assert listing.first_seen_at == earlier
    assert listing.last_seen_at > earlier
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ingest.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'listings.ingest'`

- [ ] **Step 3: Write `listings/ingest.py`**

```python
from dataclasses import dataclass, field

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .address import is_target_city, parse_address
from .extract import classify_property_type, extract_parking, has_ac, has_outdoor_space, has_washer_dryer
from .models import Listing, PriceChange, PropertyType, SourceListing

OVERRIDABLE_FIELDS = {
    "price", "beds", "baths", "sqft", "parking_spaces", "has_washer_dryer", "has_ac",
    "has_outdoor_space", "property_type", "neighborhood", "available", "title",
}


@dataclass
class IngestResult:
    seen: int = 0
    skipped: int = 0
    new_listings: list = field(default_factory=list)
    price_drops: list = field(default_factory=list)  # (listing, old_price, new_price)


def ingest(source, items, now=None):
    now = now or timezone.now()
    result = IngestResult()
    seen_ids = set()
    for item in items:
        address = parse_address(item.address)
        if address is None or not is_target_city(address.city) or item.beds is None or item.beds < 2:
            result.skipped += 1
            continue
        with transaction.atomic():
            listing, created, old_price = _upsert_listing(address, item, now)
            source_listing = _upsert_source_listing(source, listing, item, now)
        seen_ids.add(source_listing.pk)
        result.seen += 1
        if created:
            result.new_listings.append(listing)
        elif old_price is not None and listing.price is not None and listing.price < old_price:
            result.price_drops.append((listing, old_price, listing.price))
    if items:
        _mark_missing(source, seen_ids)
    return result


def _upsert_listing(address, item, now):
    listing = Listing.objects.filter(address_key=address.key).first()
    created = listing is None
    if created:
        listing = Listing(address_key=address.key, first_seen_at=now)
    old_price = listing.price
    _apply_scraped(listing, address, item)
    for name, value in (listing.overrides or {}).items():
        if name in OVERRIDABLE_FIELDS:
            setattr(listing, name, value)
    listing.is_active = True
    listing.last_seen_at = now
    listing.save()
    if listing.price is not None and listing.price != old_price:
        PriceChange.objects.create(listing=listing, price=listing.price, seen_at=now)
    return listing, created, old_price


def _apply_scraped(listing, address, item):
    text = item.full_text
    listing.address = address.display
    listing.street = address.street
    listing.unit = address.unit
    listing.city = address.city
    listing.zip_code = address.zip_code
    listing.title = (item.title or listing.title)[:300]
    listing.description = "\n\n".join(p for p in (item.description, item.amenities) if p) or listing.description
    listing.available = (item.available or listing.available)[:100]
    listing.photo_url = item.photo_url or listing.photo_url
    for name in ("price", "beds", "baths", "sqft"):
        value = getattr(item, name)
        if value is not None:
            setattr(listing, name, value)
    extracted = {
        "parking_spaces": extract_parking(text),
        "has_washer_dryer": has_washer_dryer(text),
        "has_ac": has_ac(text),
        "has_outdoor_space": has_outdoor_space(text),
    }
    for name, value in extracted.items():
        if value is not None:
            setattr(listing, name, value)
    property_type = classify_property_type(item.property_type_hint, text)
    if property_type != PropertyType.UNKNOWN:
        listing.property_type = property_type


def _upsert_source_listing(source, listing, item, now):
    source_listing, created = SourceListing.objects.get_or_create(
        source=source,
        external_id=item.external_id,
        defaults={"listing": listing, "url": item.url, "first_seen_at": now, "last_seen_at": now},
    )
    if not created:
        source_listing.listing = listing
        source_listing.url = item.url
        source_listing.is_active = True
        source_listing.missed_runs = 0
        source_listing.last_seen_at = now
        source_listing.save()
    return source_listing


def _mark_missing(source, seen_ids):
    affected = set()
    for source_listing in SourceListing.objects.filter(source=source, is_active=True).exclude(pk__in=seen_ids):
        source_listing.missed_runs += 1
        if source_listing.missed_runs >= settings.OFF_MARKET_AFTER_MISSES:
            source_listing.is_active = False
            affected.add(source_listing.listing_id)
        source_listing.save(update_fields=["missed_runs", "is_active"])
    for listing in Listing.objects.filter(pk__in=affected, is_active=True):
        if not listing.source_listings.filter(is_active=True).exists():
            listing.is_active = False
            listing.save(update_fields=["is_active", "updated_at"])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_ingest.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: ingest scraped listings with dedupe, price history, off-market"
```

---

### Task 8: Geocoding

**Files:**
- Create: `listings/geocode.py`, `tests/test_geocode.py`

**Interfaces:**
- Consumes: `Listing` (Task 2).
- Produces: `geocode_address(query: str, client: httpx.Client) -> dict(lat, lng, neighborhood)|None`; `geocode_pending(limit=50, client=None, sleep=time.sleep) -> int`.

- [ ] **Step 1: Write the failing tests**

`tests/test_geocode.py`:
```python
import httpx
import pytest

from listings.geocode import geocode_address, geocode_pending
from tests.helpers import make_listing

NOMINATIM_HIT = [{
    "lat": "45.5268", "lon": "-122.6795",
    "address": {"neighbourhood": "Pearl District", "suburb": "Northwest", "city": "Portland"},
}]


def client_returning(payload, status=200, seen=None):
    def handler(request):
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json=payload)
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_geocode_address_parses_result():
    seen = []
    result = geocode_address("937 NW Glisan Street, Portland, OR 97209", client_returning(NOMINATIM_HIT, seen=seen))
    assert result == {"lat": 45.5268, "lng": -122.6795, "neighborhood": "Pearl District"}
    assert seen[0].url.params["q"] == "937 NW Glisan Street, Portland, OR 97209"
    assert "condo-finder" in seen[0].headers["User-Agent"]


def test_geocode_address_no_match():
    assert geocode_address("nowhere", client_returning([])) is None


@pytest.mark.django_db
def test_geocode_pending_updates_listings():
    listing = make_listing()
    kept = make_listing(address_key="k", neighborhood="Custom")
    count = geocode_pending(client=client_returning(NOMINATIM_HIT), sleep=lambda s: None)
    assert count == 2
    listing.refresh_from_db()
    kept.refresh_from_db()
    assert (listing.latitude, listing.longitude, listing.neighborhood) == (45.5268, -122.6795, "Pearl District")
    assert listing.geocoded_at is not None
    assert kept.neighborhood == "Custom"
    assert geocode_pending(client=client_returning(NOMINATIM_HIT), sleep=lambda s: None) == 0


@pytest.mark.django_db
def test_geocode_pending_marks_misses_attempted():
    listing = make_listing()
    geocode_pending(client=client_returning([]), sleep=lambda s: None)
    listing.refresh_from_db()
    assert listing.latitude is None and listing.geocoded_at is not None


@pytest.mark.django_db
def test_geocode_pending_http_error_retries_later():
    listing = make_listing()
    assert geocode_pending(client=client_returning({}, status=503), sleep=lambda s: None) == 0
    listing.refresh_from_db()
    assert listing.geocoded_at is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_geocode.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'listings.geocode'`

- [ ] **Step 3: Write `listings/geocode.py`**

```python
import logging
import time

import httpx
from django.conf import settings
from django.utils import timezone

from .models import Listing

log = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "condo-finder/0.1 (personal apartment search)"


def geocode_address(query, client):
    params = {"q": query, "format": "jsonv2", "addressdetails": 1, "limit": 1, "countrycodes": "us"}
    if settings.NOMINATIM_EMAIL:
        params["email"] = settings.NOMINATIM_EMAIL
    response = client.get(NOMINATIM_URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=20)
    response.raise_for_status()
    results = response.json()
    if not results:
        return None
    hit = results[0]
    address = hit.get("address", {})
    return {
        "lat": float(hit["lat"]),
        "lng": float(hit["lon"]),
        "neighborhood": address.get("neighbourhood") or address.get("suburb") or address.get("quarter") or "",
    }


def geocode_pending(limit=50, client=None, sleep=time.sleep):
    """Geocode listings never attempted before. Nominatim allows at most 1 request/second."""
    client = client or httpx.Client()
    done = 0
    for listing in Listing.objects.filter(geocoded_at__isnull=True).order_by("pk")[:limit]:
        query = f"{listing.street}, {listing.city}, OR {listing.zip_code}".strip()
        try:
            result = geocode_address(query, client)
        except httpx.HTTPError as exc:
            log.warning("Geocoding failed (will retry next run): %s", exc)
            break
        if result:
            listing.latitude = result["lat"]
            listing.longitude = result["lng"]
            listing.neighborhood = listing.neighborhood or result["neighborhood"]
        listing.geocoded_at = timezone.now()
        listing.save(update_fields=["latitude", "longitude", "neighborhood", "geocoded_at"])
        done += 1
        sleep(1.1)
    return done
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_geocode.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: geocode listings with Nominatim"
```

---

### Task 9: Push notifications and alert criteria

**Files:**
- Create: `listings/notify.py`, `tests/test_notify.py`

**Interfaces:**
- Consumes: `Listing, PropertyType, Status` (Task 2).
- Produces: `send_push(title, message, url="", tags=None) -> bool`; `matches_alert_criteria(listing) -> bool`; `summarize(listing) -> str`; `listing_url(listing) -> str` (`{SITE_URL}/listing/{pk}/`); `alert_new_listings(listings) -> int`; `alert_price_drops(drops) -> int`; `MAX_INDIVIDUAL_ALERTS = 5`.

- [ ] **Step 1: Write the failing tests**

`tests/test_notify.py`:
```python
import itertools
from decimal import Decimal

import httpx
import pytest

from listings import notify
from listings.models import PropertyType, Status
from tests.helpers import make_listing

pytestmark = pytest.mark.django_db

_keys = itertools.count()


def good(**overrides):
    fields = dict(price=3200, beds=2, baths=Decimal("2"), sqft=1100, parking_spaces=2,
                  has_washer_dryer=True, has_ac=None, has_outdoor_space=True, property_type=PropertyType.CONDO)
    fields.update(overrides)
    return make_listing(address_key=f"key-{next(_keys)}", **fields)


@pytest.fixture
def pushes(monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "send_push", lambda title, message, url="", tags=None: sent.append((title, message, url)) or True)
    return sent


def test_criteria_accepts_unknowns():
    assert notify.matches_alert_criteria(good(parking_spaces=None, has_washer_dryer=None))


@pytest.mark.parametrize("overrides", [
    {"beds": 1}, {"baths": Decimal("1.5")}, {"price": 6000}, {"price": None},
    {"property_type": PropertyType.APARTMENT}, {"parking_spaces": 1},
    {"has_washer_dryer": False}, {"has_ac": False}, {"has_outdoor_space": False},
])
def test_criteria_rejects_known_failures(overrides):
    assert not notify.matches_alert_criteria(good(**overrides))


def test_summarize():
    listing = good(parking_spaces=None)
    assert notify.summarize(listing) == "$3,200 · 2bd/2ba · 1,100 sqft · parking ? · Portland"


def test_alert_new_listings_only_matches(pushes):
    listing = good()
    assert notify.alert_new_listings([listing, good(beds=1)]) == 1
    title, message, url = pushes[0]
    assert title == "New: 937 NW Glisan Street"
    assert url == f"http://testserver/listing/{listing.pk}/"


def test_alert_new_listings_caps_individual_pushes(pushes):
    listings = [good(sqft=1000 + i) for i in range(8)]
    notify.alert_new_listings(listings)
    assert len(pushes) == notify.MAX_INDIVIDUAL_ALERTS + 1
    assert pushes[-1][0] == "3 more new matches"


def test_alert_price_drops_only_for_interested(pushes):
    interested = good(status=Status.INTERESTED)
    ignored = good(sqft=999)
    assert notify.alert_price_drops([(interested, 3400, 3200), (ignored, 3400, 3200)]) == 1
    assert pushes[0][0] == "Price drop: 937 NW Glisan Street"
    assert pushes[0][1].startswith("$3,400 → $3,200")


def test_send_push_disabled_without_topic():
    assert notify.send_push("t", "m") is False


def test_send_push_posts_json(settings, monkeypatch):
    settings.NTFY_TOPIC = "condo-topic"
    calls = []

    def fake_post(url, json, timeout):
        calls.append((url, json))
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(notify.httpx, "post", fake_post)
    assert notify.send_push("Title — ok", "Body", url="http://x/1", tags=["house"]) is True
    assert calls == [("https://ntfy.sh", {"topic": "condo-topic", "title": "Title — ok", "message": "Body", "click": "http://x/1", "tags": ["house"]})]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_notify.py -q`
Expected: FAIL with `ImportError: cannot import name 'notify'`

- [ ] **Step 3: Write `listings/notify.py`**

```python
import logging

import httpx
from django.conf import settings

from .models import PropertyType, Status

log = logging.getLogger(__name__)

MAX_INDIVIDUAL_ALERTS = 5


def send_push(title, message, url="", tags=None):
    if not settings.NTFY_TOPIC:
        log.info("Push (ntfy disabled): %s | %s", title, message)
        return False
    payload = {"topic": settings.NTFY_TOPIC, "title": title, "message": message}
    if url:
        payload["click"] = url
    if tags:
        payload["tags"] = tags
    try:
        httpx.post(settings.NTFY_SERVER, json=payload, timeout=10).raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("ntfy push failed: %s", exc)
        return False
    return True


def matches_alert_criteria(listing):
    """Known failures disqualify; unknowns pass."""
    if listing.beds is None or listing.beds < 2:
        return False
    if listing.baths is None or listing.baths < 2:
        return False
    if listing.price is None or listing.price > settings.ALERT_MAX_PRICE:
        return False
    if listing.property_type == PropertyType.APARTMENT:
        return False
    if listing.parking_spaces is not None and listing.parking_spaces < 2:
        return False
    return all(value is not False for value in (listing.has_washer_dryer, listing.has_ac, listing.has_outdoor_space))


def summarize(listing):
    baths = "?" if listing.baths is None else f"{listing.baths.normalize():f}"
    parts = [f"${listing.price:,}" if listing.price else "price ?", f"{listing.beds}bd/{baths}ba"]
    if listing.sqft:
        parts.append(f"{listing.sqft:,} sqft")
    parts.append(f"parking {'?' if listing.parking_spaces is None else listing.parking_spaces}")
    parts.append(listing.city)
    return " · ".join(parts)


def listing_url(listing):
    return f"{settings.SITE_URL}/listing/{listing.pk}/"


def alert_new_listings(listings):
    matches = [listing for listing in listings if matches_alert_criteria(listing)]
    for listing in matches[:MAX_INDIVIDUAL_ALERTS]:
        send_push(f"New: {listing.street}", summarize(listing), url=listing_url(listing), tags=["house"])
    extra = len(matches) - MAX_INDIVIDUAL_ALERTS
    if extra > 0:
        send_push(f"{extra} more new matches", "Open Condo Finder to see them.", url=f"{settings.SITE_URL}/")
    return len(matches)


def alert_price_drops(drops):
    sent = 0
    for listing, old_price, new_price in drops:
        if listing.status != Status.INTERESTED:
            continue
        send_push(
            f"Price drop: {listing.street}",
            f"${old_price:,} → ${new_price:,} · {summarize(listing)}",
            url=listing_url(listing),
            tags=["chart_with_downwards_trend"],
        )
        sent += 1
    return sent
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_notify.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: ntfy push alerts for new matches and price drops"
```

---

### Task 10: Runner, health tracking, `scrape` command

**Files:**
- Create: `listings/runner.py`, `listings/management/__init__.py`, `listings/management/commands/__init__.py`, `listings/management/commands/scrape.py`, `tests/test_runner.py`

**Interfaces:**
- Consumes: `SOURCES, build_scraper` (Task 6), `ingest` (Task 7), `geocode_pending` (Task 8), `alert_new_listings, alert_price_drops, send_push` (Task 9).
- Produces: `sync_sources()`, `run_source(config, fetcher=None) -> SourceRun`, `run_all(keys=None, geocode=True) -> list[SourceRun]`, `run_all_in_background() -> Thread`, `is_running() -> bool`, `EmptyScrape`. Command `manage.py scrape [--source KEY ...] [--no-geocode]`.

- [ ] **Step 1: Write the failing tests**

`tests/test_runner.py`:
```python
import httpx
import pytest
from django.core.management import call_command

from listings import runner
from listings.models import Listing, Source, SourceRun
from tests.helpers import FakeFetcher, load_fixture

pytestmark = pytest.mark.django_db

PEARL = {"key": "pearl", "name": "Pearl", "platform": "appfolio", "subdomain": "pearlpropertymanagement"}
LIST_URL = "https://pearlpropertymanagement.appfolio.com/listings"


@pytest.fixture
def pushes(monkeypatch):
    sent = []
    monkeypatch.setattr(runner, "send_push", lambda title, message, url="", tags=None: sent.append(title))
    return sent


class BrokenFetcher:
    def get(self, url):
        raise httpx.ConnectError("blocked")


def pearl_fetcher():
    return FakeFetcher({LIST_URL: load_fixture("appfolio_list.html")}, default=load_fixture("appfolio_detail.html"))


def test_successful_run_ingests_and_records(pushes):
    run = runner.run_source(PEARL, fetcher=pearl_fetcher())
    assert run.ok and run.count == 7 and run.finished_at is not None
    assert run.new_count == Listing.objects.count() > 0
    source = Source.objects.get(key="pearl")
    assert source.last_count == 7 and source.consecutive_failures == 0 and source.last_success_at


def test_failures_alert_on_third_in_a_row(pushes):
    for _ in range(2):
        run = runner.run_source(PEARL, fetcher=BrokenFetcher())
        assert not run.ok and "ConnectError" in run.error
    assert pushes == []
    runner.run_source(PEARL, fetcher=BrokenFetcher())
    assert pushes == ["Scraper failing: Pearl"]
    assert Source.objects.get(key="pearl").consecutive_failures == 3


def test_success_resets_failures(pushes):
    runner.run_source(PEARL, fetcher=BrokenFetcher())
    runner.run_source(PEARL, fetcher=pearl_fetcher())
    assert Source.objects.get(key="pearl").consecutive_failures == 0


def test_empty_result_after_nonzero_alerts_immediately(pushes):
    runner.run_source(PEARL, fetcher=pearl_fetcher())
    run = runner.run_source(PEARL, fetcher=FakeFetcher({LIST_URL: "<html></html>"}))
    assert not run.ok and "0 listings" in run.error
    assert pushes == ["Pearl returned 0 listings"]
    assert Listing.objects.filter(is_active=True).count() > 0


def test_run_all_filters_keys_and_geocodes(monkeypatch):
    called = []
    monkeypatch.setattr(runner, "run_source", lambda config: called.append(config["key"]) or config["key"])
    monkeypatch.setattr(runner, "geocode_pending", lambda: called.append("geocode"))
    assert runner.run_all(keys=["uptown", "pearl"]) == ["pearl", "uptown"]
    assert called == ["pearl", "uptown", "geocode"]


def test_run_all_skips_when_already_running(monkeypatch):
    monkeypatch.setattr(runner, "run_source", lambda config: pytest.fail("should not run"))
    runner._run_lock.acquire()
    try:
        assert runner.is_running()
        assert runner.run_all() == []
    finally:
        runner._run_lock.release()


def test_scrape_command(monkeypatch, capsys):
    source = Source.objects.create(key="pearl", name="Pearl", platform="appfolio")
    fake_run = SourceRun(source=source, ok=True, count=7, new_count=2)
    monkeypatch.setattr("listings.management.commands.scrape.run_all", lambda keys, geocode: [fake_run])
    call_command("scrape", "--source", "pearl", "--no-geocode")
    assert "pearl: ok — 7 listings, 2 new" in capsys.readouterr().out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_runner.py -q`
Expected: FAIL with `ImportError: cannot import name 'runner'`

- [ ] **Step 3: Write `listings/runner.py`**

```python
import logging
import threading

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

from .geocode import geocode_pending
from .ingest import ingest
from .models import Source, SourceRun
from .notify import alert_new_listings, alert_price_drops, send_push
from .scrapers.registry import SOURCES, build_scraper

log = logging.getLogger(__name__)

_run_lock = threading.Lock()


class EmptyScrape(Exception):
    pass


def _source_for(config):
    source, _ = Source.objects.update_or_create(
        key=config["key"], defaults={"name": config["name"], "platform": config["platform"]}
    )
    return source


def sync_sources():
    for config in SOURCES:
        _source_for(config)


def run_source(config, fetcher=None):
    source = _source_for(config)
    run = SourceRun.objects.create(source=source)
    try:
        items = build_scraper(config, fetcher=fetcher).scrape()
        if not items:
            raise EmptyScrape("scraper returned 0 listings")
        result = ingest(source, items)
    except Exception as exc:  # one broken source must never stop the others
        log.exception("Source %s failed", source.key)
        _record_failure(source, run, exc)
        return run
    now = timezone.now()
    run.ok = True
    run.count = len(items)
    run.new_count = len(result.new_listings)
    run.finished_at = now
    run.save()
    source.consecutive_failures = 0
    source.last_success_at = now
    source.last_count = len(items)
    source.save()
    alert_new_listings(result.new_listings)
    alert_price_drops(result.price_drops)
    log.info("Source %s: %d listings (%d stored, %d new)", source.key, len(items), result.seen, run.new_count)
    return run


def _record_failure(source, run, exc):
    now = timezone.now()
    run.error = f"{type(exc).__name__}: {exc}"[:2000]
    run.finished_at = now
    run.save()
    source.consecutive_failures += 1
    source.last_error = run.error
    source.last_error_at = now
    source.save()
    sources_url = f"{settings.SITE_URL}/sources/"
    if isinstance(exc, EmptyScrape) and source.consecutive_failures == 1 and source.last_count:
        send_push(
            f"{source.name} returned 0 listings",
            f"It had {source.last_count} last time. The site may have changed or blocked us.",
            url=sources_url,
            tags=["warning"],
        )
    elif source.consecutive_failures == settings.HEALTH_ALERT_AFTER_FAILURES:
        send_push(
            f"Scraper failing: {source.name}",
            f"{source.consecutive_failures} failed runs in a row. {run.error}",
            url=sources_url,
            tags=["warning"],
        )


def is_running():
    return _run_lock.locked()


def run_all(keys=None, geocode=True):
    if not _run_lock.acquire(blocking=False):
        log.info("Scrape already running; skipping")
        return []
    try:
        runs = [run_source(config) for config in SOURCES if keys is None or config["key"] in keys]
        if geocode:
            try:
                geocode_pending()
            except Exception:
                log.exception("Geocoding pass failed")
        return runs
    finally:
        _run_lock.release()


def run_all_in_background():
    def target():
        try:
            run_all()
        finally:
            close_old_connections()

    thread = threading.Thread(target=target, name="scrape-now", daemon=True)
    thread.start()
    return thread
```

- [ ] **Step 4: Write the command** (`listings/management/__init__.py` and `listings/management/commands/__init__.py` empty)

`listings/management/commands/scrape.py`:
```python
from django.core.management.base import BaseCommand

from listings.runner import run_all


class Command(BaseCommand):
    help = "Scrape listing sources now."

    def add_arguments(self, parser):
        parser.add_argument("--source", action="append", dest="sources", help="Source key (repeatable). Default: all.")
        parser.add_argument("--no-geocode", action="store_true", help="Skip geocoding new listings.")

    def handle(self, *args, **options):
        for run in run_all(keys=options["sources"], geocode=not options["no_geocode"]):
            status = "ok" if run.ok else f"FAILED ({run.error})"
            self.stdout.write(f"{run.source.key}: {status} — {run.count} listings, {run.new_count} new")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: scrape runner with health tracking and scrape command"
```

---

### Task 11: Browse UI — filters, list, map, detail, status/notes

**Files:**
- Create: `listings/forms.py`, `listings/filters.py`, `listings/views.py` (replace), `listings/templates/listings/base.html`, `list.html`, `_card.html`, `_status.html`, `_feature.html`, `detail.html`, `_tracking.html`, `tests/test_filters.py`, `tests/test_views.py`
- Modify: `listings/urls.py`

**Interfaces:**
- Consumes: models (Task 2), `listing_url` path shape `/listing/<pk>/` (Task 9).
- Produces: `default_filter_data() -> dict`, `ListingFilterForm`, `TrackingForm`, `apply_filters(qs, cleaned_data) -> QuerySet`; URL names `listing_list`, `listing_detail`, `update_tracking`, `set_status`, `sources`, `scrape_now`. All six views are written here (`base.html` links to `sources`); Task 12 builds the full sources template and its tests.

- [ ] **Step 1: Write the failing tests**

`tests/test_filters.py`:
```python
from decimal import Decimal

import pytest

from listings.filters import apply_filters
from listings.forms import ListingFilterForm, default_filter_data
from listings.models import Listing, PropertyType, Status
from tests.helpers import make_listing

pytestmark = pytest.mark.django_db


def listing(key, **fields):
    base = dict(price=3000, beds=2, baths=Decimal("2"), parking_spaces=2, property_type=PropertyType.CONDO)
    base.update(fields)
    return make_listing(address_key=key, **base)


def filtered(data=None):
    form = ListingFilterForm(data or default_filter_data())
    assert form.is_valid(), form.errors
    return set(apply_filters(Listing.objects.all(), form.cleaned_data).values_list("address_key", flat=True))


def test_defaults_apply_2_2_2_and_hide_apartments_rejected_inactive():
    listing("ok")
    listing("unknown-parking", parking_spaces=None)
    listing("one-bath", baths=Decimal("1"))
    listing("one-spot", parking_spaces=1)
    listing("apartment", property_type=PropertyType.APARTMENT)
    listing("rejected", status=Status.REJECTED)
    listing("gone", is_active=False)
    listing("pricey", price=6500)
    listing("no-wd", has_washer_dryer=False)
    assert filtered() == {"ok", "unknown-parking"}


def test_feature_yes_requires_known_true():
    listing("yes", has_ac=True)
    listing("unknown", has_ac=None)
    data = default_filter_data() | {"ac": "yes"}
    assert filtered(data) == {"yes"}


def test_exclude_unknown_parking():
    listing("ok")
    listing("unknown-parking", parking_spaces=None)
    data = {k: v for k, v in default_filter_data().items() if k != "parking_unknown"}
    assert filtered(data) == {"ok"}


def test_city_and_neighborhood():
    listing("pearl", neighborhood="Pearl District")
    listing("lo", city="Lake Oswego")
    assert filtered(default_filter_data() | {"cities": ["Lake Oswego"]}) == {"lo"}
    assert filtered(default_filter_data() | {"neighborhood": "pearl"}) == {"pearl"}


def test_sort_by_price_per_sqft():
    listing("cheap-per-sqft", price=3000, sqft=1500)
    listing("pricey-per-sqft", price=2500, sqft=800)
    form = ListingFilterForm(default_filter_data() | {"sort": "ppsf"})
    assert form.is_valid()
    keys = list(apply_filters(Listing.objects.all(), form.cleaned_data).values_list("address_key", flat=True))
    assert keys == ["cheap-per-sqft", "pricey-per-sqft"]
```

`tests/test_views.py`:
```python
from decimal import Decimal

import pytest

from listings.models import Status
from tests.helpers import make_listing

pytestmark = pytest.mark.django_db


def good_listing(**fields):
    base = dict(price=3000, beds=2, baths=Decimal("2"), parking_spaces=2, latitude=45.52, longitude=-122.68,
                title="Pearl condo", property_type="condo")
    base.update(fields)
    return make_listing(**base)


def test_list_page_shows_matching_listing_and_map_data(client):
    listing = good_listing()
    response = client.get("/")
    assert response.status_code == 200
    assert b"937 NW Glisan Street" in response.content
    assert response.context["map_points"][0]["id"] == listing.pk


def test_list_page_respects_query_filters(client):
    good_listing()
    response = client.get("/?min_beds=3")
    assert b"937 NW Glisan Street" not in response.content


def test_detail_page(client):
    listing = good_listing()
    response = client.get(f"/listing/{listing.pk}/")
    assert response.status_code == 200
    assert b"Pearl condo" in response.content
    assert listing.get_absolute_url() == f"/listing/{listing.pk}/"


def test_update_tracking_htmx_returns_partial(client):
    listing = good_listing()
    response = client.post(f"/listing/{listing.pk}/tracking/", {"status": "toured", "notes": "Great light"},
                           HTTP_HX_REQUEST="true")
    assert response.status_code == 200
    assert b"Saved" in response.content
    listing.refresh_from_db()
    assert (listing.status, listing.notes) == (Status.TOURED, "Great light")


def test_set_status_keeps_notes(client):
    listing = good_listing(notes="keep me")
    response = client.post(f"/listing/{listing.pk}/status/", {"status": "interested"}, HTTP_HX_REQUEST="true")
    assert response.status_code == 200
    listing.refresh_from_db()
    assert (listing.status, listing.notes) == (Status.INTERESTED, "keep me")


def test_set_status_rejects_invalid(client):
    listing = good_listing()
    assert client.post(f"/listing/{listing.pk}/status/", {"status": "bogus"}).status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_filters.py tests/test_views.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'listings.filters'`

- [ ] **Step 3: Write `listings/forms.py`**

```python
from django import forms
from django.conf import settings

from .models import Listing, PropertyType, Status

FEATURE_CHOICES = [("any", "Any"), ("yes_or_unknown", "Yes or unknown"), ("yes", "Yes")]
SORT_CHOICES = [("price", "Price ↑"), ("-price", "Price ↓"), ("newest", "Newest"), ("ppsf", "$/sqft ↑")]


def default_filter_data():
    return {
        "min_beds": "2",
        "min_baths": "2",
        "min_parking": "2",
        "parking_unknown": "on",
        "max_price": str(settings.DEFAULT_MAX_PRICE),
        "types": [value for value, _ in PropertyType.choices if value != PropertyType.APARTMENT],
        "statuses": [value for value, _ in Status.choices if value != Status.REJECTED],
        "wd": "yes_or_unknown",
        "ac": "yes_or_unknown",
        "outdoor": "yes_or_unknown",
        "sort": "price",
    }


class ListingFilterForm(forms.Form):
    min_beds = forms.IntegerField(required=False, min_value=0, label="Min beds")
    min_baths = forms.DecimalField(required=False, min_value=0, decimal_places=1, label="Min baths")
    min_parking = forms.IntegerField(required=False, min_value=0, label="Min parking")
    parking_unknown = forms.BooleanField(required=False, label="Include unknown parking")
    max_price = forms.IntegerField(required=False, min_value=0, label="Max price")
    cities = forms.MultipleChoiceField(required=False, widget=forms.CheckboxSelectMultiple)
    neighborhood = forms.CharField(required=False)
    types = forms.MultipleChoiceField(required=False, choices=PropertyType.choices, widget=forms.CheckboxSelectMultiple)
    statuses = forms.MultipleChoiceField(required=False, choices=Status.choices, widget=forms.CheckboxSelectMultiple)
    wd = forms.ChoiceField(required=False, choices=FEATURE_CHOICES, label="In-unit W/D")
    ac = forms.ChoiceField(required=False, choices=FEATURE_CHOICES, label="AC")
    outdoor = forms.ChoiceField(required=False, choices=FEATURE_CHOICES, label="Outdoor space")
    show_inactive = forms.BooleanField(required=False, label="Show off-market")
    sort = forms.ChoiceField(required=False, choices=SORT_CHOICES)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cities"].choices = [(city, city) for city in settings.TARGET_CITIES]


class TrackingForm(forms.ModelForm):
    class Meta:
        model = Listing
        fields = ["status", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 6})}
```

- [ ] **Step 4: Write `listings/filters.py`**

```python
from django.db.models import ExpressionWrapper, F, FloatField, Q
from django.db.models.functions import Cast

FEATURE_FIELDS = {"wd": "has_washer_dryer", "ac": "has_ac", "outdoor": "has_outdoor_space"}


def apply_filters(queryset, data):
    if not data.get("show_inactive"):
        queryset = queryset.filter(is_active=True)
    if data.get("min_beds") is not None:
        queryset = queryset.filter(beds__gte=data["min_beds"])
    if data.get("min_baths") is not None:
        queryset = queryset.filter(baths__gte=data["min_baths"])
    if data.get("min_parking") is not None:
        parking = Q(parking_spaces__gte=data["min_parking"])
        if data.get("parking_unknown"):
            parking |= Q(parking_spaces__isnull=True)
        queryset = queryset.filter(parking)
    if data.get("max_price") is not None:
        queryset = queryset.filter(price__lte=data["max_price"])
    if data.get("cities"):
        queryset = queryset.filter(city__in=data["cities"])
    if data.get("neighborhood"):
        queryset = queryset.filter(neighborhood__icontains=data["neighborhood"])
    if data.get("types"):
        queryset = queryset.filter(property_type__in=data["types"])
    if data.get("statuses"):
        queryset = queryset.filter(status__in=data["statuses"])
    for key, field in FEATURE_FIELDS.items():
        if data.get(key) == "yes":
            queryset = queryset.filter(**{field: True})
        elif data.get(key) == "yes_or_unknown":
            queryset = queryset.exclude(**{field: False})
    return _sort(queryset, data.get("sort") or "price")


def _sort(queryset, sort):
    if sort == "-price":
        return queryset.order_by(F("price").desc(nulls_last=True))
    if sort == "newest":
        return queryset.order_by("-first_seen_at")
    if sort == "ppsf":
        per_sqft = ExpressionWrapper(Cast("price", FloatField()) / F("sqft"), output_field=FloatField())
        return queryset.annotate(ppsf=per_sqft).order_by(F("ppsf").asc(nulls_last=True), "price")
    return queryset.order_by(F("price").asc(nulls_last=True))
```

- [ ] **Step 5: Write `listings/views.py`**

```python
from django.contrib import messages
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .filters import apply_filters
from .forms import ListingFilterForm, TrackingForm, default_filter_data
from .models import Listing, Source, SourceRun, Status
from .runner import is_running, run_all_in_background, sync_sources

MAX_RESULTS = 500


def listing_list(request):
    form = ListingFilterForm(request.GET or default_filter_data())
    queryset = Listing.objects.all()
    if form.is_valid():
        queryset = apply_filters(queryset, form.cleaned_data)
    listings = list(queryset[:MAX_RESULTS])
    map_points = [
        {
            "id": listing.pk,
            "lat": listing.latitude,
            "lng": listing.longitude,
            "label": f"${listing.price:,} · {listing.beds}bd · {listing.street}" if listing.price else listing.street,
            "url": listing.get_absolute_url(),
        }
        for listing in listings
        if listing.latitude is not None
    ]
    return render(request, "listings/list.html", {"form": form, "listings": listings, "map_points": map_points})


def listing_detail(request, pk):
    listing = get_object_or_404(
        Listing.objects.prefetch_related("source_listings__source", "price_changes"), pk=pk
    )
    return render(request, "listings/detail.html", {"listing": listing, "tracking_form": TrackingForm(instance=listing)})


@require_POST
def update_tracking(request, pk):
    listing = get_object_or_404(Listing, pk=pk)
    form = TrackingForm(request.POST, instance=listing)
    saved = form.is_valid()
    if saved:
        form.save()
    if request.headers.get("HX-Request"):
        return render(request, "listings/_tracking.html", {"listing": listing, "tracking_form": form, "saved": saved})
    return redirect(listing)


@require_POST
def set_status(request, pk):
    listing = get_object_or_404(Listing, pk=pk)
    status = request.POST.get("status")
    if status not in Status.values:
        return HttpResponseBadRequest("invalid status")
    listing.status = status
    listing.save(update_fields=["status", "updated_at"])
    if request.headers.get("HX-Request"):
        return render(request, "listings/_status.html", {"listing": listing})
    referer = request.META.get("HTTP_REFERER", "")
    if url_has_allowed_host_and_scheme(referer, allowed_hosts={request.get_host()}):
        return redirect(referer)
    return redirect("listing_list")


def sources(request):
    sync_sources()
    return render(request, "listings/sources.html", {
        "sources": Source.objects.all(),
        "runs": SourceRun.objects.select_related("source")[:40],
        "running": is_running(),
    })


@require_POST
def scrape_now(request):
    if is_running():
        messages.info(request, "A scrape is already running.")
    else:
        run_all_in_background()
        messages.success(request, "Scrape started. Refresh this page in a few minutes.")
    return redirect("sources")
```

- [ ] **Step 6: Replace `listings/urls.py`**

```python
from django.urls import path

from . import views

urlpatterns = [
    path("", views.listing_list, name="listing_list"),
    path("listing/<int:pk>/", views.listing_detail, name="listing_detail"),
    path("listing/<int:pk>/tracking/", views.update_tracking, name="update_tracking"),
    path("listing/<int:pk>/status/", views.set_status, name="set_status"),
    path("sources/", views.sources, name="sources"),
    path("sources/scrape/", views.scrape_now, name="scrape_now"),
]
```

- [ ] **Step 7: Write templates**

`listings/templates/listings/base.html`:
```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}Condo Finder{% endblock %}</title>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
  <script src="https://cdn.jsdelivr.net/npm/htmx.org@2.0.4/dist/htmx.min.js"></script>
  <style>
    :root { --bg:#f7f7f5; --card:#fff; --ink:#1f2328; --muted:#667085; --line:#e4e4e0; --accent:#2f6f5e;
            --yes:#1f7a4d; --no:#b42318; --unk:#8a6d00; }
    * { box-sizing: border-box; }
    body { margin:0; font:15px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background:var(--bg); color:var(--ink); }
    header { display:flex; align-items:center; gap:24px; padding:12px 20px; background:var(--card); border-bottom:1px solid var(--line); }
    header .brand { font-weight:700; color:var(--accent); text-decoration:none; font-size:18px; }
    header nav a { margin-right:16px; color:var(--ink); text-decoration:none; }
    main { padding:20px; max-width:1400px; margin:0 auto; }
    a { color:var(--accent); }
    .messages { list-style:none; margin:12px 20px 0; padding:10px 14px; background:#eaf4ef; border-radius:8px; }
    .layout { display:grid; grid-template-columns:260px 1fr; gap:20px; align-items:start; }
    .filters { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px; position:sticky; top:12px; }
    .filters label { display:block; font-size:13px; color:var(--muted); margin-top:8px; }
    .filters input[type=number], .filters input[type=text], .filters select { width:100%; padding:5px 7px; }
    .filters ul { list-style:none; padding:0; margin:2px 0; } .filters ul label { color:var(--ink); margin:0; }
    .filters button { margin-top:12px; width:100%; padding:8px; background:var(--accent); color:#fff; border:0; border-radius:6px; cursor:pointer; }
    #map { height:380px; border-radius:10px; border:1px solid var(--line); margin-bottom:16px; }
    .grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(300px, 1fr)); gap:16px; }
    .card { background:var(--card); border:1px solid var(--line); border-radius:10px; overflow:hidden; display:flex; flex-direction:column; }
    .card img { width:100%; height:180px; object-fit:cover; background:#ddd; }
    .card .body { padding:12px; display:flex; flex-direction:column; gap:6px; flex:1; }
    .price { font-size:20px; font-weight:700; }
    .muted { color:var(--muted); font-size:13px; }
    .feat { display:inline-block; font-size:12px; padding:1px 7px; border-radius:10px; margin:0 4px 4px 0; border:1px solid currentColor; }
    .feat.yes { color:var(--yes); } .feat.no { color:var(--no); } .feat.unk { color:var(--unk); }
    .status { font-size:12px; padding:2px 8px; border-radius:10px; background:#eef; }
    .status-interested { background:#e3f5ea; } .status-rejected { background:#fde8e7; } .status-toured, .status-applied { background:#fff4d6; }
    .status-controls { display:flex; gap:6px; align-items:center; margin-top:auto; }
    .status-controls button { font-size:12px; padding:3px 8px; border:1px solid var(--line); background:#fff; border-radius:6px; cursor:pointer; }
    .offmarket { color:var(--no); font-weight:600; font-size:12px; }
    table { border-collapse:collapse; width:100%; background:var(--card); }
    th, td { text-align:left; padding:6px 10px; border-bottom:1px solid var(--line); font-size:14px; vertical-align:top; }
    .detail { display:grid; grid-template-columns:1fr 360px; gap:24px; }
    .detail img.hero { width:100%; max-height:420px; object-fit:cover; border-radius:10px; }
    .panel { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px; margin-bottom:16px; }
    .description { white-space:pre-line; }
    .saved { color:var(--yes); margin-left:8px; }
    @media (max-width: 800px) { .layout, .detail { grid-template-columns:1fr; } .filters { position:static; } }
  </style>
</head>
<body hx-headers='{"X-CSRFToken": "{{ csrf_token }}"}'>
  <header>
    <a class="brand" href="{% url 'listing_list' %}">Condo Finder</a>
    <nav>
      <a href="{% url 'listing_list' %}">Listings</a>
      <a href="{% url 'sources' %}">Sources</a>
      <a href="/admin/">Admin</a>
    </nav>
  </header>
  {% if messages %}<ul class="messages">{% for message in messages %}<li>{{ message }}</li>{% endfor %}</ul>{% endif %}
  <main>{% block content %}{% endblock %}</main>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
  {% block scripts %}{% endblock %}
</body>
</html>
```

`listings/templates/listings/_feature.html`:
```html
<span class="feat {% if value %}yes{% elif value is False %}no{% else %}unk{% endif %}">{{ label }} {% if value %}✓{% elif value is False %}✗{% else %}?{% endif %}</span>
```

`listings/templates/listings/_status.html`:
```html
<form class="status-controls" id="status-{{ listing.pk }}" method="post" action="{% url 'set_status' listing.pk %}"
      hx-post="{% url 'set_status' listing.pk %}" hx-target="#status-{{ listing.pk }}" hx-swap="outerHTML">
  {% csrf_token %}
  <span class="status status-{{ listing.status }}">{{ listing.get_status_display }}</span>
  <button type="submit" name="status" value="interested">♥ Interested</button>
  <button type="submit" name="status" value="rejected">✗ Reject</button>
</form>
```

`listings/templates/listings/_card.html`:
```html
{% load humanize %}
<article class="card">
  <a href="{{ listing.get_absolute_url }}">
    {% if listing.photo_url %}<img src="{{ listing.photo_url }}" alt="" loading="lazy">{% else %}<img alt="">{% endif %}
  </a>
  <div class="body">
    <div class="price">{% if listing.price %}${{ listing.price|intcomma }}{% else %}Price ?{% endif %}
      {% if not listing.is_active %}<span class="offmarket">Off market</span>{% endif %}</div>
    <div>{{ listing.beds }} bd · {{ listing.baths|floatformat:"-1" }} ba{% if listing.sqft %} · {{ listing.sqft|intcomma }} sqft{% endif %}
      · <strong>{% if listing.parking_spaces is None %}? parking{% else %}{{ listing.parking_spaces }} parking{% endif %}</strong></div>
    <a href="{{ listing.get_absolute_url }}">{{ listing.street }}{% if listing.unit %} #{{ listing.unit }}{% endif %}</a>
    <div class="muted">{{ listing.city }}{% if listing.neighborhood %} · {{ listing.neighborhood }}{% endif %} · {{ listing.get_property_type_display }} · {{ listing.days_on_market }}d listed</div>
    <div>
      {% include "listings/_feature.html" with label="W/D" value=listing.has_washer_dryer %}
      {% include "listings/_feature.html" with label="AC" value=listing.has_ac %}
      {% include "listings/_feature.html" with label="Outdoor" value=listing.has_outdoor_space %}
    </div>
    {% include "listings/_status.html" %}
  </div>
</article>
```

`listings/templates/listings/list.html`:
```html
{% extends "listings/base.html" %}
{% block content %}
<div class="layout">
  <form class="filters" method="get">
    {{ form.as_div }}
    <button type="submit">Apply filters</button>
    <p class="muted"><a href="{% url 'listing_list' %}">Reset to defaults</a></p>
  </form>
  <section>
    <p class="muted">{{ listings|length }} listing{{ listings|length|pluralize }}{% if listings|length == 500 %} (showing first 500){% endif %}</p>
    <div id="map"></div>
    <div class="grid">
      {% for listing in listings %}{% include "listings/_card.html" %}{% empty %}<p>No listings match. Try loosening the filters.</p>{% endfor %}
    </div>
  </section>
</div>
{{ map_points|json_script:"map-points" }}
{% endblock %}
{% block scripts %}
<script>
  const points = JSON.parse(document.getElementById("map-points").textContent);
  const map = L.map("map").setView([45.515, -122.68], 11);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19, attribution: "&copy; OpenStreetMap contributors",
  }).addTo(map);
  const markers = points.map(p => {
    const marker = L.marker([p.lat, p.lng]).addTo(map);
    const link = document.createElement("a");
    link.href = p.url;
    link.textContent = p.label;
    marker.bindPopup(link);
    return marker;
  });
  if (markers.length) map.fitBounds(L.featureGroup(markers).getBounds().pad(0.1));
</script>
{% endblock %}
```

`listings/templates/listings/_tracking.html`:
```html
<form id="tracking" method="post" action="{% url 'update_tracking' listing.pk %}"
      hx-post="{% url 'update_tracking' listing.pk %}" hx-target="#tracking" hx-swap="outerHTML">
  {% csrf_token %}
  {{ tracking_form.as_p }}
  <button type="submit">Save</button>{% if saved %}<span class="saved">Saved ✓</span>{% endif %}
</form>
```

`listings/templates/listings/detail.html`:
```html
{% extends "listings/base.html" %}
{% load humanize %}
{% block title %}{{ listing.street }} · Condo Finder{% endblock %}
{% block content %}
<p><a href="{% url 'listing_list' %}">← Back to listings</a></p>
<div class="detail">
  <section>
    {% if listing.photo_url %}<img class="hero" src="{{ listing.photo_url }}" alt="">{% endif %}
    <h1>{{ listing.address }}</h1>
    {% if listing.title %}<h3>{{ listing.title }}</h3>{% endif %}
    <p class="price">{% if listing.price %}${{ listing.price|intcomma }}/mo{% else %}Price ?{% endif %}
      {% if not listing.is_active %}<span class="offmarket">Off market</span>{% endif %}</p>
    <div class="panel">
      <table>
        <tr><th>Beds / Baths</th><td>{{ listing.beds }} / {{ listing.baths|floatformat:"-1" }}</td></tr>
        <tr><th>Square feet</th><td>{{ listing.sqft|default:"?" }}{% if listing.price_per_sqft %} (${{ listing.price_per_sqft }}/sqft){% endif %}</td></tr>
        <tr><th>Parking</th><td>{% if listing.parking_spaces is None %}Unknown{% else %}{{ listing.parking_spaces }}{% endif %}</td></tr>
        <tr><th>Type</th><td>{{ listing.get_property_type_display }}</td></tr>
        <tr><th>Available</th><td>{{ listing.available|default:"?" }}</td></tr>
        <tr><th>Location</th><td>{{ listing.city }}{% if listing.neighborhood %} · {{ listing.neighborhood }}{% endif %}</td></tr>
        <tr><th>Listed</th><td>{{ listing.first_seen_at|naturalday }} ({{ listing.days_on_market }} days)</td></tr>
        <tr><th>Features</th><td>
          {% include "listings/_feature.html" with label="W/D" value=listing.has_washer_dryer %}
          {% include "listings/_feature.html" with label="AC" value=listing.has_ac %}
          {% include "listings/_feature.html" with label="Outdoor" value=listing.has_outdoor_space %}
        </td></tr>
      </table>
    </div>
    <div class="panel description">{{ listing.description }}</div>
  </section>
  <aside>
    <div class="panel"><h3>Our notes</h3>{% include "listings/_tracking.html" %}</div>
    <div class="panel"><h3>Sources</h3>
      <ul>{% for sl in listing.source_listings.all %}
        <li><a href="{{ sl.url }}" target="_blank" rel="noopener">{{ sl.source.name }}</a>{% if not sl.is_active %} <span class="muted">(gone)</span>{% endif %}</li>
      {% endfor %}</ul>
    </div>
    <div class="panel"><h3>Price history</h3>
      <table>{% for change in listing.price_changes.all %}
        <tr><td>{{ change.seen_at|date:"M j, Y" }}</td><td>${{ change.price|intcomma }}</td></tr>
      {% endfor %}</table>
    </div>
    {% if listing.latitude %}<div id="map" style="height:260px"></div>{% endif %}
    <p><a href="/admin/listings/listing/{{ listing.pk }}/change/">Correct data in admin</a></p>
  </aside>
</div>
{% endblock %}
{% block scripts %}
{% if listing.latitude %}
<script>
  const map = L.map("map").setView([{{ listing.latitude }}, {{ listing.longitude }}], 15);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {maxZoom: 19, attribution: "&copy; OpenStreetMap contributors"}).addTo(map);
  L.marker([{{ listing.latitude }}, {{ listing.longitude }}]).addTo(map);
</script>
{% endif %}
{% endblock %}
```

`listings/templates/listings/sources.html` (minimal here; completed in Task 12):
```html
{% extends "listings/base.html" %}
{% block content %}<h1>Sources</h1>{% endblock %}
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat: listings browse UI with filters, map, detail, and status tracking"
```

---

### Task 12: Sources health page + "Scrape now"

**Files:**
- Modify: `listings/templates/listings/sources.html`
- Create: `tests/test_sources_page.py`

**Interfaces:**
- Consumes: views `sources`, `scrape_now` (Task 11); `run_all_in_background`, `is_running` (Task 10); `scheduler.next_run_time()` (Task 13 — guarded: the template shows it only if present in context; Task 13 adds it).

- [ ] **Step 1: Write the failing tests**

`tests/test_sources_page.py`:
```python
import pytest

from listings import views
from listings.models import Source, SourceRun
from listings.scrapers.registry import SOURCES

pytestmark = pytest.mark.django_db


def test_sources_page_lists_registry_and_runs(client):
    response = client.get("/sources/")
    assert response.status_code == 200
    assert Source.objects.count() == len(SOURCES)
    source = Source.objects.get(key="pearl")
    SourceRun.objects.create(source=source, ok=False, error="ConnectError: blocked")
    response = client.get("/sources/")
    assert b"Pearl Property Management" in response.content
    assert b"ConnectError: blocked" in response.content
    assert b"Scrape now" in response.content


def test_scrape_now_starts_background_run(client, monkeypatch):
    started = []
    monkeypatch.setattr(views, "run_all_in_background", lambda: started.append(True))
    response = client.post("/sources/scrape/", follow=True)
    assert started == [True]
    assert b"Scrape started" in response.content


def test_scrape_now_when_running(client, monkeypatch):
    monkeypatch.setattr(views, "is_running", lambda: True)
    monkeypatch.setattr(views, "run_all_in_background", lambda: pytest.fail("should not start"))
    response = client.post("/sources/scrape/", follow=True)
    assert b"already running" in response.content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sources_page.py -q`
Expected: FAIL on `assert b"Pearl Property Management" in response.content` (template is still minimal).

- [ ] **Step 3: Replace `listings/templates/listings/sources.html`**

```html
{% extends "listings/base.html" %}
{% load humanize %}
{% block title %}Sources · Condo Finder{% endblock %}
{% block content %}
<h1>Sources</h1>
<form method="post" action="{% url 'scrape_now' %}" style="margin-bottom:16px">
  {% csrf_token %}
  <button type="submit" {% if running %}disabled{% endif %}>{% if running %}Scrape running…{% else %}Scrape now{% endif %}</button>
  {% if next_run %}<span class="muted">Next scheduled scrape: {{ next_run|date:"D M j, g:i A" }}</span>{% endif %}
</form>
<table>
  <tr><th>Source</th><th>Platform</th><th>Last success</th><th>Listings</th><th>Failures in a row</th><th>Last error</th></tr>
  {% for source in sources %}
  <tr>
    <td>{{ source.name }}</td>
    <td>{{ source.platform }}</td>
    <td>{{ source.last_success_at|naturaltime|default:"never" }}</td>
    <td>{{ source.last_count|default_if_none:"–" }}</td>
    <td>{% if source.consecutive_failures %}<strong class="offmarket">{{ source.consecutive_failures }}</strong>{% else %}0{% endif %}</td>
    <td class="muted">{% if source.last_error %}{{ source.last_error_at|naturaltime }}: {{ source.last_error|truncatechars:160 }}{% endif %}</td>
  </tr>
  {% endfor %}
</table>
<h2>Recent runs</h2>
<table>
  <tr><th>Started</th><th>Source</th><th>Result</th><th>Listings</th><th>New</th><th>Error</th></tr>
  {% for run in runs %}
  <tr>
    <td>{{ run.started_at|date:"M j g:i A" }}</td>
    <td>{{ run.source.name }}</td>
    <td>{% if run.ok %}ok{% elif run.finished_at %}<span class="offmarket">failed</span>{% else %}running{% endif %}</td>
    <td>{{ run.count }}</td>
    <td>{{ run.new_count }}</td>
    <td class="muted">{{ run.error|truncatechars:200 }}</td>
  </tr>
  {% empty %}
  <tr><td colspan="6">No runs yet.</td></tr>
  {% endfor %}
</table>
{% endblock %}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: sources health page with scrape-now button"
```

---

### Task 13: Scheduler, deployment, README, live smoke test

**Files:**
- Create: `listings/scheduler.py`, `tests/test_scheduler.py`, `deploy/gunicorn.conf.py`, `deploy/com.condofinder.web.plist.template`, `deploy/install.sh`, `.env.example`, `README.md`
- Modify: `listings/apps.py`, `listings/views.py` (`sources` view passes `next_run`)

**Interfaces:**
- Consumes: `run_all` (Task 10).
- Produces: `build_scheduler() -> BackgroundScheduler`, `start() -> BackgroundScheduler`, `next_run_time() -> datetime|None`; job id `"scrape-all"`.

- [ ] **Step 1: Write the failing tests**

`tests/test_scheduler.py`:
```python
from datetime import datetime
from zoneinfo import ZoneInfo

from listings import scheduler

PACIFIC = ZoneInfo("America/Los_Angeles")


def fire_after(trigger, when):
    return trigger.get_next_fire_time(None, when)


def test_default_schedule_every_four_hours_daytime():
    job = scheduler.build_scheduler().get_job("scrape-all")
    assert fire_after(job.trigger, datetime(2026, 9, 26, 12, 0, tzinfo=PACIFIC)).hour == 15
    late = fire_after(job.trigger, datetime(2026, 9, 26, 23, 30, tzinfo=PACIFIC))
    assert (late.day, late.hour) == (27, 7)


def test_schedule_is_configurable(settings):
    settings.SCRAPE_HOURS = "9,21"
    job = scheduler.build_scheduler().get_job("scrape-all")
    assert fire_after(job.trigger, datetime(2026, 9, 26, 10, 0, tzinfo=PACIFIC)).hour == 21


def test_next_run_time_none_when_not_started():
    assert scheduler.next_run_time() is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_scheduler.py -q`
Expected: FAIL with `ImportError: cannot import name 'scheduler'`

- [ ] **Step 3: Write `listings/scheduler.py`**

```python
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from django.conf import settings

log = logging.getLogger(__name__)

JOB_ID = "scrape-all"
_scheduler = None


def _scheduled_run():
    from django.db import close_old_connections

    from .runner import run_all

    try:
        run_all()
    finally:
        close_old_connections()


def build_scheduler():
    scheduler = BackgroundScheduler(timezone=settings.TIME_ZONE)
    scheduler.add_job(
        _scheduled_run,
        CronTrigger(hour=settings.SCRAPE_HOURS, minute=0, timezone=settings.TIME_ZONE),
        id=JOB_ID,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    return scheduler


def start():
    global _scheduler
    if _scheduler is None:
        _scheduler = build_scheduler()
        _scheduler.start()
        log.info("Scheduler started; scraping at hours %s", settings.SCRAPE_HOURS)
    return _scheduler


def next_run_time():
    if _scheduler is None:
        return None
    job = _scheduler.get_job(JOB_ID)
    return job.next_run_time if job else None
```

- [ ] **Step 4: Replace `listings/apps.py`**

```python
import os

from django.apps import AppConfig


class ListingsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "listings"

    def ready(self):
        # Only the long-running gunicorn process (launchd sets this) runs scheduled scrapes.
        if os.environ.get("CONDOFINDER_SCHEDULER") == "1":
            from .scheduler import start

            start()
```

- [ ] **Step 5: Pass `next_run` to the sources page**

In `listings/views.py`, add `from .scheduler import next_run_time` to the imports and add `"next_run": next_run_time(),` to the `sources` view's context dict.

- [ ] **Step 6: Run tests**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 7: Write deployment files**

`deploy/gunicorn.conf.py`:
```python
# Exactly one worker: the in-process scheduler must exist once.
bind = "0.0.0.0:8000"
workers = 1
worker_class = "gthread"
threads = 4
timeout = 120
accesslog = "-"
errorlog = "-"
```

`deploy/com.condofinder.web.plist.template`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.condofinder.web</string>
  <key>ProgramArguments</key>
  <array>
    <string>__UV__</string><string>run</string><string>--frozen</string><string>--no-dev</string>
    <string>gunicorn</string><string>-c</string><string>deploy/gunicorn.conf.py</string><string>condofinder.wsgi</string>
  </array>
  <key>WorkingDirectory</key><string>__PROJECT_DIR__</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>CONDOFINDER_SCHEDULER</key><string>1</string>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>__PROJECT_DIR__/logs/web.log</string>
  <key>StandardErrorPath</key><string>__PROJECT_DIR__/logs/web.log</string>
</dict>
</plist>
```

`deploy/install.sh`:
```bash
#!/usr/bin/env bash
# Install/refresh the Condo Finder launchd service for the current user.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
UV="$(command -v uv)"
LABEL="com.condofinder.web"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

cd "$PROJECT_DIR"
mkdir -p logs "$HOME/Library/LaunchAgents"
"$UV" sync --frozen --no-dev
"$UV" run --frozen --no-dev python manage.py migrate --noinput
"$UV" run --frozen --no-dev python manage.py collectstatic --noinput

sed -e "s#__PROJECT_DIR__#$PROJECT_DIR#g" -e "s#__UV__#$UV#g" "deploy/$LABEL.plist.template" > "$PLIST"
plutil -lint "$PLIST"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Condo Finder is running at http://$(scutil --get LocalHostName).local:8000"
```
Then: `chmod +x deploy/install.sh`

`.env.example`:
```
# Copy to .env and edit.
DJANGO_SECRET_KEY=change-me-to-a-long-random-string
SITE_URL=http://your-mac-mini.local:8000
# Pick a hard-to-guess topic; subscribe to it in the ntfy app on both phones.
NTFY_TOPIC=
SCRAPE_HOURS=7,11,15,19,23
ALERT_MAX_PRICE=5000
DEFAULT_MAX_PRICE=5000
TARGET_CITIES=Portland,Lake Oswego,Beaverton
REQUEST_DELAY_SECONDS=1.5
NOMINATIM_EMAIL=
```

`README.md`:
````markdown
# Condo Finder

Aggregates Portland / Lake Oswego / Beaverton rental listings from local property managers into one
browsable database with a map, filters, shared status + notes, and push alerts.

## Develop

```bash
uv sync
uv run python manage.py migrate
uv run python manage.py scrape            # scrape all sources once (add --source pearl for one)
uv run python manage.py runserver 0.0.0.0:8000
uv run pytest
```

## Run on the Mac mini (always on)

1. `cp .env.example .env` and fill it in (set `SITE_URL` to `http://<mac-mini>.local:8000`, choose an `NTFY_TOPIC`).
2. `./deploy/install.sh` — installs a launchd agent that starts gunicorn at login, restarts it on crash,
   and runs scheduled scrapes (default 7am, 11am, 3pm, 7pm, 11pm).
3. System Settings → Users & Groups → enable automatic login for your user (LaunchAgents start at login),
   and System Settings → Energy → prevent automatic sleeping.
4. Approve the macOS firewall prompt for incoming connections to Python.
5. Create an admin user for data corrections: `uv run python manage.py createsuperuser`.

Logs: `logs/web.log`. Restart after pulling changes: re-run `./deploy/install.sh`.

## Alerts

Install the **ntfy** app on both phones and subscribe to your `NTFY_TOPIC`. You'll get pushes for new
listings matching 2bd/2ba/2 parking (unknowns allowed), price drops on listings marked Interested, and
scrapers that keep failing.

## Adding a property manager

If their listings page is AppFolio (`<name>.appfolio.com/listings`) or Nesthub (`/_system/listings/...`
links), add one entry to `SOURCES` in `listings/scrapers/registry.py`.

## Correcting data

Open a listing → "Correct data in admin". To make a correction survive re-scrapes, put it in the
`overrides` JSON field, e.g. `{"parking_spaces": 2, "has_ac": true}`.
````

- [ ] **Step 8: Validate the plist template renders**

Run: `sed -e "s#__PROJECT_DIR__#$PWD#g" -e "s#__UV__#$(command -v uv)#g" deploy/com.condofinder.web.plist.template > /tmp/cf.plist && plutil -lint /tmp/cf.plist`
Expected: `/tmp/cf.plist: OK`

- [ ] **Step 9: Live smoke test**

```bash
uv run python manage.py migrate
uv run python manage.py scrape --source pearl --source uptown
```
Expected: two lines like `pearl: ok — 7 listings, N new` and `uptown: ok — 19 listings, M new`. If a live page structure has drifted from the fixtures, fix the parser and add a regression test. Then run the full scrape (`uv run python manage.py scrape`) and start `uv run gunicorn -c deploy/gunicorn.conf.py condofinder.wsgi`, load `http://localhost:8000/` and `/sources/`, and confirm listings, map pins, and source statuses render.

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "feat: in-process scheduler, launchd deployment, README"
```

---

## Phase 2 (separate plan)

Craigslist, Realtor.com, Zillow, Redfin scrapers (Playwright for the portals), each registered in
`SOURCES` with its own platform class. Written after Phase 1 is running, against live page captures.
