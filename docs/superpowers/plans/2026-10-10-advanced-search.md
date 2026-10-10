# Advanced Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `/search/` page with keyword search, about 25 new filters, a sortable and configurable results table, CSV export, inline status and votes, and group-shared saved searches, all running on the same filter engine as the home page.

**Architecture:** New filters go into the shared `ListingFilterForm` / `apply_filters` so a Search URL works anywhere. Keyword search is an SQLite FTS5 table kept in sync by triggers. The Search page is a server-rendered Django view with HTMX live updates (the home page's pattern: re-render the page, swap `#results`). Column choices live on `Profile`; saved searches are a new `SavedSearch` model per group that stores the page's URL query.

**Tech Stack:** Django 6.1, SQLite (FTS5, already compiled in: SQLite 3.47), HTMX 2.0.4, pytest + pytest-django, uv.

**Spec:** `docs/superpowers/specs/2026-10-10-advanced-search-decisions.md` (moved from `docs/plan-decisions.md` in Task 1, step 0). Decision numbers below (D1–D17) refer to it.

## Global Constraints

- Production is live: add new migrations, never edit or squash applied ones. Data fixes go in data migrations.
- New migrations, in order: `listings/0022_listing_effective_price` (PR 1), `listings/0023_listing_search` (PR 2), `accounts/0007_profile_search_columns` (PR 4), `listings/0024_savedsearch` (PR 5).
- Deliver as five stacked PRs titled `[Advanced search n/5] …`, branches `search-1-filters` … `search-5-saved`, each based on the previous one. Each PR body lists the stack and says: merge bottom-up with **Create a merge commit**.
- Commit messages use `feat:` / `fix:` / `docs:` prefixes and end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. PR bodies end with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.
- Tests assert on element markup (e.g. `'<td class="m-card">'`), never on bare class names: class names also appear in the inline stylesheet in `base.html`.
- Group state (status, votes) isn't on `Listing`: call `collab.decorate(listings, request.group, request.user)` before rendering, and pass the group to `apply_filters`.
- CSS lives inline in `listings/templates/listings/base.html`. No JS build step.
- The shell is zsh. Never put `# comments` after commands you hand the owner to paste.
- Every UI change is checked in a browser against the dev server with real data, on desktop and at phone width (375px): nothing scrolls sideways and the console has no errors. Restore any status, vote or saved search you changed while testing.
- Phone breakpoint for the Search page is **700px** (D15). The rest of the site keeps its 800px breakpoint.
- Results page size on Search is **100** (D12); keyword debounce is **400 ms** (D14).
- Keep `CLAUDE.md` current in every PR (Current state, Code map, Gotchas). Update `docs/architecture.html` and republish it to https://claude.ai/artifact/MASfMv25dYKcHeYTx6eUgq in PR 5.
- Run the whole suite with `uv run pytest -q` before every commit; it must stay green (758 tests at the start).

## Review Focus

1. **Opening `/search/` with no filters, then clicking a column header or "Next →".** The person expects the group's default filters to stay applied. Links must be built from the form's effective data, not `request.GET` (which is empty). Test: `test_header_and_page_links_keep_the_default_filters` in Task 9.
2. **A Search-only filter (keyword, ZIP, sqft…) opened on the home page, then any home filter changed or "Save as our defaults" clicked.** The person expects the Search filter to stay applied, including when it came from the group's saved defaults. Test: `test_search_only_filters_survive_home_changes_and_saved_defaults` in Task 15.
3. **Messy keyword input:** unbalanced quotes, a lone `OR` or `-`, `***`, `col:umn`, `NEAR(a b)`, or `<script>` in a listing's text. The person expects no error page and no injected markup. Tests: `test_messy_queries_never_raise` (Task 6) and `test_highlights_escape_listing_text` (Task 7).
4. **One bad value in a Search URL** (`min_sqft=abc`, a ZIP no longer listed). The person expects that one filter to be skipped with a note, and the rest of the search to apply; a stale ZIP stays checked. Tests: `test_a_bad_value_skips_only_that_filter` (Task 9) and `test_a_zip_no_longer_listed_still_filters_and_stays_picked` (Task 5).
5. **A typed max rent above $8,000.** The home slider's top value (8000) means "no max", but on Search a typed 9000 must filter. Test: `test_typed_max_price_above_the_slider_top_filters` in Task 2.

---

## File map

| File | Responsibility | PR |
|---|---|---|
| `listings/forms.py` | New fields, tri-state choices, sort choices, `home_menus`/`search_menus`, `SEARCH_ONLY_FIELDS`, `active_count()`, `search_only_values()` | 1, 3, 5 |
| `listings/filters.py` | `apply_filters` for every new filter; `dom_expr()`, `first_day_expr()`; `SORTS` registry | 1, 2 |
| `listings/models.py` | `Listing.effective_price` + `save()` sync; `SavedSearch` | 1, 5 |
| `listings/search_index.py` (new) | FTS5 query translation (`parse`), `filter_listings`, `rank_expr`, `highlights` | 2 |
| `listings/search_columns.py` (new) | Column registry, defaults, `keys_from()`, CSV fields | 3, 4 |
| `listings/search_views.py` (new) | Search page, CSV, column save, saved-search CRUD, `query_string()` | 3, 4, 5 |
| `listings/templates/listings/search.html` (new) + `_range.html`, `_number.html`, `_select.html`, `_search_cell.html`, `_search_card.html`, `_status_menu.html`, `_saved_searches.html` (new) | Search UI | 1, 3, 4, 5 |
| `listings/templates/listings/_filter_bar.html`, `list.html` | Home menus via `home_menus`; Search-only chip | 1, 5 |
| `listings/views.py` | `save_default_filters` multi-value detection; `set_status` "menu" variant; home chip context | 1, 4, 5 |
| `listings/sql_console.py` | Hide FTS shadow tables from the schema sidebar | 2 |
| `accounts/models.py` | `Profile.search_columns` | 4 |
| `tests/test_search_filters.py`, `test_search_index.py`, `test_search_page.py`, `test_search_columns.py`, `test_saved_searches.py`, `test_home_search_chip.py` (new) | Tests | 1–5 |

---

# PR 1 — `[Advanced search 1/5] New filters in the shared filter engine`

Branch: `git checkout main && git pull && git checkout -b search-1-filters`

### Task 1: Tri-state feature filters, and home menus that don't change

**Files:**
- Move: `docs/plan-decisions.md` → `docs/superpowers/specs/2026-10-10-advanced-search-decisions.md`
- Modify: `listings/forms.py`, `listings/filters.py`
- Create: `listings/templates/listings/_select.html`
- Modify: `listings/templates/listings/_filter_bar.html`, `listings/templates/listings/list.html`
- Test: `tests/test_search_filters.py` (new)

**Interfaces:**
- Produces: `FEATURE_CHOICES` (any, yes, no, unknown, yes_or_unknown); `FURNISHED_CHOICES` (those plus legacy `hide`, `only`); new form field `parking` (has-parking tri-state); `ListingFilterForm.home_menus` and `.search_menus` (cached properties: `{field name: [{"value", "label", "selected"}]}`); `filters._feature_q(field, choice) -> Q | None`; `filters.PARKING_Q`; template `listings/_select.html` taking `name`, `options`, optional `form_id`, `label`.

- [ ] **Step 0: Keep the decisions file as the spec**

```bash
mv docs/plan-decisions.md docs/superpowers/specs/2026-10-10-advanced-search-decisions.md
```

- [ ] **Step 1: Write the failing tests**

Create `tests/test_search_filters.py`:

```python
import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from listings.filters import apply_filters
from listings.forms import ListingFilterForm
from listings.models import Listing, PropertyType
from tests.helpers import home_group, make_listing

pytestmark = pytest.mark.django_db


def listing(key, **fields):
    base = dict(price=3000, beds=2, baths=Decimal("2"), sqft=1000, parking_spaces=2, property_type=PropertyType.CONDO)
    base.update(fields)
    return make_listing(address_key=key, **base)


def found(**data):
    """Keys of the listings a search finds. Starts from no filters at all (Search's "Clear all")."""
    form = ListingFilterForm(data)
    assert form.is_valid(), form.errors
    return set(apply_filters(Listing.objects.all(), form.cleaned_data, home_group()).values_list("address_key", flat=True))


@pytest.mark.parametrize("choice, expected", [
    ("any", {"yes", "no", "unknown"}),
    ("yes", {"yes"}),
    ("no", {"no"}),
    ("unknown", {"unknown"}),
    ("yes_or_unknown", {"yes", "unknown"}),
])
@pytest.mark.parametrize("name, field", [("wd", "has_washer_dryer"), ("ac", "has_ac"), ("outdoor", "has_outdoor_space"),
                                         ("furnished", "is_furnished")])
def test_feature_filters_are_tri_state(name, field, choice, expected):
    listing("yes", **{field: True})
    listing("no", **{field: False})
    listing("unknown", **{field: None})
    assert found(**{name: choice}) == expected


def test_furnished_keeps_its_older_hide_and_only_values():
    listing("yes", is_furnished=True)
    listing("no", is_furnished=False)
    listing("unknown", is_furnished=None)
    assert found(furnished="hide") == {"no", "unknown"}
    assert found(furnished="only") == {"yes"}


@pytest.mark.parametrize("choice, expected", [
    ("yes", {"spaces", "has-parking"}),
    ("no", {"zero", "no-parking"}),
    ("unknown", {"unknown"}),
    ("yes_or_unknown", {"spaces", "has-parking", "unknown"}),
])
def test_parking_known_is_tri_state(choice, expected):
    listing("spaces", parking_spaces=2)
    listing("has-parking", parking_spaces=None, has_parking=True)
    listing("zero", parking_spaces=0)
    listing("no-parking", parking_spaces=None, has_parking=False)
    listing("unknown", parking_spaces=None, has_parking=None)
    assert found(parking=choice) == expected


def test_home_menus_keep_the_short_lists_but_show_a_search_value():
    menus = ListingFilterForm({"wd": "no"}).home_menus
    assert [option["value"] for option in menus["ac"]] == ["any", "yes_or_unknown", "yes"]
    assert [option["value"] for option in menus["furnished"]] == ["any", "hide", "only"]
    assert [option["value"] for option in menus["wd"]] == ["any", "yes_or_unknown", "yes", "no"]
    assert [option["value"] for option in menus["wd"] if option["selected"]] == ["no"]


def test_search_menus_offer_every_choice_but_furnisheds_alias():
    menus = ListingFilterForm({}).search_menus
    assert [option["value"] for option in menus["wd"]] == ["any", "yes", "no", "unknown", "yes_or_unknown"]
    assert "only" not in [option["value"] for option in menus["furnished"]]
    assert "hide" in [option["value"] for option in menus["furnished"]]


def test_home_drawer_selects_show_a_search_only_value(client):
    content = client.get("/?wd=no").content.decode()
    select = re.search(r'<select name="wd".*?</select>', content, re.S).group(0)
    assert '<option value="no" selected>No</option>' in select
    assert '<option value="unknown"' not in select
```

Later tasks append more tests to this file; move each block's imports up to the top of the file as you add it.

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_search_filters.py -q`
Expected: FAIL (`"no"` is not a valid choice; `home_menus` doesn't exist).

- [ ] **Step 3: Implement the choices and menus in `listings/forms.py`**

Replace the `FEATURE_CHOICES` and `FURNISHED_CHOICES` lines and add the menus. Add `from django.utils.functional import cached_property` to the imports.

```python
FEATURE_CHOICES = [("any", "Any"), ("yes", "Yes"), ("no", "No"), ("unknown", "Unknown"), ("yes_or_unknown", "Yes or unknown")]
# Furnished also keeps the home page's older values: "hide" (no or unknown) and "only" (an alias of yes).
FURNISHED_CHOICES = [*FEATURE_CHOICES, ("hide", "No or unknown"), ("only", "Furnished only")]
```

Keep `SORT_CHOICES` as is for now (Task 5 replaces it). After `SORT_CHOICES`, add:

```python
SHORT_FEATURE_MENU = [("any", "Any"), ("yes_or_unknown", "Yes or unknown"), ("yes", "Yes")]
# The home page's drawer keeps its short menus (D2). Search shows every choice.
HOME_MENUS = {
    "wd": SHORT_FEATURE_MENU,
    "ac": SHORT_FEATURE_MENU,
    "outdoor": SHORT_FEATURE_MENU,
    "furnished": [("any", "Any"), ("hide", "Hide furnished"), ("only", "Furnished only")],
    "sort": [("price", "Price ↑"), ("-price", "Price ↓"), ("newest", "Newest"), ("ppsf", "$/sqft ↑")],
}
SEARCH_MENU_FIELDS = ("wd", "ac", "outdoor", "furnished", "parking", "votes")
SEARCH_MENU_SKIP = {"furnished": {"only"}}  # an alias of "yes"
```

Add the field next to `furnished`:

```python
    parking = forms.ChoiceField(required=False, choices=FEATURE_CHOICES, label="Has parking")
```

Add to `ListingFilterForm` (after `__init__`):

```python
    def _menu(self, name, choices):
        """Options for a select. A value from elsewhere (a Search link on the home page, say) is added, so the
        menu shows it and the next change doesn't drop it."""
        current = str(self[name].value() or "")
        if current and current not in dict(choices):
            choices = [*choices, (current, dict(self.fields[name].choices).get(current, current))]
        return [{"value": value, "label": label, "selected": value == current} for value, label in choices]

    @cached_property
    def home_menus(self):
        return {name: self._menu(name, choices) for name, choices in HOME_MENUS.items()}

    @cached_property
    def search_menus(self):
        return {
            name: self._menu(name, [(v, label) for v, label in self.fields[name].choices if v not in SEARCH_MENU_SKIP.get(name, ())])
            for name in SEARCH_MENU_FIELDS
        }
```

- [ ] **Step 4: Implement the filters in `listings/filters.py`**

Replace `FEATURE_FIELDS`, delete the `furnished` hide/only branch and the feature loop at the end of `apply_filters`, and use:

```python
FEATURE_FIELDS = {"wd": "has_washer_dryer", "ac": "has_ac", "outdoor": "has_outdoor_space", "furnished": "is_furnished"}

PARKING_Q = {
    "yes": Q(parking_spaces__gt=0) | Q(parking_spaces__isnull=True, has_parking=True),
    "no": Q(parking_spaces=0) | Q(parking_spaces__isnull=True, has_parking=False),
    "unknown": Q(parking_spaces__isnull=True, has_parking__isnull=True),
}
PARKING_Q["yes_or_unknown"] = PARKING_Q["yes"] | PARKING_Q["unknown"]


def _feature_q(field, choice):
    """Yes / No / Unknown / Yes or unknown (and furnished's older Hide / Only) as a Q; None means Any."""
    return {
        "yes": Q(**{field: True}),
        "only": Q(**{field: True}),
        "no": Q(**{field: False}),
        "unknown": Q(**{f"{field}__isnull": True}),
        "yes_or_unknown": ~Q(**{field: False}),  # negating a nullable column keeps the NULLs
        "hide": ~Q(**{field: True}),
    }.get(choice)
```

In `apply_filters`, where the furnished branch and feature loop were:

```python
    for key, field in FEATURE_FIELDS.items():
        condition = _feature_q(field, data.get(key))
        if condition is not None:
            queryset = queryset.filter(condition)
    if data.get("parking") in PARKING_Q:
        queryset = queryset.filter(PARKING_Q[data["parking"]])
```

- [ ] **Step 5: Create `listings/templates/listings/_select.html`**

```django
{# A select from a form's home_menus / search_menus: name, options, optional form_id and label. #}
<select name="{{ name }}"{% if form_id %} form="{{ form_id }}"{% endif %}{% if label %} aria-label="{{ label }}"{% endif %}>
  {% for option in options %}<option value="{{ option.value }}"{% if option.selected %} selected{% endif %}>{{ option.label }}</option>{% endfor %}
</select>
```

- [ ] **Step 6: Use the home menus in the home templates**

In `listings/templates/listings/_filter_bar.html`, replace the four feature lines:

```django
          <label class="field">In-unit W/D {% include "listings/_select.html" with name="wd" options=form.home_menus.wd %}</label>
          <label class="field">AC {% include "listings/_select.html" with name="ac" options=form.home_menus.ac %}</label>
          <label class="field">Outdoor space {% include "listings/_select.html" with name="outdoor" options=form.home_menus.outdoor %}</label>
          <label class="field">Furnished {% include "listings/_select.html" with name="furnished" options=form.home_menus.furnished %}</label>
```

In `listings/templates/listings/list.html`, replace the sort `<select>…</select>` block with:

```django
        {% include "listings/_select.html" with name="sort" options=form.home_menus.sort form_id="filters" %}
```

- [ ] **Step 7: Run the tests**

Run: `uv run pytest tests/test_search_filters.py tests/test_filters.py tests/test_filter_bar.py tests/test_furnished.py tests/test_default_filters.py -q`
Expected: PASS. Then `uv run pytest -q`: all pass.

- [ ] **Step 8: Commit**

```bash
git add docs/superpowers/specs/2026-10-10-advanced-search-decisions.md listings/forms.py listings/filters.py listings/templates/listings/_select.html listings/templates/listings/_filter_bar.html listings/templates/listings/list.html tests/test_search_filters.py
git commit -m "feat: tri-state feature filters and a has-parking filter

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 2: Size, $/sqft and effective-rent ranges

**Files:**
- Modify: `listings/models.py` (`Listing.effective_price`, `Listing.save`)
- Create: `listings/migrations/0022_listing_effective_price.py`
- Modify: `listings/forms.py`, `listings/filters.py`
- Test: `tests/test_search_filters.py`

**Interfaces:**
- Produces: `Listing.effective_price` (int or None: rent after move-in specials over a 12-month lease, else `price`), kept current by `Listing.save()` even with `update_fields`; form fields `max_beds`, `max_baths`, `max_parking`, `min_sqft`, `max_sqft`, `min_ppsf`, `max_ppsf`, `min_effective`, `max_effective`; `filters.ppsf_expr()`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_search_filters.py`)

```python
from listings.forms import PRICE_SLIDER_MAX
from listings.specials import effective_rent


def test_size_ranges_exclude_unknowns():
    listing("small", beds=1, baths=Decimal("1"), sqft=600)
    listing("mid", beds=2, baths=Decimal("2"), sqft=1100)
    listing("big", beds=4, baths=Decimal("3"), sqft=2400)
    listing("no-sqft", sqft=None)
    assert found(min_beds=2, max_beds=3) == {"mid", "no-sqft"}
    assert found(max_baths="1.5") == {"small"}
    assert found(min_sqft=800, max_sqft=2000) == {"mid"}


def test_parking_range_with_and_without_unknown():
    listing("one", parking_spaces=1)
    listing("two", parking_spaces=2)
    listing("three", parking_spaces=3)
    listing("unknown", parking_spaces=None)
    assert found(min_parking=1, max_parking=2) == {"one", "two"}
    assert found(max_parking=1, parking_unknown="on") == {"one", "unknown"}


def test_price_per_sqft_range():
    listing("cheap", price=2000, sqft=1000)   # $2.00
    listing("dear", price=4000, sqft=1000)    # $4.00
    listing("no-sqft", price=3000, sqft=None)
    assert found(min_ppsf="2.5") == {"dear"}
    assert found(max_ppsf="2.5") == {"cheap"}


def test_typed_max_price_above_the_slider_top_filters():
    listing("ok", price=8500)
    listing("too-dear", price=9500)
    assert found(max_price=9000) == {"ok"}
    assert found(max_price=PRICE_SLIDER_MAX) == {"ok", "too-dear"}  # the home slider's top still means no max


def test_effective_price_follows_the_special_and_the_price():
    offer = "Get 4 weeks free on a 12-month lease."
    special = listing("special", price=3000, special_offer=offer)
    plain = listing("plain", price=3000)
    assert special.effective_price == effective_rent(3000, offer) < 3000
    assert plain.effective_price == 3000
    special.price = 3200
    special.save(update_fields=["price", "updated_at"])  # how ingest saves a new price
    special.refresh_from_db()
    assert special.effective_price == effective_rent(3200, offer)
    special.special_offer = ""
    special.save(update_fields=["special_offer", "updated_at"])
    special.refresh_from_db()
    assert special.effective_price == 3200


def test_effective_rent_range():
    listing("special", price=3000, special_offer="Get 4 weeks free on a 12-month lease.")
    listing("plain", price=3000)
    assert found(max_effective=2900) == {"special"}
    assert found(min_effective=2900) == {"plain"}


@pytest.mark.django_db(transaction=True)
def test_migration_fills_in_effective_price():
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    def migrate(target):
        MigrationExecutor(connection).migrate(target)
        return MigrationExecutor(connection).loader.project_state(target).apps

    apps = migrate([("listings", "0021_trendreport_discoveries")])
    Old = apps.get_model("listings", "Listing")
    old = Old.objects.create(address_key="k", address="1 A St", street="1 A St", city="Portland", price=3000,
                             special_offer="Get 4 weeks free on a 12-month lease.")
    try:
        apps = migrate([("listings", "0022_listing_effective_price")])
        assert apps.get_model("listings", "Listing").objects.get(pk=old.pk).effective_price == effective_rent(
            3000, "Get 4 weeks free on a 12-month lease.")
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_search_filters.py -q -k "range or effective or max_price"`
Expected: FAIL (unknown fields, no `effective_price`).

- [ ] **Step 3: Add the model field and save hook in `listings/models.py`**

In `Listing`, after `special_offer`:

```python
    # Rent after the move-in special, spread over a 12-month lease; the price when there's no special or it
    # doesn't say how much. Kept by save() so the Search page can filter and sort on it.
    effective_price = models.IntegerField(null=True, blank=True)
```

Add to `Listing` (after `__str__`):

```python
    def save(self, *args, **kwargs):
        self.effective_price = self.effective_rent or self.price
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and {"price", "special_offer"} & set(update_fields):
            kwargs["update_fields"] = {*update_fields, "effective_price"}
        super().save(*args, **kwargs)
```

- [ ] **Step 4: Write the migration**

Run `uv run python manage.py makemigrations listings -n listing_effective_price`, then add the backfill so the file reads:

```python
from django.db import migrations, models


def fill_effective_price(apps, schema_editor):
    from listings.specials import effective_rent

    Listing = apps.get_model("listings", "Listing")
    for listing in Listing.objects.only("pk", "price", "special_offer").iterator():
        value = (effective_rent(listing.price, listing.special_offer) if listing.special_offer else None) or listing.price
        Listing.objects.filter(pk=listing.pk).update(effective_price=value)


class Migration(migrations.Migration):
    dependencies = [("listings", "0021_trendreport_discoveries")]

    operations = [
        migrations.AddField(model_name="listing", name="effective_price", field=models.IntegerField(blank=True, null=True)),
        migrations.RunPython(fill_effective_price, migrations.RunPython.noop),
    ]
```

- [ ] **Step 5: Add the form fields in `listings/forms.py`** (after `max_price`)

```python
    max_beds = forms.IntegerField(required=False, min_value=0, label="Max beds")
    max_baths = forms.DecimalField(required=False, min_value=0, decimal_places=1, label="Max baths")
    max_parking = forms.IntegerField(required=False, min_value=0, label="Max parking")
    min_sqft = forms.IntegerField(required=False, min_value=0, label="Min sqft")
    max_sqft = forms.IntegerField(required=False, min_value=0, label="Max sqft")
    min_ppsf = forms.DecimalField(required=False, min_value=0, decimal_places=2, label="Min $/sqft")
    max_ppsf = forms.DecimalField(required=False, min_value=0, decimal_places=2, label="Max $/sqft")
    min_effective = forms.IntegerField(required=False, min_value=0, label="Min effective rent")
    max_effective = forms.IntegerField(required=False, min_value=0, label="Max effective rent")
```

- [ ] **Step 6: Apply them in `listings/filters.py`**

Add near the top:

```python
RANGE_LOOKUPS = [
    ("max_beds", "beds__lte"), ("max_baths", "baths__lte"),
    ("min_sqft", "sqft__gte"), ("max_sqft", "sqft__lte"),
    ("min_effective", "effective_price__gte"), ("max_effective", "effective_price__lte"),
]


def ppsf_expr():
    return ExpressionWrapper(Cast("price", FloatField()) / F("sqft"), output_field=FloatField())
```

Replace the parking block and the `max_price` line in `apply_filters`:

```python
    parking = Q()
    if data.get("min_parking") is not None:
        parking &= Q(parking_spaces__gte=data["min_parking"])
    if data.get("max_parking") is not None:
        parking &= Q(parking_spaces__lte=data["max_parking"])
    if parking:
        if data.get("parking_unknown"):
            parking |= Q(parking_spaces__isnull=True)
        queryset = queryset.filter(parking)
    if data.get("min_price") is not None:
        queryset = queryset.filter(price__gte=data["min_price"])
    # The home slider's top value means "no maximum"; a typed value above it (on Search) still filters.
    if data.get("max_price") is not None and data["max_price"] != PRICE_SLIDER_MAX:
        queryset = queryset.filter(price__lte=data["max_price"])
    for name, lookup in RANGE_LOOKUPS:
        if data.get(name) is not None:
            queryset = queryset.filter(**{lookup: data[name]})
    if data.get("min_ppsf") is not None or data.get("max_ppsf") is not None:
        queryset = queryset.alias(ppsf_value=ppsf_expr())
        if data.get("min_ppsf") is not None:
            queryset = queryset.filter(ppsf_value__gte=float(data["min_ppsf"]))
        if data.get("max_ppsf") is not None:
            queryset = queryset.filter(ppsf_value__lte=float(data["max_ppsf"]))
```

In `_sort`, replace the inline `per_sqft` expression with `ppsf_expr()`.

- [ ] **Step 7: Run the tests**

Run: `uv run pytest tests/test_search_filters.py tests/test_filters.py tests/test_specials.py tests/test_specials_ingest.py -q`, then `uv run pytest -q`.
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add listings/models.py listings/migrations/0022_listing_effective_price.py listings/forms.py listings/filters.py tests/test_search_filters.py
git commit -m "feat: size, \$/sqft and effective-rent range filters

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 3: Time-on-market filters

**Files:**
- Modify: `listings/forms.py`, `listings/filters.py`
- Test: `tests/test_search_filters.py`

**Interfaces:**
- Produces: `filters.first_day_expr()` (the day the current rental listing started: the site's listed date when it's earlier than first seen) and `filters.dom_expr()` (integer days, equal to `Listing.days_on_market`); form fields `min_dom`, `max_dom`, `new_within` (first seen within N days), `gone_within` (went off-market within N days; includes off-market listings by itself), `listed_from`, `listed_to` (dates, compared with `first_day_expr()`).

- [ ] **Step 1: Write the failing tests** (append)

```python
from listings.filters import dom_expr


def days_ago(n, at=time(12)):
    return timezone.make_aware(datetime.combine(timezone.localdate() - timedelta(days=n), at))


def test_dom_in_sql_matches_the_python_property():
    rows = [
        listing("seen-10", first_seen_at=days_ago(10)),
        listing("listed-earlier", first_seen_at=days_ago(5), listed_at=timezone.localdate() - timedelta(days=30)),
        listing("listed-later", first_seen_at=days_ago(5), listed_at=timezone.localdate() - timedelta(days=2)),
        listing("gone", first_seen_at=days_ago(20), last_seen_at=days_ago(3), is_active=False),
        listing("late-evening", first_seen_at=days_ago(1, time(23, 30))),  # after 4pm Pacific: the next day in UTC
    ]
    in_sql = dict(Listing.objects.annotate(dom=dom_expr()).values_list("pk", "dom"))
    assert in_sql == {row.pk: row.days_on_market for row in rows}


def test_days_on_market_range():
    listing("fresh", first_seen_at=days_ago(2))
    listing("stale", first_seen_at=days_ago(60))
    assert found(min_dom=30) == {"stale"}
    assert found(max_dom=7) == {"fresh"}


def test_new_within_and_gone_within():
    listing("new", first_seen_at=days_ago(2))
    listing("old", first_seen_at=days_ago(40))
    listing("just-gone", first_seen_at=days_ago(40), last_seen_at=days_ago(1), is_active=False)
    listing("long-gone", first_seen_at=days_ago(40), last_seen_at=days_ago(30), is_active=False)
    assert found(new_within=7) == {"new"}
    assert found(gone_within=7) == {"just-gone"}  # includes off-market listings without "Show off-market"


def test_listed_date_range_uses_the_listings_start():
    listing("listed-in-sept", first_seen_at=days_ago(1), listed_at=date(2026, 9, 10))
    listing("seen-in-oct", first_seen_at=timezone.make_aware(datetime(2026, 10, 3, 12)))
    assert found(listed_from="2026-09-01", listed_to="2026-09-30") == {"listed-in-sept"}
    assert found(listed_from="2026-10-01") == {"seen-in-oct"}
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_search_filters.py -q -k "dom or within or listed"`
Expected: FAIL (`dom_expr` not defined).

- [ ] **Step 3: Add the fields in `listings/forms.py`** (after `show_inactive`)

```python
    min_dom = forms.IntegerField(required=False, min_value=0, label="Min days on market")
    max_dom = forms.IntegerField(required=False, min_value=0, label="Max days on market")
    new_within = forms.IntegerField(required=False, min_value=1, label="New in the last (days)")
    gone_within = forms.IntegerField(required=False, min_value=1, label="Off-market in the last (days)")
    listed_from = forms.DateField(required=False, label="Listed from")
    listed_to = forms.DateField(required=False, label="Listed to")
```

- [ ] **Step 4: Add the expressions and filters in `listings/filters.py`**

Imports become:

```python
from datetime import date, timedelta

from django.db.models import (Case, Count, DateField, ExpressionWrapper, F, FloatField, Func, IntegerField, Max, Min,
                              OuterRef, Q, Subquery, Value, When)
from django.db.models.functions import Cast, Coalesce, Least, TruncDate
from django.utils import timezone
```

Add:

```python
class JulianDay(Func):
    function = "julianday"
    output_field = FloatField()


def first_day_expr():
    """The day the current rental listing started: the site's listed date when it's before we first saw it."""
    seen = TruncDate("first_seen_at")  # in the current time zone, like timezone.localdate()
    return Least(Coalesce("listed_at", seen), seen)


def dom_expr():
    """Listing.days_on_market in SQL: to today, or to the last day seen once off-market."""
    end = Case(When(is_active=True, then=Value(timezone.localdate())), default=TruncDate("last_seen_at"),
               output_field=DateField())
    return Cast(JulianDay(end) - JulianDay(first_day_expr()), IntegerField())
```

In `apply_filters`, change the first lines to:

```python
def apply_filters(queryset, data, group):
    if not data.get("show_inactive") and not data.get("gone_within"):
        queryset = queryset.filter(is_active=True)
```

and add before the sort:

```python
    now = timezone.now()
    if data.get("min_dom") is not None or data.get("max_dom") is not None:
        queryset = queryset.alias(dom=dom_expr())
        if data.get("min_dom") is not None:
            queryset = queryset.filter(dom__gte=data["min_dom"])
        if data.get("max_dom") is not None:
            queryset = queryset.filter(dom__lte=data["max_dom"])
    if data.get("new_within"):
        queryset = queryset.filter(first_seen_at__gte=now - timedelta(days=data["new_within"]))
    if data.get("gone_within"):
        queryset = queryset.filter(is_active=False, last_seen_at__gte=now - timedelta(days=data["gone_within"]))
    if data.get("listed_from") or data.get("listed_to"):
        queryset = queryset.alias(listed_day=first_day_expr())
        if data.get("listed_from"):
            queryset = queryset.filter(listed_day__gte=data["listed_from"])
        if data.get("listed_to"):
            queryset = queryset.filter(listed_day__lte=data["listed_to"])
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_search_filters.py -q`, then `uv run pytest -q`.
Expected: PASS. If `test_dom_in_sql_matches_the_python_property` fails only on `late-evening`, `TruncDate` isn't using the current time zone: pass `tzinfo=timezone.get_current_timezone()` to both `TruncDate` calls.

- [ ] **Step 6: Commit**

```bash
git add listings/forms.py listings/filters.py tests/test_search_filters.py
git commit -m "feat: days-on-market, new, off-market and listed-date filters

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 4: Price-movement filters

**Files:**
- Modify: `listings/forms.py`, `listings/filters.py`
- Test: `tests/test_search_filters.py`

**Interfaces:**
- Produces: `filters._with_price_range(queryset)` (annotates `peak_price` and `low_price` during the current rental listing, once); `filters.price_change_count()` (subquery: "Price change" history entries during the current listing); form fields `min_drop_amount`, `min_drop_percent`, `min_price_changes`, `price_raised`.

- [ ] **Step 1: Write the failing tests** (append)

```python
from listings.models import PriceChange


def with_history(key, prices, **fields):
    """A listing whose history ran through prices (first is the listing price), ending at the last one."""
    row = listing(key, price=prices[-1], **fields)
    for n, price in enumerate(prices):
        PriceChange.objects.create(listing=row, price=price, seen_at=days_ago(len(prices) - n),
                                   event="Listed for rent" if n == 0 else "Price change")
    return row


def test_drop_by_amount_and_percent():
    with_history("small-cut", [3000, 2950])      # $50, 1.7%
    with_history("big-cut", [3000, 2700])        # $300, 10%
    with_history("never-cut", [3000])
    assert found(min_drop_amount=100) == {"big-cut"}
    assert found(min_drop_percent=5) == {"big-cut"}
    assert found(min_drop_amount=25, min_drop_percent=1) == {"small-cut", "big-cut"}


def test_number_of_price_changes_and_price_went_up():
    with_history("twice", [3000, 2900, 2800])
    with_history("raised", [3000, 2800, 2950])
    with_history("once", [3000, 3100])
    with_history("never", [3000])
    assert found(min_price_changes=2) == {"twice", "raised"}
    assert found(price_raised="on") == {"raised", "once"}


def test_price_movement_ignores_an_earlier_rental_listing():
    row = with_history("relisted", [3500, 2800])
    row.listed_at = timezone.localdate()  # a new listing started today, after both entries
    row.save()
    assert found(min_drop_amount=100) == set()
    assert found(min_price_changes=1) == set()
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_search_filters.py -q -k "drop or changes or relisted"`
Expected: FAIL (unknown fields).

- [ ] **Step 3: Add the fields in `listings/forms.py`** (after `price_reduced`)

```python
    min_drop_amount = forms.IntegerField(required=False, min_value=1, label="Dropped at least ($)")
    min_drop_percent = forms.IntegerField(required=False, min_value=1, max_value=99, label="Dropped at least (%)")
    min_price_changes = forms.IntegerField(required=False, min_value=1, label="Price changes at least")
    price_raised = forms.BooleanField(required=False, label="Price went up")
```

- [ ] **Step 4: Implement in `listings/filters.py`**

Add `PriceChange` to the `.models` import. Add:

```python
def _with_price_range(queryset):
    """Annotates peak_price and low_price during the current rental listing (all history when the listed date
    is unknown). Safe to call twice."""
    if "peak_price" in queryset.query.annotations:
        return queryset
    in_current_listing = Q(listed_at__isnull=True) | Q(price_changes__seen_at__date__gte=F("listed_at"))
    return queryset.annotate(peak_price=Max("price_changes__price", filter=in_current_listing),
                             low_price=Min("price_changes__price", filter=in_current_listing))


def price_change_count():
    """How many times a site changed the price during the current rental listing."""
    since = Coalesce(OuterRef("listed_at"), Value(date(1900, 1, 1)), output_field=DateField())
    changes = (PriceChange.objects.filter(listing=OuterRef("pk"), event="Price change", seen_at__date__gte=since)
               .order_by().values("listing").annotate(n=Count("pk")).values("n"))
    return Coalesce(Subquery(changes, output_field=IntegerField()), 0)
```

Replace the `price_reduced` block in `apply_filters` with:

```python
    if data.get("price_reduced"):
        queryset = _with_price_range(queryset).filter(peak_price__gt=F("price"))
    if data.get("min_drop_amount"):
        queryset = _with_price_range(queryset).filter(peak_price__gte=F("price") + data["min_drop_amount"])
    if data.get("min_drop_percent"):
        drop_x100 = ExpressionWrapper((F("peak_price") - F("price")) * 100, output_field=IntegerField())
        queryset = (_with_price_range(queryset).alias(drop_x100=drop_x100)
                    .filter(drop_x100__gte=F("peak_price") * data["min_drop_percent"]))
    if data.get("price_raised"):
        queryset = _with_price_range(queryset).filter(low_price__lt=F("price"))
    if data.get("min_price_changes"):
        queryset = queryset.alias(change_count=price_change_count()).filter(change_count__gte=data["min_price_changes"])
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_search_filters.py tests/test_price_drop_ui.py tests/test_filters.py -q`, then `uv run pytest -q`.
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add listings/forms.py listings/filters.py tests/test_search_filters.py
git commit -m "feat: price drop, price change count and price-went-up filters

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 5: Location and source filters, every sort, and PR 1

**Files:**
- Modify: `listings/forms.py`, `listings/filters.py`, `listings/views.py` (`save_default_filters`), `CLAUDE.md`
- Test: `tests/test_search_filters.py`, `tests/test_default_filters.py`

**Interfaces:**
- Produces: `forms.OpenMultipleChoiceField`; form fields `zips`, `neighborhoods` (pick lists from active listings; any submitted value is accepted and kept as a choice), `min_sites`, `has_photo`, `has_location`; `forms.SORT_FIELDS` (sort key → label) and `SORT_CHOICES` (`newest` plus `key`/`-key` for every sort field); `forms.SEARCH_ONLY_FIELDS` (tuple of field names the home page has no control for); `ListingFilterForm.raw_values(name) -> list[str]`; `filters.SORTS` (sort key → `fn(queryset, group) -> (queryset, [expressions])`); `filters.active_site_count()`; `_sort(queryset, data, group)` (now takes `data`).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_search_filters.py`)

```python
from listings.forms import SORT_CHOICES
from listings.models import SourceListing, Status, Vote
from listings.collab import set_status, set_vote
from tests.helpers import make_source, make_user


def test_zips_and_neighborhoods_are_ored_within_and_anded_across():
    listing("pearl-09", zip_code="97209", neighborhood="Pearl")
    listing("nw-10", zip_code="97210", neighborhood="Northwest")
    listing("pearl-10", zip_code="97210", neighborhood="Pearl")
    listing("se", zip_code="97214", neighborhood="Buckman")
    assert found(zips=["97209", "97210"]) == {"pearl-09", "nw-10", "pearl-10"}
    assert found(zips=["97210"], neighborhoods=["Pearl", "Buckman"]) == {"pearl-10"}


def test_zip_and_neighborhood_choices_come_from_active_listings():
    listing("a", zip_code="97209", neighborhood="Pearl")
    listing("gone", zip_code="97201", neighborhood="Goose Hollow", is_active=False)
    form = ListingFilterForm({})
    assert [value for value, _ in form.fields["zips"].choices] == ["97209"]
    assert [value for value, _ in form.fields["neighborhoods"].choices] == ["Pearl"]


def test_a_zip_no_longer_listed_still_filters_and_stays_picked():
    listing("a", zip_code="97209")
    form = ListingFilterForm({"zips": ["97299"]})
    assert form.is_valid(), form.errors
    assert ("97299", "97299") in form.fields["zips"].choices
    assert found(zips=["97299"]) == set()


def test_listed_on_n_sites_photo_and_location():
    pearl, zillow = make_source("pearl"), make_source("zillow")
    both = listing("both", photo_url="https://example.com/p.jpg", latitude=45.5, longitude=-122.6)
    one = listing("one")
    SourceListing.objects.create(listing=both, source=pearl, external_id="p1", url="https://p.example/1")
    SourceListing.objects.create(listing=both, source=zillow, external_id="z1", url="https://z.example/1")
    SourceListing.objects.create(listing=one, source=zillow, external_id="z2", url="https://z.example/2", is_active=False)
    assert found(min_sites=2) == {"both"}
    assert found(has_photo="on") == {"both"}
    assert found(has_location="on") == {"both"}


@pytest.mark.parametrize("sort", [value for value, _ in SORT_CHOICES])
def test_every_sort_runs(sort):
    listing("a", price=2500)
    listing("b", price=3500, sqft=None)
    form = ListingFilterForm({"sort": sort})
    assert form.is_valid(), form.errors
    assert sorted(apply_filters(Listing.objects.all(), form.cleaned_data, home_group()).values_list("address_key", flat=True)) == ["a", "b"]


def ordered(sort):
    form = ListingFilterForm({"sort": sort})
    assert form.is_valid(), form.errors
    return list(apply_filters(Listing.objects.all(), form.cleaned_data, home_group()).values_list("address_key", flat=True))


def test_sort_by_status_follows_the_search_stages():
    listing("rejected", status=Status.REJECTED)  # no statuses filter here, so rejected is included
    listing("new")
    listing("toured", status=Status.TOURED)
    assert ordered("status") == ["new", "toured", "rejected"]
    assert ordered("-status") == ["rejected", "toured", "new"]


def test_sort_by_votes_and_area():
    sam, alex = make_user("s@example.com", "S"), make_user("a@example.com", "A")
    liked, mixed, plain = listing("liked", city="Portland"), listing("mixed", city="Beaverton"), listing("plain", city="Lake Oswego")
    set_vote(liked, home_group(), sam, Vote.Value.UP)
    set_vote(liked, home_group(), alex, Vote.Value.UP)
    set_vote(mixed, home_group(), sam, Vote.Value.UP)
    set_vote(mixed, home_group(), alex, Vote.Value.DOWN)
    assert ordered("-votes") == ["liked", "mixed", "plain"]
    assert ordered("area") == ["mixed", "plain", "liked"]


def test_ties_break_by_id_so_pages_dont_repeat():
    rows = [listing(f"same-{n}", price=3000) for n in range(3)]
    assert ordered("price") == [row.address_key for row in rows]
```

Append to `tests/test_default_filters.py`:

```python
def test_save_as_our_defaults_keeps_every_pick_of_a_multi_pick_filter(client):
    client.post("/filters/defaults/", {"zips": ["97209", "97210"], "neighborhoods": ["Pearl"], "max_price": "8000"})
    saved = home_group().default_filters
    assert saved["zips"] == ["97209", "97210"] and saved["neighborhoods"] == ["Pearl"]
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_search_filters.py tests/test_default_filters.py -q`
Expected: FAIL (unknown fields and sorts).

- [ ] **Step 3: Implement the form side in `listings/forms.py`**

Replace `SORT_CHOICES` with:

```python
SORT_FIELDS = {  # sort key -> label; each sorts both ways ("price" ascending, "-price" descending)
    "price": "Price", "effective": "Effective rent", "ppsf": "$/sqft", "beds": "Beds", "baths": "Baths",
    "sqft": "Sqft", "parking": "Parking", "dom": "Days on market", "drop": "Price drop", "address": "Address",
    "area": "Area", "zip": "ZIP", "type": "Type", "sites": "Sites", "listed": "Listed", "first_seen": "First seen",
    "last_seen": "Last seen", "status": "Status", "votes": "Votes",
}
SORT_CHOICES = [("newest", "Newest")] + [
    choice for key, label in SORT_FIELDS.items() for choice in ((key, f"{label} ↑"), (f"-{key}", f"{label} ↓"))
]
```

Add before the form class:

```python
class OpenMultipleChoiceField(forms.MultipleChoiceField):
    """A pick list built from the data. A value that's no longer listed still filters, so an old link or
    saved search keeps working."""

    def valid_value(self, value):
        return bool(value) and len(value) <= 100
```

Add the fields (after `neighborhood`):

```python
    zips = OpenMultipleChoiceField(required=False, widget=forms.CheckboxSelectMultiple, label="ZIP codes")
    neighborhoods = OpenMultipleChoiceField(required=False, widget=forms.CheckboxSelectMultiple, label="Neighborhoods")
    min_sites = forms.IntegerField(required=False, min_value=1, label="Listed on at least (sites)")
    has_photo = forms.BooleanField(required=False, label="Has a photo")
    has_location = forms.BooleanField(required=False, label="On the map")
```

Change `sort` to `forms.ChoiceField(required=False, choices=SORT_CHOICES)` (unchanged line, new list). Replace `__init__` with:

```python
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cities"].choices = [(city, city) for city in settings.TARGET_CITIES]
        self.fields["sources"].choices = list(Source.objects.order_by("name").values_list("key", "name"))
        active = Listing.objects.filter(is_active=True)
        for name, column in (("zips", "zip_code"), ("neighborhoods", "neighborhood")):
            values = set(active.exclude(**{column: ""}).values_list(column, flat=True).distinct())
            values |= {value for value in self.raw_values(name) if value}
            self.fields[name].choices = [(value, value) for value in sorted(values)]

    def raw_values(self, name):
        """The submitted values for a field as a list of strings (the data may be a QueryDict or a dict)."""
        if not self.is_bound:
            return []
        if hasattr(self.data, "getlist"):
            return self.data.getlist(name)
        value = self.data.get(name)
        if value in (None, ""):
            return []
        return [str(v) for v in value] if isinstance(value, (list, tuple)) else [str(value)]
```

Add after `SEARCH_MENU_SKIP`:

```python
# Filters the home page has no control for. It keeps them as hidden inputs and shows a chip (PR 5).
SEARCH_ONLY_FIELDS = (
    "max_beds", "max_baths", "max_parking", "min_sqft", "max_sqft", "min_ppsf", "max_ppsf", "min_effective",
    "max_effective", "parking", "min_dom", "max_dom", "new_within", "gone_within", "listed_from", "listed_to",
    "min_drop_amount", "min_drop_percent", "min_price_changes", "price_raised", "zips", "neighborhoods",
    "min_sites", "has_photo", "has_location",
)
```

- [ ] **Step 4: Implement the filters and sorts in `listings/filters.py`**

Add `SourceListing`, `Status` to the `.models` import. Add:

```python
def active_site_count():
    sites = (SourceListing.objects.filter(listing=OuterRef("pk"), is_active=True)
             .order_by().values("listing").annotate(n=Count("pk")).values("n"))
    return Coalesce(Subquery(sites, output_field=IntegerField()), 0)
```

In `apply_filters`, after the `neighborhood` line:

```python
    if data.get("zips"):
        queryset = queryset.filter(zip_code__in=data["zips"])
    if data.get("neighborhoods"):
        queryset = queryset.filter(neighborhood__in=data["neighborhoods"])
    if data.get("min_sites"):
        queryset = queryset.alias(site_count=active_site_count()).filter(site_count__gte=data["min_sites"])
    if data.get("has_photo"):
        queryset = queryset.exclude(photo_url="")
    if data.get("has_location"):
        queryset = queryset.filter(latitude__isnull=False, longitude__isnull=False)
```

Change the last line of `apply_filters` to `return _sort(queryset, data, group)` and replace `_sort` with:

```python
def _fields(*names):
    return lambda queryset, group: (queryset, [F(name) for name in names])


def _sort_drop(queryset, group):
    queryset = _with_price_range(queryset)
    return queryset, [Coalesce(F("peak_price") - F("price"), 0)]


def _sort_status(queryset, group):
    from .collab import status_expr

    queryset = queryset.alias(sort_status=status_expr(group))
    stages = Case(*[When(sort_status=value, then=Value(rank)) for rank, value in enumerate(Status.values)],
                  output_field=IntegerField())
    return queryset, [stages]


def _sort_votes(queryset, group):
    up, down = _vote_count(group, Vote.Value.UP), _vote_count(group, Vote.Value.DOWN)
    return queryset, [up - down, up]


SORTS = {
    "price": _fields("price"),
    "effective": _fields("effective_price"),
    "ppsf": lambda queryset, group: (queryset, [ppsf_expr(), F("price")]),
    "beds": _fields("beds", "baths"),
    "baths": _fields("baths", "beds"),
    "sqft": _fields("sqft"),
    "parking": _fields("parking_spaces"),
    "dom": lambda queryset, group: (queryset, [dom_expr()]),
    "drop": _sort_drop,
    "address": _fields("street", "unit"),
    "area": _fields("city", "quadrant", "neighborhood"),
    "zip": _fields("zip_code"),
    "type": _fields("property_type"),
    "sites": lambda queryset, group: (queryset, [active_site_count()]),
    "listed": lambda queryset, group: (queryset, [first_day_expr()]),
    "first_seen": _fields("first_seen_at"),
    "last_seen": _fields("last_seen_at"),
    "status": _sort_status,
    "votes": _sort_votes,
}


def _sort(queryset, data, group):
    sort = data.get("sort") or "price"
    descending = sort.startswith("-")
    key = sort.lstrip("-")
    if key == "newest":
        key, descending = "first_seen", True
    if key not in SORTS:
        key, descending = "price", False
    queryset, expressions = SORTS[key](queryset, group)
    order = [e.desc(nulls_last=True) if descending else e.asc(nulls_last=True) for e in expressions]
    return queryset.order_by(*order, "pk")  # pk breaks ties, so pages never repeat or skip a listing
```

- [ ] **Step 5: Save every pick of a multi-pick filter as a default (`listings/views.py`)**

Delete `MULTI_VALUE_FILTERS` and change the dict in `save_default_filters` to:

```python
    request.group.default_filters = {
        name: request.POST.getlist(name) if isinstance(field, forms.MultipleChoiceField) else request.POST.get(name, "")
        for name, field in form.fields.items()
        if name not in AREA_FILTERS
    }
```

with `from django import forms` added to the imports.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_search_filters.py tests/test_default_filters.py tests/test_filters.py tests/test_votes.py -q`, then `uv run pytest -q`.
Expected: PASS.

- [ ] **Step 7: Update `CLAUDE.md`**

- Code map, `listings/forms.py` bullet: add "New filters for the Search page (size/price/time ranges, tri-state features incl. `parking`, ZIP and neighborhood pick lists, sites, photo, map). `SEARCH_ONLY_FIELDS` lists the ones the home page has no control for; `home_menus` keeps the home drawer's short menus and adds a value set elsewhere so it isn't dropped."
- Code map, new bullet for `listings/filters.py`: "`apply_filters` runs every filter; `dom_expr()`/`first_day_expr()` mirror `Listing.days_on_market`; `SORTS` holds every sort (ties break by pk); price movement uses `_with_price_range` (peak/low during the current rental listing)."
- Code map, `listings/specials.py` bullet: append "`Listing.effective_price` stores it (the price when there's no valued special); `Listing.save()` keeps it current, even with `update_fields`."
- Gotchas: "`max_price` equal to `PRICE_SLIDER_MAX` (8000) means no maximum (the home slider's top); any other value filters."
- Current state: add "**Open:** Advanced search stack (plan `docs/superpowers/plans/2026-10-10-advanced-search.md`): PR 1/5 new filters."

- [ ] **Step 8: Commit, push and open PR 1**

```bash
git add listings/forms.py listings/filters.py listings/views.py tests/test_search_filters.py tests/test_default_filters.py CLAUDE.md
git commit -m "feat: ZIP, neighborhood, sites, photo and map filters; sort by any column

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push -u origin search-1-filters
gh pr create --base main --title "[Advanced search 1/5] New filters in the shared filter engine" --body-file <scratchpad>/pr1.md
```

Write the PR body to a file in the session's scratchpad directory first, using this template for every PR in the stack:

```markdown
New filters for the coming Search page, in the shared filter code so a Search URL works on the home page too. No UI yet; the home page looks the same.

- Tri-state W/D, AC, outdoor, furnished and has-parking (Any / Yes / No / Unknown / Yes or unknown)
- Min/max beds, baths, parking, sqft, $/sqft and effective rent (new `Listing.effective_price`, migration 0022 backfills it)
- Days on market, new in N days, off-market in N days, listed date range
- Price drop ($ or %), number of price changes, price went up
- ZIP and neighborhood pick lists, listed on N+ sites, has photo, on the map
- Sort by any column, ties broken by id

**Stack** (merge bottom-up with "Create a merge commit"):
1. **#this** New filters
2. Keyword search (FTS5)
3. The /search/ page
4. Columns, CSV, inline status and votes
5. Saved searches and the home page chip

Plan: `docs/superpowers/plans/2026-10-10-advanced-search.md`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

---

# PR 2 — `[Advanced search 2/5] Keyword search with SQLite FTS5`

Branch: `git checkout -b search-2-keywords` (from `search-1-filters`). Open the PR with `--base search-1-filters`.

### Task 6: The FTS5 index and the query translator

**Files:**
- Create: `listings/migrations/0023_listing_search.py`, `listings/search_index.py`
- Test: `tests/test_search_index.py` (new)

**Interfaces:**
- Produces: table `listing_search` (FTS5, external content `listings_listing`, columns `title, description, address, neighborhood`, tokenizer `porter unicode61 remove_diacritics 2`) kept in sync by triggers `listing_search_ai/_ad/_au`; `search_index.Keywords(include: str, exclude: str)`; `search_index.parse(text) -> Keywords | None` (None when there's nothing to search for).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_search_index.py`:

```python
import pytest
from django.db import connection

from listings.models import Listing
from listings.search_index import Keywords, parse
from tests.helpers import make_listing

pytestmark = pytest.mark.django_db


def matches(fts):
    with connection.cursor() as cursor:
        cursor.execute("SELECT rowid FROM listing_search WHERE listing_search MATCH %s", [fts])
        return {row[0] for row in cursor.fetchall()}


def in_sync():
    with connection.cursor() as cursor:  # raises if the index and listings_listing disagree
        cursor.execute("INSERT INTO listing_search(listing_search, rank) VALUES ('integrity-check', 1)")


@pytest.mark.parametrize("text, expected", [
    ("balcony", Keywords('("balcony")', "")),
    ('"walk in closet"', Keywords('("walk in closet")', "")),
    ("pearl balcony OR terrace", Keywords('("pearl") AND ("balcony" OR "terrace")', "")),
    ("-studio", Keywords("", '"studio"')),
    ("pearl -studio -\"no pets\"", Keywords('("pearl")', '"studio" OR "no pets"')),
    ("balc*", Keywords('("balc"*)', "")),
    ('"unbalanced phrase', Keywords('("unbalanced phrase")', "")),
    ("two-bedroom", Keywords('("two bedroom")', "")),
    ("pearl AND balcony", Keywords('("pearl") AND ("balcony")', "")),
])
def test_parse(text, expected):
    assert parse(text) == expected


@pytest.mark.parametrize("text", ["", "   ", "OR", "-", "***", '""', '"" -""', "OR OR", "- -"])
def test_nothing_to_search_for(text):
    assert parse(text) is None


@pytest.mark.parametrize("text", ['"unbalanced', "AND NOT", "(paren", "col:umn", "^start", "NEAR(a b)", "a OR", "OR a",
                                  "café", "<script>", "50%", "a\"b\"c", "-\"", "*a", "😀 balcony"])
def test_messy_queries_never_raise(text):
    make_listing(address_key="k", title="Balcony views")
    keywords = parse(text)
    if keywords and keywords.include:
        matches(keywords.include)
    if keywords and keywords.exclude:
        matches(keywords.exclude)


def test_index_follows_inserts_updates_and_deletes():
    row = make_listing(address_key="a", title="Pearl loft", description="Big balcony", neighborhood="Pearl")
    assert matches('"balcony"') == {row.pk}
    row.description = "Rooftop deck"
    row.save()
    assert matches('"balcony"') == set() and matches('"rooftop"') == {row.pk}
    Listing.objects.filter(pk=row.pk).update(title="Sunny condo")  # QuerySet.update skips save(); the trigger doesn't
    assert matches('"sunny"') == {row.pk} and matches('"loft"') == set()
    in_sync()
    row.delete()
    assert matches('"rooftop"') == set()
    in_sync()


def test_stemming_and_accents():
    row = make_listing(address_key="a", description="Two balconies near the café")
    assert matches('"balcony"') == {row.pk}
    assert matches('"cafe"') == {row.pk}


@pytest.mark.django_db(transaction=True)
def test_migration_indexes_existing_listings():
    from django.db.migrations.executor import MigrationExecutor

    def migrate(target):
        MigrationExecutor(connection).migrate(target)
        return MigrationExecutor(connection).loader.project_state(target).apps

    apps = migrate([("listings", "0022_listing_effective_price")])
    old = apps.get_model("listings", "Listing").objects.create(
        address_key="k", address="1 A St", street="1 A St", city="Portland", description="Wraparound terrace")
    try:
        migrate([("listings", "0023_listing_search")])
        assert matches('"terrace"') == {old.pk}
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_search_index.py -q`
Expected: FAIL (`listings.search_index` doesn't exist).

- [ ] **Step 3: Write the migration `listings/migrations/0023_listing_search.py`**

```python
"""Keyword search: an FTS5 index over listings, kept in sync by triggers (so QuerySet.update is covered too)."""

from django.db import migrations

COLUMNS = "title, description, address, neighborhood"
NEW = "new.title, new.description, new.address, new.neighborhood"
OLD = "old.title, old.description, old.address, old.neighborhood"

FORWARD = [
    f"""CREATE VIRTUAL TABLE listing_search USING fts5({COLUMNS}, content='listings_listing', content_rowid='id',
        tokenize='porter unicode61 remove_diacritics 2')""",
    f"""CREATE TRIGGER listing_search_ai AFTER INSERT ON listings_listing BEGIN
        INSERT INTO listing_search(rowid, {COLUMNS}) VALUES (new.id, {NEW});
    END""",
    f"""CREATE TRIGGER listing_search_ad AFTER DELETE ON listings_listing BEGIN
        INSERT INTO listing_search(listing_search, rowid, {COLUMNS}) VALUES ('delete', old.id, {OLD});
    END""",
    f"""CREATE TRIGGER listing_search_au AFTER UPDATE OF {COLUMNS} ON listings_listing BEGIN
        INSERT INTO listing_search(listing_search, rowid, {COLUMNS}) VALUES ('delete', old.id, {OLD});
        INSERT INTO listing_search(rowid, {COLUMNS}) VALUES (new.id, {NEW});
    END""",
    "INSERT INTO listing_search(listing_search) VALUES ('rebuild')",  # index the listings already there
]

BACKWARD = [
    "DROP TRIGGER IF EXISTS listing_search_au",
    "DROP TRIGGER IF EXISTS listing_search_ad",
    "DROP TRIGGER IF EXISTS listing_search_ai",
    "DROP TABLE IF EXISTS listing_search",
]


class Migration(migrations.Migration):
    dependencies = [("listings", "0022_listing_effective_price")]

    operations = [migrations.RunSQL(FORWARD, BACKWARD)]
```

- [ ] **Step 4: Write `listings/search_index.py` (parsing only for now)**

```python
"""Keyword search over listings with SQLite FTS5.

listing_search indexes each listing's title, description, address and neighborhood; triggers from
migration 0023 keep it in step with listings_listing on every insert, update and delete. People type
Google-style queries ("quoted phrases", -exclude, OR, prefix*); parse() turns them into FTS5 syntax built
only from quoted terms, so no input can make a malformed query."""

import re
from dataclasses import dataclass

_TOKEN = re.compile(r'(-?)"([^"]*)"?|(\S+)')
_WORD = re.compile(r"[^\W_]+", re.UNICODE)


@dataclass(frozen=True)
class Keywords:
    include: str  # FTS5 expression a listing must match ("" for none)
    exclude: str  # FTS5 expression a listing must not match ("" for none)


def _term(text, prefix=False):
    """A quoted FTS5 phrase from the words in text, or "" when it has none."""
    words = _WORD.findall(text)
    if not words:
        return ""
    return f'"{" ".join(words)}"' + ("*" if prefix else "")


def parse(text):
    """Keywords for a search box entry, or None when it has nothing to search for. Words are ANDed; OR joins
    the words on either side of it (it binds tighter than AND, as people expect); -word or -"phrase" excludes."""
    groups, excludes, join_next = [], [], False
    for negate, phrase, word in _TOKEN.findall(text or ""):
        if word in ("OR", "AND"):
            join_next = word == "OR" and bool(groups)
            continue
        if word.startswith("-") and len(word) > 1:
            negate, word = "-", word[1:]
        term = _term(phrase) if phrase or not word else _term(word, prefix=word.endswith("*"))
        if not term:
            join_next = False
            continue
        if negate:
            excludes.append(term)
        elif join_next:
            groups[-1].append(term)
        else:
            groups.append([term])
        join_next = False
    if not groups and not excludes:
        return None
    include = " AND ".join(f"({' OR '.join(group)})" for group in groups)
    return Keywords(include, " OR ".join(excludes))
```

Note: in `_TOKEN`, a bare `-` followed by a quoted phrase is captured by the first alternative (`(-?)"…"`), so `-"no pets"` arrives as `negate="-"`, `phrase="no pets"`. A `-word` arrives as `word="-word"` and is handled by the `startswith("-")` branch. `"a OR"` leaves `join_next` set at the end, which is harmless.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_search_index.py -q`
Expected: PASS. If a `test_parse` case fails, fix `parse`, not the expectation: the expectations are the contract later tasks rely on.

- [ ] **Step 6: Commit**

```bash
git add listings/migrations/0023_listing_search.py listings/search_index.py tests/test_search_index.py
git commit -m "feat: FTS5 keyword index over listings, kept in sync by triggers

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 7: Keyword filter, best-match sort, highlights, and PR 2

**Files:**
- Modify: `listings/search_index.py`, `listings/forms.py`, `listings/filters.py`, `listings/sql_console.py`, `CLAUDE.md`
- Test: `tests/test_search_index.py`, `tests/test_sql_console.py`

**Interfaces:**
- Consumes: `parse`, `Keywords` (Task 6); `_sort(queryset, data, group)` (Task 5).
- Produces: form field `q` (added to `SEARCH_ONLY_FIELDS`); `search_index.filter_listings(queryset, text)`; `search_index.rank_expr(keywords) -> RawSQL` (bm25, lower is better); `search_index.highlights(listing_ids, text) -> {id: {"title", "address", "snippet"}}` of safe HTML with `<mark>` around matches; sort `""` means best match when there's a keyword, else price.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_search_index.py`)

```python
from listings.filters import apply_filters
from listings.forms import ListingFilterForm
from listings.search_index import highlights
from tests.helpers import home_group


def searched(q, **data):
    form = ListingFilterForm({"q": q, **data})
    assert form.is_valid(), form.errors
    return list(apply_filters(Listing.objects.all(), form.cleaned_data, home_group()).values_list("address_key", flat=True))


def test_keyword_search_filters_and_ranks_title_matches_first():
    make_listing(address_key="desc", price=2000, description="Quiet unit. " * 20 + "Small balcony.")
    make_listing(address_key="title", price=3000, title="Balcony views over the Pearl")
    make_listing(address_key="none", price=2500, description="Garden level")
    assert searched("balcony") == ["title", "desc"]
    assert searched("balcony", sort="price") == ["desc", "title"]  # a chosen sort wins


def test_or_phrase_prefix_and_exclude():
    make_listing(address_key="pb", description="Pearl loft with balcony")
    make_listing(address_key="pt", description="Pearl flat with terrace")
    make_listing(address_key="b", description="Balcony in Sellwood")
    make_listing(address_key="studio", description="Pearl studio with balcony")
    assert set(searched("pearl balcony OR terrace")) == {"pb", "pt", "studio"}
    assert set(searched("pearl balcony OR terrace -studio")) == {"pb", "pt"}
    assert set(searched('"loft with"')) == {"pb"}
    assert set(searched("balc*")) == {"pb", "b", "studio"}


def test_exclude_only_keeps_everything_else_sorted_by_price():
    make_listing(address_key="studio", price=2000, description="Studio")
    make_listing(address_key="b", price=3000, description="Two bedroom")
    make_listing(address_key="a", price=2500, description="One bedroom")
    assert searched("-studio") == ["a", "b"]


def test_keywords_and_filters_combine():
    make_listing(address_key="cheap", price=2000, description="balcony")
    make_listing(address_key="dear", price=4000, description="balcony")
    assert searched("balcony", max_price=3000) == ["cheap"]


def test_highlights_mark_matches():
    row = make_listing(address_key="a", title="Pearl loft", description="A sunny unit with a big balcony and views.")
    marks = highlights([row.pk], "balcony pearl")[row.pk]
    assert "<mark>Pearl</mark>" in marks["title"]
    assert "<mark>balcony</mark>" in marks["snippet"]


def test_highlights_escape_listing_text():
    row = make_listing(address_key="a", description='<script>alert("x")</script> balcony <b>bold</b>')
    snippet = str(highlights([row.pk], "balcony")[row.pk]["snippet"])
    assert "<script>" not in snippet and "&lt;script&gt;" in snippet
    assert "<b>" not in snippet and "<mark>balcony</mark>" in snippet


def test_no_highlights_without_keywords():
    row = make_listing(address_key="a", description="balcony")
    assert highlights([row.pk], "") == {} and highlights([row.pk], "-balcony") == {}
```

Append to `tests/test_sql_console.py`:

```python
def test_schema_hides_the_keyword_index_internals():
    names = {table.name for table in sql_console.schema()}
    assert "listing_search" in names
    assert not any(name.startswith("listing_search_") for name in names)
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_search_index.py tests/test_sql_console.py -q`
Expected: FAIL (`q` isn't a field; `highlights` missing; shadow tables listed).

- [ ] **Step 3: Finish `listings/search_index.py`**

Add the imports at the top (below the docstring):

```python
from django.db import connection
from django.db.models import FloatField
from django.db.models.expressions import RawSQL
from django.utils.html import escape
from django.utils.safestring import mark_safe
```

Append:

```python
_MATCHING_IDS = "SELECT rowid FROM listing_search WHERE listing_search MATCH %s"


def filter_listings(queryset, text):
    keywords = parse(text)
    if keywords is None:
        return queryset
    if keywords.include:
        queryset = queryset.filter(pk__in=RawSQL(_MATCHING_IDS, [keywords.include]))
    if keywords.exclude:
        queryset = queryset.exclude(pk__in=RawSQL(_MATCHING_IDS, [keywords.exclude]))
    return queryset


def rank_expr(keywords):
    """bm25 relevance (lower is better), weighting title over address and neighborhood over description."""
    return RawSQL(
        '(SELECT bm25(listing_search, 10.0, 1.0, 4.0, 4.0) FROM listing_search '
        'WHERE listing_search MATCH %s AND rowid = "listings_listing"."id")',
        [keywords.include], output_field=FloatField(),
    )


_START, _END = "\x02", "\x03"  # placeholders FTS5 wraps matches in; swapped for <mark> after escaping


def _marked(text):
    if not text or _START not in text:
        return ""
    return mark_safe(escape(text).replace(_START, "<mark>").replace(_END, "</mark>"))


def highlights(listing_ids, text):
    """{listing id: {"title", "address", "snippet"}}: safe HTML with matched words in <mark> ("" where nothing
    matched), for one page of results."""
    keywords = parse(text)
    ids = list(listing_ids)
    if keywords is None or not keywords.include or not ids:
        return {}
    placeholders = ", ".join(["%s"] * len(ids))
    sql = ("SELECT rowid, highlight(listing_search, 0, %s, %s), highlight(listing_search, 2, %s, %s), "
           "snippet(listing_search, 1, %s, %s, '…', 18) "
           f"FROM listing_search WHERE listing_search MATCH %s AND rowid IN ({placeholders})")
    with connection.cursor() as cursor:
        cursor.execute(sql, [_START, _END] * 3 + [keywords.include, *ids])
        return {row[0]: {"title": _marked(row[1]), "address": _marked(row[2]), "snippet": _marked(row[3])}
                for row in cursor.fetchall()}
```

- [ ] **Step 4: Add `q` and wire it into the filters**

In `listings/forms.py`, add the first field of the form:

```python
    q = forms.CharField(required=False, max_length=300, label="Keywords")
```

and add `"q"` as the first entry of `SEARCH_ONLY_FIELDS`. Add `("", "Best match")` handling to Search's sort menu by appending to `ListingFilterForm.search_menus` (replace the property):

```python
    @cached_property
    def search_menus(self):
        menus = {
            name: self._menu(name, [(v, label) for v, label in self.fields[name].choices if v not in SEARCH_MENU_SKIP.get(name, ())])
            for name in SEARCH_MENU_FIELDS
        }
        menus["sort"] = self._menu("sort", [("", "Best match"), *SORT_CHOICES])
        return menus
```

In `listings/filters.py`, add `from . import search_index` and, in `apply_filters` right after the `is_active` filter:

```python
    queryset = search_index.filter_listings(queryset, data.get("q"))
```

Change the start of `_sort`:

```python
def _sort(queryset, data, group):
    """A chosen sort; with none, best match when there are keywords to rank by, else price."""
    sort = data.get("sort") or ""
    if not sort:
        keywords = search_index.parse(data.get("q"))
        if keywords and keywords.include:
            return queryset.order_by(search_index.rank_expr(keywords).asc(), "pk")
        sort = "price"
    descending = sort.startswith("-")
```

(the rest of `_sort` is unchanged from Task 5).

- [ ] **Step 5: Hide the index's internal tables from the SQL console sidebar**

In `listings/sql_console.py`, `schema()`, change the query to:

```python
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
            "AND name NOT LIKE 'listing\\_search\\_%' ESCAPE '\\' ORDER BY name"
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_search_index.py tests/test_sql_console.py tests/test_sql_queries.py -q`, then `uv run pytest -q`.
Expected: PASS.

- [ ] **Step 7: Check speed against real data**

Run on a copy of the dev database (the laptop's launchd service shares `db.sqlite3`):

```bash
cp db.sqlite3 /private/tmp/claude-501/search-check.sqlite3
```

Then run with `DATABASES` pointed at the copy (or simply run `uv run python manage.py migrate` on the dev DB if no service is using it), and time a search:

```bash
uv run python manage.py shell -c "import time; from listings.models import Listing; from listings.filters import apply_filters; from listings.forms import ListingFilterForm; from accounts.groups import owners_group; f=ListingFilterForm({'q': 'balcony OR terrace'}); f.is_valid(); t=time.time(); n=len(list(apply_filters(Listing.objects.all(), f.cleaned_data, owners_group())[:100])); print(n, round((time.time()-t)*1000), 'ms')"
```

Expected: well under 200 ms. If not, replace `rank_expr`'s correlated subquery with one MATCH query that returns `rowid, bm25(...)` for all matches and order with `Case(When(pk=…))` over those ids, and note it in `CLAUDE.md`.

- [ ] **Step 8: Update `CLAUDE.md`**

- Code map, new bullet: "`listings/search_index.py`: keyword search. `listing_search` is an FTS5 table (external content on `listings_listing`) kept in sync by triggers from migration 0023, so even `QuerySet.update` is covered. `parse()` turns Google-style input (phrases, `-exclude`, `OR`, `prefix*`) into FTS5 built only from quoted terms; OR binds tighter than AND. A blank sort means best match (bm25) when there are keywords. `highlights()` wraps matches in `<mark>` after escaping."
- Gotchas: "The SQL console hides `listing_search_*` (FTS5's shadow tables). To rebuild the index by hand: `INSERT INTO listing_search(listing_search) VALUES ('rebuild')`."
- Current state: "PR 2/5 keyword search."

- [ ] **Step 9: Commit, push and open PR 2**

```bash
git add listings/search_index.py listings/forms.py listings/filters.py listings/sql_console.py tests/test_search_index.py tests/test_sql_console.py CLAUDE.md
git commit -m "feat: keyword search with best-match sort and highlights

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push -u origin search-2-keywords
gh pr create --base search-1-filters --title "[Advanced search 2/5] Keyword search with SQLite FTS5" --body-file <scratchpad>/pr2.md
```

PR body: the template from Task 5 with this PR's summary (FTS5 index + triggers + backfill in migration 0023; phrases, -exclude, OR, prefix*; best-match sort; highlights) and **#this** on line 2 of the stack.

---

# PR 3 — `[Advanced search 3/5] The /search/ page`

Branch: `git checkout -b search-3-page` (from `search-2-keywords`). Open the PR with `--base search-2-keywords`.

### Task 8: The column registry

**Files:**
- Create: `listings/search_columns.py`
- Test: `tests/test_search_columns.py` (new)

**Interfaces:**
- Produces: `Column(key, label, sort="", default=False)`; `COLUMNS` (registry order is display order); `DEFAULT_KEYS`; `keys_from(keys) -> list[str]` (known keys in registry order, defaults when none); `headers(keys, current_sort, url_for) -> list[dict]` with `key`, `label`, `sort_key` (`""` when not sortable), `next_sort`, `arrow` (`"↑"`, `"↓"` or `""`), `url`.

- [ ] **Step 1: Write the failing tests**

```python
from listings.forms import SORT_FIELDS
from listings.search_columns import COLUMNS, DEFAULT_KEYS, headers, keys_from


def test_defaults_match_the_decisions():
    assert DEFAULT_KEYS == ["photo", "address", "area", "price", "beds_baths", "sqft", "ppsf", "parking", "features",
                            "dom", "status", "votes"]


def test_every_sortable_column_has_a_sort():
    assert all(column.sort in SORT_FIELDS for column in COLUMNS if column.sort)


def test_keys_from_keeps_known_keys_in_registry_order():
    assert keys_from(["price", "bogus", "address"]) == ["address", "price"]
    assert keys_from([]) == DEFAULT_KEYS
    assert keys_from(["bogus"]) == DEFAULT_KEYS


def test_headers_toggle_direction_and_show_an_arrow():
    url = lambda sort: f"?sort={sort}"
    by_key = {h["key"]: h for h in headers(["photo", "price", "sqft"], "price", url)}
    assert by_key["photo"]["sort_key"] == "" and by_key["photo"]["url"] == ""
    assert (by_key["price"]["arrow"], by_key["price"]["next_sort"], by_key["price"]["url"]) == ("↑", "-price", "?sort=-price")
    assert (by_key["sqft"]["arrow"], by_key["sqft"]["next_sort"]) == ("", "sqft")
    assert {h["key"]: h for h in headers(["price"], "-price", url)}["price"]["next_sort"] == "price"
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_search_columns.py -q`
Expected: FAIL (module missing).

- [ ] **Step 3: Write `listings/search_columns.py`**

```python
"""The Search page's table columns: which exist, which show by default, and how each header sorts."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    sort: str = ""  # a SORT_FIELDS key; "" when the column doesn't sort
    default: bool = False


COLUMNS = [
    Column("photo", "Photo", default=True),
    Column("address", "Address", "address", True),
    Column("area", "Area", "area", True),
    Column("price", "Price", "price", True),
    Column("beds_baths", "Bd / Ba", "beds", True),
    Column("sqft", "Sqft", "sqft", True),
    Column("ppsf", "$/sqft", "ppsf", True),
    Column("parking", "Parking", "parking", True),
    Column("features", "Features", default=True),
    Column("dom", "On market", "dom", True),
    Column("status", "Status", "status", True),
    Column("votes", "Votes", "votes", True),
    Column("effective", "Effective rent", "effective"),
    Column("drop", "Price drop", "drop"),
    Column("special", "Special"),
    Column("type", "Type", "type"),
    Column("zip", "ZIP", "zip"),
    Column("sources", "Sources", "sites"),
    Column("listed", "Listed", "listed"),
    Column("first_seen", "First seen", "first_seen"),
    Column("last_seen", "Last seen", "last_seen"),
]
BY_KEY = {column.key: column for column in COLUMNS}
DEFAULT_KEYS = [column.key for column in COLUMNS if column.default]


def keys_from(keys):
    """The known keys among keys, in registry order; the defaults when there are none."""
    wanted = set(keys or [])
    return [column.key for column in COLUMNS if column.key in wanted] or list(DEFAULT_KEYS)


def headers(keys, current_sort, url_for):
    """Header cells for the table. Clicking a header sorts by it ascending, or flips it if it's the sort now."""
    cells = []
    for key in keys:
        column = BY_KEY[key]
        cell = {"key": key, "label": column.label, "sort_key": column.sort, "next_sort": "", "arrow": "", "url": ""}
        if column.sort:
            ascending, descending = current_sort == column.sort, current_sort == f"-{column.sort}"
            cell["next_sort"] = f"-{column.sort}" if ascending else column.sort
            cell["arrow"] = "↑" if ascending else "↓" if descending else ""
            cell["url"] = url_for(cell["next_sort"])
        cells.append(cell)
    return cells
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_search_columns.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add listings/search_columns.py tests/test_search_columns.py
git commit -m "feat: column registry for the Search page

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 9: The Search page: filter panel, live results table, sorting, paging

**Files:**
- Create: `listings/search_views.py`, `listings/templates/listings/search.html`, `_range.html`, `_number.html`, `_search_cell.html`, `_search_card.html`
- Modify: `listings/urls.py`, `listings/forms.py` (`active_count`), `listings/templates/listings/base.html` (nav, CSS)
- Test: `tests/test_search_page.py` (new)

**Interfaces:**
- Consumes: `ListingFilterForm` (+ `search_menus`, `raw_values`), `apply_filters`, `search_index.highlights`, `search_columns.keys_from/headers/DEFAULT_KEYS`, `collab.decorate`.
- Produces: URL name `search` at `/search/`; `search_views.STATE_PARAMS = {"page", "cols", "saved"}`; `search_views.search_form(request) -> ListingFilterForm`; `search_views.query_string(data, **changes) -> str` (urlencoded; a change of `None` removes the key); `search_views.searched(request) -> (form, queryset)`; `ListingFilterForm.active_count() -> int`. Template context: `form`, `page_obj`, `listings`, `headers`, `column_keys`, `query` (the effective search, without `page`), `filter_count`, `ignored` (list of "Label: message"), `prev_url`, `next_url`, `clear_url`. Each listing gets `.hl` (highlights dict, maybe empty).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_search_page.py`:

```python
import re
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest

from tests.helpers import make_listing

pytestmark = pytest.mark.django_db


def good(key, **extra):
    fields = dict(address_key=key, price=3000, beds=2, baths=Decimal("2"), parking_spaces=2, property_type="condo")
    fields.update(extra)
    return make_listing(**fields)


def page(client, query=""):
    response = client.get(f"/search/{query}")
    assert response.status_code == 200
    return response.content.decode()


def test_search_is_in_the_nav_and_starts_from_the_group_defaults(client):
    good("fits")
    good("one-bed", beds=1)
    content = page(client)
    assert '<a href="/search/">Search</a>' in content
    assert re.search(r'<form id="search-filters"[^>]*hx-trigger="change, input delay:400ms"', content)
    assert re.search(r'<input id="search-q" type="search" name="q"', content)
    keys = {listing.address_key for listing in client.get("/search/").context["listings"]}
    assert keys == {"fits"}


def test_clear_all_searches_every_active_listing(client):
    good("fits")
    good("one-bed", beds=1)
    good("gone", is_active=False)
    content = page(client)
    assert '<a class="clear-all" href="/search/?q=">Clear all</a>' in content
    keys = {listing.address_key for listing in client.get("/search/?q=").context["listings"]}
    assert keys == {"fits", "one-bed"}


def test_header_and_page_links_keep_the_default_filters(client):
    for n in range(101):
        good(f"fits-{n:03}", price=3000 + n)
    good("one-bed", beds=1)
    response = client.get("/search/")
    headers = {h["key"]: h for h in response.context["headers"]}
    for url in (headers["price"]["url"], response.context["next_url"]):
        params = parse_qs(urlparse(url).query)
        assert params["min_beds"] == ["2"] and "types" in params, url
    assert parse_qs(urlparse(headers["price"]["url"]).query)["sort"] == ["price"]
    assert "page" not in parse_qs(urlparse(headers["price"]["url"]).query)


def test_results_page_at_100_with_a_count(client):
    for n in range(101):
        good(f"fits-{n:03}", price=3000 + n)
    content = page(client, "?q=")
    assert "101 listings" in content and "showing 1–100" in content
    assert content.count('<td class="m-card">') == 100
    assert "Page 1 of 2" in content


def test_clicking_a_header_sorts(client):
    good("cheap", price=2500)
    good("dear", price=3500)
    keys = [listing.address_key for listing in client.get("/search/?q=&sort=-price").context["listings"]]
    assert keys == ["dear", "cheap"]
    content = page(client, "?q=&sort=-price")
    assert re.search(r'<a href="/search/\?[^"]*sort=price[^"]*" data-sort="price" class="sort-link sorted">Price ↓</a>', content)


def test_default_columns_render(client):
    good("fits", sqft=1000, photo_url="https://example.com/p.jpg")
    content = page(client, "?q=")
    for key in ("photo", "address", "area", "price", "beds_baths", "sqft", "ppsf", "parking", "features", "dom", "status", "votes"):
        assert f'<td class="col-{key}">' in content, key
    assert "$3.00" in content  # $/sqft


def test_a_bad_value_skips_only_that_filter(client):
    good("fits", sqft=1000)
    good("one-bed", beds=1, sqft=1000)
    response = client.get("/search/?q=&min_beds=2&min_sqft=abc")
    assert {listing.address_key for listing in response.context["listings"]} == {"fits"}
    assert "Ignored Min sqft: Enter a whole number." in response.content.decode()


def test_keyword_matches_are_highlighted(client):
    good("a", description="Corner unit with a huge balcony.")
    content = page(client, "?q=balcony")
    assert '<div class="search-snippet">' in content and "<mark>balcony</mark>" in content


def test_filter_count_updates_out_of_band(client):
    content = page(client, "?q=&min_beds=3&zips=97209")
    assert '<span id="filter-count">(2)</span>' in content
    assert 'hx-select-oob="#filter-count"' in content


def test_search_only_and_shared_filters_render_in_the_panel(client):
    content = page(client, "?q=&wd=no&zips=97209&max_sqft=1500")
    assert re.search(r'<select name="wd"[^>]*>.*?<option value="no" selected>No</option>', content, re.S)
    assert re.search(r'<input type="checkbox" name="zips" value="97209"[^>]*checked', content)
    assert 'name="max_sqft" value="1500"' in content
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_search_page.py -q`
Expected: FAIL (404 for `/search/`).

- [ ] **Step 3: Add `active_count` to `ListingFilterForm`**

```python
    def active_count(self):
        """How many filters are set (Search's "Filters (n)"). Sort isn't a filter; the map area counts once."""
        data = getattr(self, "cleaned_data", {})
        area = ("north", "south", "east", "west")
        count = sum(1 for name, value in data.items()
                    if name not in ("sort", *area) and value not in (None, "", [], False, "any"))
        return count + all(data.get(side) is not None for side in area)
```

- [ ] **Step 4: Write `listings/search_views.py`**

```python
"""The Search page: every filter, a configurable table, CSV, and the group's saved searches."""

from django.core.paginator import Paginator
from django.http import QueryDict
from django.shortcuts import render
from django.urls import reverse

from . import collab, search_columns, search_index
from .filters import apply_filters
from .forms import ListingFilterForm, default_filter_data
from .models import Listing

PAGE_SIZE = 100
STATE_PARAMS = {"page", "cols", "saved"}  # not filters: a URL with only these starts from the group's defaults


def search_form(request):
    """The URL's search, or the group's defaults (sorted by best match) when the URL has no filters."""
    if any(key not in STATE_PARAMS for key in request.GET):
        return ListingFilterForm(request.GET)
    return ListingFilterForm({**default_filter_data(request.group), "sort": ""})


def query_string(data, **changes):
    """A URL query for a search's data (a QueryDict, or a dict of defaults whose values may be lists), with
    changes applied; a change of None removes that key. Links are built from this, not request.GET, so a page
    that started from the defaults keeps them."""
    query = QueryDict(mutable=True)
    for key in data:
        values = data.getlist(key) if isinstance(data, QueryDict) else data[key]
        values = values if isinstance(values, (list, tuple)) else [values]
        query.setlist(key, [str(value) for value in values])
    for key, value in changes.items():
        if value is None:
            query.pop(key, None)
        else:
            query[key] = value
    return query.urlencode()


def searched(request):
    form = search_form(request)
    form.is_valid()  # a bad value drops that one filter: cleaned_data keeps the rest
    return form, apply_filters(Listing.objects.all(), form.cleaned_data, request.group)


def _url(form, **changes):
    return f"{reverse('search')}?{query_string(form.data, page=None, **changes)}"


def search_page(request):
    form, queryset = searched(request)
    page_obj = Paginator(queryset.prefetch_related("source_listings__source", "price_changes"), PAGE_SIZE).get_page(
        request.GET.get("page"))
    listings = collab.decorate(page_obj.object_list, request.group, request.user)
    marks = search_index.highlights([listing.pk for listing in listings], form.cleaned_data.get("q"))
    for listing in listings:
        listing.hl = marks.get(listing.pk, {})
    column_keys = search_columns.DEFAULT_KEYS
    current_sort = form.cleaned_data.get("sort") or ""
    return render(request, "listings/search.html", {
        "form": form,
        "page_obj": page_obj,
        "listings": listings,
        "column_keys": column_keys,
        "headers": search_columns.headers(column_keys, current_sort, lambda sort: _url(form, sort=sort)),
        "query": query_string(form.data, page=None),
        "filter_count": form.active_count(),
        "ignored": [f"{form[name].label}: {errors[0]}" for name, errors in form.errors.items()],
        "prev_url": _url(form, page=page_obj.previous_page_number()) if page_obj.has_previous() else "",
        "next_url": _url(form, page=page_obj.next_page_number()) if page_obj.has_next() else "",
        "clear_url": f"{reverse('search')}?q=",
    })
```

- [ ] **Step 5: Add the URL and nav link**

`listings/urls.py`: add `search_views` to the import and `path("search/", search_views.search_page, name="search"),` after the `listing_list` path.

`listings/templates/listings/base.html`, in `<nav>` after the Listings link:

```django
      <a href="{% url 'search' %}">Search</a>
```

- [ ] **Step 6: Write the small templates**

`listings/templates/listings/_range.html`:

```django
{# A min–max pair of number inputs: label, low and high (bound fields), optional step. #}
<div class="range-row">
  <span class="range-label">{{ label }}</span>
  <input type="number" name="{{ low.html_name }}" value="{{ low.value|default_if_none:'' }}" min="0" step="{{ step|default:1 }}" inputmode="decimal" placeholder="Min" aria-label="Minimum {{ label|lower }}">
  <span class="muted">–</span>
  <input type="number" name="{{ high.html_name }}" value="{{ high.value|default_if_none:'' }}" min="0" step="{{ step|default:1 }}" inputmode="decimal" placeholder="Max" aria-label="Maximum {{ label|lower }}">
</div>
```

`listings/templates/listings/_number.html`:

```django
{# One labeled number input: field (bound), optional step. #}
<label class="field">{{ field.label }} <input type="number" name="{{ field.html_name }}" value="{{ field.value|default_if_none:'' }}" min="0" step="{{ step|default:1 }}" inputmode="numeric"></label>
```

`listings/templates/listings/_search_card.html`:

```django
{% load humanize %}
<a class="m-card-link" href="{{ listing.get_absolute_url }}">
  {% if listing.photo_url %}<img src="{{ listing.photo_url }}" alt="" loading="lazy">{% else %}<span class="m-thumb"></span>{% endif %}
  <span class="m-lines">
    <span><strong>{% if listing.price %}${{ listing.price|intcomma }}{% else %}?{% endif %}</strong> · {{ listing.beds|default_if_none:"?" }} bd / {{ listing.baths|floatformat:"-1"|default:"?" }} ba{% if listing.sqft %} · {{ listing.sqft|intcomma }} sqft{% endif %}</span>
    <span class="muted">{{ listing.street }}{% if listing.unit %} #{{ listing.unit }}{% endif %}{% if listing.location_label %} · {{ listing.location_label }}{% endif %}</span>
  </span>
  <span class="status status-{{ listing.group_status }}">{{ listing.group_status_label }}</span>
</a>
```

`listings/templates/listings/_search_cell.html`:

```django
{% load humanize %}
{% if column == "photo" %}<a href="{{ listing.get_absolute_url }}">{% if listing.photo_url %}<img class="thumb" src="{{ listing.photo_url }}" alt="" loading="lazy">{% else %}<span class="thumb"></span>{% endif %}</a>
{% elif column == "address" %}<a href="{{ listing.get_absolute_url }}">{% if listing.hl.address %}{{ listing.hl.address }}{% else %}{{ listing.street }}{% if listing.unit %} #{{ listing.unit }}{% endif %}{% endif %}</a>
  {% if listing.hl.title %}<div class="small">{{ listing.hl.title }}</div>{% endif %}
  {% if listing.hl.snippet %}<div class="search-snippet">{{ listing.hl.snippet }}</div>{% endif %}
  {% if not listing.is_active %}<div class="offmarket">Off market</div>{% endif %}
{% elif column == "area" %}{{ listing.location_label|default:"–" }}
{% elif column == "price" %}<strong>{% if listing.price %}${{ listing.price|intcomma }}{% else %}?{% endif %}</strong>
  {% if listing.price_drop %}<div class="drop" title="Down {{ listing.price_drop_percent }}% since listed">↓ ${{ listing.price_drop|intcomma }}</div>{% endif %}
  {% if listing.special_offer %}<div>{% include "listings/_special.html" %}</div>{% endif %}
{% elif column == "beds_baths" %}{{ listing.beds|default_if_none:"?" }} / {{ listing.baths|floatformat:"-1"|default:"?" }}
{% elif column == "sqft" %}{{ listing.sqft|intcomma|default:"?" }}
{% elif column == "ppsf" %}{% if listing.price_per_sqft %}${{ listing.price_per_sqft|floatformat:2 }}{% else %}–{% endif %}
{% elif column == "parking" %}{% if listing.parking_spaces is not None %}{{ listing.parking_spaces }}{% elif listing.has_parking %}Yes (spaces ?){% elif listing.has_parking is False %}None{% else %}?{% endif %}
{% elif column == "features" %}{% include "listings/_feature.html" with label="W/D" value=listing.has_washer_dryer %}{% include "listings/_feature.html" with label="AC" value=listing.has_ac %}{% include "listings/_feature.html" with label="Outdoor" value=listing.has_outdoor_space %}{% include "listings/_furnished.html" %}
{% elif column == "dom" %}{{ listing.days_on_market }}d
{% elif column == "status" %}<span class="status status-{{ listing.group_status }}">{{ listing.group_status_label }}</span>
{% elif column == "votes" %}{% if listing.up_count %}👍 {{ listing.up_count }}{% endif %} {% if listing.down_count %}👎 {{ listing.down_count }}{% endif %}
{% elif column == "effective" %}{% if listing.effective_rent %}${{ listing.effective_rent|intcomma }}{% else %}–{% endif %}
{% elif column == "drop" %}{% if listing.price_drop %}${{ listing.price_drop|intcomma }} ({{ listing.price_drop_percent }}%){% else %}–{% endif %}
{% elif column == "special" %}{% if listing.special_offer %}{% include "listings/_special.html" %}{% else %}–{% endif %}
{% elif column == "type" %}{{ listing.get_property_type_display }}
{% elif column == "zip" %}{{ listing.zip_code|default:"–" }}
{% elif column == "sources" %}{% include "listings/_sources.html" %}
{% elif column == "listed" %}{{ listing.listed_at|date:"M j, Y"|default:"–" }}
{% elif column == "first_seen" %}{{ listing.first_seen_at|date:"M j, Y" }}
{% elif column == "last_seen" %}{{ listing.last_seen_at|date:"M j, Y" }}
{% endif %}
```

- [ ] **Step 7: Write `listings/templates/listings/search.html`**

```django
{% extends "listings/base.html" %}
{% load humanize %}
{% block title %}Search · Condo Finder{% endblock %}
{% block content %}
<div class="search-head">
  <h1>Search</h1>
  <a class="clear-all" href="{{ clear_url }}">Clear all</a>
  <button type="button" class="filters-toggle" data-filters-toggle aria-controls="search-filters">Filters <span id="filter-count">({{ filter_count }})</span></button>
</div>

<form id="search-filters" class="search-panel" method="get" action="{% url 'search' %}"
      hx-get="{% url 'search' %}" hx-target="#results" hx-select="#results" hx-select-oob="#filter-count" hx-swap="outerHTML"
      hx-push-url="true" hx-trigger="change, input delay:400ms" hx-sync="this:replace" hx-indicator="#results">
  <input type="hidden" name="north" value="{{ form.north.value|default_if_none:'' }}">
  <input type="hidden" name="south" value="{{ form.south.value|default_if_none:'' }}">
  <input type="hidden" name="east" value="{{ form.east.value|default_if_none:'' }}">
  <input type="hidden" name="west" value="{{ form.west.value|default_if_none:'' }}">

  <div class="search-keywords">
    <label class="panel-title" for="search-q">Keywords</label>
    <input id="search-q" type="search" name="q" value="{{ form.q.value|default_if_none:'' }}" autocomplete="off"
           placeholder='e.g. "walk-in closet" balcony OR terrace -studio'>
    <p class="muted small">"Quotes" for a phrase, -word to leave it out, OR between alternatives, word* for prefixes.</p>
    <label class="field sort-field">Sort {% include "listings/_select.html" with name="sort" options=form.search_menus.sort %}</label>
  </div>

  <div class="search-groups">
    <fieldset><legend>Price</legend>
      {% include "listings/_range.html" with label="Rent" low=form.min_price high=form.max_price step=50 %}
      {% include "listings/_range.html" with label="Effective" low=form.min_effective high=form.max_effective step=50 %}
      {% include "listings/_range.html" with label="$/sqft" low=form.min_ppsf high=form.max_ppsf step="0.05" %}
      {% include "listings/_number.html" with field=form.min_drop_amount step=25 %}
      {% include "listings/_number.html" with field=form.min_drop_percent %}
      {% include "listings/_number.html" with field=form.min_price_changes %}
      <label class="inline">{{ form.price_reduced }} Price reduced</label>
      <label class="inline">{{ form.price_raised }} Price went up</label>
      <label class="inline">{{ form.specials }} Move-in specials only</label>
    </fieldset>

    <fieldset><legend>Size</legend>
      {% include "listings/_range.html" with label="Beds" low=form.min_beds high=form.max_beds %}
      {% include "listings/_range.html" with label="Baths" low=form.min_baths high=form.max_baths step="0.5" %}
      {% include "listings/_range.html" with label="Sqft" low=form.min_sqft high=form.max_sqft step=50 %}
      {% include "listings/_range.html" with label="Parking" low=form.min_parking high=form.max_parking %}
      <label class="inline">{{ form.parking_unknown }} Include unknown parking</label>
      <div class="panel-title">Type</div>
      <div class="check-list">{% for option in form.types %}<label>{{ option.tag }} {{ option.choice_label }}</label>{% endfor %}</div>
    </fieldset>

    <fieldset><legend>Features</legend>
      <label class="field">In-unit W/D {% include "listings/_select.html" with name="wd" options=form.search_menus.wd %}</label>
      <label class="field">AC {% include "listings/_select.html" with name="ac" options=form.search_menus.ac %}</label>
      <label class="field">Outdoor space {% include "listings/_select.html" with name="outdoor" options=form.search_menus.outdoor %}</label>
      <label class="field">Furnished {% include "listings/_select.html" with name="furnished" options=form.search_menus.furnished %}</label>
      <label class="field">Has parking {% include "listings/_select.html" with name="parking" options=form.search_menus.parking %}</label>
    </fieldset>

    <fieldset><legend>Location</legend>
      <div class="check-list">{% for option in form.cities %}<label>{{ option.tag }} {{ option.choice_label }}</label>{% endfor %}</div>
      <div class="panel-title">Portland quadrant</div>
      <div class="check-list columns">{% for option in form.quadrants %}<label>{{ option.tag }} {{ option.choice_label }}</label>{% endfor %}</div>
      <div class="panel-title">Neighborhoods</div>
      <div class="check-list scroll">{% for option in form.neighborhoods %}<label>{{ option.tag }} {{ option.choice_label }}</label>{% endfor %}</div>
      <label class="field">Name contains <input type="text" name="neighborhood" value="{{ form.neighborhood.value|default_if_none:'' }}" autocomplete="off"></label>
      <div class="panel-title">ZIP codes</div>
      <div class="check-list scroll columns">{% for option in form.zips %}<label>{{ option.tag }} {{ option.choice_label }}</label>{% endfor %}</div>
      <label class="inline">{{ form.has_location }} On the map only</label>
    </fieldset>

    <fieldset><legend>Time on market</legend>
      {% include "listings/_range.html" with label="Days" low=form.min_dom high=form.max_dom %}
      {% include "listings/_number.html" with field=form.new_within %}
      {% include "listings/_number.html" with field=form.gone_within %}
      <label class="field">Listed from <input type="date" name="listed_from" value="{{ form.listed_from.value|default_if_none:'' }}"></label>
      <label class="field">Listed to <input type="date" name="listed_to" value="{{ form.listed_to.value|default_if_none:'' }}"></label>
      <label class="inline">{{ form.show_inactive }} Show off-market</label>
    </fieldset>

    <fieldset><legend>Ours and sources</legend>
      <div class="check-list">{% for option in form.statuses %}<label>{{ option.tag }} {{ option.choice_label }}</label>{% endfor %}</div>
      <label class="field">Votes {% include "listings/_select.html" with name="votes" options=form.search_menus.votes %}</label>
      <div class="panel-title">Sources</div>
      <div class="check-list columns">{% for option in form.sources %}<label>{{ option.tag }} {{ option.choice_label }}</label>{% endfor %}</div>
      {% include "listings/_number.html" with field=form.min_sites %}
      <label class="inline">{{ form.has_photo }} Has a photo</label>
    </fieldset>
  </div>
  <button type="button" class="filters-done" data-filters-toggle>Show results</button>
  <noscript><button type="submit">Search</button></noscript>
</form>

<section id="results">
  {% if ignored %}<p class="panel notice error">Ignored {{ ignored|join:"; " }}</p>{% endif %}
  <div class="results-bar">
    <p class="muted">{{ page_obj.paginator.count|intcomma }} listing{{ page_obj.paginator.count|pluralize }}
      {% if page_obj.paginator.num_pages > 1 %}· showing {{ page_obj.start_index }}–{{ page_obj.end_index }}{% endif %}</p>
  </div>
  <div class="table-wrap">
  <table class="listing-table search-table">
    <thead><tr>
      {% for header in headers %}<th>{% if header.url %}<a href="{{ header.url }}" data-sort="{{ header.next_sort }}" class="sort-link{% if header.arrow %} sorted{% endif %}">{{ header.label }}{% if header.arrow %} {{ header.arrow }}{% endif %}</a>{% else %}{{ header.label }}{% endif %}</th>{% endfor %}
    </tr></thead>
    <tbody>
    {% for listing in listings %}
      <tr>
        {% for key in column_keys %}<td class="col-{{ key }}">{% include "listings/_search_cell.html" with column=key %}</td>{% endfor %}
        <td class="m-card">{% include "listings/_search_card.html" %}</td>
      </tr>
    {% empty %}
      <tr><td colspan="{{ column_keys|length }}">No listings match. Try removing a filter, or <a href="{{ clear_url }}">clear them all</a>.</td></tr>
    {% endfor %}
    </tbody>
  </table>
  </div>
  {% include "listings/_pagination.html" %}
</section>
{% endblock %}
{% block scripts %}
<script>
  const searchForm = document.getElementById("search-filters");
  document.addEventListener("click", event => {
    const header = event.target.closest("a[data-sort]");
    if (header && searchForm) {  // sort through the form so the URL, the Sort menu and the results agree
      event.preventDefault();
      searchForm.elements.sort.value = header.dataset.sort;
      htmx.trigger(searchForm, "change");
    }
    if (event.target.closest("[data-filters-toggle]")) document.body.classList.toggle("filters-open");
  });
</script>
{% endblock %}
```

- [ ] **Step 8: Add the Search CSS to `base.html`** (before the `@media (max-width: 800px)` block)

```css
    /* Search page */
    .search-head { display:flex; flex-wrap:wrap; align-items:center; gap:8px 16px; margin-bottom:12px; }
    .search-head h1 { margin:0; font-size:26px; } .clear-all { font-size:14px; }
    .filters-toggle, .filters-done { display:none; }
    .search-panel { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px 16px; margin-bottom:16px; }
    .search-keywords { display:grid; grid-template-columns:minmax(0, 1fr) auto; gap:4px 16px; align-items:center; margin-bottom:12px; }
    .search-keywords .panel-title, .search-keywords p { grid-column:1 / -1; margin:0; }
    .search-keywords input[type=search] { width:100%; padding:9px 12px; border:1px solid var(--line); border-radius:8px; font:inherit; }
    .search-groups { display:grid; grid-template-columns:repeat(auto-fill, minmax(250px, 1fr)); gap:14px 24px; }
    .search-groups fieldset { border:0; margin:0; padding:0; min-width:0; }
    .search-groups legend { font-size:12px; font-weight:700; text-transform:uppercase; letter-spacing:.04em; color:var(--accent); margin-bottom:6px; }
    .search-panel select, .search-panel input[type=number], .search-panel input[type=date], .search-panel input[type=text] {
      padding:5px 7px; border:1px solid var(--line); border-radius:6px; font:inherit; font-size:14px; min-width:0; }
    .range-row { display:grid; grid-template-columns:5.5em minmax(0, 1fr) auto minmax(0, 1fr); gap:6px; align-items:center; font-size:14px; padding:3px 0; }
    .range-row input { width:100%; }
    .search-panel label.field input[type=number] { width:6.5em; }
    .check-list.scroll { max-height:160px; overflow-y:auto; padding-right:4px; }
    .search-table { min-width:960px; }
    .search-table .sort-link { color:inherit; text-decoration:none; white-space:nowrap; } .search-table .sort-link.sorted { color:var(--accent); }
    .search-table mark { background:#fff1a8; padding:0 1px; border-radius:2px; }
    .search-snippet { font-size:12px; color:var(--muted); max-width:52ch; margin-top:2px; }
    .search-table td.m-card { display:none; }
```

- [ ] **Step 9: Run the tests**

Run: `uv run pytest tests/test_search_page.py -q`, then `uv run pytest -q`.
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add listings/search_views.py listings/urls.py listings/forms.py listings/templates/listings/search.html listings/templates/listings/_range.html listings/templates/listings/_number.html listings/templates/listings/_search_cell.html listings/templates/listings/_search_card.html listings/templates/listings/base.html tests/test_search_page.py
git commit -m "feat: /search/ page with every filter and a live, sortable results table

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 10: Phone layout, a browser check, and PR 3

**Files:**
- Modify: `listings/templates/listings/base.html` (CSS)
- Test: `tests/test_search_page.py`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: the Search page from Task 9 (`.filters-toggle`, `.filters-done`, `td.m-card`, `body.filters-open`).

- [ ] **Step 1: Write the failing test** (append to `tests/test_search_page.py`)

```python
def test_phone_layout_has_a_filters_drawer_and_compact_cards(client):
    good("fits")
    content = page(client)
    assert re.search(r'<button type="button" class="filters-toggle" data-filters-toggle', content)
    assert '<button type="button" class="filters-done" data-filters-toggle>Show results</button>' in content
    assert '<td class="m-card"><a class="m-card-link"' in content.replace("\n", "")
    assert "@media (max-width: 700px)" in content
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/test_search_page.py -q -k phone`
Expected: FAIL (no 700px media query).

- [ ] **Step 3: Add the phone CSS** (after the Search page rules, before the 800px block)

```css
    @media (max-width: 700px) {
      .filters-toggle { display:inline-block; margin-left:auto; padding:7px 14px; border:1px solid var(--accent); border-radius:999px;
                        background:var(--card); color:var(--accent); font:600 14px/1.2 inherit; }
      .search-panel { display:none; }
      body.filters-open .search-panel { display:block; position:fixed; inset:0; z-index:1500; margin:0; border:0; border-radius:0;
                                        overflow-y:auto; padding:16px 16px 76px; }
      .filters-done { display:block; position:fixed; left:16px; right:16px; bottom:16px; padding:12px; border:0; border-radius:999px;
                      background:var(--accent); color:#fff; font:600 15px/1 inherit; z-index:1600; }
      .search-keywords { grid-template-columns:minmax(0, 1fr); }
      .table-wrap { overflow-x:visible; border:0; }
      .search-table { min-width:0; background:none; }
      .search-table thead, .search-table td:not(.m-card) { display:none; }
      .search-table, .search-table tbody, .search-table tr { display:block; }
      .search-table td.m-card { display:block; padding:0; border:0; margin-bottom:8px; }
      .m-card-link { display:grid; grid-template-columns:72px minmax(0, 1fr) auto; gap:10px; align-items:center; padding:8px;
                     background:var(--card); border:1px solid var(--line); border-radius:10px; color:var(--ink); text-decoration:none; }
      .m-card-link img, .m-thumb { width:72px; height:54px; object-fit:cover; border-radius:6px; background:#ddd; display:block; }
      .m-lines { display:flex; flex-direction:column; min-width:0; font-size:14px; }
      .m-lines span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    }
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_search_page.py -q`, then `uv run pytest -q`.
Expected: PASS.

- [ ] **Step 5: Check it in a browser**

Start the dev server (`DJANGO_DEBUG=1 uv run python manage.py runserver 127.0.0.1:8000` after `uv run python manage.py migrate`; if the laptop's launchd service already serves `db.sqlite3` on :8000, use port 8001 and migrate a copy as described in the "Laptop service shares dev DB" memory). Log in, open `/search/`, and check with Claude in Chrome:
- Desktop (1280px): the panel shows every group; typing `balcony OR terrace` updates the table after a pause, the URL changes, Back restores the previous search; clicking "Price" then "Price" again flips the arrow; "Next →" keeps the filters; Clear all shows every active listing; matched words are highlighted.
- Phone (375px): "Filters (n)" opens a full-screen panel, "Show results" closes it, rows are two-line cards, `document.documentElement.scrollWidth <= innerWidth`, and the console has no errors.
- The home page still looks and works as before (the drawer's menus are unchanged).

- [ ] **Step 6: Update `CLAUDE.md`**

- Code map, new bullet: "`listings/search_views.py` and `search.html`: the Search page (`/search/`). It starts from the group's default filters (best-match sort); `?q=` is Clear all. Links (headers, pages) come from `query_string(form.data)`, never `request.GET`, so default filters survive. A bad value skips only that filter (`form.cleaned_data` keeps the rest) and is listed as Ignored. HTMX re-renders the page and swaps `#results` (plus `#filter-count` out of band). Below 700px rows become cards (`td.m-card`) and the panel a drawer. `search_columns.py` is the column registry."
- Current state: "PR 3/5 the Search page."

- [ ] **Step 7: Commit, push and open PR 3**

```bash
git add listings/templates/listings/base.html tests/test_search_page.py CLAUDE.md
git commit -m "feat: phone layout for the Search page

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push -u origin search-3-page
gh pr create --base search-2-keywords --title "[Advanced search 3/5] The /search/ page" --body-file <scratchpad>/pr3.md
```

PR body: the template with this PR's summary and **#this** on line 3 of the stack. Mention the browser check (desktop and 375px).

---

# PR 4 — `[Advanced search 4/5] Columns, CSV, inline status and votes`

Branch: `git checkout -b search-4-columns` (from `search-3-page`). Open the PR with `--base search-3-page`.

### Task 11: The Columns menu, saved per person

**Files:**
- Modify: `accounts/models.py` (`Profile.search_columns`); create `accounts/migrations/0007_profile_search_columns.py`
- Modify: `listings/search_views.py`, `listings/urls.py`, `listings/templates/listings/search.html`, `base.html` (CSS)
- Test: `tests/test_search_page.py`

**Interfaces:**
- Consumes: `search_columns.COLUMNS`, `keys_from`, `query_string`.
- Produces: `Profile.search_columns` (JSON list of column keys; empty = defaults); URL `search_columns` (POST `/search/columns/`: `cols` (list), `query`, optional `reset`) answering with `HX-Redirect` (or a redirect without HTMX) to `/search/?<query without cols and page>`; `search_views.column_keys(request) -> list[str]` (`?cols=a,b` from a link wins over the person's choice); context `all_columns`, `cols_param`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_search_page.py`)

```python
def test_column_choices_are_saved_per_person_and_follow_them(client, owner, member_client):
    good("fits", zip_code="97209")
    response = client.post("/search/columns/", {"cols": ["address", "price", "zip"], "query": "q=&sort=-price&page=2"},
                           HTTP_HX_REQUEST="true")
    assert response["HX-Redirect"] == "/search/?q=&sort=-price"
    owner.profile.refresh_from_db()
    assert owner.profile.search_columns == ["address", "price", "zip"]
    content = page(client, "?q=")
    assert re.search(r'<td class="col-zip">\s*97209\s*</td>', content) and '<td class="col-sqft">' not in content
    assert '<td class="col-sqft">' in member_client.get("/search/?q=").content.decode()  # Alex still has the defaults


def test_reset_brings_back_the_default_columns(client, owner):
    client.post("/search/columns/", {"cols": ["address"], "query": ""})
    client.post("/search/columns/", {"reset": "1", "query": ""})
    owner.profile.refresh_from_db()
    assert owner.profile.search_columns == []


def test_columns_in_a_link_win_and_are_kept_while_filtering(client):
    good("fits", zip_code="97209")
    content = page(client, "?q=&cols=address,zip")
    assert re.search(r'<td class="col-zip">\s*97209\s*</td>', content) and '<td class="col-price">' not in content
    assert '<input type="hidden" name="cols" value="address,zip">' in content
    assert "Keep these columns" in content


def test_unknown_columns_are_ignored(client):
    good("fits")
    assert '<td class="col-price">' in page(client, "?q=&cols=nonsense")
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_search_page.py -q -k column`
Expected: FAIL.

- [ ] **Step 3: Add the field and migration**

`accounts/models.py`, in `Profile` after `feed_seen_at`:

```python
    search_columns = models.JSONField(default=list, blank=True)  # the Search table's columns; empty = the defaults
```

Run `uv run python manage.py makemigrations accounts -n profile_search_columns`.

- [ ] **Step 4: Implement in `listings/search_views.py`**

Add imports: `from django.http import HttpResponse`, `from django.shortcuts import redirect`, `from django.views.decorators.http import require_POST`.

```python
def column_keys(request):
    """Columns from the link (?cols=a,b) when it has them, else the person's own choice."""
    if request.GET.get("cols"):
        return search_columns.keys_from(request.GET["cols"].split(","))
    return search_columns.keys_from(request.profile.search_columns)


@require_POST
def save_columns(request):
    known = {column.key for column in search_columns.COLUMNS}
    keys = [] if request.POST.get("reset") else [key for key in request.POST.getlist("cols") if key in known]
    request.profile.search_columns = search_columns.keys_from(keys) if keys else []
    request.profile.save(update_fields=["search_columns"])
    target = f"{reverse('search')}?{query_string(QueryDict(request.POST.get('query', '')), cols=None, page=None)}"
    if request.headers.get("HX-Request"):
        response = HttpResponse("")
        response["HX-Redirect"] = target
        return response
    return redirect(target)
```

In `search_page`, replace `column_keys = search_columns.DEFAULT_KEYS` with `keys = column_keys(request)`, use `keys` for `column_keys` and `headers`, and add to the context:

```python
        "all_columns": search_columns.COLUMNS,
        "cols_param": request.GET.get("cols", ""),
```

and change `"query"` to `query_string(form.data, page=None, cols=None)` (the Columns form posts this; it must not carry the link's columns back).

`listings/urls.py`: `path("search/columns/", search_views.save_columns, name="search_columns"),`.

- [ ] **Step 5: Add the menu and the hidden `cols` input to `search.html`**

In the `<form id="search-filters">`, after the four area inputs:

```django
  {% if cols_param %}<input type="hidden" name="cols" value="{{ cols_param }}">{% endif %}
```

In `#results`, replace the `results-bar` div with:

```django
  <div class="results-bar">
    <p class="muted">{{ page_obj.paginator.count|intcomma }} listing{{ page_obj.paginator.count|pluralize }}
      {% if page_obj.paginator.num_pages > 1 %}· showing {{ page_obj.start_index }}–{{ page_obj.end_index }}{% endif %}</p>
    <div class="results-controls">
      <details class="chip columns-menu">
        <summary>Columns</summary>
        <form class="chip-panel" method="post" action="{% url 'search_columns' %}" hx-post="{% url 'search_columns' %}" hx-trigger="change, submit">
          {% csrf_token %}
          <input type="hidden" name="query" value="{{ query }}">
          <div class="check-list columns">
            {% for column in all_columns %}<label><input type="checkbox" name="cols" value="{{ column.key }}"{% if column.key in column_keys %} checked{% endif %}> {{ column.label }}</label>{% endfor %}
          </div>
          <button type="submit" name="reset" value="1" class="link">Back to the default columns</button>
        </form>
      </details>
    </div>
  </div>
  {% if cols_param %}
  <form class="panel notice" method="post" action="{% url 'search_columns' %}">
    {% csrf_token %}<input type="hidden" name="query" value="{{ query }}">
    {% for key in column_keys %}<input type="hidden" name="cols" value="{{ key }}">{% endfor %}
    This link chose its own columns. <button type="submit" class="link">Keep these columns as mine</button>
  </form>
  {% endif %}
```

Add CSS: `.columns-menu .chip-panel { left:auto; right:0; min-width:300px; }` and inside the 700px block `.columns-menu { display:none; }` (phone cards have fixed content).

The home page's chip-closing script doesn't run here; add to the Search page script:

```js
  document.addEventListener("click", event => {
    if (!event.target.closest("details.columns-menu")) document.querySelectorAll("details.columns-menu[open]").forEach(d => d.open = false);
  });
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_search_page.py tests/test_group_settings.py -q`, then `uv run pytest -q`.
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add accounts/models.py accounts/migrations/0007_profile_search_columns.py listings/search_views.py listings/urls.py listings/templates/listings/search.html listings/templates/listings/base.html tests/test_search_page.py
git commit -m "feat: choose the Search table's columns, saved per person

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 12: CSV export

**Files:**
- Modify: `listings/search_columns.py` (`CSV_FIELDS`, `csv_cell`), `listings/search_views.py`, `listings/urls.py`, `search.html`
- Test: `tests/test_search_columns.py`, `tests/test_search_page.py`

**Interfaces:**
- Consumes: `searched(request)`, `collab.decorate`.
- Produces: URL `search_csv` (GET `/search/csv/?<same query>`): every matching listing (no page cap), one row each, fixed columns `CSV_FIELDS` plus "Link"; `search_columns.csv_cell(value)` neutralises spreadsheet formulas.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_search_columns.py`:

```python
from listings.search_columns import csv_cell


def test_csv_cells_never_start_a_formula():
    assert csv_cell("=HYPERLINK(\"x\")") == "'=HYPERLINK(\"x\")"
    assert csv_cell("+1") == "'+1" and csv_cell("-1") == "'-1" and csv_cell("@sum") == "'@sum"
    assert csv_cell("821 NW 11th") == "821 NW 11th" and csv_cell(3000) == 3000 and csv_cell(None) == ""
```

Append to `tests/test_search_page.py`:

```python
import csv
import io


def test_csv_exports_every_match_with_the_same_filters(client):
    for n in range(105):
        good(f"fits-{n:03}", price=3000 + n)
    good("one-bed", beds=1)
    response = client.get("/search/csv/?min_beds=2&sort=price")
    assert response["Content-Type"] == "text/csv; charset=utf-8"
    assert response["Content-Disposition"].startswith('attachment; filename="search-')
    rows = list(csv.reader(io.StringIO(response.content.decode())))
    assert rows[0][:3] == ["Address", "Unit", "City"] and rows[0][-1] == "Link"
    assert len(rows) == 106  # header + every match, not just a page
    assert rows[1][rows[0].index("Price")] == "3000"
    assert "/listing/" in rows[1][-1] and rows[1][-1].startswith("http")


def test_search_page_links_to_its_csv(client):
    good("fits")
    content = page(client, "?q=balcony")
    assert re.search(r'<a class="csv-link" href="/search/csv/\?[^"]*q=balcony', content)
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_search_columns.py tests/test_search_page.py -q -k csv`
Expected: FAIL.

- [ ] **Step 3: Add the CSV fields to `listings/search_columns.py`**

```python
def _known(value):
    return {True: "yes", False: "no"}.get(value, "")


# Every useful fact, whatever the table shows: a spreadsheet can hide columns, it can't add them.
CSV_FIELDS = [
    ("Address", lambda l: l.street), ("Unit", lambda l: l.unit), ("City", lambda l: l.city),
    ("Quadrant", lambda l: l.quadrant), ("Neighborhood", lambda l: l.neighborhood), ("ZIP", lambda l: l.zip_code),
    ("Price", lambda l: l.price), ("Effective rent", lambda l: l.effective_price), ("Beds", lambda l: l.beds),
    ("Baths", lambda l: l.baths), ("Sqft", lambda l: l.sqft), ("$/sqft", lambda l: l.price_per_sqft),
    ("Parking", lambda l: l.parking_spaces), ("W/D", lambda l: _known(l.has_washer_dryer)),
    ("AC", lambda l: _known(l.has_ac)), ("Outdoor", lambda l: _known(l.has_outdoor_space)),
    ("Furnished", lambda l: _known(l.is_furnished)), ("Type", lambda l: l.get_property_type_display()),
    ("Special", lambda l: l.special_offer), ("Price drop", lambda l: l.price_drop or ""),
    ("Days on market", lambda l: l.days_on_market), ("Listed", lambda l: l.listed_at or ""),
    ("First seen", lambda l: l.first_seen_at.date()), ("Last seen", lambda l: l.last_seen_at.date()),
    ("Active", lambda l: _known(l.is_active)), ("Status", lambda l: l.group_status_label),
    ("Up votes", lambda l: l.up_count), ("Down votes", lambda l: l.down_count),
    ("Sources", lambda l: ", ".join(sl.source.name for sl in l.source_listings.all() if sl.is_active)),
    ("Photo", lambda l: l.photo_url),
]


def csv_cell(value):
    """A cell a spreadsheet won't run as a formula."""
    if value is None:
        return ""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{value}"
    return value
```

- [ ] **Step 4: Add the view and URL**

`listings/search_views.py` (add `import csv`, `from django.conf import settings`, `from django.utils import timezone`):

```python
def _absolute(request, path):
    return f"{settings.PUBLIC_URL}{path}" if settings.PUBLIC_URL else request.build_absolute_uri(path)


def search_csv(request):
    _, queryset = searched(request)
    listings = collab.decorate(queryset.prefetch_related("source_listings__source", "price_changes"), request.group, request.user)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="search-{timezone.localtime():%Y%m%d-%H%M}.csv"'
    writer = csv.writer(response)
    writer.writerow([label for label, _ in search_columns.CSV_FIELDS] + ["Link"])
    for listing in listings:
        writer.writerow([search_columns.csv_cell(value(listing)) for _, value in search_columns.CSV_FIELDS]
                        + [_absolute(request, listing.get_absolute_url())])
    return response
```

`listings/urls.py`: `path("search/csv/", search_views.search_csv, name="search_csv"),`.

In `search.html`, inside `.results-controls` before the Columns menu:

```django
      <a class="csv-link" href="{% url 'search_csv' %}?{{ query }}" download>Download CSV</a>
```

and CSS `.csv-link { font-size:14px; }`.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_search_columns.py tests/test_search_page.py -q`, then `uv run pytest -q`.
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add listings/search_columns.py listings/search_views.py listings/urls.py listings/templates/listings/search.html listings/templates/listings/base.html tests/test_search_columns.py tests/test_search_page.py
git commit -m "feat: CSV export of a search

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 13: Inline status menu and votes in each row, and PR 4

**Files:**
- Create: `listings/templates/listings/_status_menu.html`
- Modify: `listings/views.py` (`set_status`), `_search_cell.html`, `_votes.html` (title), `base.html` (CSS), `CLAUDE.md`
- Test: `tests/test_search_page.py`

**Interfaces:**
- Consumes: `set_status` view (`POST /listing/<pk>/status/`), `vote` view (`POST /listing/<pk>/vote/`, returns `_votes.html`).
- Produces: `set_status` accepts `variant=menu` and returns `_status_menu.html` (a `<form id="status-menu-<pk>">` with `<select name="status">`).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_search_page.py`)

```python
from listings.models import FeedEvent, Vote


def test_rows_have_a_status_menu_and_vote_buttons(client):
    row = good("fits")
    content = page(client, "?q=")
    assert re.search(rf'<form id="status-menu-{row.pk}" class="status-menu"[^>]*hx-trigger="change"', content)
    assert f'<form class="votes" id="votes-{row.pk}"' in content


def test_changing_status_from_the_menu_saves_and_tells_the_group(client):
    row = good("fits")
    response = client.post(f"/listing/{row.pk}/status/", {"status": "toured", "variant": "menu"}, HTTP_HX_REQUEST="true")
    html = response.content.decode()
    assert f'<form id="status-menu-{row.pk}"' in html and '<option value="toured" selected>Toured</option>' in html
    assert FeedEvent.objects.filter(listing=row, kind=FeedEvent.Kind.STATUS).exists()


def test_voting_from_a_row(client):
    row = good("fits")
    client.post(f"/listing/{row.pk}/vote/", {"value": "up"}, HTTP_HX_REQUEST="true")
    assert Vote.objects.filter(listing=row).count() == 1
    assert re.search(r'class="vote mine" aria-pressed="true"[^>]*>👍 1', page(client, "?q="))
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_search_page.py -q -k "status or vot"`
Expected: FAIL.

- [ ] **Step 3: Write `listings/templates/listings/_status_menu.html`**

```django
{# The group's status as a compact menu for table rows. Saves on change; set_status swaps this form back in. #}
<form id="status-menu-{{ listing.pk }}" class="status-menu" method="post" action="{% url 'set_status' listing.pk %}"
      hx-post="{% url 'set_status' listing.pk %}" hx-trigger="change" hx-target="this" hx-swap="outerHTML">
  {% csrf_token %}
  <input type="hidden" name="variant" value="menu">
  <select name="status" aria-label="Status" class="status-{{ listing.group_status }}">
    {% for value, label in listing.STATUS_CHOICES %}<option value="{{ value }}"{% if listing.group_status == value %} selected{% endif %}>{{ label }}</option>{% endfor %}
  </select>
  <noscript><button type="submit">Save</button></noscript>
</form>
```

- [ ] **Step 4: Let `set_status` render it (`listings/views.py`)**

Replace the template line in `set_status`:

```python
        templates = {"pills": "listings/_status_pills.html", "menu": "listings/_status_menu.html"}
        template = templates.get(request.POST.get("variant"), "listings/_status.html")
```

- [ ] **Step 5: Use them in the table**

In `_search_cell.html`, replace the `status` and `votes` branches:

```django
{% elif column == "status" %}{% include "listings/_status_menu.html" %}
{% elif column == "votes" %}{% include "listings/_votes.html" %}
```

In `_votes.html`, add `{% if listing.vote_names %} title="{{ listing.vote_names }}"{% endif %}` to the `<form class="votes" …>` tag (after `hx-swap="outerHTML"`), so the table, which hides the names, still shows them on hover.

CSS in `base.html`:

```css
    .status-menu { margin:0; } .status-menu select { padding:3px 6px; border:1px solid var(--line); border-radius:999px; font:600 13px/1.2 inherit; background:var(--card); }
    .status-menu .status-interested { background:#c0265f; color:#fff; border-color:#c0265f; }
    .status-menu .status-toured, .status-menu .status-applied { background:#f5c542; border-color:#e0ad1f; }
    .status-menu .status-rejected { background:#667085; color:#fff; border-color:#667085; }
    .search-table .vote-who { display:none; } .search-table .votes { flex-wrap:nowrap; }
```

Note: after a status change the `<select>`'s class updates only because the whole form is swapped in; that's the point of `hx-target="this"`.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_search_page.py tests/test_group_status.py tests/test_votes.py -q`, then `uv run pytest -q`.
Expected: PASS.

- [ ] **Step 7: Check in a browser**

On the dev server at desktop width: choose columns (they persist after reload and on another browser logged in as the same person, not for a second account); open `/search/?q=&cols=address,price` and click "Keep these columns as mine"; download a CSV and open it; change a row's status (Feed shows it) and vote, then **restore** both. At 375px: no sideways scroll, the Columns menu is hidden.

- [ ] **Step 8: Update `CLAUDE.md`**

- Search page bullet: append "Columns: `Profile.search_columns` (empty = defaults); `?cols=a,b` in a link wins and is kept while filtering. CSV (`/search/csv/`) exports every match with fixed `CSV_FIELDS`; `csv_cell` stops formulas. Rows have the status menu (`set_status` variant `menu`) and vote buttons."
- Current state: "PR 4/5 columns, CSV, inline status and votes."

- [ ] **Step 9: Commit, push and open PR 4**

```bash
git add listings/templates/listings/_status_menu.html listings/views.py listings/templates/listings/_search_cell.html listings/templates/listings/_votes.html listings/templates/listings/base.html tests/test_search_page.py CLAUDE.md
git commit -m "feat: status menu and votes in Search rows

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push -u origin search-4-columns
gh pr create --base search-3-page --title "[Advanced search 4/5] Columns, CSV, inline status and votes" --body-file <scratchpad>/pr4.md
```

---

# PR 5 — `[Advanced search 5/5] Saved searches and the home page chip`

Branch: `git checkout -b search-5-saved` (from `search-4-columns`). Open the PR with `--base search-4-columns`.

### Task 14: Group saved searches

**Files:**
- Modify: `listings/models.py` (`SavedSearch`); create `listings/migrations/0024_savedsearch.py`
- Modify: `listings/search_views.py`, `listings/urls.py`, `search.html`, `base.html` (CSS), `listings/admin.py`
- Create: `listings/templates/listings/_saved_searches.html`
- Test: `tests/test_saved_searches.py` (new)

**Interfaces:**
- Consumes: `query_string`, `column_keys`, `STATE_PARAMS`.
- Produces: `SavedSearch(group, name, query, created_by, created_by_name, created_at, updated_at)` with `.by` and `.get_absolute_url()` (`/search/?<query>&saved=<pk>`); URLs `saved_search_create` (`POST /search/saved/`), `saved_search_update` (`POST /search/saved/<pk>/update/`), `saved_search_rename` (`POST …/rename/`), `saved_search_delete` (`POST …/delete/`). POST fields: `name`, `query`, `columns` (comma-separated current keys), `with_columns` (checkbox). `search_views.clean_saved_query(raw, columns, with_columns) -> str`. Context `saved_searches`, `current_saved`, `current_columns`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_saved_searches.py`:

```python
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
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_saved_searches.py -q`
Expected: FAIL.

- [ ] **Step 3: Add the model** (end of `listings/models.py`)

```python
class SavedSearch(models.Model):
    """A named Search page query that everyone in a group sees. Stored as the page's URL query."""

    group = models.ForeignKey("accounts.SearchGroup", on_delete=models.CASCADE, related_name="saved_searches")
    name = models.CharField(max_length=100)
    query = models.TextField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_by_name = models.CharField(max_length=60, blank=True)  # shown if the account is gone
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "pk"]

    def __str__(self):
        return self.name

    @property
    def by(self):
        return display_name(self.created_by) if self.created_by_id else (self.created_by_name or "Someone")

    def get_absolute_url(self):
        return f"{reverse('search')}?{self.query}{'&' if self.query else ''}saved={self.pk}"
```

Run `uv run python manage.py makemigrations listings -n savedsearch`. Register it in `listings/admin.py` with `admin.site.register(SavedSearch)` (follow that file's style; add a `list_display = ("name", "group", "created_by_name", "updated_at")` if other models there use a ModelAdmin).

- [ ] **Step 4: Add the views to `listings/search_views.py`**

Add imports `from django.contrib import messages`, `from django.shortcuts import get_object_or_404`, `from accounts.models import display_name`, and `SavedSearch` to the `.models` import.

```python
SAVED_QUERY_LIMIT = 4000


def clean_saved_query(raw, columns, with_columns):
    """The query to store: the search without paging or saved-search state, with the person's columns only
    when they asked to save them. None when it's too long to be a real search."""
    query = QueryDict(raw or "", mutable=True)
    for key in ("page", "saved", "cols"):
        query.pop(key, None)
    if with_columns:
        keys = search_columns.keys_from((columns or "").split(","))
        query["cols"] = ",".join(keys)
    text = query.urlencode()
    return None if len(text) > SAVED_QUERY_LIMIT else text


def _own_saved(request, pk):
    return get_object_or_404(SavedSearch, pk=pk, group=request.group)


def _saved_query_or_error(request):
    query = clean_saved_query(request.POST.get("query"), request.POST.get("columns"), request.POST.get("with_columns"))
    if query is None:
        messages.error(request, "That search is too long to save.")
    return query


@require_POST
def saved_search_create(request):
    name = request.POST.get("name", "").strip()[:100]
    query = _saved_query_or_error(request)
    if not name:
        messages.error(request, "Give the search a name to save it.")
    if not name or query is None:
        return redirect(f"{reverse('search')}?{request.POST.get('query', '')}")
    saved = SavedSearch.objects.create(group=request.group, name=name, query=query, created_by=request.user,
                                       created_by_name=display_name(request.user))
    messages.success(request, f"Saved “{saved.name}” for {request.group.name}.")
    return redirect(saved.get_absolute_url())


@require_POST
def saved_search_update(request, pk):
    saved = _own_saved(request, pk)
    query = _saved_query_or_error(request)
    if query is not None:
        saved.query = query
        saved.save(update_fields=["query", "updated_at"])
        messages.success(request, f"Updated “{saved.name}”.")
    return redirect(saved.get_absolute_url())


@require_POST
def saved_search_rename(request, pk):
    saved = _own_saved(request, pk)
    name = request.POST.get("name", "").strip()[:100]
    if name:
        saved.name = name
        saved.save(update_fields=["name", "updated_at"])
    return redirect(saved.get_absolute_url())


@require_POST
def saved_search_delete(request, pk):
    saved = _own_saved(request, pk)
    saved.delete()
    messages.success(request, f"Deleted “{saved.name}”.")
    return redirect(f"{reverse('search')}?{saved.query}")
```

In `search_page`, add to the context:

```python
        "saved_searches": SavedSearch.objects.filter(group=request.group).select_related("created_by__profile"),
        "current_saved": _current_saved(request),
        "current_columns": ",".join(keys),
        "save_query": query_string(form.data, page=None, saved=None, cols=None),
```

with

```python
def _current_saved(request):
    pk = request.GET.get("saved", "")
    return SavedSearch.objects.filter(pk=pk, group=request.group).first() if pk.isdigit() else None
```

`listings/urls.py`:

```python
    path("search/saved/", search_views.saved_search_create, name="saved_search_create"),
    path("search/saved/<int:pk>/update/", search_views.saved_search_update, name="saved_search_update"),
    path("search/saved/<int:pk>/rename/", search_views.saved_search_rename, name="saved_search_rename"),
    path("search/saved/<int:pk>/delete/", search_views.saved_search_delete, name="saved_search_delete"),
```

- [ ] **Step 5: Write `listings/templates/listings/_saved_searches.html`** (inside `#results`, so its hidden query is current after every live update)

```django
{# The group's saved searches, and saving the search on screen. Inside #results so the query stays current. #}
<div class="saved-searches panel">
  {% if current_saved %}
  <div class="saved-current">
    <strong>Viewing “{{ current_saved.name }}”</strong> <span class="muted">by {{ current_saved.by }}</span>
    <form method="post" action="{% url 'saved_search_update' current_saved.pk %}">
      {% csrf_token %}<input type="hidden" name="query" value="{{ save_query }}"><input type="hidden" name="columns" value="{{ current_columns }}">
      <label class="inline"><input type="checkbox" name="with_columns"{% if "cols=" in current_saved.query %} checked{% endif %}> with my columns</label>
      <button type="submit" class="link">Update it to this search</button>
    </form>
    <details><summary class="link">Rename</summary>
      <form class="inline-form" method="post" action="{% url 'saved_search_rename' current_saved.pk %}">{% csrf_token %}
        <input type="text" name="name" value="{{ current_saved.name }}" maxlength="100" required><button type="submit">Rename</button></form>
    </details>
    <details><summary class="link danger">Delete…</summary>
      <form method="post" action="{% url 'saved_search_delete' current_saved.pk %}">{% csrf_token %}
        <button type="submit" class="link danger">Delete “{{ current_saved.name }}” for everyone</button></form>
    </details>
  </div>
  {% endif %}
  <details class="saved-list"{% if not current_saved and saved_searches %} open{% endif %}>
    <summary>Saved searches ({{ saved_searches|length }})</summary>
    <ul>
      {% for saved in saved_searches %}<li><a href="{{ saved.get_absolute_url }}">{{ saved.name }}</a> <span class="muted">by {{ saved.by }}</span></li>
      {% empty %}<li class="muted">None yet. Save this one for {{ request.group.name }}.</li>{% endfor %}
    </ul>
    <form class="inline-form" method="post" action="{% url 'saved_search_create' %}">
      {% csrf_token %}<input type="hidden" name="query" value="{{ save_query }}"><input type="hidden" name="columns" value="{{ current_columns }}">
      <input type="text" name="name" placeholder="Name this search" maxlength="100" required>
      <label class="inline"><input type="checkbox" name="with_columns"> with my columns</label>
      <button type="submit">Save</button>
    </form>
  </details>
</div>
```

In `search.html`: add `{% include "listings/_saved_searches.html" %}` as the first child of `#results` (above `ignored`), and inside the search form add:

```django
  {% if current_saved %}<input type="hidden" name="saved" value="{{ current_saved.pk }}">{% endif %}
```

CSS: `.saved-searches { display:flex; flex-direction:column; gap:8px; font-size:14px; } .saved-searches ul { margin:6px 0; padding-left:18px; } .saved-current { display:flex; flex-wrap:wrap; align-items:center; gap:6px 14px; } .saved-current form, .saved-current details { margin:0; }`

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_saved_searches.py tests/test_search_page.py -q`, then `uv run pytest -q`.
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add listings/models.py listings/migrations/0024_savedsearch.py listings/admin.py listings/search_views.py listings/urls.py listings/templates/listings/_saved_searches.html listings/templates/listings/search.html listings/templates/listings/base.html tests/test_saved_searches.py
git commit -m "feat: named saved searches shared within the group

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 15: The home page's "n more filters from Search" chip

**Files:**
- Modify: `listings/forms.py` (`search_only_values`), `listings/views.py` (`listing_list`, `NON_FILTER_PARAMS`), `_filter_bar.html`, `list.html` (script), `base.html` (CSS)
- Test: `tests/test_home_search_chip.py` (new)

**Interfaces:**
- Consumes: `SEARCH_ONLY_FIELDS`, `raw_values`, `search_views.query_string`.
- Produces: `ListingFilterForm.search_only_values() -> list[(name, value)]`; home context `search_only`, `search_only_count`, `search_url`.

- [ ] **Step 1: Write the failing tests**

```python
import re
from decimal import Decimal

import pytest

from tests.helpers import home_group, make_listing

pytestmark = pytest.mark.django_db


def good(key, **extra):
    fields = dict(address_key=key, price=3000, beds=2, baths=Decimal("2"), parking_spaces=2, property_type="condo")
    fields.update(extra)
    return make_listing(**fields)


def test_a_search_link_filters_the_home_page_and_shows_a_chip(client):
    good("balcony", description="balcony", zip_code="97209")
    good("plain", zip_code="97209")
    response = client.get("/?q=balcony&zips=97209&zips=97210&min_beds=2")
    assert {listing.address_key for listing in response.context["listings"]} == {"balcony"}
    content = response.content.decode()
    assert '<input type="hidden" name="q" value="balcony" data-search-only>' in content
    assert content.count('name="zips"') == 2
    assert re.search(r'<a href="/search/\?[^"]*q=balcony[^"]*">2 more filters from Search</a>', content)


def test_no_chip_without_search_only_filters(client):
    good("a")
    assert "from Search</a>" not in client.get("/?min_beds=2").content.decode()


def test_search_only_filters_survive_home_changes_and_saved_defaults(client):
    good("a", description="balcony")
    client.post("/filters/defaults/", {"q": "balcony", "min_beds": "2", "max_price": "8000", "min_price": "0"})
    assert home_group().default_filters["q"] == "balcony"
    content = client.get("/").content.decode()  # no URL filters: starts from the saved defaults
    assert '<input type="hidden" name="q" value="balcony" data-search-only>' in content
    assert "1 more filter from Search" in content


def test_cols_and_saved_in_a_link_dont_count_as_filters_on_home(client):
    good("fits")
    good("one-bed", beds=1)
    keys = {listing.address_key for listing in client.get("/?cols=address&saved=3").context["listings"]}
    assert keys == {"fits"}  # still the defaults
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_home_search_chip.py -q`
Expected: FAIL.

- [ ] **Step 3: Add `search_only_values` to `ListingFilterForm`**

```python
    def search_only_values(self):
        """(name, value) for each Search-only filter in this form's data, for the home page's hidden inputs."""
        return [(name, value) for name in SEARCH_ONLY_FIELDS for value in self.raw_values(name) if value not in ("", "any")]
```

- [ ] **Step 4: Pass them to the home page (`listings/views.py`)**

Change `NON_FILTER_PARAMS = {"view", "page", "cols", "saved"}`. In `listing_list`, before `render`:

```python
    search_only = form.search_only_values()
```

and add to the context:

```python
        "search_only": search_only,
        "search_only_count": len({name for name, _ in search_only}),
        "search_url": f"{reverse('search')}?{query_string(form.data, view=None, page=None)}",
```

with imports `from django.urls import reverse` and `from .search_views import query_string`.

- [ ] **Step 5: Render the hidden inputs and chip (`_filter_bar.html`)**

After the four area inputs:

```django
  {% for name, value in search_only %}<input type="hidden" name="{{ name }}" value="{{ value }}" data-search-only>
  {% endfor %}
```

After the `area-chip` button:

```django
  {% if search_only %}
  <span class="search-chip" data-search-chip>
    <a href="{{ search_url }}">{{ search_only_count }} more filter{{ search_only_count|pluralize }} from Search</a>
    <button type="button" data-clear-search-only aria-label="Remove the filters from Search">✕</button>
  </span>
  {% endif %}
```

In `list.html`'s script, after the `data-clear-area` listener:

```js
  // Filters set on the Search page ride along as hidden inputs. The chip opens them on Search as they are now,
  // or drops them.
  filters.querySelector("[data-search-chip] a")?.addEventListener("click", event => {
    const query = new URLSearchParams(new FormData(filters));
    query.delete("view");
    event.currentTarget.href = `/search/?${query}`;
  });
  filters.querySelector("[data-clear-search-only]")?.addEventListener("click", () => {
    filters.querySelectorAll("[data-search-only]").forEach(input => input.remove());
    filters.querySelector("[data-search-chip]").remove();
    htmx.trigger(filters, "change");
  });
```

CSS: `.search-chip { display:inline-flex; align-items:center; gap:2px; padding:4px 6px 4px 12px; border:1px solid var(--accent); border-radius:999px; background:#eef6f2; font:600 14px/1.2 inherit; white-space:nowrap; } .search-chip a { text-decoration:none; } .search-chip button { border:0; background:none; color:var(--accent); cursor:pointer; font:inherit; padding:0 4px; }`

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_home_search_chip.py tests/test_filter_bar.py tests/test_default_filters.py tests/test_views.py -q`, then `uv run pytest -q`.
Expected: PASS.

- [ ] **Step 7: Check in a browser**

On the dev server: from Search, set a keyword and a ZIP, then open the home page with the same query (edit the URL path to `/`). The chip shows "2 more filters from Search"; changing beds keeps the keyword applied; the chip link opens Search with the current home filters plus the Search ones; ✕ removes them. Save and open a saved search in two browsers (two accounts in the same group), rename and delete it, and check a third account in another group can't see it. Phone width: no sideways scroll on Search or home. Delete the saved searches you made.

- [ ] **Step 8: Commit**

```bash
git add listings/forms.py listings/views.py listings/templates/listings/_filter_bar.html listings/templates/listings/list.html listings/templates/listings/base.html tests/test_home_search_chip.py
git commit -m "feat: home page keeps Search-only filters and shows them as a chip

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 16: Docs, architecture diagrams, and PR 5

**Files:**
- Modify: `CLAUDE.md`, `docs/architecture.html`

- [ ] **Step 1: Update `CLAUDE.md`**

- Current state: replace the stack's "Open" note with "**Open:** Advanced search stack PRs 1–5 (`docs/superpowers/plans/2026-10-10-advanced-search.md`); after merging, deploy (migrations 0022–0024 and accounts 0007; 0023 builds the keyword index for every listing)." Update the test count from `uv run pytest -q`.
- Code map, Search page bullet: append "Saved searches: `SavedSearch` per group, stored as the page's URL query (`clean_saved_query` drops `page`/`saved`, and `cols` unless 'with my columns'); any member renames, updates or deletes; other groups get 404. The home page keeps Search-only filters (`SEARCH_ONLY_FIELDS`) as hidden inputs from `form.data` (so saved defaults keep them too) and shows 'n more filters from Search'."
- Header nav mention: "Listings · Search · Trends · Feed · Group".

- [ ] **Step 2: Update `docs/architecture.html`**

Read it first. Add the Search page to the pages diagram (`/search/` → `search_views` → `apply_filters` + `search_index` → `listing_search` FTS5 table, kept in sync by triggers on `listings_listing`), add `SavedSearch` (group FK) and `Profile.search_columns` to the models diagram, and `Listing.effective_price`. Keep the existing style.

- [ ] **Step 3: Republish the diagrams**

Read the artifact (`Artifact` action `read`, url `https://claude.ai/artifact/MASfMv25dYKcHeYTx6eUgq`), then publish `docs/architecture.html` to that `url`.

- [ ] **Step 4: Run everything**

Run: `uv run pytest -q`
Expected: all pass. Run `uv run python manage.py makemigrations --check --dry-run`: "No changes detected".

- [ ] **Step 5: Commit, push and open PR 5**

```bash
git add CLAUDE.md docs/architecture.html
git commit -m "docs: Search page, saved searches and keyword index in the handoff notes and diagrams

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push -u origin search-5-saved
gh pr create --base search-4-columns --title "[Advanced search 5/5] Saved searches and the home page chip" --body-file <scratchpad>/pr5.md
```

PR body: the template with this PR's summary and **#this** on line 5, plus a "Deploy" note: `git pull && ./deploy/install.sh` on the Mac mini runs four migrations; 0023 indexes every listing (seconds for ~2,600 rows).
