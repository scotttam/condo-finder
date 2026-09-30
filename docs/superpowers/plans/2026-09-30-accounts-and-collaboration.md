# Accounts and Collaboration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add email logins and search groups, so several households each get their own shared status, comments, votes, default filters, Trends and Feed, and so partners can work on a search together. The site goes public over Tailscale Funnel (HTTPS).

**Architecture:** A new `accounts` app holds `SearchGroup`, `Profile` (one per user, exactly one group) and `Invite`. Everything a group says about a listing moves out of `Listing` into group-scoped rows in `listings`: `ListingState` (status), `Comment`, `Vote`. Scraped data (listings, price history, sources) stays global. `listings/collab.py` is the one place that reads and writes group state. `collab.decorate()` attaches a group's view of listings (`group_status`, votes) to `Listing` instances for templates. Django's `LoginRequiredMiddleware` guards every page. A small middleware sets `request.profile` and `request.group`.

**Tech Stack:** Django 6.1 (built-in auth, `LoginRequiredMiddleware`), SQLite, HTMX 2 (polling with `hx-trigger="every 30s"`), pytest + pytest-django, gunicorn under launchd, Tailscale Funnel.

**Spec:** `docs/superpowers/specs/2026-09-30-accounts-decisions.md` (moved there from `docs/plan-decisions.md` in Task 1).

## Global Constraints

- Django's built-in `User`. `username` is the lowercased email; people log in with their email. No custom user model.
- A display name is required at signup. It is shown on comments, votes and Feed activity.
- No outgoing email. Invites are copy-paste links. The site admin resets passwords with `manage.py changepassword <email>`.
- Each user is in exactly one group. There is no group switcher.
- Invite links are single-use and expire after 7 days (`INVITE_DAYS = 7`).
- Every page requires login except `/login/`, `/invite/<token>/` and the admin login page.
- Staff only: price-history add/edit/delete, Refresh from sites, the Sources page and Scrape now, and admin overrides. Other users see this data read-only.
- Scraped listings, price history and sources stay global. Group state never leaks between groups.
- Polling interval: 30 seconds (`every 30s`) for the comment thread and the Feed badge.
- Trends per group: about $0.50 per group per day on the owner's API key. Market charts (`trend_stats`) stay shared.
- Brute-force lockout (django-axes) and 2FA are out of scope. Add no new dependencies.
- Production is live. Add new migrations only; never edit or squash applied ones. Data moves go in data migrations.
- Tests assert on element markup, not bare class names (class names also appear in the inline CSS in `base.html`).
- Commit prefixes: `feat:` / `fix:` / `docs:`. PR titles: `[Accounts n/10] …`. The owner merges bottom-up with **Create a merge commit**.
- Every PR updates `CLAUDE.md` ("Current state", plus the code map when code moves).
- Don't enable Funnel until login protection is live (Task 17's runbook).
- Commands for the owner to paste: zsh, no inline `# comments`, one code block per command that runs at a different time.

## Review Focus

1. **An HTMX request after the session expires** (the Feed badge poll, the comment-thread poll, a status click). Expected: the whole page goes to the login page; the login form is never swapped into a badge or panel. Pinned in Task 1 (`test_htmx_request_without_a_login_redirects_the_whole_page`).
2. **Reaching another group's data by ID.** Examples: editing or deleting another person's comment, `?report=<id>` for another group's Trends report, revoking another group's invite, removing someone from another group. Expected: 404 and nothing changes. Pinned in Task 9 (`test_only_the_author_can_edit_or_delete`), Task 14 (`test_another_groups_report_is_not_shown`), Task 15 (`test_cannot_remove_someone_from_another_group`) and Task 16 (`test_cannot_revoke_another_groups_invite`).
3. **A used, expired or double-submitted invite link.** Expected: a clear "this link has expired or was already used" page (410). An invite never creates two accounts or adds two people. Pinned in Task 16 (`test_invite_is_single_use`, `test_signup_rolls_back_if_the_link_was_used_meanwhile`, `test_expired_invite_is_refused`).
4. **Merging duplicate listings when several groups have state on both copies.** This includes the same person voting on both copies. Expected: every group's status, comments and votes survive, the furthest status wins, one vote per person, and no unique-constraint crash. Pinned in Task 5 (`test_merge_keeps_every_groups_status`), Task 9 (`test_merge_moves_comments`) and Task 10 (`test_merge_keeps_one_vote_per_person`).
5. **Deleting or editing a comment after it reached the Feed.** Expected: deleting removes the Feed item; editing updates its text. Pinned in Task 9 (`test_feed_follows_comment_edits_and_deletes`).

---

## The PR stack

Each PR branches off the previous one; PR 1 branches off `main`. Titles are `[Accounts n/10] <title>`. Each PR body lists the whole stack and says "merge bottom-up with Create a merge commit".

| PR | Branch | Tasks | What it ships |
|----|--------|-------|---------------|
| 1 | `accounts-1-login` | 1, 2 | `accounts` app, groups, email login, `create_owner` |
| 2 | `accounts-2-staff-only` | 3 | Staff-only controls |
| 3 | `accounts-3-group-status` | 4, 5 | Per-group status (`ListingState`) |
| 4 | `accounts-4-group-feed` | 6, 7 | Group Feed, per-user unread state, badge polling |
| 5 | `accounts-5-comments` | 8, 9 | Notes become a comment thread |
| 6 | `accounts-6-votes` | 10, 11 | 👍/👎 votes and vote filters |
| 7 | `accounts-7-default-filters` | 12 | "Save as our defaults" |
| 8 | `accounts-8-group-trends` | 13, 14 | Per-group Trends |
| 9 | `accounts-9-invites` | 15, 16 | Invites, signup, group settings page |
| 10 | `accounts-10-public-https` | 17, 18 | HTTPS hardening, Funnel runbook, docs |

**Deploy once, after the whole stack merges.** PR 1 turns on login. Until PR 9 there is no way to invite the second owner, so a partial deploy would lock her out. Task 17's README runbook gives the order: pull, install, `create_owner`, invite, Funnel.

## File structure

**New `accounts` app**
- `accounts/models.py`: `SearchGroup`, `Profile`, `Invite`, `display_name(user)`.
- `accounts/groups.py`: `owners_group()`, `new_group()`, `profile_for()`, `move_to_group()`.
- `accounts/middleware.py`: `LoginRequired` (HTMX-aware), `CurrentGroup` (`request.profile`, `request.group`).
- `accounts/forms.py`: `EmailAuthenticationForm`, `SignupForm`.
- `accounts/decorators.py`: `staff_required`.
- `accounts/invites.py`: `create_invite()`, `invite_url()`, `claim()`.
- `accounts/views.py`: invite/signup, group settings, password change.
- `accounts/urls.py`, `accounts/admin.py`, `accounts/apps.py`.
- `accounts/management/commands/create_owner.py`.
- `accounts/templates/accounts/`: `login.html`, `signup.html`, `invite_gone.html`, `invite_existing.html`, `group.html`, `password_change.html`.

**New in `listings`**
- `listings/collab.py`: group state. `status_expr`, `decorate`, `set_status`, comments, votes.
- `listings/collab_views.py`: comment and vote endpoints.
- Templates: `_comments.html`, `_comment_form.html`, `_votes.html`, `_feed_badge.html`, `_save_defaults.html`.

**Modified:** `listings/models.py`, `filters.py`, `forms.py`, `feed.py`, `views.py`, `urls.py`, `analyst.py`, `merge.py`, `admin.py`, `context_processors.py`, templates, `condofinder/settings.py`, `condofinder/urls.py`, `deploy/gunicorn.conf.py`, `deploy/install.sh`, `README.md`, `INTENT.md`, `CLAUDE.md`, `docs/architecture.html`, `.env.example`, `tests/conftest.py`, `tests/helpers.py`.

## Shared test helpers (defined in Task 1, extended later)

Task 1 adds these to `tests/helpers.py` and `tests/conftest.py`, and later tasks use them. Every existing view test uses the `client` fixture, which becomes a logged-in staff user named Sam in the owners' group ("home group").

- `home_group()`: the owners' group (oldest `SearchGroup`, created by the migration; re-created if a transactional test flushed it).
- `make_user(email, name, group=None, staff=False)`: a user with password `pw` and a profile.
- Fixtures: `owner` (Sam, staff, home group), `client` (logged in as `owner`), `anon_client`, `member` (Alex, not staff, home group; Task 3), `member_client` (Task 3).
- Task 3 adds `status_of(listing, group=None)`. Task 3 teaches `make_listing(status=...)` to write a `ListingState`. Task 8 teaches `make_listing(notes=...)` to write a `Comment`. So old tests keep working.

---

# PR 1 — `[Accounts 1/10] Groups and email login`

Branch: `git checkout main && git pull && git checkout -b accounts-1-login`

### Task 1: `accounts` app, groups, email login

**Files:**
- Create: `accounts/__init__.py`, `accounts/apps.py`, `accounts/models.py`, `accounts/groups.py`, `accounts/middleware.py`, `accounts/forms.py`, `accounts/urls.py`, `accounts/admin.py`, `accounts/migrations/__init__.py`, `accounts/migrations/0001_initial.py` (generated), `accounts/migrations/0002_owners_group.py`, `accounts/templates/accounts/login.html`
- Modify: `condofinder/settings.py`, `condofinder/urls.py`, `listings/context_processors.py`, `listings/templates/listings/base.html`, `tests/conftest.py`, `tests/helpers.py`, `tests/test_views.py`
- Move: `docs/plan-decisions.md` → `docs/superpowers/specs/2026-09-30-accounts-decisions.md`
- Test: `tests/test_login.py`

**Interfaces:**
- Produces:
  - `accounts.models.SearchGroup(name, created_at)`, with `Profile` rows reached as `group.members`.
  - `accounts.models.Profile(user OneToOne related_name="profile", group FK related_name="members", display_name, joined_at)`.
  - `accounts.models.display_name(user) -> str`.
  - `accounts.groups.owners_group() -> SearchGroup`, `new_group(name) -> SearchGroup`, `profile_for(user) -> Profile`, `move_to_group(user, group) -> Profile`.
  - `request.profile` / `request.group` (None when logged out).
  - URL names `login`, `logout`.
  - `tests.helpers.home_group()`, `tests.helpers.make_user(...)`, and fixtures `owner`, `client`, `anon_client`.

- [ ] **Step 1: Move the decisions file into specs**

```bash
mkdir -p docs/superpowers/specs
mv docs/plan-decisions.md docs/superpowers/specs/2026-09-30-accounts-decisions.md
```

(`git mv` fails on untracked files; use `mv`.)

- [ ] **Step 2: Add the test helpers and fixtures**

Append to `tests/helpers.py`:

```python
def home_group():
    """The owners' group: the oldest group, made by accounts' migration (re-made if a test flushed it)."""
    from accounts.groups import owners_group

    return owners_group()


def make_user(email, name, group=None, staff=False):
    from django.contrib.auth import get_user_model

    from accounts.models import Profile

    user = get_user_model().objects.create_user(username=email, email=email, password="pw", is_staff=staff)
    Profile.objects.create(user=user, group=group or home_group(), display_name=name)
    return user
```

Replace `tests/conftest.py` with:

```python
import pytest


@pytest.fixture(autouse=True)
def condo_settings(settings):
    settings.REQUEST_DELAY_SECONDS = 0
    settings.TARGET_CITIES = ["Portland", "Lake Oswego", "Beaverton"]


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
```

- [ ] **Step 3: Write the failing tests**

Create `tests/test_login.py`:

```python
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
```

- [ ] **Step 4: Run them to verify they fail**

Run: `uv run pytest tests/test_login.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'accounts'`.

- [ ] **Step 5: Create the app**

`accounts/__init__.py` and `accounts/migrations/__init__.py`: empty files.

`accounts/apps.py`:

```python
from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"
```

`accounts/models.py`:

```python
from django.conf import settings
from django.db import models
from django.utils import timezone


class SearchGroup(models.Model):
    """A household searching together. It owns the shared status, comments, votes, default filters,
    priorities, Trends reports and Feed activity. Every user belongs to exactly one."""

    name = models.CharField(max_length=100)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["pk"]

    def __str__(self):
        return self.name


class Profile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    group = models.ForeignKey(SearchGroup, on_delete=models.PROTECT, related_name="members")
    display_name = models.CharField(max_length=60)
    joined_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["joined_at", "pk"]

    def __str__(self):
        return self.display_name


def display_name(user):
    """How a person is shown on comments, votes and the Feed."""
    if user is None:
        return ""
    profile = getattr(user, "profile", None)  # RelatedObjectDoesNotExist is an AttributeError
    return profile.display_name if profile else user.get_username()
```

`accounts/groups.py`:

```python
"""Search groups: which one a person is in, and moving people between them."""

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Profile, SearchGroup


def owners_group():
    """The original group, the site owners', made by accounts' second migration."""
    return SearchGroup.objects.order_by("pk").first() or SearchGroup.objects.create(name="Our search")


def new_group(name):
    return SearchGroup.objects.create(name=name[:100])


def profile_for(user):
    """The person's profile. An account made outside the app (createsuperuser, admin) gets a solo group."""
    try:
        return Profile.objects.select_related("group").get(user=user)
    except Profile.DoesNotExist:
        pass
    name = user.first_name or (user.email or user.get_username()).split("@")[0]
    try:
        with transaction.atomic():
            return Profile.objects.create(user=user, group=new_group(f"{name}'s search"), display_name=name[:60])
    except IntegrityError:  # a parallel request made it first
        return Profile.objects.select_related("group").get(user=user)


def move_to_group(user, group):
    """Puts the person in `group` (a no-op if they're already in it)."""
    profile = profile_for(user)
    if profile.group_id == group.pk:
        return profile
    profile.group = group
    profile.joined_at = timezone.now()
    profile.save(update_fields=["group", "joined_at"])
    return profile
```

`accounts/middleware.py`:

```python
from urllib.parse import urlencode, urlsplit

from django.conf import settings
from django.contrib.auth.middleware import LoginRequiredMiddleware
from django.http import HttpResponse
from django.shortcuts import resolve_url

from .groups import profile_for


class LoginRequired(LoginRequiredMiddleware):
    """Every page needs a login except views marked @login_not_required. An HTMX request (a poll or a
    swap) is told to load the login page, instead of having the login form swapped into part of a page."""

    def handle_no_permission(self, request, view_func):
        if not request.headers.get("HX-Request"):
            return super().handle_no_permission(request, view_func)
        current = urlsplit(request.headers.get("HX-Current-URL", "")).path or "/"
        response = HttpResponse("")
        response["HX-Redirect"] = f"{resolve_url(settings.LOGIN_URL)}?{urlencode({'next': current})}"
        return response


class CurrentGroup:
    """Sets request.profile and request.group for the logged-in person (None when logged out)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        profile = profile_for(request.user) if request.user.is_authenticated else None
        request.profile = profile
        request.group = profile.group if profile else None
        return self.get_response(request)
```

`accounts/forms.py`:

```python
from django import forms
from django.contrib.auth.forms import AuthenticationForm


class EmailAuthenticationForm(AuthenticationForm):
    """Log in with an email address. Usernames are the lowercased email."""

    username = forms.EmailField(label="Email", widget=forms.EmailInput(attrs={"autofocus": True, "autocomplete": "email"}))
    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": "That email and password do not match an account.",
    }

    def clean_username(self):
        return self.cleaned_data["username"].strip().lower()
```

`accounts/urls.py`:

```python
from django.contrib.auth import views as auth_views
from django.urls import path

from .forms import EmailAuthenticationForm

urlpatterns = [
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="accounts/login.html",
            authentication_form=EmailAuthenticationForm,
            redirect_authenticated_user=True,
        ),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
]
```

`accounts/admin.py`:

```python
from django.contrib import admin

from .models import Profile, SearchGroup


class ProfileInline(admin.TabularInline):
    model = Profile
    extra = 0
    fields = ("user", "display_name", "joined_at")
    readonly_fields = ("user", "joined_at")


@admin.register(SearchGroup)
class SearchGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "created_at")
    inlines = [ProfileInline]


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("display_name", "user", "group", "joined_at")
    list_filter = ("group",)
```

`accounts/templates/accounts/login.html`:

```html
{% extends "listings/base.html" %}
{% block title %}Log in · Condo Finder{% endblock %}
{% block content %}
<div class="panel auth-card">
  <h1>Log in</h1>
  <form method="post" action="{% url 'login' %}">
    {% csrf_token %}
    {% if form.non_field_errors %}<p class="form-error">{{ form.non_field_errors|join:" " }}</p>{% endif %}
    <label class="stack">Email
      <input type="email" name="username" value="{{ form.username.value|default_if_none:'' }}" autocomplete="email" required autofocus></label>
    <label class="stack">Password
      <input type="password" name="password" autocomplete="current-password" required></label>
    <input type="hidden" name="next" value="{{ next }}">
    <button type="submit">Log in</button>
  </form>
  <p class="muted small">Forgot your password? Ask the site admin to reset it.</p>
</div>
{% endblock %}
```

- [ ] **Step 6: Wire settings and URLs**

In `condofinder/settings.py`:
- Add `"accounts",` to `INSTALLED_APPS`, just before `"listings",`.
- In `MIDDLEWARE`, directly after `"django.contrib.auth.middleware.AuthenticationMiddleware",`, add:

```python
    "accounts.middleware.LoginRequired",
    "accounts.middleware.CurrentGroup",
```

- After `DEFAULT_AUTO_FIELD`, add:

```python
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "login"
```

In `condofinder/urls.py`, add `path("", include("accounts.urls")),` before the `listings.urls` line.

In `listings/context_processors.py`, return early for anonymous visitors:

```python
def listings_nav(request):
    """Link back to the listings page as the viewer last left it (view, filters, sort, page)."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"listings_url": "/", "feed_unread": 0}
    session = getattr(request, "session", None)
    query = session.get("listing_query", "") if session is not None else ""
    from . import feed

    on_feed = getattr(getattr(request, "resolver_match", None), "url_name", None) == "feed"
    return {"listings_url": f"/{query}", "feed_unread": 0 if on_feed else feed.unread_count(request)}
```

- [ ] **Step 7: Make migrations**

Run: `uv run python manage.py makemigrations accounts`
Expected: `accounts/migrations/0001_initial.py` with `SearchGroup` and `Profile`.

Create `accounts/migrations/0002_owners_group.py`:

```python
from django.db import migrations


def create_owners_group(apps, schema_editor):
    """The owners' group comes first, so it is always the oldest group. Existing statuses, notes,
    priorities and Trends reports move into it in later migrations."""
    SearchGroup = apps.get_model("accounts", "SearchGroup")
    if not SearchGroup.objects.exists():
        SearchGroup.objects.create(name="Our search")


class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial")]
    operations = [migrations.RunPython(create_owners_group, migrations.RunPython.noop)]
```

- [ ] **Step 8: Header shows who's logged in; nav only when logged in**

In `listings/templates/listings/base.html`, replace the `<header>…</header>` block with:

```html
  <header>
    <a class="brand" href="{% url 'listing_list' %}">Condo Finder</a>
    {% if user.is_authenticated %}
    <nav>
      <a href="{{ listings_url }}">Listings</a>
      <a href="{% url 'trends' %}">Trends</a>
      <a href="{% url 'feed' %}">Feed{% if feed_unread %} <span class="nav-badge">{{ feed_unread }}</span>{% endif %}</a>
      <a href="{% url 'sources' %}">Sources</a>
      <a href="/admin/">Admin</a>
    </nav>
    <div class="account">
      <span class="muted whoami">{{ request.profile.display_name }}</span>
      <form method="post" action="{% url 'logout' %}">{% csrf_token %}<button type="submit" class="link">Log out</button></form>
    </div>
    {% endif %}
  </header>
```

Add to the inline `<style>`, after the `header nav a` rule:

```css
    header .account { margin-left:auto; display:flex; align-items:center; gap:8px; } header .account form { margin:0; }
    .auth-card { max-width:400px; margin:40px auto; } .auth-card h1 { margin-top:0; font-size:22px; }
    .stack { display:block; margin:0 0 12px; font-size:14px; font-weight:600; }
    .stack input, .stack textarea { display:block; width:100%; margin-top:4px; padding:8px 10px; border:1px solid var(--line); border-radius:8px; font:inherit; font-weight:400; }
    .auth-card button[type=submit] { padding:8px 18px; border:0; border-radius:8px; background:var(--accent); color:#fff; font:600 15px/1.2 inherit; cursor:pointer; }
```

- [ ] **Step 9: Fix the one test that makes its own client**

In `tests/test_views.py`, `test_status_buttons_pass_csrf_over_tailscale` builds an anonymous `Client`. Give it the `owner` fixture and log in:

```python
def test_status_buttons_pass_csrf_over_tailscale(owner):
    from django.test import Client

    listing = good_listing()
    browser = Client(enforce_csrf_checks=True)
    browser.force_login(owner)
    browser.get("/", HTTP_HOST=TAILSCALE_HOST)
```

(Leave the rest of the test as is.)

- [ ] **Step 10: Run the new tests and the full suite**

Run: `uv run pytest tests/test_login.py -q`
Expected: 10 passed.

Run: `uv run pytest -q`
Expected: all pass (528 + 10).

- [ ] **Step 11: Commit**

```bash
git add accounts condofinder listings/context_processors.py listings/templates/listings/base.html tests docs/superpowers/specs/2026-09-30-accounts-decisions.md docs/superpowers/plans/2026-09-30-accounts-and-collaboration.md
git commit -m "feat: search groups and email login on every page"
```

### Task 2: `create_owner` command

**Files:**
- Create: `accounts/management/__init__.py`, `accounts/management/commands/__init__.py`, `accounts/management/commands/create_owner.py`
- Modify: `CLAUDE.md`
- Test: `tests/test_create_owner.py`

**Interfaces:**
- Consumes: `owners_group()`, `move_to_group()`, `Profile` (Task 1).
- Produces: `manage.py create_owner --email E --name N [--password P]`. Task 9 extends it to claim author-less comments.

- [ ] **Step 1: Write the failing tests**

`tests/test_create_owner.py`:

```python
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from accounts.groups import new_group
from accounts.models import Profile
from tests.helpers import home_group

pytestmark = pytest.mark.django_db


def run(**options):
    out = StringIO()
    call_command("create_owner", stdout=out, **options)
    return out.getvalue()


def test_creates_a_staff_account_in_the_owners_group():
    out = run(email="Scott.T@Example.com", name="Scott", password="a long pass phrase")
    user = get_user_model().objects.get()
    assert user.username == user.email == "scott.t@example.com"
    assert user.is_staff and user.is_superuser and user.check_password("a long pass phrase")
    assert user.profile.group == home_group() and user.profile.display_name == "Scott"
    assert 'Created scott.t@example.com (Scott) in "Our search".' in out


def test_rerunning_updates_the_name_and_keeps_the_password():
    run(email="scott@example.com", name="Scott", password="a long pass phrase")
    run(email="scott@example.com", name="Scott T")
    user = get_user_model().objects.get()
    assert user.profile.display_name == "Scott T" and user.check_password("a long pass phrase")
    assert Profile.objects.count() == 1


def test_adopts_an_existing_superuser_by_email_and_moves_it_in():
    old = get_user_model().objects.create_superuser("scott", "scott@example.com", "old password")
    Profile.objects.create(user=old, group=new_group("scott's search"), display_name="scott")
    run(email="scott@example.com", name="Scott")
    old.refresh_from_db()
    assert old.username == "scott@example.com" and old.profile.group == home_group()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_create_owner.py -q`
Expected: FAIL with `CommandError: Unknown command: 'create_owner'`.

- [ ] **Step 3: Implement**

Create empty `accounts/management/__init__.py` and `accounts/management/commands/__init__.py`, then `accounts/management/commands/create_owner.py`:

```python
import getpass

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from accounts.groups import move_to_group, owners_group
from accounts.models import Profile


class Command(BaseCommand):
    help = "Create or update the site admin's account (staff) in the owners' group."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--name", required=True, help="Display name shown on comments, votes and the Feed.")
        parser.add_argument("--password", help="Asked for when creating an account and this is omitted.")

    def handle(self, *args, email, name, password=None, **options):
        email, name = email.strip().lower(), name.strip()[:60]
        User = get_user_model()
        user = User.objects.filter(Q(username__iexact=email) | Q(email__iexact=email)).first()
        created = user is None
        if created:
            user = User(username=email)
            password = password or self._ask_password()
        user.username = user.email = email
        user.is_staff = user.is_superuser = True
        if password:
            user.set_password(password)
        user.save()

        group = owners_group()
        profile = Profile.objects.filter(user=user).first()
        if profile is None:
            profile = Profile.objects.create(user=user, group=group, display_name=name)
        else:
            profile = move_to_group(user, group)
            profile.display_name = name
            profile.save(update_fields=["display_name"])
        self.stdout.write(f'{"Created" if created else "Updated"} {email} ({name}) in "{group.name}".')

    def _ask_password(self):
        password = getpass.getpass("Password: ")
        if password != getpass.getpass("Password again: "):
            raise CommandError("The passwords do not match.")
        try:
            validate_password(password)
        except ValidationError as error:
            raise CommandError(" ".join(error.messages))
        return password
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_create_owner.py -q`
Expected: 3 passed.

- [ ] **Step 5: Update CLAUDE.md**

- In **Current state**, add an "Open:" line for this stack. Keep it accurate as PRs open and merge: `**Open: accounts stack #<n>–#<n+9>** (logins, search groups, collaboration; deploy once after the whole stack merges, following the README runbook).`
- In **Code map**, add a bullet at the top:

```markdown
- `accounts/`: logins and search groups (spec: `docs/superpowers/specs/2026-09-30-accounts-decisions.md`).
  - `SearchGroup` owns everything a household says about listings; each user has one `Profile` in
    exactly one group. `accounts/groups.py` has `owners_group()` (the oldest group), `profile_for()`
    (makes a solo group for accounts created outside the app) and `move_to_group()`.
  - `LoginRequired` middleware guards every page (views opt out with `@login_not_required`); an HTMX
    request without a login gets `HX-Redirect` to the login page. `CurrentGroup` sets `request.profile`
    and `request.group`.
  - Log in with email (`username` is the lowercased email). `manage.py create_owner --email --name`
    makes the site admin (staff) in the owners' group; `manage.py changepassword <email>` resets a password.
```

- In **Conventions → Tests**, add: "The `client` fixture is logged in as Sam, a staff user in the owners' group (`home_group()`); `anon_client` is logged out."

- [ ] **Step 6: Commit and open PR 1**

```bash
git add accounts/management tests/test_create_owner.py CLAUDE.md
git commit -m "feat: create_owner command for the site admin account"
git push -u origin accounts-1-login
gh pr create --base main --title "[Accounts 1/10] Groups and email login" --body-file /dev/stdin <<'EOF'
Adds the accounts app: search groups, one profile per user, email login on every page, and `create_owner`.

Stack (merge bottom-up with **Create a merge commit**; deploy once after all ten merge, following the README runbook in PR 10):
1. **Groups and email login** ← this PR
2. Staff-only controls
3. Per-group status
4. Group Feed
5. Comments
6. Votes
7. Group default filters
8. Per-group Trends
9. Invites and group settings
10. Public HTTPS and docs

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
```

---

# PR 2 — `[Accounts 2/10] Staff-only controls`

Branch: `git checkout -b accounts-2-staff-only` (from `accounts-1-login`)

### Task 3: Staff-only shared-data controls

**Files:**
- Create: `accounts/decorators.py`
- Modify: `listings/views.py` (decorate 6 views), `listings/templates/listings/_history.html`, `listings/templates/listings/detail.html`, `listings/templates/listings/base.html`, `tests/conftest.py`, `CLAUDE.md`
- Test: `tests/test_staff_only.py`

**Interfaces:**
- Produces: `accounts.decorators.staff_required(view)`. It returns 403 "Only the site admin can do that." for non-staff users. Fixtures `member` (Alex, not staff, home group) and `member_client`.

- [ ] **Step 1: Add member fixtures**

Append to `tests/conftest.py`:

```python
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
```

- [ ] **Step 2: Write the failing tests**

`tests/test_staff_only.py`:

```python
import pytest

from listings.models import PriceChange
from tests.helpers import make_listing

pytestmark = pytest.mark.django_db


def listing_with_history():
    listing = make_listing(price=3000)
    return listing, PriceChange.objects.create(listing=listing, price=3100)


def test_members_cannot_change_shared_data(member_client):
    listing, change = listing_with_history()
    posts = [
        f"/listing/{listing.pk}/refresh/",
        f"/listing/{listing.pk}/history/add/",
        f"/listing/{listing.pk}/history/{change.pk}/edit/",
        f"/listing/{listing.pk}/history/{change.pk}/delete/",
        "/sources/scrape/",
    ]
    for url in posts:
        assert member_client.post(url, {"date": "2026-09-01", "price": "1", "event": "x"}).status_code == 403, url
    assert member_client.get(f"/listing/{listing.pk}/history/{change.pk}/edit/").status_code == 403
    assert member_client.get("/sources/").status_code == 403
    assert list(PriceChange.objects.values_list("price", flat=True)) == [3100]


def test_members_see_price_history_read_only(member_client):
    listing, _ = listing_with_history()
    content = member_client.get(f"/listing/{listing.pk}/").content.decode()
    assert '<div class="panel" id="price-history">' in content and "$3,100" in content
    assert f'hx-post="/listing/{listing.pk}/history/add/"' not in content
    assert f'hx-get="/listing/{listing.pk}/history/' not in content
    assert f'href="/admin/listings/listing/{listing.pk}/change/"' not in content
    assert '<a href="/sources/">' not in content and '<a href="/admin/">' not in content


def test_staff_keeps_every_control(client):
    listing, change = listing_with_history()
    content = client.get(f"/listing/{listing.pk}/").content.decode()
    assert f'hx-post="/listing/{listing.pk}/history/add/"' in content
    assert f'hx-get="/listing/{listing.pk}/history/{change.pk}/edit/"' in content
    assert f'href="/admin/listings/listing/{listing.pk}/change/"' in content
    assert '<a href="/sources/">' in content and '<a href="/admin/">' in content
    assert client.get("/sources/").status_code == 200
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_staff_only.py -q`
Expected: FAIL, since members currently get 200 and 302 responses.

- [ ] **Step 4: Implement the decorator and apply it**

`accounts/decorators.py`:

```python
from functools import wraps

from django.http import HttpResponseForbidden


def staff_required(view):
    """Shared scraped data (price history, refreshes, sources) is changed only by the site admin."""

    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_staff:
            return HttpResponseForbidden("Only the site admin can do that.")
        return view(request, *args, **kwargs)

    return wrapped
```

In `listings/views.py`, add `from accounts.decorators import staff_required`. Put `@staff_required` directly above each of `refresh_listing`, `history_add`, `history_edit`, `history_delete`, `sources` and `scrape_now`. Where a view also has `@require_POST`, keep `@require_POST` outermost:

```python
@require_POST
@staff_required
def refresh_listing(request, pk):
```

- [ ] **Step 5: Hide the controls from members**

In `listings/templates/listings/_history.html`:
- Wrap the `{% if refreshable %}…{% endif %}` refresh button in `{% if user.is_staff %}…{% endif %}`.
- Wrap the `<td class="row-actions nowrap">…</td>` cell in `{% if user.is_staff %}…{% endif %}`. Change the header row to `<tr><th>Date</th><th>Price</th><th>Change</th><th>Event</th>{% if user.is_staff %}<th></th>{% endif %}</tr>`.
- Wrap the whole `<form class="history-form add" …>…</form>`, the `<datalist>` and the final `<p class="muted small">Entries are history only…</p>` in `{% if user.is_staff %}…{% endif %}`.

In `listings/templates/listings/detail.html`, wrap the "Correct data in admin" paragraph in `{% if user.is_staff %}…{% endif %}`.

In `listings/templates/listings/base.html`, change the last two nav links to:

```html
      {% if user.is_staff %}<a href="{% url 'sources' %}">Sources</a>
      <a href="/admin/">Admin</a>{% endif %}
```

- [ ] **Step 6: Run the tests and the suite**

Run: `uv run pytest tests/test_staff_only.py -q` → 3 passed.
Run: `uv run pytest -q` → all pass.

- [ ] **Step 7: Update CLAUDE.md and commit**

In `CLAUDE.md` **Conventions**, change "**Admin-style controls on normal pages are fine.** Only the two owners use the app." to:

```markdown
- **Staff-only controls.** Price-history edits, Refresh from sites, the Sources page and admin
  overrides are for the site admin (`is_staff`, via `accounts.decorators.staff_required`, and hidden
  in templates with `{% if user.is_staff %}`). Everyone else sees that data read-only.
```

```bash
git add accounts/decorators.py listings tests CLAUDE.md
git commit -m "feat: price history, refresh and sources are staff-only"
git push -u origin accounts-2-staff-only
gh pr create --base accounts-1-login --title "[Accounts 2/10] Staff-only controls" --body "<same stack list as PR 1, with this PR marked>"
```

(Write the PR body by hand with the same stack list and footer as PR 1. Do this for every PR below.)

---
# PR 3 — `[Accounts 3/10] Per-group status`

Branch: `git checkout -b accounts-3-group-status` (from `accounts-2-staff-only`)

### Task 4: `ListingState` model and moving existing statuses

**Files:**
- Modify: `listings/models.py`
- Create: `listings/migrations/0008_listingstate.py` (generated), `listings/migrations/0009_move_status_to_owners_group.py`
- Test: `tests/test_status_migration.py`

**Interfaces:**
- Produces: `listings.models.ListingState(group FK accounts.SearchGroup related_name="listing_states", listing FK related_name="states", status, status_by FK user null, status_at null)`, unique `(group, listing)`, with the property `status_by_name -> str`. No row means New.

- [ ] **Step 1: Add the model**

At the top of `listings/models.py`, add `from django.conf import settings` and `from accounts.models import display_name`. After `SourceListing`, add:

```python
class ListingState(models.Model):
    """A search group's shared status for a listing. No row means New."""

    group = models.ForeignKey("accounts.SearchGroup", on_delete=models.CASCADE, related_name="listing_states")
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="states")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    status_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    status_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["group", "listing"], name="unique_group_listing_state")]

    @property
    def status_by_name(self):
        return display_name(self.status_by)
```

- [ ] **Step 2: Generate the schema migration**

Run: `uv run python manage.py makemigrations listings --name listingstate`
Expected: `listings/migrations/0008_listingstate.py`, depending on `accounts` and `listings.0007_listing_is_furnished`.

- [ ] **Step 3: Write the failing migration test**

`tests/test_status_migration.py`:

```python
import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

BEFORE = [("listings", "0008_listingstate")]
AFTER = [("listings", "0009_move_status_to_owners_group")]


def migrate(targets):
    executor = MigrationExecutor(connection)
    executor.migrate(targets)
    return MigrationExecutor(connection).loader.project_state(targets).apps


@pytest.mark.django_db(transaction=True)
def test_statuses_move_to_the_owners_group():
    apps = migrate(BEFORE)
    Listing = apps.get_model("listings", "Listing")
    liked = Listing.objects.create(address_key="a", address="1 A St", street="1 A St", city="Portland", status="interested")
    Listing.objects.create(address_key="b", address="2 B St", street="2 B St", city="Portland")
    try:
        apps = migrate(AFTER)
        State = apps.get_model("listings", "ListingState")
        SearchGroup = apps.get_model("accounts", "SearchGroup")
        owners = SearchGroup.objects.order_by("pk").first()
        assert list(State.objects.values_list("group_id", "listing_id", "status")) == [(owners.pk, liked.pk, "interested")]
        assert State.objects.get().status_at is not None
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())  # leave the schema fully migrated
```

- [ ] **Step 4: Run to verify failure**

Run: `uv run pytest tests/test_status_migration.py -q`
Expected: FAIL with `NodeNotFoundError` for `0009_move_status_to_owners_group`.

- [ ] **Step 5: Write the data migration**

`listings/migrations/0009_move_status_to_owners_group.py`:

```python
from django.db import migrations


def forwards(apps, schema_editor):
    """Statuses set before accounts existed belong to the owners' group (the oldest group)."""
    Listing = apps.get_model("listings", "Listing")
    ListingState = apps.get_model("listings", "ListingState")
    SearchGroup = apps.get_model("accounts", "SearchGroup")
    group = SearchGroup.objects.order_by("pk").first() or SearchGroup.objects.create(name="Our search")
    ListingState.objects.bulk_create([
        ListingState(group=group, listing=listing, status=listing.status, status_at=listing.updated_at)
        for listing in Listing.objects.exclude(status="new")
    ])


def backwards(apps, schema_editor):
    Listing = apps.get_model("listings", "Listing")
    ListingState = apps.get_model("listings", "ListingState")
    SearchGroup = apps.get_model("accounts", "SearchGroup")
    group = SearchGroup.objects.order_by("pk").first()
    for state in ListingState.objects.filter(group=group):
        Listing.objects.filter(pk=state.listing_id).update(status=state.status)


class Migration(migrations.Migration):
    dependencies = [("listings", "0008_listingstate"), ("accounts", "0002_owners_group")]
    operations = [migrations.RunPython(forwards, backwards)]
```

- [ ] **Step 6: Run the test and the suite**

Run: `uv run pytest tests/test_status_migration.py -q` → 1 passed.
Run: `uv run pytest -q` → all pass. `Listing.status` still exists, so nothing else has changed yet.

- [ ] **Step 7: Commit**

```bash
git add listings/models.py listings/migrations/0008_listingstate.py listings/migrations/0009_move_status_to_owners_group.py tests/test_status_migration.py
git commit -m "feat: ListingState holds each group's status; existing statuses move to the owners' group"
```

### Task 5: Read and write status per group everywhere

**Files:**
- Create: `listings/collab.py`, `listings/migrations/0010_remove_listing_status.py` (generated)
- Modify: `listings/models.py`, `listings/filters.py`, `listings/feed.py`, `listings/forms.py`, `listings/views.py`, `listings/analyst.py`, `listings/merge.py`, `listings/admin.py`, templates `_status.html`, `_status_pills.html`, `_tracking.html`, `detail.html`, `feed.html`, `base.html` (one CSS rule), `tests/helpers.py`, plus the existing tests listed in Step 9
- Test: `tests/test_group_status.py`

**Interfaces:**
- Consumes: `ListingState` (Task 4), `request.group` (Task 1).
- Produces:
  - `collab.status_expr(group)`: a Coalesce expression for annotating a queryset.
  - `collab.decorate(listings, group, user=None) -> list[Listing]`. It sets `.state` (a `ListingState` or None), `.group_status` (str) and `.group_status_label` (str).
  - `collab.set_status(listing, group, user, status) -> ListingState`.
  - `filters.apply_filters(queryset, data, group)`: `group` is now required.
  - `feed.events(group, tab="all", show_apartments=False)`.
  - `analyst.candidates(group)`, `analyst.passed_on(group)`, `analyst._prepare(listings, group)`.
  - Test helpers: `status_of(listing, group=None)`, and `make_listing(status=...)` now writes a `ListingState` in the home group.

- [ ] **Step 1: Test helpers**

In `tests/helpers.py`, change `make_listing` to pop `status`:

```python
def make_listing(**overrides):
    from listings.models import Listing

    status = overrides.pop("status", None)
    fields = dict(
        address_key="937 nw glisan st|435|97209",
        address="937 NW Glisan Street #435, Portland, OR 97209",
        street="937 NW Glisan Street",
        unit="435",
        city="Portland",
        zip_code="97209",
    )
    fields.update(overrides)
    listing = Listing.objects.create(**fields)
    if status:
        from listings.collab import set_status

        set_status(listing, home_group(), None, status)
    return listing
```

Append:

```python
def status_of(listing, group=None):
    from listings.collab import decorate

    return decorate([listing], group or home_group())[0].group_status
```

- [ ] **Step 2: Write the failing tests**

`tests/test_group_status.py`:

```python
from decimal import Decimal

import pytest
from django.test import Client

from accounts.groups import new_group
from listings.models import ListingState, Status
from tests.helpers import make_listing, make_user, status_of

pytestmark = pytest.mark.django_db


def good_listing(**extra):
    return make_listing(price=3000, beds=2, baths=Decimal("2"), parking_spaces=2, property_type="condo", **extra)


def shown(browser):
    return [listing.pk for listing in browser.get("/").context["listings"]]


def test_each_group_has_its_own_status(client):
    pat = make_user("pat@example.com", "Pat", group=new_group("Pat's search"))
    listing = good_listing()
    client.post(f"/listing/{listing.pk}/status/", {"status": "rejected"}, HTTP_HX_REQUEST="true")
    assert status_of(listing) == Status.REJECTED
    assert status_of(listing, pat.profile.group) == Status.NEW
    pat_browser = Client()
    pat_browser.force_login(pat)
    assert listing.pk not in shown(client)  # the default filters hide rejected listings
    assert listing.pk in shown(pat_browser)


def test_setting_a_status_records_who_and_when(client, owner):
    listing = good_listing()
    client.post(f"/listing/{listing.pk}/status/", {"status": "toured", "variant": "pills"}, HTTP_HX_REQUEST="true")
    state = ListingState.objects.get(listing=listing)
    assert state.status_by == owner and state.status_at is not None
    content = client.get(f"/listing/{listing.pk}/").content.decode()
    assert '<p class="muted small status-by">Set by Sam · ' in content


def test_setting_the_same_status_again_keeps_who_set_it(client, member_client, owner):
    listing = good_listing()
    client.post(f"/listing/{listing.pk}/status/", {"status": "toured"}, HTTP_HX_REQUEST="true")
    member_client.post(f"/listing/{listing.pk}/status/", {"status": "toured"}, HTTP_HX_REQUEST="true")
    assert ListingState.objects.get().status_by == owner


def test_cards_and_pins_show_our_status(client):
    listing = good_listing(status=Status.INTERESTED)
    response = client.get("/")
    content = response.content.decode()
    assert '<span class="status status-interested">Interested</span>' in content
    assert response.context["map_points"][0]["label"].startswith("♥ ")
```

Add to `tests/test_unit_duplicates.py`. Also add the imports `from accounts.groups import new_group`, `from listings.collab import set_status` and `from tests.helpers import home_group, status_of` next to the existing imports:

```python
def test_merge_keeps_every_groups_status():
    bare, unit = _duplicates()
    other = new_group("Pat's search")
    set_status(bare, home_group(), None, Status.INTERESTED)
    set_status(unit, other, None, Status.REJECTED)
    set_status(unit, home_group(), None, Status.TOURED)
    merge_unit_duplicates()
    listing = Listing.objects.get()
    assert status_of(listing) == Status.TOURED and status_of(listing, other) == Status.REJECTED
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_group_status.py tests/test_unit_duplicates.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'listings.collab'`.

- [ ] **Step 4: Create `listings/collab.py`**

```python
"""What a search group says about listings: its shared status (later also votes and comments).
Scraped data on Listing is global; everything here is per group."""

from django.db import models
from django.db.models import OuterRef, Subquery, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from .models import ListingState, Status

STATUS_LABELS = dict(Status.choices)


def status_expr(group):
    """The group's status for each listing in a queryset (New when it hasn't set one), to annotate with."""
    states = ListingState.objects.filter(group=group, listing=OuterRef("pk")).values("status")[:1]
    return Coalesce(Subquery(states), Value(Status.NEW), output_field=models.CharField())


def decorate(listings, group, user=None):
    """Attach the group's view of each listing for templates: .state, .group_status, .group_status_label."""
    listings = list(listings)
    states = {
        state.listing_id: state
        for state in ListingState.objects.filter(group=group, listing__in=listings).select_related("status_by__profile")
    }
    for listing in listings:
        state = states.get(listing.pk)
        listing.state = state
        listing.group_status = state.status if state else Status.NEW
        listing.group_status_label = STATUS_LABELS[listing.group_status]
    return listings


def set_status(listing, group, user, status):
    """Sets the group's status and records who set it. Setting the same status again changes nothing."""
    state, _ = ListingState.objects.get_or_create(group=group, listing=listing)
    if state.status == status and state.status_at:
        return state
    state.status, state.status_by, state.status_at = status, user, timezone.now()
    state.save()
    return state
```

- [ ] **Step 5: Remove `Listing.status`**

In `listings/models.py`, delete the line `status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)` from `Listing`. Keep `STATUS_CHOICES = Status.choices`, because templates still use it.

Run: `uv run python manage.py makemigrations listings --name remove_listing_status`
Expected: `0010_remove_listing_status.py` with one `RemoveField`.

- [ ] **Step 6: Switch the code over**

`listings/filters.py`: change the signature and the statuses filter:

```python
def apply_filters(queryset, data, group):
```

```python
    if data.get("statuses"):
        from .collab import status_expr

        queryset = queryset.annotate(our_status=status_expr(group)).filter(our_status__in=data["statuses"])
```

`listings/feed.py`: import `Exists, OuterRef` from `django.db.models` and `ListingState` from `.models`. Replace `events` and `unread_count`:

```python
def events(group, tab="all", show_apartments=False):
    """New listings, plus updates to listings the group has given a status (anything but New)."""
    tracked = Q(Exists(ListingState.objects.filter(group=group, listing=OuterRef("listing")).exclude(status=Status.NEW)))
    queryset = FeedEvent.objects.select_related("listing")
    if tab == "new":
        queryset = queryset.filter(kind=FeedEvent.Kind.NEW_LISTING)
    elif tab == "updates":
        queryset = queryset.exclude(kind=FeedEvent.Kind.NEW_LISTING).filter(tracked)
    else:
        queryset = queryset.filter(Q(kind=FeedEvent.Kind.NEW_LISTING) | tracked)
    if not show_apartments:
        queryset = queryset.exclude(listing__property_type=PropertyType.APARTMENT)
    return queryset.order_by("-created_at", "-pk")
```

```python
def unread_count(request):
    return events(request.group).filter(created_at__gt=seen_at(request)).count()
```

`listings/forms.py`: `TrackingForm.Meta.fields = ["notes"]`. Keep the widget. (Notes move to comments in Task 9.)

`listings/views.py`: add `from . import collab`, then:
- `listing_list`: pass the group to `apply_filters`, and decorate the page:

```python
    queryset = Listing.objects.all()
    if form.is_valid():
        queryset = apply_filters(queryset, form.cleaned_data, request.group)
    page_obj = Paginator(queryset.prefetch_related("source_listings__source", "price_changes"), PAGE_SIZE).get_page(
        request.GET.get("page")
    )
    listings = collab.decorate(page_obj.object_list, request.group, request.user)
```

  In the context, use `"listings": listings,` and `"map_points": _map_points(listings) if view == "map" else [],`.
- `_pin_style`: `PIN_MARKS.get(listing.group_status, ("", ""))`. In `_map_points`: `"status": listing.group_status,`.
- `feed_page`: `feed.events(request.group, tab, show_apartments)`. After the loop that builds `rows`, add `collab.decorate([row["listing"] for row in rows], request.group, request.user)`.
- `listing_detail`: after fetching, `collab.decorate([listing], request.group, request.user)`.
- `set_status`:

```python
@require_POST
def set_status(request, pk):
    listing = get_object_or_404(Listing, pk=pk)
    status = request.POST.get("status")
    if status not in Status.values:
        return HttpResponseBadRequest("invalid status")
    collab.set_status(listing, request.group, request.user, status)
    collab.decorate([listing], request.group, request.user)
    if request.headers.get("HX-Request"):
        template = "listings/_status_pills.html" if request.POST.get("variant") == "pills" else "listings/_status.html"
        return render(request, template, {"listing": listing})
    referer = request.META.get("HTTP_REFERER", "")
    if url_has_allowed_host_and_scheme(referer, allowed_hosts={request.get_host()}):
        return redirect(referer)
    return redirect("listing_list")
```

- `trends_page`: after `listings = Listing.objects.in_bulk(...)`, add `collab.decorate(listings.values(), request.group, request.user)`.

`listings/analyst.py`: add `from django.db.models import Q`, `from accounts.groups import owners_group`, `from .collab import decorate` and `ListingState` to the models import. Then:

```python
def _prepare(listings, group):
    """The group's view of these listings, as compact_facts reads it."""
    return decorate(listings, group)


def candidates(group):
    """Listings that pass the default filters, plus active listings the group marked as interesting."""
    form = ListingFilterForm(default_filter_data())
    form.is_valid()
    matching = apply_filters(Listing.objects.all(), form.cleaned_data, group).values("pk")
    tracked = ListingState.objects.filter(group=group, status__in=TRACKED, listing__is_active=True).values("listing")
    pool = (
        Listing.objects.filter(Q(pk__in=matching) | Q(pk__in=tracked))
        .prefetch_related("price_changes", "source_listings__source")
        .order_by("price", "pk")
    )
    return _prepare(pool, group)


def passed_on(group, limit=40):
    """Listings the group rejected, most recent first: they show what it doesn't want."""
    ids = list(
        ListingState.objects.filter(group=group, status=Status.REJECTED)
        .order_by("-status_at", "-pk").values_list("listing_id", flat=True)[:limit]
    )
    by_id = Listing.objects.prefetch_related("price_changes").in_bulk(ids)
    return _prepare([by_id[pk] for pk in ids if pk in by_id], group)
```

In `compact_facts`, change `"status": listing.status,` to `"status": listing.group_status,`. In `_clean_picks`, change `listing.status == Status.REJECTED` to `listing.group_status == Status.REJECTED`. In `diff_picks`, change `elif listing.status == Status.REJECTED:` to `elif listing.group_status == Status.REJECTED:`. In `run_report`:
- Right after `try:`, add `group = owners_group()  # Task 14 makes reports per group`.
- `pool = candidates(group)`.
- `rejected = passed_on(group)`.
- Change the diff line to:

```python
            listings = _prepare(Listing.objects.in_bulk(ids).values(), group)
            report.changes = diff_picks(previous.picks, report.picks, {l.pk: l for l in listings})
```

`listings/merge.py`: import `ListingState`. Replace `touched`:

```python
def touched(listing):
    """Whether anyone has done anything to this listing by hand."""
    return bool(
        listing.states.exclude(status=Status.NEW).exists() or listing.notes.strip() or listing.overrides
        or listing.price_changes.filter(source="").exists()
    )
```

In `merge`, delete the two lines `if STATUS_RANK.get(drop.status, 0) > STATUS_RANK.get(keep.status, 0):` / `keep.status = drop.status`. Right after `events.update(listing=keep)`, add `_merge_states(keep, drop)`, and add this function:

```python
def _merge_states(keep, drop):
    """Each group keeps one status for the merged listing: the one further along."""
    for state in drop.states.all():
        mine = keep.states.filter(group_id=state.group_id).first()
        if mine is None:
            state.listing = keep
            state.save(update_fields=["listing"])
        elif STATUS_RANK.get(state.status, 0) > STATUS_RANK.get(mine.status, 0):
            mine.status, mine.status_by, mine.status_at = state.status, state.status_by, state.status_at
            mine.save(update_fields=["status", "status_by", "status_at"])
```

Update the `merge` docstring to "…its sites, price history, feed, notes and every group's status."

`listings/admin.py`: remove `"status"` from `ListingAdmin.list_display` and `list_filter`. Add `ListingState` to the import and register it:

```python
@admin.register(ListingState)
class ListingStateAdmin(admin.ModelAdmin):
    list_display = ("listing", "group", "status", "status_by", "status_at")
    list_filter = ("group", "status")
```

- [ ] **Step 7: Templates**

`_status.html`: change the `<span>` line to:

```html
  <span class="status status-{{ listing.group_status }}">{{ listing.group_status_label }}</span>
```

`_status_pills.html`: change the comment to `{# The group's shared status as a row of pills that saves on click. Posts to set_status, which swaps this form back in. #}`. Change the checked test to `{% if listing.group_status == value %} checked{% endif %}`. Before `<noscript>`, add:

```html
  {% if listing.state.status_at %}<p class="muted small status-by">Set by {{ listing.state.status_by_name|default:"someone" }} · {{ listing.state.status_at|date:"M j" }}</p>{% endif %}
```

In `base.html` CSS, next to `.status-pills`, add `.status-by { flex-basis:100%; margin:2px 0 0; }`.

`_tracking.html` now holds notes only:

```html
{# Notes. Saves a moment after typing stops; only the small "Saved" indicator is swapped in, #}
{# so the notes box keeps focus while you type. #}
<form id="tracking" method="post" action="{% url 'update_tracking' listing.pk %}"
      hx-post="{% url 'update_tracking' listing.pk %}" hx-trigger="change, keyup delay:800ms"
      hx-target="find .save-state" hx-select=".save-state" hx-swap="outerHTML" hx-sync="this:replace">
  {% csrf_token %}
  <textarea name="notes" rows="6" placeholder="Thoughts, questions for the landlord, tour notes…">{{ tracking_form.notes.value|default_if_none:"" }}</textarea>
  <div class="tracking-foot">
    {% if saved %}<span class="save-state saved">Saved ✓ {% now "g:i A" %}</span>
    {% elif tracking_form.errors %}<span class="save-state error">Couldn't save: {{ tracking_form.errors.as_text|striptags }}</span>
    {% else %}<span class="save-state muted">Changes save automatically</span>{% endif %}
  </div>
  <noscript><button type="submit">Save</button></noscript>
</form>
```

`detail.html`: change the notes panel to:

```html
    <div class="panel"><h3>Our notes</h3>{% include "listings/_status_pills.html" %}{% include "listings/_tracking.html" %}</div>
```

`feed.html`: change the status cell to:

```html
    <td class="nowrap">{% if listing.group_status != "new" %}<span class="status status-{{ listing.group_status }}">{{ listing.group_status_label }}</span>{% endif %}</td>
```

- [ ] **Step 8: Run the new tests**

Run: `uv run pytest tests/test_group_status.py tests/test_unit_duplicates.py -q`
Expected: the new tests pass. The older tests that still use `listing.status` fail; Step 9 fixes them.

- [ ] **Step 9: Update existing tests for group status**

Pass the group to every direct `apply_filters` call, and import `home_group`:

```bash
sed -i '' 's/apply_filters(Listing.objects.all(), form.cleaned_data)/apply_filters(Listing.objects.all(), form.cleaned_data, home_group())/' tests/test_filters.py tests/test_map_area.py tests/test_filter_bar.py tests/test_price_drop_ui.py
sed -i '' 's/^from tests.helpers import make_listing$/from tests.helpers import home_group, make_listing/' tests/test_filters.py tests/test_map_area.py tests/test_filter_bar.py tests/test_price_drop_ui.py
```

`tests/test_models.py`: import `status_of` from `tests.helpers`. Change `assert listing.status == Status.NEW` to `assert status_of(listing) == Status.NEW`.

`tests/test_views.py`: import `status_of` from `tests.helpers`. Replace the two tracking tests:

```python
def test_update_tracking_htmx_returns_partial(client):
    listing = good_listing()
    response = client.post(f"/listing/{listing.pk}/tracking/", {"notes": "Great light"}, HTTP_HX_REQUEST="true")
    assert response.status_code == 200
    assert b"Saved" in response.content
    listing.refresh_from_db()
    assert listing.notes == "Great light"


def test_set_status_keeps_notes(client):
    listing = good_listing(notes="keep me")
    response = client.post(f"/listing/{listing.pk}/status/", {"status": "interested"}, HTTP_HX_REQUEST="true")
    assert response.status_code == 200
    listing.refresh_from_db()
    assert (status_of(listing), listing.notes) == (Status.INTERESTED, "keep me")
```

At the end of `test_status_buttons_pass_csrf_over_tailscale`, change `listing.refresh_from_db()` / `assert listing.status == Status.INTERESTED` to `assert status_of(listing) == Status.INTERESTED`.

`tests/test_tracking_controls.py`: replace the file body (keep its imports, and add `status_of`) with:

```python
def section(content, start):
    begin = content.index(start)
    return content[begin:content.index("</form>", begin)]


def test_status_is_a_row_of_pills_with_the_current_one_selected(client):
    listing = make_listing(status=Status.TOURED)
    pills = section(client.get(f"/listing/{listing.pk}/").content.decode(), f'id="pills-{listing.pk}"')
    for value in ("new", "interested", "toured", "applied", "rejected"):
        assert f'name="status" value="{value}"' in pills
    assert re.search(r'name="status" value="toured"[^>]*checked', pills)
    assert "<select" not in pills


def test_notes_save_while_typing_without_a_save_button(client):
    listing = make_listing()
    tracking = section(client.get(f"/listing/{listing.pk}/").content.decode(), 'id="tracking"')
    assert 'hx-trigger="change, keyup delay:800ms"' in tracking
    assert 'hx-select=".save-state"' in tracking  # only the indicator is swapped, so typing isn't interrupted
    assert 'name="status"' not in tracking
    assert re.sub(r"<noscript>.*?</noscript>", "", tracking, flags=re.S).count("<button") == 0


def test_saving_returns_the_indicator(client):
    listing = make_listing(notes="old")
    response = client.post(f"/listing/{listing.pk}/tracking/", {"notes": "Great light"}, HTTP_HX_REQUEST="true")
    content = response.content.decode()
    assert 'class="save-state saved"' in content and "Saved ✓" in content
    listing.refresh_from_db()
    assert listing.notes == "Great light"
```

`tests/test_trends_page.py`: import `status_of` from `tests.helpers`. In `test_pick_cards_have_status_pills_that_post_and_swap`, replace the final `item.refresh_from_db()` / `assert item.status == Status.TOURED` with `assert status_of(item) == Status.TOURED`.

`tests/test_analyst.py`: add `from listings.collab import set_status` and `from tests.helpers import home_group, make_listing`. Then:
- `ids = {listing.pk for listing in analyst.candidates()}` → `ids = {listing.pk for listing in analyst.candidates(home_group())}`.
- `analyst.passed_on()` → `analyst.passed_on(home_group())`.
- `facts = analyst.compact_facts(listing)` → `facts = analyst.compact_facts(analyst._prepare([listing], home_group())[0])`.
- `analyst.full_facts(listing)` → `analyst.full_facts(analyst._prepare([listing], home_group())[0])`.
- In `test_previous_picks_are_sent_and_changes_recorded`, replace `c.status = Status.REJECTED` / `c.save()` with `set_status(c, home_group(), None, Status.REJECTED)`.

`tests/test_unit_duplicates.py`:
- In `test_sweep_keeps_the_listing_with_notes_and_takes_the_unit_address`, replace `bare.notes, bare.status = "High ceilings.", Status.INTERESTED` / `bare.save()` with:

```python
    bare.notes = "High ceilings."
    bare.save()
    set_status(bare, home_group(), None, Status.INTERESTED)
```

  and change its assertion to `assert listing.pk == bare.pk and listing.notes == "High ceilings." and status_of(listing) == Status.INTERESTED`.
- In `test_sweep_merges_notes_and_status_when_both_were_touched`, replace the two `update(...)` lines with:

```python
    Listing.objects.filter(pk=bare.pk).update(notes="High ceilings.")
    Listing.objects.filter(pk=unit.pk).update(notes="Toured Tuesday.", overrides={"has_ac": True})
    set_status(bare, home_group(), None, Status.INTERESTED)
    set_status(unit, home_group(), None, Status.TOURED)
```

  and the last assertion with `assert status_of(listing) == Status.TOURED and listing.overrides == {"has_ac": True}`.

Then find anything else still using the old field:

Run: `grep -rn "\.status\b" tests listings --include='*.py' | grep -v "TrendReport\|report\.status\|state\.status\|status_code\|raise_for_status"`
Expected: no hits that read or assign `Listing.status`.

- [ ] **Step 10: Run the full suite**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 11: Check it in a browser**

Run `DJANGO_DEBUG=1 uv run python manage.py runserver 127.0.0.1:8000` and log in (`uv run python manage.py create_owner --email you@example.com --name You` on your dev database first). Click Interested on a card, open the listing, and change status with the pills. Confirm "Set by You · <date>" appears, that the pin shows ♥, and that there are no console errors at desktop and phone width. Restore any status you changed.

- [ ] **Step 12: Update CLAUDE.md and commit**

In `CLAUDE.md` **Code map**, add a bullet:

```markdown
- `listings/collab.py`: everything a search group says about a listing. `ListingState` holds its
  status (no row = New) with who set it and when. `decorate(listings, group, user)` attaches
  `group_status`/`group_status_label`/`state` for templates; `status_expr(group)` annotates querysets
  (the statuses filter). `apply_filters(queryset, data, group)` needs the group.
```

In the `merge.py` bullet, change "the furthest status wins" to "each group keeps one status, the furthest along (new < interested < toured < applied < rejected)".

```bash
git add listings tests CLAUDE.md
git commit -m "feat: status is per search group, with who set it and when"
git push -u origin accounts-3-group-status
gh pr create --base accounts-2-staff-only --title "[Accounts 3/10] Per-group status" --body "<stack list, this PR marked>"
```

---
# PR 4 — `[Accounts 4/10] Group Feed`

Branch: `git checkout -b accounts-4-group-feed` (from `accounts-3-group-status`)

### Task 6: Group activity in the Feed, unread state per person

**Files:**
- Modify: `accounts/models.py`, `listings/models.py`, `listings/feed.py`, `listings/collab.py`, `listings/views.py`, `listings/context_processors.py`, `listings/templates/listings/feed.html`, `listings/templates/listings/base.html` (CSS), `tests/test_feed_page.py`
- Create: `accounts/migrations/0003_profile_feed_seen_at.py`, `listings/migrations/0011_feed_group_activity.py` (both generated)
- Test: `tests/test_feed_activity.py`

**Interfaces:**
- Consumes: `collab.set_status` (Task 5), `display_name` (Task 1).
- Produces:
  - `Profile.feed_seen_at`.
  - `FeedEvent.group` (null = a scraped event every group sees), `FeedEvent.actor`, and the new kinds `STATUS`, `COMMENT`, `VOTE`.
  - `feed.record_activity(listing, group, actor, kind, summary) -> FeedEvent`.
  - `feed.events(group, tab, show_apartments)`, with tabs `all|new|updates|activity`.
  - `feed.seen_at(profile)`, `feed.is_unread(event, profile, last_seen)`, `feed.unread_count(profile)`, `feed.mark_seen(profile)`.

- [ ] **Step 1: Write the failing tests**

`tests/test_feed_activity.py`:

```python
from datetime import timedelta
from decimal import Decimal

import pytest
from django.test import Client
from django.utils import timezone

from accounts.groups import new_group
from accounts.models import Profile
from listings.collab import set_status
from listings.models import FeedEvent, Status
from tests.helpers import home_group, make_listing, make_user

pytestmark = pytest.mark.django_db
_n = iter(range(1000))


def listing(**fields):
    base = dict(address_key=f"a{next(_n)}", street=f"{next(_n)} Activity St", price=3000, beds=2, baths=Decimal("2"),
                property_type="condo")
    base.update(fields)
    return make_listing(**base)


def event(home, kind, summary="something"):
    now = timezone.now()
    return FeedEvent.objects.create(listing=home, kind=kind, summary=summary, happened_at=now, created_at=now)


def test_a_members_status_change_shows_in_the_group_feed(client, member_client):
    home = listing(street="1 Shared St")
    member_client.post(f"/listing/{home.pk}/status/", {"status": "toured"}, HTTP_HX_REQUEST="true")
    content = client.get("/feed/").content.decode()
    assert "Alex marked it Toured" in content
    assert '<span class="feed-kind kind-status">Status</span>' in content


def test_another_groups_activity_and_tracking_stay_private(client):
    pat = make_user("pat@example.com", "Pat", group=new_group("Pat's search"))
    home = listing(street="2 Private St")
    set_status(home, pat.profile.group, pat, Status.INTERESTED)
    event(home, "price_change", summary="Zillow: $3,200 → $3,000")
    content = client.get("/feed/").content.decode()
    assert "Pat marked it" not in content and "Zillow: $3,200 → $3,000" not in content


def test_own_activity_is_never_unread(client, owner):
    set_status(listing(), home_group(), owner, Status.TOURED)
    assert 'class="nav-badge"' not in client.get("/").content.decode()


def test_unread_state_is_per_person_and_follows_them_across_devices(client, owner, member_client):
    event(listing(), "new_listing")
    client.get("/feed/")
    phone = Client()
    phone.force_login(owner)
    assert 'class="nav-badge"' not in phone.get("/").content.decode()
    assert '<span class="nav-badge">1</span>' in member_client.get("/").content.decode()


def test_activity_tab_shows_only_the_groups_own_activity(client, member_client):
    home = listing(street="3 Tab St")
    event(listing(street="4 New St"), "new_listing")
    member_client.post(f"/listing/{home.pk}/status/", {"status": "interested"}, HTTP_HX_REQUEST="true")
    content = client.get("/feed/?tab=activity").content.decode()
    assert "Alex marked it Interested" in content and "4 New St" not in content
    assert '<a href="?tab=activity" class="active">Activity</a>' in content


def test_apartment_filter_does_not_hide_our_own_activity(client, member_client):
    home = listing(street="5 Complex Ave", property_type="apartment")
    member_client.post(f"/listing/{home.pk}/status/", {"status": "interested"}, HTTP_HX_REQUEST="true")
    assert "Alex marked it Interested" in client.get("/feed/").content.decode()
```

In `tests/test_feed_page.py`, add `from accounts.models import Profile` and replace `test_unread_items_are_highlighted_and_visiting_marks_them_seen`:

```python
def test_unread_items_are_highlighted_and_visiting_marks_them_seen(client, owner):
    old = event(listing(street="8 Old St"), "new_listing", when=timezone.now() - timedelta(days=3))
    event(listing(street="9 Recent St"), "new_listing")
    Profile.objects.filter(user=owner).update(feed_seen_at=timezone.now() - timedelta(days=1))
    content = feed(client).content.decode()
    assert content.count('class="feed-row unread"') == 1
    assert Profile.objects.get(user=owner).feed_seen_at > timezone.now() - timedelta(minutes=1)
    assert old.pk  # the older item is still listed, just not unread
    assert "8 Old St" in content
```

In `test_nav_badge_counts_unread_and_clears_after_visiting`, change the comment `# no cookie yet: …` to `# never visited: the last 7 days count as unread`.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_feed_activity.py tests/test_feed_page.py -q`
Expected: FAIL (no status activity, `feed_seen_at` field missing).

- [ ] **Step 3: Models and migrations**

`accounts/models.py`, in `Profile`, add:

```python
    feed_seen_at = models.DateTimeField(null=True, blank=True)  # the Feed's unread line, synced across devices
```

`listings/models.py`, in `FeedEvent.Kind`, add:

```python
        STATUS = "status", "Status"
        COMMENT = "comment", "Comment"
        VOTE = "vote", "Vote"
```

and add these fields to `FeedEvent`:

```python
    # A group's own activity (status changes, comments, votes) has its group and who did it. Scraped
    # events have no group, and every group sees them.
    group = models.ForeignKey("accounts.SearchGroup", on_delete=models.CASCADE, null=True, blank=True, related_name="feed_events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
```

Run:

```bash
uv run python manage.py makemigrations accounts --name profile_feed_seen_at
uv run python manage.py makemigrations listings --name feed_group_activity
```

Expected: `accounts/migrations/0003_profile_feed_seen_at.py` and `listings/migrations/0011_feed_group_activity.py`.

- [ ] **Step 4: Feed queries**

In `listings/feed.py`, remove `SEEN_COOKIE`, the old `seen_at`/`unread_count` and the `datetime` import. Then replace `events` and add the functions below:

```python
def record_activity(listing, group, actor, kind, summary):
    """Something a group member did, shown only in that group's Feed."""
    now = timezone.now()
    return FeedEvent.objects.create(
        listing=listing, group=group, actor=actor, kind=kind, summary=summary[:300], created_at=now, happened_at=now,
    )


def events(group, tab="all", show_apartments=False):
    """New listings and updates to listings the group tracks (scraped events every group sees), plus the
    group's own activity: status changes, comments and votes by its members."""
    site = Q(group__isnull=True)
    tracked = Q(Exists(ListingState.objects.filter(group=group, listing=OuterRef("listing")).exclude(status=Status.NEW)))
    queryset = FeedEvent.objects.select_related("listing", "actor__profile")
    if tab == "new":
        queryset = queryset.filter(site, kind=FeedEvent.Kind.NEW_LISTING)
    elif tab == "updates":
        queryset = queryset.filter(site & tracked).exclude(kind=FeedEvent.Kind.NEW_LISTING)
    elif tab == "activity":
        queryset = queryset.filter(group=group)
    else:
        queryset = queryset.filter((site & (Q(kind=FeedEvent.Kind.NEW_LISTING) | tracked)) | Q(group=group))
    if not show_apartments:
        queryset = queryset.exclude(site & Q(listing__property_type=PropertyType.APARTMENT))
    return queryset.order_by("-created_at", "-pk")


def seen_at(profile):
    return profile.feed_seen_at or timezone.now() - FIRST_VISIT_UNREAD


def is_unread(event, profile, last_seen):
    """Newer than the person's last Feed visit, and not something they did themselves."""
    return event.created_at > last_seen and event.actor_id != profile.user_id


def unread_count(profile):
    return events(profile.group).filter(created_at__gt=seen_at(profile)).exclude(actor=profile.user).count()


def mark_seen(profile):
    profile.feed_seen_at = timezone.now()
    profile.save(update_fields=["feed_seen_at"])
```

In `label()`, add these three entries to the dict:

```python
        FeedEvent.Kind.STATUS: "Status",
        FeedEvent.Kind.COMMENT: "Comment",
        FeedEvent.Kind.VOTE: "Vote",
```

- [ ] **Step 5: Record status changes**

In `listings/collab.py`, add `from accounts.models import display_name` and `from . import feed`, and import `FeedEvent` from `.models`. At the end of `set_status`, before `return state`:

```python
    if user is not None:
        feed.record_activity(listing, group, user, FeedEvent.Kind.STATUS,
                             f"{display_name(user)} marked it {STATUS_LABELS[status]}")
```

- [ ] **Step 6: Views, context processor, template**

`listings/views.py`, `feed_page`:

```python
def feed_page(request):
    """New listings, updates to listings the group tracks, and the group's own activity, newest first."""
    requested = request.GET.get("tab")
    tab = requested if requested in ("new", "updates", "activity") else "all"
    show_apartments = request.GET.get("apartments") == "show"
    last_seen = feed.seen_at(request.profile)
    page_obj = Paginator(feed.events(request.group, tab, show_apartments), FEED_PAGE_SIZE).get_page(request.GET.get("page"))
```

In the row dict, set `"unread": feed.is_unread(event, request.profile, last_seen),`. Delete the `response.set_cookie(...)` line. Render and return directly, calling `feed.mark_seen(request.profile)` just before `return render(...)`.

`listings/context_processors.py`: change the last line to:

```python
    return {"listings_url": f"/{query}", "feed_unread": 0 if on_feed else feed.unread_count(request.profile)}
```

`listings/templates/listings/feed.html`:
- Add a fourth tab after "Updates":

```html
      <a href="?tab=activity{% if show_apartments %}&amp;apartments=show{% endif %}"{% if tab == "activity" %} class="active"{% endif %}>Activity</a>
```

- Change the description paragraph to:

```html
<p class="muted">New listings, updates to listings your group has given a status, and what your group has been doing (statuses, comments, votes).</p>
```

`base.html` CSS, after the `.kind-back_on_market` rule:

```css
    .kind-status, .kind-comment, .kind-vote { background:#eef2ff; color:#3730a3; }
```

- [ ] **Step 7: Run the tests and the suite**

Run: `uv run pytest tests/test_feed_activity.py tests/test_feed_page.py -q` → all pass.
Run: `uv run pytest -q` → all pass.

- [ ] **Step 8: Commit**

```bash
git add accounts listings tests
git commit -m "feat: the Feed shows the group's own activity; unread state is per person"
```

### Task 7: Feed badge polling

**Files:**
- Create: `listings/templates/listings/_feed_badge.html`
- Modify: `listings/views.py`, `listings/urls.py`, `listings/context_processors.py`, `listings/templates/listings/base.html`, `CLAUDE.md`
- Test: `tests/test_feed_activity.py` (append)

**Interfaces:**
- Produces: URL `feed_badge` at `/feed/badge/`, which returns `_feed_badge.html`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_feed_activity.py`:

```python
def test_nav_badge_polls_every_30_seconds(client):
    content = client.get("/").content.decode()
    assert '<span id="feed-badge" hx-get="/feed/badge/" hx-trigger="every 30s" hx-swap="outerHTML">' in content


def test_badge_endpoint_counts_without_marking_seen(client, owner):
    event(listing(), "new_listing")
    assert '<span class="nav-badge">1</span>' in client.get("/feed/badge/").content.decode()
    assert Profile.objects.get(user=owner).feed_seen_at is None
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_feed_activity.py -q -k badge`
Expected: FAIL (404 for `/feed/badge/`, no `id="feed-badge"`).

- [ ] **Step 3: Implement**

`listings/templates/listings/_feed_badge.html`:

```html
<span id="feed-badge" hx-get="{% url 'feed_badge' %}" hx-trigger="every 30s" hx-swap="outerHTML">{% if feed_unread %} <span class="nav-badge">{{ feed_unread }}</span>{% endif %}</span>
```

In `base.html`, change the Feed link to:

```html
      <a href="{% url 'feed' %}">Feed{% include "listings/_feed_badge.html" %}</a>
```

`listings/views.py`:

```python
def feed_badge(request):
    """The nav's unread count, polled every 30 seconds."""
    return render(request, "listings/_feed_badge.html", {"feed_unread": feed.unread_count(request.profile)})
```

`listings/urls.py`: add `path("feed/badge/", views.feed_badge, name="feed_badge"),` after the `feed/` line.

`listings/context_processors.py`: skip the count on both Feed URLs:

```python
    url_name = getattr(getattr(request, "resolver_match", None), "url_name", None)
    if url_name in ("feed", "feed_badge"):  # the Feed marks everything seen; the badge view counts itself
        return {"listings_url": f"/{query}", "feed_unread": 0}
    return {"listings_url": f"/{query}", "feed_unread": feed.unread_count(request.profile)}
```

(This replaces the `on_feed` lines.)

- [ ] **Step 4: Run the tests and the suite**

Run: `uv run pytest -q` → all pass.

- [ ] **Step 5: Check it in a browser**

Open two browsers logged in as two accounts in the same group. Change a status in one. Within 30 seconds the other's Feed badge should show 1 without a reload. Check the console for errors.

- [ ] **Step 6: Update CLAUDE.md and commit**

Replace the `listings/feed.py` bullet in `CLAUDE.md`:

```markdown
- `listings/feed.py` records `FeedEvent` rows. Scraped events (new listings, changes) have no
  `group`, and every group sees them; change events show for listings the group tracks (status ≠ New).
  A group's own activity (status changes, comments, votes) has `group` and `actor` and shows only to
  that group. `happened_at` is when the change happened; `created_at` is when we learned of it. Unread
  state is per person (`Profile.feed_seen_at`); your own actions never count as unread. The nav badge
  polls `/feed/badge/` every 30s.
```

```bash
git add listings tests CLAUDE.md
git commit -m "feat: the Feed badge updates every 30 seconds"
git push -u origin accounts-4-group-feed
gh pr create --base accounts-3-group-status --title "[Accounts 4/10] Group Feed" --body "<stack list, this PR marked>"
```

---
# PR 5 — `[Accounts 5/10] Comments`

Branch: `git checkout -b accounts-5-comments` (from `accounts-4-group-feed`)

### Task 8: `Comment` model and turning notes into comments

**Files:**
- Modify: `listings/models.py`
- Create: `listings/migrations/0012_comment.py` (generated), `listings/migrations/0013_notes_to_comments.py`
- Test: `tests/test_notes_migration.py`

**Interfaces:**
- Produces:
  - `listings.models.Comment(listing FK related_name="comments", group FK related_name="comments", author FK user SET_NULL null, author_name, body, created_at, edited_at)`, ordered `created_at, pk`, with the property `by -> str`.
  - `FeedEvent.comment` FK (CASCADE, null), so deleting a comment deletes its Feed item.

- [ ] **Step 1: Add the model**

In `listings/models.py`, after `ListingState`:

```python
class Comment(models.Model):
    """One message in a group's thread on a listing. Only its author edits or deletes it."""

    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="comments")
    group = models.ForeignKey("accounts.SearchGroup", on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="comments")
    author_name = models.CharField(max_length=60, blank=True)  # the author's name when written, shown if the account is gone
    body = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)
    edited_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "pk"]

    def __str__(self):
        return f"{self.by}: {self.body[:40]}"

    @property
    def by(self):
        return display_name(self.author) if self.author_id else (self.author_name or "Someone")
```

In `FeedEvent`, add (a string reference, because `Comment` is defined after it):

```python
    comment = models.ForeignKey("Comment", on_delete=models.CASCADE, null=True, blank=True, related_name="feed_events")
```

Run: `uv run python manage.py makemigrations listings --name comment`
Expected: `0012_comment.py` (CreateModel Comment, AddField feedevent.comment).

- [ ] **Step 2: Write the failing migration test**

`tests/test_notes_migration.py`:

```python
import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

BEFORE = [("listings", "0012_comment")]
AFTER = [("listings", "0013_notes_to_comments")]


def migrate(targets):
    MigrationExecutor(connection).migrate(targets)
    return MigrationExecutor(connection).loader.project_state(targets).apps


@pytest.mark.django_db(transaction=True)
def test_notes_become_the_owners_first_comment():
    apps = migrate(BEFORE)
    Listing = apps.get_model("listings", "Listing")
    SearchGroup = apps.get_model("accounts", "SearchGroup")
    Profile = apps.get_model("accounts", "Profile")
    User = apps.get_model("auth", "User")
    owners = SearchGroup.objects.order_by("pk").first() or SearchGroup.objects.create(name="Our search")
    scott = User.objects.create(username="scott@example.com", email="scott@example.com", is_staff=True)
    Profile.objects.create(user=scott, group=owners, display_name="Scott")
    noted = Listing.objects.create(address_key="a", address="1 A St", street="1 A St", city="Portland", notes="  Big deck.  ")
    Listing.objects.create(address_key="b", address="2 B St", street="2 B St", city="Portland", notes="   ")
    try:
        apps = migrate(AFTER)
        Comment = apps.get_model("listings", "Comment")
        comment = Comment.objects.get()
        assert (comment.listing_id, comment.group_id, comment.author_id) == (noted.pk, owners.pk, scott.pk)
        assert comment.body == "Big deck." and comment.author_name == "Scott"
        assert comment.created_at == Listing.objects.get(pk=noted.pk).updated_at
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_notes_migration.py -q`
Expected: FAIL with `NodeNotFoundError` for `0013_notes_to_comments`.

- [ ] **Step 4: Write the data migration**

`listings/migrations/0013_notes_to_comments.py`:

```python
from django.db import migrations


def forwards(apps, schema_editor):
    """Each listing's notes become the first comment in the owners' group, by the site admin if their
    account exists yet (create_owner claims author-less comments otherwise), dated at the listing's
    last update."""
    Listing = apps.get_model("listings", "Listing")
    Comment = apps.get_model("listings", "Comment")
    SearchGroup = apps.get_model("accounts", "SearchGroup")
    Profile = apps.get_model("accounts", "Profile")
    noted = [listing for listing in Listing.objects.exclude(notes="") if listing.notes.strip()]
    if not noted:
        return
    group = SearchGroup.objects.order_by("pk").first() or SearchGroup.objects.create(name="Our search")
    owner = Profile.objects.filter(group=group, user__is_staff=True).order_by("joined_at", "pk").first()
    Comment.objects.bulk_create([
        Comment(listing=listing, group=group, author_id=owner.user_id if owner else None,
                author_name=owner.display_name if owner else "", body=listing.notes.strip(), created_at=listing.updated_at)
        for listing in noted
    ])


def backwards(apps, schema_editor):
    Listing = apps.get_model("listings", "Listing")
    Comment = apps.get_model("listings", "Comment")
    SearchGroup = apps.get_model("accounts", "SearchGroup")
    group = SearchGroup.objects.order_by("pk").first()
    bodies = {}
    for comment in Comment.objects.filter(group=group).order_by("created_at", "pk"):
        bodies.setdefault(comment.listing_id, []).append(comment.body)
    for listing_id, texts in bodies.items():
        Listing.objects.filter(pk=listing_id).update(notes="\n\n".join(texts))


class Migration(migrations.Migration):
    dependencies = [("listings", "0012_comment"), ("accounts", "0003_profile_feed_seen_at")]
    operations = [migrations.RunPython(forwards, backwards)]
```

- [ ] **Step 5: Run the test and the suite**

Run: `uv run pytest tests/test_notes_migration.py -q` → 1 passed.
Run: `uv run pytest -q` → all pass.

- [ ] **Step 6: Commit**

```bash
git add listings/models.py listings/migrations/0012_comment.py listings/migrations/0013_notes_to_comments.py tests/test_notes_migration.py
git commit -m "feat: Comment model; existing notes become the owners' first comment"
```

### Task 9: Comment thread on the listing page

**Files:**
- Create: `listings/collab_views.py`, `listings/templates/listings/_comments.html`, `listings/templates/listings/_comment_form.html`, `listings/migrations/0014_remove_listing_notes.py` (generated)
- Modify: `listings/models.py` (remove `notes`), `listings/collab.py`, `listings/feed.py`, `listings/urls.py`, `listings/views.py`, `listings/forms.py`, `listings/merge.py`, `listings/analyst.py`, `listings/admin.py`, `accounts/management/commands/create_owner.py`, `listings/templates/listings/detail.html`, `base.html` (CSS), `tests/helpers.py`, `tests/test_views.py`, `tests/test_tracking_controls.py`, `tests/test_analyst.py`, `tests/test_unit_duplicates.py`, `tests/test_create_owner.py`, `CLAUDE.md`
- Delete: `listings/templates/listings/_tracking.html`
- Test: `tests/test_comments.py`

**Interfaces:**
- Consumes: `Comment`, `FeedEvent.comment` (Task 8), `feed.record_activity` (Task 6).
- Produces:
  - `collab.comments_for(listing, group) -> QuerySet[Comment]`, `collab.add_comment(listing, group, user, body) -> Comment`, `collab.edit_comment(comment, body)`, `collab.attach_comments(listings, group)` (sets `.group_comments`).
  - URL names `comment_list` (`listing/<pk>/comments/`), `comment_add` (`…/comments/add/`), `comment_edit` (`…/comments/<comment_pk>/edit/`), `comment_delete` (`…/comments/<comment_pk>/delete/`).
  - `feed.record_activity(..., comment=None)`.
  - `analyst._prepare` also attaches comments; `compact_facts` has `"comments"` instead of `"notes"`.
  - Test helper: `make_listing(notes=...)` writes a comment by "Sam" in the home group.

- [ ] **Step 1: Test helper for notes**

In `tests/helpers.py` `make_listing`, also pop `notes = overrides.pop("notes", "")`. After the status block, add:

```python
    if notes:
        from listings.models import Comment

        Comment.objects.create(listing=listing, group=home_group(), author_name="Sam", body=notes)
```

- [ ] **Step 2: Write the failing tests**

`tests/test_comments.py`:

```python
import pytest
from django.test import Client

from accounts.groups import new_group
from listings.merge import merge
from listings.models import Comment, FeedEvent
from tests.helpers import make_listing, make_user

pytestmark = pytest.mark.django_db


def post(browser, url, data=None):
    return browser.post(url, data or {}, HTTP_HX_REQUEST="true").content.decode()


def test_listing_page_has_a_thread_that_polls_and_a_form(client):
    listing = make_listing()
    content = client.get(f"/listing/{listing.pk}/").content.decode()
    assert (f'<div id="comments" hx-get="/listing/{listing.pk}/comments/" '
            "hx-trigger=\"every 30s [!document.querySelector('#comments form')]\" hx-swap=\"outerHTML\">") in content
    assert f'<form id="comment-form" method="post" action="/listing/{listing.pk}/comments/add/"' in content
    assert 'name="notes"' not in content


def test_posting_shows_the_comment_with_author_and_time(client):
    listing = make_listing()
    thread = post(client, f"/listing/{listing.pk}/comments/add/", {"body": "Loved the light.\nAsk about parking."})
    assert '<strong class="comment-by">Sam</strong>' in thread
    assert "Loved the light.<br>Ask about parking." in thread
    comment = Comment.objects.get()
    assert comment.author.username == "sam@example.com" and comment.author_name == "Sam"


def test_blank_comment_is_ignored(client):
    listing = make_listing()
    post(client, f"/listing/{listing.pk}/comments/add/", {"body": "   "})
    assert not Comment.objects.exists()


def test_only_the_author_can_edit_or_delete(client, member_client):
    listing = make_listing()
    post(client, f"/listing/{listing.pk}/comments/add/", {"body": "Mine"})
    comment = Comment.objects.get()
    theirs = member_client.get(f"/listing/{listing.pk}/comments/").content.decode()
    assert "Mine" in theirs and f"/comments/{comment.pk}/edit/" not in theirs
    assert member_client.post(f"/listing/{listing.pk}/comments/{comment.pk}/edit/", {"body": "Hacked"}).status_code == 404
    assert member_client.post(f"/listing/{listing.pk}/comments/{comment.pk}/delete/").status_code == 404
    assert Comment.objects.get().body == "Mine"


def test_author_edits_in_place_and_deletes(client):
    listing = make_listing()
    post(client, f"/listing/{listing.pk}/comments/add/", {"body": "Frist"})
    comment = Comment.objects.get()
    form = client.get(f"/listing/{listing.pk}/comments/{comment.pk}/edit/", HTTP_HX_REQUEST="true").content.decode()
    assert f'<form class="comment-edit" hx-post="/listing/{listing.pk}/comments/{comment.pk}/edit/"' in form
    thread = post(client, f"/listing/{listing.pk}/comments/{comment.pk}/edit/", {"body": "First"})
    assert "First" in thread and "· edited" in thread
    thread = post(client, f"/listing/{listing.pk}/comments/{comment.pk}/delete/")
    assert not Comment.objects.exists() and "No comments yet." in thread


def test_other_groups_never_see_our_comments(client):
    listing = make_listing()
    post(client, f"/listing/{listing.pk}/comments/add/", {"body": "Private to us"})
    pat = Client()
    pat.force_login(make_user("pat@example.com", "Pat", group=new_group("Pat's search")))
    assert "Private to us" not in pat.get(f"/listing/{listing.pk}/").content.decode()
    assert "Private to us" not in pat.get(f"/listing/{listing.pk}/comments/").content.decode()


def test_feed_follows_comment_edits_and_deletes(client, member_client):
    listing = make_listing()
    post(member_client, f"/listing/{listing.pk}/comments/add/", {"body": "Ask about pets"})
    comment = Comment.objects.get()
    assert "Alex: Ask about pets" in client.get("/feed/").content.decode()
    post(member_client, f"/listing/{listing.pk}/comments/{comment.pk}/edit/", {"body": "Ask about cats"})
    assert "Alex: Ask about cats" in client.get("/feed/").content.decode()
    post(member_client, f"/listing/{listing.pk}/comments/{comment.pk}/delete/")
    assert not FeedEvent.objects.filter(kind=FeedEvent.Kind.COMMENT).exists()


def test_merge_moves_comments():
    keep = make_listing(address_key="k", notes="On the keeper")
    drop = make_listing(address_key="d", notes="On the duplicate")
    merge(keep, drop)
    assert sorted(Comment.objects.filter(listing=keep).values_list("body", flat=True)) == ["On the duplicate", "On the keeper"]
```

Append to `tests/test_create_owner.py` (and add `from listings.models import Comment` and `from tests.helpers import make_listing` to its imports):

```python
def test_claims_comments_from_before_the_account_existed():
    listing = make_listing()
    Comment.objects.create(listing=listing, group=home_group(), body="Old note")
    run(email="scott@example.com", name="Scott", password="a long pass phrase")
    comment = Comment.objects.get()
    assert comment.author.username == "scott@example.com" and comment.by == "Scott"
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_comments.py tests/test_create_owner.py -q`
Expected: FAIL (404s for the comment URLs; `create_owner` doesn't claim).

- [ ] **Step 4: collab and feed**

`listings/feed.py`, `record_activity`: add a `comment=None` parameter and pass `comment=comment` to `create`.

`listings/collab.py`: import `Comment`, and add:

```python
COMMENT_LIMIT = 5000


def comments_for(listing, group):
    return Comment.objects.filter(listing=listing, group=group).select_related("author__profile")


def add_comment(listing, group, user, body):
    name = display_name(user)
    comment = Comment.objects.create(listing=listing, group=group, author=user, author_name=name, body=body[:COMMENT_LIMIT])
    feed.record_activity(listing, group, user, FeedEvent.Kind.COMMENT, f"{name}: {comment.body}", comment=comment)
    return comment


def edit_comment(comment, body):
    comment.body, comment.edited_at = body[:COMMENT_LIMIT], timezone.now()
    comment.save(update_fields=["body", "edited_at"])
    FeedEvent.objects.filter(comment=comment).update(summary=f"{comment.by}: {comment.body}"[:300])


def attach_comments(listings, group):
    """Sets .group_comments on each listing: the group's thread, oldest first."""
    listings = list(listings)
    threads = {}
    for comment in Comment.objects.filter(group=group, listing__in=listings).select_related("author__profile"):
        threads.setdefault(comment.listing_id, []).append(comment)
    for listing in listings:
        listing.group_comments = threads.get(listing.pk, [])
    return listings
```

- [ ] **Step 5: Views and URLs**

`listings/collab_views.py`:

```python
"""A group's comment thread on a listing (and, from the next PR, votes)."""

from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import collab
from .models import Comment, Listing


def _thread(request, listing, editing=None):
    return render(request, "listings/_comments.html", {
        "listing": listing,
        "comments": collab.comments_for(listing, request.group),
        "editing": editing,
    })


def _own_comment(request, pk, comment_pk):
    """The person's own comment in their group; anyone else's is a 404."""
    return get_object_or_404(Comment.objects.select_related("listing"), pk=comment_pk, listing_id=pk,
                             group=request.group, author=request.user)


def comment_list(request, pk):
    """The thread, polled every 30 seconds by the listing page."""
    return _thread(request, get_object_or_404(Listing, pk=pk))


@require_POST
def comment_add(request, pk):
    listing = get_object_or_404(Listing, pk=pk)
    body = request.POST.get("body", "").strip()
    if body:
        collab.add_comment(listing, request.group, request.user, body)
    if not request.headers.get("HX-Request"):
        return redirect(listing)
    return _thread(request, listing)


def comment_edit(request, pk, comment_pk):
    comment = _own_comment(request, pk, comment_pk)
    if request.method == "POST":
        body = request.POST.get("body", "").strip()
        if body:
            collab.edit_comment(comment, body)
        return _thread(request, comment.listing)
    return _thread(request, comment.listing, editing=comment.pk)


@require_POST
def comment_delete(request, pk, comment_pk):
    comment = _own_comment(request, pk, comment_pk)
    listing = comment.listing
    comment.delete()  # its Feed item goes with it
    return _thread(request, listing)
```

`listings/urls.py`: add `from . import collab_views` and, in place of the `update_tracking` line:

```python
    path("listing/<int:pk>/comments/", collab_views.comment_list, name="comment_list"),
    path("listing/<int:pk>/comments/add/", collab_views.comment_add, name="comment_add"),
    path("listing/<int:pk>/comments/<int:comment_pk>/edit/", collab_views.comment_edit, name="comment_edit"),
    path("listing/<int:pk>/comments/<int:comment_pk>/delete/", collab_views.comment_delete, name="comment_delete"),
```

`listings/views.py`: delete `update_tracking`, drop `TrackingForm` from the forms import, and change `listing_detail` to:

```python
def listing_detail(request, pk):
    listing = get_object_or_404(
        Listing.objects.prefetch_related("source_listings__source", "price_changes"), pk=pk
    )
    collab.decorate([listing], request.group, request.user)
    return render(request, "listings/detail.html", {
        **_history_context(listing),
        "listing": listing,
        "comments": collab.comments_for(listing, request.group),
    })
```

(`_history_context` re-fetches its own copy of the listing, so pass the decorated `listing` last, as shown, so the template gets the decorated instance.)

`listings/forms.py`: delete `TrackingForm`.

- [ ] **Step 6: Templates**

`listings/templates/listings/_comments.html`:

```html
{% load humanize %}
{# The group's thread on a listing. Re-fetched every 30s, but not while a comment is being edited. #}
<div id="comments" hx-get="{% url 'comment_list' listing.pk %}" hx-trigger="every 30s [!document.querySelector('#comments form')]" hx-swap="outerHTML">
  {% for comment in comments %}
  <div class="comment" id="comment-{{ comment.pk }}">
    {% if comment.pk == editing %}
    <form class="comment-edit" hx-post="{% url 'comment_edit' listing.pk comment.pk %}" hx-target="#comments" hx-swap="outerHTML">
      {% csrf_token %}
      <textarea name="body" rows="3" required>{{ comment.body }}</textarea>
      <button type="submit">Save</button>
      <button type="button" class="link" hx-get="{% url 'comment_list' listing.pk %}" hx-target="#comments" hx-swap="outerHTML">Cancel</button>
    </form>
    {% else %}
    <div class="comment-head">
      <strong class="comment-by">{{ comment.by }}</strong>
      <span class="muted">{{ comment.created_at|date:"M j, g:i A" }}{% if comment.edited_at %} · edited{% endif %}</span>
      {% if comment.author_id == user.pk %}
      <span class="row-actions">
        <button type="button" class="link" hx-get="{% url 'comment_edit' listing.pk comment.pk %}" hx-target="#comments" hx-swap="outerHTML">Edit</button>
        <button type="button" class="link danger" hx-post="{% url 'comment_delete' listing.pk comment.pk %}" hx-target="#comments"
                hx-swap="outerHTML" hx-confirm="Delete this comment?">Delete</button>
      </span>
      {% endif %}
    </div>
    <div class="comment-body">{{ comment.body|linebreaksbr }}</div>
    {% endif %}
  </div>
  {% empty %}
  <p class="muted">No comments yet.</p>
  {% endfor %}
</div>
```

`listings/templates/listings/_comment_form.html`:

```html
{# Posting swaps in the updated thread and clears the box. Without JavaScript it posts and reloads. #}
<form id="comment-form" method="post" action="{% url 'comment_add' listing.pk %}"
      hx-post="{% url 'comment_add' listing.pk %}" hx-target="#comments" hx-swap="outerHTML"
      hx-on::after-request="if (event.detail.successful) this.reset()">
  {% csrf_token %}
  <textarea name="body" rows="3" placeholder="Thoughts, questions for the landlord, tour notes…" required></textarea>
  <button type="submit">Post</button>
</form>
```

In `detail.html`, replace the "Our notes" panel with:

```html
    <div class="panel"><h3>Our status</h3>{% include "listings/_status_pills.html" %}</div>
    <div class="panel"><h3>Comments</h3>{% include "listings/_comments.html" %}{% include "listings/_comment_form.html" %}</div>
```

Delete `listings/templates/listings/_tracking.html`.

`base.html` CSS, replacing the `.tracking-foot` rule's neighbourhood:

```css
    .comment { padding:8px 0; border-bottom:1px solid var(--line); } .comment:last-child { border-bottom:0; }
    .comment-head { display:flex; flex-wrap:wrap; align-items:baseline; gap:6px; font-size:14px; }
    .comment-head .row-actions { margin-left:auto; }
    .comment-body { margin-top:2px; font-size:14px; overflow-wrap:anywhere; }
    #comment-form, .comment-edit { display:flex; flex-direction:column; gap:6px; margin-top:10px; }
    #comment-form textarea, .comment-edit textarea { width:100%; padding:8px 10px; border:1px solid var(--line); border-radius:8px; font:inherit; font-size:14px; resize:vertical; }
    #comment-form button[type=submit], .comment-edit button[type=submit] { align-self:flex-start; }
```

Keep `.tracking-foot` and `.save-state`, which the priorities box still uses.

- [ ] **Step 7: Remove `Listing.notes`; update merge, analyst, admin, create_owner**

`listings/models.py`: delete `notes = models.TextField(blank=True)` from `Listing`.
Run: `uv run python manage.py makemigrations listings --name remove_listing_notes` → `0014_remove_listing_notes.py`.

`listings/merge.py`: import `Comment`. In `touched`, replace `listing.notes.strip()` with `listing.comments.exists()`. In `merge`, delete the two `notes = …` / `keep.notes = …` lines, and add after `_merge_states(keep, drop)`:

```python
    Comment.objects.filter(listing=drop).update(listing=keep)
```

Update the module docstring's "notes and status" to "comments, votes and every group's status". Update `touched`'s docstring to "…done anything by hand (a status, a comment, an override, a hand-entered price)".

`listings/analyst.py`: import `attach_comments` from `.collab`. Change `_prepare` to:

```python
def _prepare(listings, group):
    """The group's view of these listings (status and comments), as compact_facts reads it."""
    return attach_comments(decorate(listings, group), group)
```

In `compact_facts`, replace `"notes": listing.notes,` with:

```python
        "comments": [
            {"by": comment.by, "date": timezone.localdate(comment.created_at).isoformat(), "text": comment.body}
            for comment in listing.group_comments
        ],
```

`listings/admin.py`: import and register `Comment`:

```python
@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ("created_at", "listing", "group", "author", "body")
    list_filter = ("group",)
    search_fields = ("body", "listing__address")
```

`accounts/management/commands/create_owner.py`: after saving the profile, claim comments that have no author yet:

```python
        from listings.models import Comment

        claimed = Comment.objects.filter(group=group, author__isnull=True, author_name="").update(author=user, author_name=name)
        if claimed:
            self.stdout.write(f"Claimed {claimed} comment{'s' if claimed != 1 else ''} from before this account existed.")
```

- [ ] **Step 8: Update the older tests**

`tests/test_views.py`:
- Delete `test_update_tracking_htmx_returns_partial`.
- Replace `test_set_status_keeps_notes`:

```python
def test_set_status_keeps_comments(client):
    listing = good_listing(notes="keep me")
    response = client.post(f"/listing/{listing.pk}/status/", {"status": "interested"}, HTTP_HX_REQUEST="true")
    assert response.status_code == 200
    assert status_of(listing) == Status.INTERESTED
    assert list(listing.comments.values_list("body", flat=True)) == ["keep me"]
```

`tests/test_tracking_controls.py`: delete `test_notes_save_while_typing_without_a_save_button` and `test_saving_returns_the_indicator` (comments are covered in `tests/test_comments.py`).

`tests/test_analyst.py`: in `test_compact_facts_describe_unknowns_and_history`, change `assert facts["notes"] == "Loved the kitchen"` to `assert facts["comments"][0]["text"] == "Loved the kitchen"`.

`tests/test_unit_duplicates.py` (add `from listings.models import Comment`):
- In `test_sweep_keeps_the_listing_with_notes_and_takes_the_unit_address`, replace `bare.notes = "High ceilings."` / `bare.save()` with `Comment.objects.create(listing=bare, group=home_group(), body="High ceilings.")`. Change the assertion to `assert listing.pk == bare.pk and status_of(listing) == Status.INTERESTED` followed by `assert list(listing.comments.values_list("body", flat=True)) == ["High ceilings."]`.
- In `test_sweep_merges_notes_and_status_when_both_were_touched`, replace the two `update(...)` lines with:

```python
    Comment.objects.create(listing=bare, group=home_group(), body="High ceilings.")
    Comment.objects.create(listing=unit, group=home_group(), body="Toured Tuesday.")
    Listing.objects.filter(pk=unit.pk).update(overrides={"has_ac": True})
```

  and replace `assert listing.notes == "Toured Tuesday.\n\nHigh ceilings."` with `assert sorted(listing.comments.values_list("body", flat=True)) == ["High ceilings.", "Toured Tuesday."]`.

Run: `grep -rn "notes" listings tests --include='*.py' --include='*.html' | grep -v "migrations/"`
Expected: only `make_listing(notes=...)` calls, the helper itself, and prose (docstrings and the analyst SYSTEM prompt). Change the prompt's "Their own notes and statuses" to "Their own comments and statuses". Task 14 rewrites the prompt anyway.

- [ ] **Step 9: Run the full suite**

Run: `uv run pytest -q` → all pass.

- [ ] **Step 10: Check it in a browser**

Log in as two people in the same group, in two browsers, and open the same listing. Post from one. The other's thread should show it within 30 seconds. While editing a comment, the poll must not wipe the edit box: wait 40 seconds, then save. Check that Delete asks for confirmation, that the Feed shows "Name: text", and that there are no console errors at desktop and phone width. Delete your test comments.

- [ ] **Step 11: Update CLAUDE.md and commit**

Extend the `listings/collab.py` bullet in `CLAUDE.md`: "…and `Comment` threads (author-only edit/delete in `collab_views.py`; the thread polls every 30s but not while a comment is being edited; each comment has a Feed item that follows edits and deletes)." In the Trends bullet, change "notes" to "comments". In **Current state → Production**, add: "After deploying the accounts stack, `create_owner` claims the owner's migrated notes (now comments) if the account didn't exist when migrating."

```bash
git add accounts listings tests CLAUDE.md
git rm listings/templates/listings/_tracking.html
git commit -m "feat: notes become a comment thread with authors, edits and Feed items"
git push -u origin accounts-5-comments
gh pr create --base accounts-4-group-feed --title "[Accounts 5/10] Comments" --body "<stack list, this PR marked>"
```

---
# PR 6 — `[Accounts 6/10] Votes`

Branch: `git checkout -b accounts-6-votes` (from `accounts-5-comments`)

### Task 10: 👍/👎 per person, shown everywhere a listing appears

**Files:**
- Modify: `listings/models.py`, `listings/collab.py`, `listings/collab_views.py`, `listings/urls.py`, `listings/views.py` (`_pin_style`), `listings/merge.py`, `listings/admin.py`, `accounts/groups.py`, templates `_card.html`, `_table.html`, `detail.html`, `base.html` (CSS)
- Create: `listings/migrations/0015_vote.py` (generated), `listings/templates/listings/_votes.html`
- Test: `tests/test_votes.py`

**Interfaces:**
- Consumes: `collab.decorate` (Task 5), `feed.record_activity` (Task 6).
- Produces:
  - `listings.models.Vote(listing FK related_name="votes", group FK related_name="votes", user FK related_name="votes", value ∈ {1, -1}, updated_at)`, unique `(listing, user)`, with `Vote.Value.UP` / `Vote.Value.DOWN`.
  - `collab.set_vote(listing, group, user, value_or_None) -> Vote | None`.
  - `collab.vote_mark(listing) -> str`.
  - `decorate` also sets `.group_votes` (a list of Vote), `.up_count`, `.down_count`, `.my_vote` (1, -1 or 0) and `.vote_names` (str).
  - URL `vote` at `listing/<pk>/vote/`.
  - `move_to_group` deletes the person's votes.

- [ ] **Step 1: Write the failing tests**

`tests/test_votes.py`:

```python
from decimal import Decimal

import pytest
from django.test import Client

from accounts.groups import move_to_group, new_group
from listings.collab import set_vote
from listings.merge import merge
from listings.models import Vote
from tests.helpers import home_group, make_listing, make_user

pytestmark = pytest.mark.django_db
UP, DOWN = Vote.Value.UP, Vote.Value.DOWN


def good_listing(key="good", **extra):
    return make_listing(address_key=key, price=3000, beds=2, baths=Decimal("2"), parking_spaces=2, property_type="condo",
                        latitude=45.52, longitude=-122.68, **extra)


def vote(browser, listing, value):
    return browser.post(f"/listing/{listing.pk}/vote/", {"value": value}, HTTP_HX_REQUEST="true").content.decode()


def test_voting_and_clicking_again_to_clear(client):
    listing = good_listing()
    html = vote(client, listing, "up")
    assert '<button type="submit" name="value" value="up" class="vote mine" aria-pressed="true"' in html
    assert Vote.objects.get().value == UP
    vote(client, listing, "up")
    assert not Vote.objects.exists()


def test_switching_keeps_one_vote(client):
    listing = good_listing()
    vote(client, listing, "up")
    vote(client, listing, "down")
    assert list(Vote.objects.values_list("value", flat=True)) == [DOWN]


def test_invalid_vote_is_refused(client):
    assert client.post(f"/listing/{good_listing().pk}/vote/", {"value": "meh"}).status_code == 400


def test_each_members_vote_shows_on_cards_table_and_listing_page(client, member_client):
    listing = good_listing()
    vote(client, listing, "up")
    vote(member_client, listing, "down")
    for url in ("/", "/?view=list", f"/listing/{listing.pk}/"):
        assert '<span class="muted vote-who">Sam 👍 · Alex 👎</span>' in client.get(url).content.decode(), url


def test_pins_show_how_the_group_voted(client, member_client):
    listing = good_listing()
    vote(client, listing, "up")
    vote(member_client, listing, "up")
    assert client.get("/").context["map_points"][0]["label"] == "👍 $3k"
    vote(member_client, listing, "down")
    assert client.get("/").context["map_points"][0]["label"] == "👍👎 $3k"


def test_other_groups_do_not_see_our_votes(client):
    listing = good_listing()
    vote(client, listing, "up")
    pat = Client()
    pat.force_login(make_user("pat@example.com", "Pat", group=new_group("Pat's search")))
    assert "Sam 👍" not in pat.get(f"/listing/{listing.pk}/").content.decode()


def test_a_vote_shows_in_the_group_feed(client, member_client):
    vote(member_client, good_listing(), "up")
    assert "Alex voted 👍" in client.get("/feed/").content.decode()


def test_leaving_a_group_removes_your_votes(member):
    set_vote(good_listing(), home_group(), member, UP)
    move_to_group(member, new_group("Alex's search"))
    assert not Vote.objects.exists()


def test_merge_keeps_one_vote_per_person(owner, member):
    keep, drop = good_listing("keep"), good_listing("drop")
    set_vote(keep, home_group(), owner, UP)
    set_vote(drop, home_group(), owner, DOWN)
    set_vote(drop, home_group(), member, UP)
    merge(keep, drop)
    assert sorted(Vote.objects.values_list("user__email", "value", "listing")) == [
        ("alex@example.com", UP, keep.pk), ("sam@example.com", UP, keep.pk)]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_votes.py -q`
Expected: FAIL with `ImportError: cannot import name 'set_vote'`.

- [ ] **Step 3: Model and migration**

In `listings/models.py`, after `Comment`:

```python
class Vote(models.Model):
    """One person's 👍 or 👎 on a listing, seen by their group."""

    class Value(models.IntegerChoices):
        UP = 1, "👍"
        DOWN = -1, "👎"

    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="votes")
    group = models.ForeignKey("accounts.SearchGroup", on_delete=models.CASCADE, related_name="votes")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="votes")
    value = models.SmallIntegerField(choices=Value.choices)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["listing", "user"], name="unique_listing_user_vote")]
```

Run: `uv run python manage.py makemigrations listings --name vote` → `0015_vote.py`.

- [ ] **Step 4: collab**

In `listings/collab.py`, import `Vote`. At the end of `decorate`, before `return listings`, add the vote attributes. The final `decorate` reads:

```python
def decorate(listings, group, user=None):
    """Attach the group's view of each listing for templates: .state, .group_status, .group_status_label,
    and votes (.group_votes, .up_count, .down_count, .my_vote, .vote_names)."""
    listings = list(listings)
    states = {
        state.listing_id: state
        for state in ListingState.objects.filter(group=group, listing__in=listings).select_related("status_by__profile")
    }
    votes = {}
    for vote in Vote.objects.filter(group=group, listing__in=listings).select_related("user__profile").order_by("pk"):
        votes.setdefault(vote.listing_id, []).append(vote)
    user_id = getattr(user, "pk", None)
    for listing in listings:
        state = states.get(listing.pk)
        listing.state = state
        listing.group_status = state.status if state else Status.NEW
        listing.group_status_label = STATUS_LABELS[listing.group_status]
        group_votes = votes.get(listing.pk, [])
        listing.group_votes = group_votes
        listing.up_count = sum(vote.value == Vote.Value.UP for vote in group_votes)
        listing.down_count = sum(vote.value == Vote.Value.DOWN for vote in group_votes)
        listing.my_vote = next((vote.value for vote in group_votes if vote.user_id == user_id), 0)
        listing.vote_names = " · ".join(f"{display_name(vote.user)} {vote.get_value_display()}" for vote in group_votes)
    return listings


def set_vote(listing, group, user, value):
    """Sets the person's 👍/👎 (None clears it) and tells the group."""
    if value is None:
        Vote.objects.filter(listing=listing, user=user).delete()
        return None
    vote, _ = Vote.objects.update_or_create(listing=listing, user=user, defaults={"group": group, "value": value})
    feed.record_activity(listing, group, user, FeedEvent.Kind.VOTE, f"{display_name(user)} voted {vote.get_value_display()}")
    return vote


def vote_mark(listing):
    """A decorated listing's votes in a map pin: 👍 when all votes are up, 👎 when all are down, 👍👎 when split."""
    if listing.up_count and listing.down_count:
        return "👍👎"
    return "👍" if listing.up_count else "👎" if listing.down_count else ""
```

- [ ] **Step 5: View, URL, pins**

`listings/collab_views.py`: add `from django.http import HttpResponseBadRequest` and import `Vote`:

```python
VOTE_VALUES = {"up": Vote.Value.UP, "down": Vote.Value.DOWN}


@require_POST
def vote(request, pk):
    """👍 or 👎 from the person; clicking their current vote again clears it."""
    listing = get_object_or_404(Listing, pk=pk)
    value = VOTE_VALUES.get(request.POST.get("value"))
    if value is None:
        return HttpResponseBadRequest("invalid vote")
    current = Vote.objects.filter(listing=listing, user=request.user).values_list("value", flat=True).first()
    collab.set_vote(listing, request.group, request.user, None if current == value else value)
    collab.decorate([listing], request.group, request.user)
    if request.headers.get("HX-Request"):
        return render(request, "listings/_votes.html", {"listing": listing})
    return redirect(listing)
```

`listings/urls.py`: `path("listing/<int:pk>/vote/", collab_views.vote, name="vote"),`.

`listings/views.py`, `_pin_style`:

```python
def _pin_style(listing):
    mark, status_class = PIN_MARKS.get(listing.group_status, ("", ""))
    votes = collab.vote_mark(listing)
    drop = listing.price_drop
    special = bool(listing.special_offer)
    classes = ["pin", drop and "pin-drop", special and "pin-special", status_class, not listing.is_active and "pin-off"]
    return {
        "label": f"{mark}{votes + ' ' if votes else ''}{'↓' if drop else ''}{'★' if special else ''}{_short_price(listing.price)}",
        "classes": " ".join(c for c in classes if c),
    }
```

- [ ] **Step 6: Template and placement**

`listings/templates/listings/_votes.html`:

```html
{# Each member's 👍/👎 on a listing. Clicking your current vote again clears it; the form swaps itself. #}
<form class="votes" id="votes-{{ listing.pk }}" method="post" action="{% url 'vote' listing.pk %}"
      hx-post="{% url 'vote' listing.pk %}" hx-target="this" hx-swap="outerHTML">
  {% csrf_token %}
  <button type="submit" name="value" value="up" class="vote{% if listing.my_vote == 1 %} mine{% endif %}" aria-pressed="{% if listing.my_vote == 1 %}true{% else %}false{% endif %}" title="I like it">👍{% if listing.up_count %} {{ listing.up_count }}{% endif %}</button>
  <button type="submit" name="value" value="down" class="vote{% if listing.my_vote == -1 %} mine{% endif %}" aria-pressed="{% if listing.my_vote == -1 %}true{% else %}false{% endif %}" title="Not for me">👎{% if listing.down_count %} {{ listing.down_count }}{% endif %}</button>
  {% if listing.vote_names %}<span class="muted vote-who">{{ listing.vote_names }}</span>{% endif %}
</form>
```

- `_card.html`: add `{% include "listings/_votes.html" %}` on the line before `{% include "listings/_status.html" %}`.
- `_table.html`: change the status cell to `<td>{% include "listings/_status.html" %}{% include "listings/_votes.html" %}</td>`.
- `detail.html`: change the status panel to `<div class="panel"><h3>Our status</h3>{% include "listings/_status_pills.html" %}{% include "listings/_votes.html" %}</div>`.

`base.html` CSS:

```css
    .votes { display:flex; flex-wrap:wrap; align-items:center; gap:6px; margin:0; }
    .vote { font-size:13px; padding:2px 9px; border:1px solid var(--line); border-radius:999px; background:var(--card); cursor:pointer; }
    .vote.mine { border-color:var(--accent); background:#eef6f2; font-weight:700; }
    .vote-who { font-size:12px; }
```

- [ ] **Step 7: Leaving a group, merging, admin**

`accounts/groups.py`, in `move_to_group`, after the early return and before changing the group:

```python
    from listings.models import Vote

    Vote.objects.filter(user=user).delete()  # votes belong to the group being left
```

`listings/merge.py`: import `Vote`. In `touched`, add `or listing.votes.exists()`. After the `Comment…update` line in `merge`, add `_merge_votes(keep, drop)`:

```python
def _merge_votes(keep, drop):
    """One vote per person: their vote on the survivor wins."""
    for vote in drop.votes.all():
        if keep.votes.filter(user_id=vote.user_id).exists():
            vote.delete()
        else:
            vote.listing = keep
            vote.save(update_fields=["listing"])
```

`listings/admin.py`: register `Vote` with `list_display = ("listing", "group", "user", "value", "updated_at")`.

- [ ] **Step 8: Run the tests and the suite**

Run: `uv run pytest tests/test_votes.py -q` → 10 passed.
Run: `uv run pytest -q` → all pass.

- [ ] **Step 9: Commit**

```bash
git add listings accounts tests
git commit -m "feat: 👍/👎 votes per person on cards, pins, the table and the listing page"
```

### Task 11: Vote filters and votes in the Trends prompt

**Files:**
- Modify: `listings/forms.py`, `listings/filters.py`, `listings/analyst.py`, `listings/templates/listings/_filter_bar.html`, `listings/templates/listings/list.html`, `CLAUDE.md`
- Test: `tests/test_votes.py` (append)

**Interfaces:**
- Produces: a filter-form field `votes` with choices `any|everyone_likes|someone_likes|disagree|unvoted` (default `any`), and `compact_facts(...)["votes"] -> {name: "like"|"dislike"}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_votes.py`:

```python
from listings import analyst
from listings.filters import apply_filters
from listings.forms import ListingFilterForm, default_filter_data
from listings.models import Listing


def filtered(choice):
    form = ListingFilterForm(default_filter_data() | {"votes": choice})
    assert form.is_valid(), form.errors
    return set(apply_filters(Listing.objects.all(), form.cleaned_data, home_group()).values_list("address_key", flat=True))


def test_vote_filters(owner, member):
    group = home_group()
    both, one, split, nope = good_listing("both"), good_listing("one"), good_listing("split"), good_listing("nope")
    good_listing("none")
    set_vote(both, group, owner, UP)
    set_vote(both, group, member, UP)
    set_vote(one, group, owner, UP)
    set_vote(split, group, owner, UP)
    set_vote(split, group, member, DOWN)
    set_vote(nope, group, member, DOWN)
    assert filtered("everyone_likes") == {"both"}
    assert filtered("someone_likes") == {"both", "one", "split"}
    assert filtered("disagree") == {"split"}
    assert filtered("unvoted") == {"none"}
    assert filtered("any") == {"both", "one", "split", "nope", "none"}


def test_vote_filter_is_in_the_more_filters_drawer(client):
    content = client.get("/").content.decode()
    assert '<select name="votes" id="id_votes">' in content
    assert '"votes"' in content.split("DRAWER_FIELDS")[1].split("]")[0]


def test_votes_reach_the_analyst(owner, member):
    listing = good_listing()
    set_vote(listing, home_group(), owner, UP)
    set_vote(listing, home_group(), member, DOWN)
    facts = analyst.compact_facts(analyst._prepare([listing], home_group())[0])
    assert facts["votes"] == {"Sam": "like", "Alex": "dislike"}
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_votes.py -q -k "filter or analyst"`
Expected: FAIL (the `votes` field is unknown and ignored, so every listing matches; the analyst facts have no `votes` key).

- [ ] **Step 3: Implement**

`listings/forms.py`:

```python
VOTE_FILTER_CHOICES = [("any", "Any"), ("everyone_likes", "Everyone 👍"), ("someone_likes", "Someone 👍"),
                       ("disagree", "We disagree"), ("unvoted", "No votes yet")]
```

Add `"votes": "any",` to `default_filter_data()`. In `ListingFilterForm`, after `statuses`, add:

```python
    votes = forms.ChoiceField(required=False, choices=VOTE_FILTER_CHOICES, label="Votes")
```

`listings/filters.py`: add imports `from django.db.models import Count, IntegerField, OuterRef, Subquery` and `from django.db.models.functions import Coalesce` (merge them into the existing import lines), plus `from .models import Vote`. In `apply_filters`, after the statuses block:

```python
    if data.get("votes") and data["votes"] != "any":
        queryset = _filter_votes(queryset, data["votes"], group)
```

and add:

```python
def _vote_count(group, value):
    # A subquery, not Count() over a join: joins would multiply with the price-history join below.
    votes = (Vote.objects.filter(listing=OuterRef("pk"), group=group, value=value)
             .order_by().values("listing").annotate(n=Count("pk")).values("n"))
    return Coalesce(Subquery(votes, output_field=IntegerField()), 0)


def _filter_votes(queryset, choice, group):
    queryset = queryset.annotate(up_votes=_vote_count(group, Vote.Value.UP), down_votes=_vote_count(group, Vote.Value.DOWN))
    if choice == "everyone_likes":
        return queryset.filter(up_votes=group.members.count(), up_votes__gt=0)
    if choice == "someone_likes":
        return queryset.filter(up_votes__gt=0)
    if choice == "disagree":
        return queryset.filter(up_votes__gt=0, down_votes__gt=0)
    if choice == "unvoted":
        return queryset.filter(up_votes=0, down_votes=0)
    return queryset
```

`_filter_bar.html`: in the drawer section with "Our status", after the statuses `check-list` div, add:

```html
          <div class="panel-title">Our votes</div>
          <label class="field">Votes {{ form.votes }}</label>
```

`list.html`: add `"votes"` to `DRAWER_FIELDS` (after `"statuses"`).

`listings/analyst.py`: import `display_name` from `accounts.models` and `Vote` from `.models`. In `compact_facts`, after `"status"`:

```python
        "votes": {display_name(vote.user): "like" if vote.value == Vote.Value.UP else "dislike" for vote in listing.group_votes},
```

- [ ] **Step 4: Run the tests and the suite**

Run: `uv run pytest -q` → all pass.

- [ ] **Step 5: Check it in a browser**

Vote from two accounts in the same group. Under More filters, try each Votes option; the chip badge counts it when it isn't "Any". Check the pins, then check phone width (the votes row must not overflow cards). No console errors. Clear your test votes.

- [ ] **Step 6: Update CLAUDE.md and commit**

Extend the `collab.py` bullet: "…and `Vote` (one 👍/👎 per person per listing, cleared by clicking again; deleted when the person leaves the group). The Votes filter (`everyone_likes`, `someone_likes`, `disagree`, `unvoted`) counts votes with subqueries so it composes with the price-history join." In `listings/forms.py`'s bullet, add "Votes: Any" to the defaults.

```bash
git add listings tests CLAUDE.md
git commit -m "feat: vote filters, and votes in the Trends analysis"
git push -u origin accounts-6-votes
gh pr create --base accounts-5-comments --title "[Accounts 6/10] Votes" --body "<stack list, this PR marked>"
```

---

# PR 7 — `[Accounts 7/10] Group default filters`

Branch: `git checkout -b accounts-7-default-filters` (from `accounts-6-votes`)

### Task 12: "Save as our defaults"

**Files:**
- Modify: `accounts/models.py`, `listings/forms.py`, `listings/views.py`, `listings/urls.py`, `listings/analyst.py`, `listings/templates/listings/_filter_bar.html`, `listings/templates/listings/list.html`, `base.html` (CSS), `CLAUDE.md`
- Create: `accounts/migrations/0004_searchgroup_default_filters.py` (generated), `accounts/migrations/0005_owners_default_filters.py`, `listings/templates/listings/_save_defaults.html`
- Test: `tests/test_default_filters.py`

**Interfaces:**
- Produces:
  - `SearchGroup.default_filters` (JSON, `{}` means app defaults).
  - `forms.app_default_filters() -> dict`; `forms.default_filter_data(group=None) -> dict`, which returns the group's saved values over the app defaults.
  - URL `save_default_filters` (POST `/filters/defaults/`).
  - `analyst.candidates(group)` uses the group's defaults.

- [ ] **Step 1: Write the failing tests**

`tests/test_default_filters.py`:

```python
import json
from decimal import Decimal

import pytest
from django.conf import settings
from django.test import Client

from accounts.groups import new_group
from listings import analyst
from listings.forms import app_default_filters, default_filter_data
from tests.helpers import home_group, make_listing, make_user

pytestmark = pytest.mark.django_db


def good(key, **extra):
    fields = dict(address_key=key, price=3000, beds=2, baths=Decimal("2"), parking_spaces=2, property_type="condo")
    fields.update(extra)
    return make_listing(**fields)


def keys(browser, url="/"):
    return {listing.address_key for listing in browser.get(url).context["listings"]}


def test_new_groups_start_from_the_app_defaults():
    assert default_filter_data(new_group("Fresh")) == app_default_filters()


def test_the_owners_group_starts_from_the_old_hard_coded_defaults():
    saved = home_group().default_filters
    assert (saved["min_beds"], saved["min_baths"], saved["min_parking"]) == ("2", "2", "2")
    assert saved["min_price"] == str(settings.DEFAULT_MIN_PRICE) and "apartment" not in saved["types"]
    assert "rejected" not in saved["statuses"]


def test_save_as_our_defaults_stores_the_filter_bar(client):
    response = client.post("/filters/defaults/", {
        "min_beds": "3", "min_baths": "", "min_price": "2500", "max_price": "8000", "types": ["condo", "townhome"],
        "statuses": ["new", "interested"], "wd": "yes", "ac": "any", "outdoor": "any", "furnished": "any",
        "votes": "any", "sort": "newest", "north": "45.6", "south": "45.5", "east": "-122.6", "west": "-122.7",
    }, HTTP_HX_REQUEST="true")
    assert '<button type="button" id="save-defaults"' in response.content.decode()
    assert "Saved as our defaults ✓" in response.content.decode()
    saved = home_group().default_filters
    assert saved["min_beds"] == "3" and saved["types"] == ["condo", "townhome"] and saved["sort"] == "newest"
    assert saved["parking_unknown"] == "" and "north" not in saved


def test_the_list_page_starts_from_the_groups_defaults(client):
    good("two")
    good("three", beds=3)
    group = home_group()
    group.default_filters = app_default_filters() | {"min_beds": "3"}
    group.save()
    assert keys(client) == {"three"}
    defaults = json.loads(client.get("/").content.decode().split('id="filter-defaults" type="application/json">')[1].split("</script>")[0])
    assert defaults["min_beds"] == "3"


def test_each_group_keeps_its_own_defaults(client):
    good("two")
    good("three", beds=3)
    group = home_group()
    group.default_filters = app_default_filters() | {"min_beds": "3"}
    group.save()
    pat = Client()
    pat.force_login(make_user("pat@example.com", "Pat", group=new_group("Pat's search")))
    assert keys(pat) == {"two", "three"}


def test_the_filter_bar_has_the_button(member_client):
    assert '<button type="button" id="save-defaults"' in member_client.get("/").content.decode()


def test_trends_candidates_use_the_groups_defaults():
    cheap = good("cheap", price=1500)
    group = home_group()
    group.default_filters = app_default_filters() | {"min_price": "1000"}
    group.save()
    assert cheap.pk in {listing.pk for listing in analyst.candidates(group)}
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_default_filters.py -q`
Expected: FAIL with `ImportError: cannot import name 'app_default_filters'`.

- [ ] **Step 3: Model and migrations**

`accounts/models.py`, in `SearchGroup`:

```python
    # The filter bar a visit starts from ("Save as our defaults"). Empty means the app defaults.
    default_filters = models.JSONField(default=dict, blank=True)
```

Run: `uv run python manage.py makemigrations accounts --name searchgroup_default_filters` → `0004_searchgroup_default_filters.py`.

`accounts/migrations/0005_owners_default_filters.py`:

```python
from django.conf import settings
from django.db import migrations


def forwards(apps, schema_editor):
    """The filters that were hard-coded before groups existed become the owners' saved defaults, so a
    later change to the app defaults doesn't move theirs."""
    SearchGroup = apps.get_model("accounts", "SearchGroup")
    group = SearchGroup.objects.order_by("pk").first()
    if group is None or group.default_filters:
        return
    group.default_filters = {
        "min_beds": "2", "min_baths": "2", "min_parking": "2", "parking_unknown": "on",
        "min_price": str(settings.DEFAULT_MIN_PRICE), "max_price": str(settings.DEFAULT_MAX_PRICE),
        "types": ["condo", "townhome", "house", "other", "unknown"],
        "statuses": ["new", "interested", "toured", "applied"],
        "wd": "yes_or_unknown", "ac": "yes_or_unknown", "outdoor": "yes_or_unknown", "furnished": "any",
        "votes": "any", "sort": "price",
    }
    group.save(update_fields=["default_filters"])


class Migration(migrations.Migration):
    dependencies = [("accounts", "0004_searchgroup_default_filters")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
```

- [ ] **Step 4: Forms, view, URL, analyst**

`listings/forms.py`: rename `default_filter_data` to `app_default_filters` (same body, docstring "The filters a new group starts from."). Then add:

```python
def default_filter_data(group=None):
    """The group's saved defaults over the app defaults (so a filter added later still has a value)."""
    return {**app_default_filters(), **(group.default_filters if group else {})}
```

`listings/views.py`:
- In `listing_list`, use `default_filter_data(request.group)` in both places (the form fallback and `"filter_defaults"`).
- Add the view:

```python
MULTI_VALUE_FILTERS = ("cities", "quadrants", "sources", "types", "statuses")
AREA_FILTERS = ("north", "south", "east", "west")  # "Search this area" isn't a default


@require_POST
def save_default_filters(request):
    """'Save as our defaults': the filter bar as it is now becomes where the group's visits start."""
    form = ListingFilterForm(request.POST)
    if not form.is_valid():
        return HttpResponseBadRequest("invalid filters")
    request.group.default_filters = {
        name: request.POST.getlist(name) if name in MULTI_VALUE_FILTERS else request.POST.get(name, "")
        for name in form.fields
        if name not in AREA_FILTERS
    }
    request.group.save(update_fields=["default_filters"])
    return render(request, "listings/_save_defaults.html", {"saved": True})
```

`listings/urls.py`: `path("filters/defaults/", views.save_default_filters, name="save_default_filters"),`.

`listings/analyst.py` `candidates`: `form = ListingFilterForm(default_filter_data(group))`.

- [ ] **Step 5: Template and script**

`listings/templates/listings/_save_defaults.html`:

```html
{# Saves the filter bar as the group's defaults. Inside the filters form, so HTMX posts its values with it. #}
<button type="button" id="save-defaults" class="save-defaults" hx-post="{% url 'save_default_filters' %}" hx-include="#filters"
        hx-target="this" hx-swap="outerHTML"
        title="Visits and Reset start from these filters, for everyone in {{ request.group.name }}">{% if saved %}Saved as our defaults ✓{% else %}Save as our defaults{% endif %}</button>
```

In `_filter_bar.html`, directly after the Reset `<a class="reset" …>` link, add `{% include "listings/_save_defaults.html" %}`.

In `list.html`, at the end of the filter-bar script (after `refreshFilterBar();`):

```javascript
  // A saved-defaults tick is stale once the filters change again.
  filters.addEventListener("change", () => {
    const button = document.getElementById("save-defaults");
    if (button) button.textContent = "Save as our defaults";
  });
```

`base.html` CSS: `.save-defaults { font-size:14px; border:0; background:none; color:var(--accent); cursor:pointer; padding:0 4px; white-space:nowrap; }`.

- [ ] **Step 6: Run the tests and the suite**

Run: `uv run pytest -q`
Expected: all pass. If a test sets `settings.DEFAULT_MIN_PRICE` and expects the list page to follow it, change it to set `home_group().default_filters` instead. The owners' group now has saved defaults.

- [ ] **Step 7: Check it in a browser**

Change a few filters, click "Save as our defaults", then click Reset. The saved filters should come back. Open a second account in another group and confirm its defaults didn't change. Check the chip badge count and phone width (the button must stay inside the scrolling filter bar). Restore your group's defaults afterwards.

- [ ] **Step 8: Update CLAUDE.md and commit**

Change the `listings/forms.py` bullet to: "`listings/forms.py` holds `ListingFilterForm`. `app_default_filters()` (2 bd / 2 ba / 2 parking, a $2,000 minimum, apartments and rejected hidden, Votes: Any) is where a new group starts; `default_filter_data(group)` lays the group's saved defaults (`SearchGroup.default_filters`, set by "Save as our defaults") over them. The owners' group got the old hard-coded defaults as its saved copy."

```bash
git add accounts listings tests CLAUDE.md
git commit -m "feat: each group saves its own default filters"
git push -u origin accounts-7-default-filters
gh pr create --base accounts-6-votes --title "[Accounts 7/10] Group default filters" --body "<stack list, this PR marked>"
```

---
# PR 8 — `[Accounts 8/10] Per-group Trends`

Branch: `git checkout -b accounts-8-group-trends` (from `accounts-7-default-filters`)

### Task 13: Reports and priorities belong to a group

**Files:**
- Modify: `listings/models.py`, `listings/admin.py`, `listings/views.py`, `listings/analyst.py`, `tests/test_analyst.py`, `tests/test_trends_page.py`, `tests/test_trend_models.py`
- Create: `listings/migrations/0016_trends_per_group.py` (generated), `listings/migrations/0017_trends_to_owners_group.py`
- Test: `tests/test_trends_migration.py`

**Interfaces:**
- Produces: `TrendReport.group` (FK, nullable in the schema, always set by code), `SearchPriorities.group` (OneToOne, related_name="priorities"), and `SearchPriorities.get(group)`.

- [ ] **Step 1: Models**

In `listings/models.py`, add to `TrendReport`:

```python
    group = models.ForeignKey("accounts.SearchGroup", on_delete=models.CASCADE, null=True, blank=True, related_name="trend_reports")
```

Replace `SearchPriorities` with:

```python
class SearchPriorities(models.Model):
    """What a group is looking for, in its own words. Read by its Trends analysis."""

    group = models.OneToOneField("accounts.SearchGroup", on_delete=models.CASCADE, null=True, blank=True, related_name="priorities")
    text = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "search priorities"

    @classmethod
    def get(cls, group):
        return cls.objects.get_or_create(group=group)[0]
```

Run: `uv run python manage.py makemigrations listings --name trends_per_group` → `0016_trends_per_group.py`.

In `listings/admin.py`, add `"group"` to `TrendReportAdmin.list_display` and `list_filter`, and set `SearchPrioritiesAdmin.list_display = ("group", "updated_at")`.

Update the callers of `SearchPriorities.get()` so the suite stays green:
- `listings/views.py`: in `trends_page` and `trends_priorities`, change `SearchPriorities.get()` to `SearchPriorities.get(request.group)`.
- `listings/analyst.py` `_context`: `SearchPriorities.get(owners_group())`. Task 14 passes the report's group instead.
- Tests:

```bash
sed -i '' 's/SearchPriorities.objects.create(pk=1, /SearchPriorities.objects.create(group=home_group(), /' tests/test_analyst.py tests/test_trends_page.py
sed -i '' 's/SearchPriorities.get()/SearchPriorities.get(home_group())/' tests/test_trends_page.py
```

  In `tests/test_trend_models.py`, add `from accounts.groups import new_group` and `from tests.helpers import home_group`. Replace the first test with:

```python
def test_search_priorities_are_one_row_per_group():
    first = SearchPriorities.get(home_group())
    first.text = "Quiet, near a park"
    first.save()
    assert SearchPriorities.get(home_group()).text == "Quiet, near a park"
    assert SearchPriorities.get(new_group("Pat's search")).text == ""
    assert SearchPriorities.objects.count() == 2
```

- [ ] **Step 2: Write the failing migration test**

`tests/test_trends_migration.py`:

```python
import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

BEFORE = [("listings", "0016_trends_per_group")]
AFTER = [("listings", "0017_trends_to_owners_group")]


def migrate(targets):
    MigrationExecutor(connection).migrate(targets)
    return MigrationExecutor(connection).loader.project_state(targets).apps


@pytest.mark.django_db(transaction=True)
def test_existing_reports_and_priorities_move_to_the_owners_group():
    apps = migrate(BEFORE)
    TrendReport = apps.get_model("listings", "TrendReport")
    SearchPriorities = apps.get_model("listings", "SearchPriorities")
    SearchGroup = apps.get_model("accounts", "SearchGroup")
    owners = SearchGroup.objects.order_by("pk").first() or SearchGroup.objects.create(name="Our search")
    report = TrendReport.objects.create(status="done")
    SearchPriorities.objects.create(pk=1, text="Near a park")
    try:
        apps = migrate(AFTER)
        assert apps.get_model("listings", "TrendReport").objects.get(pk=report.pk).group_id == owners.pk
        assert apps.get_model("listings", "SearchPriorities").objects.get().group_id == owners.pk
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_trends_migration.py -q`
Expected: FAIL with `NodeNotFoundError` for `0017_trends_to_owners_group`.

- [ ] **Step 4: Write the data migration**

`listings/migrations/0017_trends_to_owners_group.py`:

```python
from django.db import migrations


def forwards(apps, schema_editor):
    """Reports and priorities from before groups existed are the owners'."""
    TrendReport = apps.get_model("listings", "TrendReport")
    SearchPriorities = apps.get_model("listings", "SearchPriorities")
    SearchGroup = apps.get_model("accounts", "SearchGroup")
    group = SearchGroup.objects.order_by("pk").first()
    if group is None:
        return
    TrendReport.objects.filter(group__isnull=True).update(group=group)
    row = SearchPriorities.objects.filter(group__isnull=True).order_by("pk").first()
    if row and not SearchPriorities.objects.filter(group=group).exists():
        row.group = group
        row.save(update_fields=["group"])


class Migration(migrations.Migration):
    dependencies = [("listings", "0016_trends_per_group"), ("accounts", "0002_owners_group")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
```

- [ ] **Step 5: Run the test**

Run: `uv run pytest tests/test_trends_migration.py -q` → 1 passed.
Run: `uv run pytest -q` → all pass.

- [ ] **Step 6: Commit**

```bash
git add listings tests
git commit -m "feat: Trends reports and priorities belong to a group"
```

### Task 14: The analyst and the Trends page per group

**Files:**
- Modify: `listings/analyst.py`, `listings/views.py`, `tests/test_analyst.py`, `tests/test_trends_page.py`, `tests/test_trend_models.py` (the `TrendReport` sed below), `CLAUDE.md`
- Test: `tests/test_group_trends.py`

**Interfaces:**
- Consumes: `TrendReport.group`, `SearchPriorities.get(group)` (Task 13), `default_filter_data(group)` (Task 12), `compact_facts` votes and comments (Tasks 9 and 11).
- Produces:
  - `analyst.run_report(group=None, trigger=MANUAL, client=None, report=None)`: the group comes from `report.group` when a report is passed.
  - `analyst.start_report(group, trigger) -> bool`, `analyst.start_reports(groups, trigger) -> bool`.
  - `analyst._launch(groups, trigger, first_report)`.
  - `analyst.is_running(group=None) -> bool`, `analyst.manual_runs_left(group) -> int`, `analyst.due_today() -> list[SearchGroup]`.
  - `analyst.run_daily_if_due() -> bool` (unchanged signature).

- [ ] **Step 1: Write the failing tests**

`tests/test_group_trends.py`:

```python
from decimal import Decimal

import pytest
from django.test import Client

from accounts.groups import new_group
from listings import analyst
from listings.models import PropertyType, SearchPriorities, TrendReport
from tests.helpers import home_group, make_listing, make_user
from tests.test_analyst import FakeClient, final, message, pick

pytestmark = pytest.mark.django_db
DONE, AUTO = TrendReport.Status.DONE, TrendReport.Trigger.AUTO


def candidate(key, **extra):
    fields = dict(address_key=key, address=f"{key} St", street=f"{key} St", city="Portland", price=3000, beds=2,
                  baths=Decimal("2"), parking_spaces=2, property_type=PropertyType.CONDO, has_washer_dryer=True,
                  has_ac=True, has_outdoor_space=True)
    fields.update(extra)
    return make_listing(**fields)


def test_each_group_gets_its_own_report_prompt_and_history():
    pat_group = new_group("Pat's search")
    SearchPriorities.objects.create(group=home_group(), text="Near a park")
    SearchPriorities.objects.create(group=pat_group, text="Quiet street")
    listing = candidate("a")
    client = FakeClient(message({"shortlist": [{"id": listing.pk, "reason": ""}]}), message(final([pick(listing.pk)])))
    report = analyst.run_report(pat_group, client=client)
    prompt = client.calls[0]["messages"][0]["content"]
    assert report.group == pat_group and report.status == DONE, report.error
    assert "Quiet street" in prompt and "Near a park" not in prompt
    assert "<their_default_filters>" in prompt


def test_another_groups_report_is_not_shown(client):
    pat_group = new_group("Pat's search")
    theirs = TrendReport.objects.create(group=pat_group, status=DONE, summary="Pat's secret summary")
    content = client.get(f"/trends/?report={theirs.pk}").content.decode()
    assert "Pat's secret summary" not in content and "Pat&#x27;s secret summary" not in content


def test_trends_page_uses_our_priorities(client):
    SearchPriorities.objects.create(group=new_group("Pat's search"), text="Their words")
    client.post("/trends/priorities/", {"text": "Our words"}, HTTP_HX_REQUEST="true")
    assert SearchPriorities.get(home_group()).text == "Our words"
    content = client.get("/trends/").content.decode()
    assert "Our words" in content and "Their words" not in content


def test_manual_runs_are_counted_per_group(settings):
    settings.TRENDS_MANUAL_RUNS_PER_DAY = 2
    TrendReport.objects.create(group=new_group("Pat's search"), trigger=TrendReport.Trigger.MANUAL)
    assert analyst.manual_runs_left(home_group()) == 2


def test_daily_runs_each_group_with_members_once(monkeypatch, owner):
    pat_group = make_user("pat@example.com", "Pat", group=new_group("Pat's search")).profile.group
    new_group("Nobody's search")
    started = []
    monkeypatch.setattr(analyst, "start_reports", lambda groups, trigger: started.append(([g.pk for g in groups], trigger)) or True)
    monkeypatch.setattr(analyst, "is_configured", lambda: True)
    assert analyst.run_daily_if_due() is True
    assert started == [([home_group().pk, pat_group.pk], AUTO)]
    TrendReport.objects.create(group=home_group(), trigger=AUTO, status=DONE)
    TrendReport.objects.create(trigger=AUTO, status=DONE)  # a report with no group must not hide everyone
    started.clear()
    assert analyst.run_daily_if_due() is True
    assert started == [([pat_group.pk], AUTO)]


def test_reports_run_one_after_another(monkeypatch):
    groups = [home_group(), new_group("Pat's search")]
    ran = []
    monkeypatch.setattr(analyst, "run_report", lambda group, trigger, report=None: ran.append((group.pk, report is not None)))
    monkeypatch.setattr(analyst.threading, "Thread", lambda target, **kw: type("T", (), {"start": staticmethod(target)})())
    assert analyst.start_reports(groups, AUTO) is True
    assert ran == [(groups[0].pk, True), (groups[1].pk, False)]
    assert not analyst._lock.locked()


def test_a_run_for_another_group_blocks_with_a_clear_message(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    TrendReport.objects.create(group=new_group("Pat's search"), status=TrendReport.Status.RUNNING)
    response = client.post("/trends/run/", follow=True)
    assert "Another household" in response.content.decode()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_group_trends.py -q`
Expected: FAIL (`run_report` takes no group, `start_reports` is missing).

- [ ] **Step 3: The analyst**

In `listings/analyst.py`:

Imports: add `from accounts.models import SearchGroup`. Remove the now-unused `owners_group` import.

Replace `SYSTEM` with:

```python
SYSTEM = """You help a household (one person, or a few people searching together) find a home to rent in \
Portland, Lake Oswego or Beaverton, Oregon. Their default search filters, given below, say what they need: \
bedrooms, bathrooms, parking, price range, property types and must-have features. Treat them as requirements \
unless their own words say otherwise.

You are given listings gathered from property-manager sites, Zillow, Redfin and Craigslist. Parking and \
amenities were parsed from listing text: "unknown" means the listing didn't say, not that it's missing. \
Each listing's price history shows how its asking rent has moved, and special_offer quotes any \
move-in special (weeks free, dollars off), with effective_rent_12mo when its value is stated: count \
specials toward value, and note that a landlord already offering one may have more room to negotiate. Their \
comments, each person's vote (like or dislike) and the status they share (interested, toured, applied, \
rejected) are the strongest signal of their taste: favor what they liked, steer away from what they rejected \
or voted down and why, point out where they disagree, and weigh what they wrote under "What we're looking \
for" above your own assumptions.

Be concrete and honest. Name the specific facts behind each judgment, and say when something is \
unknown and worth asking about rather than guessing."""
```

Replace `_context`, `_shortlist_prompt` and `_picks_prompt` so they take the group:

```python
def _context(stats, group):
    priorities = SearchPriorities.get(group).text.strip() or "(nothing written yet)"
    return [
        f"Today is {timezone.localdate():%A, %B %-d, %Y}.",
        _section("their_default_filters", default_filter_data(group)),
        _section("what_we_are_looking_for", priorities),
        _section("market_statistics", stats),
    ]


def _shortlist_prompt(stats, pool, group):
    return "\n\n".join([*_context(stats, group), _section("candidates", [compact_facts(l) for l in pool]), SHORTLIST_TASK])


def _picks_prompt(stats, shortlisted, rejected, previous, group):
    parts = [
        *_context(stats, group),
        _section("shortlist", [full_facts(l) for l in shortlisted]),
        _section("rejected_by_us", [compact_facts(l) for l in rejected]),
    ]
    if previous:
        earlier = [{"id": p["listing_id"], "rank": p["rank"], "headline": p["headline"]} for p in previous.picks]
        parts.append(_section(f"previous_picks_{timezone.localdate(previous.created_at).isoformat()}", earlier))
    parts.append(PICKS_TASK)
    return "\n\n".join(parts)
```

In `run_report`, change the signature and opening:

```python
def run_report(group=None, trigger=TrendReport.Trigger.MANUAL, client=None, report=None):
    """Runs both passes for one group and saves the report. Never raises: a failure is saved on the report."""
    report = report or TrendReport.objects.create(group=group, trigger=trigger)
    group = report.group
    try:
        previous = TrendReport.objects.filter(group=group, status=TrendReport.Status.DONE).exclude(pk=report.pk).first()
```

Then:
- Delete the `group = owners_group()` line added in Task 5.
- Change the two prompt calls to `_shortlist_prompt(stats, pool, group)` and `_picks_prompt(stats, [by_id[pk] for pk in shortlist], rejected, previous, group)`.

Replace the whole "Running in the background" section (from `_running_reports` through `run_daily_if_due`) with:

```python
def _running_reports():
    return TrendReport.objects.filter(status=TrendReport.Status.RUNNING)


def _fresh_running():
    return _running_reports().filter(created_at__gte=timezone.now() - STALE_AFTER)


def is_running(group=None):
    """Whether a report is being made for this group, or (without a group) for anyone."""
    if group is None:
        return _lock.locked() or _fresh_running().exists()
    return _fresh_running().filter(group=group).exists()


def _launch(groups, trigger, first):
    """Runs one report per group, one after another, in a background thread; releases the lock after."""
    def target():
        try:
            for index, group in enumerate(groups):
                try:
                    run_report(group, trigger, report=first if index == 0 else None)
                finally:
                    close_old_connections()
        finally:
            _lock.release()

    threading.Thread(target=target, name="trend-report", daemon=True).start()


def start_reports(groups, trigger):
    """Starts reports for these groups in the background, one at a time. False if one is already running."""
    groups = list(groups)
    if not groups or not _lock.acquire(blocking=False):
        return False
    try:
        if _fresh_running().exists():
            _lock.release()
            return False
        # Reports left "running" by a restart never finished.
        _running_reports().update(
            status=TrendReport.Status.FAILED, error="Interrupted before it finished.", finished_at=timezone.now()
        )
        first = TrendReport.objects.create(group=groups[0], trigger=trigger)  # so the page shows it running at once
    except Exception:
        _lock.release()
        raise
    _launch(groups, trigger, first)
    return True


def start_report(group, trigger):
    return start_reports([group], trigger)


def _today_start():
    return timezone.make_aware(datetime.combine(timezone.localdate(), time.min))


def manual_runs_left(group):
    used = TrendReport.objects.filter(group=group, trigger=TrendReport.Trigger.MANUAL, created_at__gte=_today_start()).count()
    return max(settings.TRENDS_MANUAL_RUNS_PER_DAY - used, 0)


def due_today():
    """Groups with members that don't have today's automatic report yet."""
    done = (TrendReport.objects.filter(trigger=TrendReport.Trigger.AUTO, created_at__gte=_today_start(), group__isnull=False)
            .exclude(status=TrendReport.Status.FAILED).values("group"))  # no NULLs: NOT IN (…, NULL) matches nothing
    return list(SearchGroup.objects.filter(members__isnull=False).exclude(pk__in=done).distinct().order_by("pk"))


def run_daily_if_due():
    """Starts today's automatic reports, one per group with members, if an API key is set."""
    if not is_configured():
        return False
    groups = due_today()
    return start_reports(groups, TrendReport.Trigger.AUTO) if groups else False
```

- [ ] **Step 4: Views**

In `listings/views.py`:

```python
def trends_page(request):
    group = request.group
    reports = TrendReport.objects.filter(group=group)
    done = reports.filter(status=TrendReport.Status.DONE)
    newest = done.first()
    requested = request.GET.get("report", "")
    report = (done.filter(pk=requested).first() if requested.isdigit() else None) or newest
    latest = reports.first()
```

(The rest is unchanged, apart from `"running": analyst.is_running(group)` and `"runs_left": analyst.manual_runs_left(group)`.)

```python
@require_POST
def trends_run(request):
    group = request.group
    if not analyst.is_configured():
        messages.error(request, "Add ANTHROPIC_API_KEY to .env and restart the app to run the analysis.")
    elif analyst.manual_runs_left(group) <= 0:
        limit = settings.TRENDS_MANUAL_RUNS_PER_DAY
        messages.info(request, f"You've used all {limit} re-runs for today. The daily report still runs after the morning scrape.")
    elif analyst.start_report(group, TrendReport.Trigger.MANUAL):
        messages.success(request, "Analysis started. It takes a minute or two.")
    elif analyst.is_running(group):
        messages.info(request, "An analysis is already running.")
    else:
        messages.info(request, "Another household's analysis is running. Try again in a few minutes.")
    return redirect("trends")
```

In `trends_status`: `if analyst.is_running(request.group):`.

- [ ] **Step 5: Update the older Trends tests**

```bash
sed -i '' 's/TrendReport.objects.create(/TrendReport.objects.create(group=home_group(), /' tests/test_analyst.py tests/test_trends_page.py tests/test_trend_models.py
sed -i '' 's/analyst.run_report(client=/analyst.run_report(home_group(), client=/' tests/test_analyst.py
sed -i '' 's/"start_report", lambda trigger:/"start_report", lambda group, trigger:/' tests/test_trends_page.py
sed -i '' 's/"is_running", lambda: /"is_running", lambda group=None: /' tests/test_trends_page.py
```

Make sure `home_group` is imported in `tests/test_trends_page.py` (`from tests.helpers import home_group, make_listing`); `tests/test_trend_models.py` got it in Task 13.

In `tests/test_analyst.py`:
- `analyst.manual_runs_left()` → `analyst.manual_runs_left(home_group())`.
- Each `monkeypatch.setattr(analyst, "_launch", lambda report: …)` → `lambda groups, trigger, first: …`, with `started.append(first)` where it appended the report.
- `analyst.start_report("manual")` → `analyst.start_report(home_group(), "manual")` (three places).
- Replace the three `run_daily…` tests with:

```python
def test_run_daily_skips_groups_that_already_have_todays_report(monkeypatch, owner):
    started = []
    monkeypatch.setattr(analyst, "start_reports", lambda groups, trigger: started.append(trigger) or True)
    monkeypatch.setattr(analyst, "is_configured", lambda: True)
    assert analyst.run_daily_if_due() is True
    TrendReport.objects.create(group=home_group(), trigger=TrendReport.Trigger.AUTO, status=TrendReport.Status.DONE)
    assert analyst.run_daily_if_due() is False
    assert started == ["auto"]


def test_run_daily_retries_after_a_failed_daily_run(monkeypatch, owner):
    monkeypatch.setattr(analyst, "start_reports", lambda groups, trigger: True)
    monkeypatch.setattr(analyst, "is_configured", lambda: True)
    TrendReport.objects.create(group=home_group(), trigger=TrendReport.Trigger.AUTO, status=TrendReport.Status.FAILED)
    assert analyst.run_daily_if_due() is True


def test_run_daily_skips_when_not_configured(monkeypatch, owner):
    monkeypatch.setattr(analyst, "is_configured", lambda: False)
    monkeypatch.setattr(analyst, "start_reports", lambda groups, trigger: pytest.fail("should not start"))
    assert analyst.run_daily_if_due() is False
```



- [ ] **Step 6: Run the tests and the suite**

Run: `uv run pytest -q` → all pass.

- [ ] **Step 7: Check it in a browser**

On the Trends page, save priorities. If your dev `.env` has an API key and you accept the ~$0.50 cost, click Re-run once, and confirm the running banner and the finished report. Otherwise confirm the "Add ANTHROPIC_API_KEY" message. Log in as a user in another group and confirm they see neither report nor priorities.

- [ ] **Step 8: Update CLAUDE.md and commit**

In the **Trends** bullets, change: "pass 2 ranks the top 5 from full descriptions, comments, votes, rejected listings, the group's default filters and 'What we're looking for' (`SearchPriorities`, one per group)". Also: "Each group has its own reports (`TrendReport.group`) and re-run cap. The daily run makes one report per group with members, one after another in one background thread (about $0.50 each). One report runs at a time across all groups." Keep "market charts are shared".

```bash
git add listings tests CLAUDE.md
git commit -m "feat: Trends reports, priorities and re-run caps per group"
git push -u origin accounts-8-group-trends
gh pr create --base accounts-7-default-filters --title "[Accounts 8/10] Per-group Trends" --body "<stack list, this PR marked>"
```

---
# PR 9 — `[Accounts 9/10] Invites and group settings`

Branch: `git checkout -b accounts-9-invites` (from `accounts-8-group-trends`)

### Task 15: Group settings page (rename, members, remove, leave, password)

**Files:**
- Create: `accounts/views.py`, `accounts/templates/accounts/group.html`, `accounts/templates/accounts/password_change.html`
- Modify: `accounts/urls.py`, `listings/templates/listings/base.html` (nav link, CSS)
- Test: `tests/test_group_settings.py`

**Interfaces:**
- Consumes: `move_to_group`, `new_group` (Task 1; `move_to_group` deletes votes since Task 10), `collab.add_comment`, `collab.set_vote`.
- Produces:
  - URL names `group_settings` (`/group/`), `rename_group`, `remove_member` (`/group/members/<user_id>/remove/`), `leave_group`, `password_change` (`/account/password/`).
  - `accounts.views._to_solo_group(profile)`.

- [ ] **Step 1: Write the failing tests**

`tests/test_group_settings.py`:

```python
import pytest

from accounts.groups import new_group
from listings.collab import add_comment, set_vote
from listings.models import Comment, Vote
from tests.helpers import home_group, make_listing, make_user

pytestmark = pytest.mark.django_db


def test_nav_links_to_the_group_page(client):
    assert '<a href="/group/">Group</a>' in client.get("/").content.decode()


def test_group_page_lists_members(client, member):
    content = client.get("/group/").content.decode()
    assert '<input type="text" name="name" value="Our search"' in content
    assert "<td>Sam <span class=\"muted\">(you)</span></td>" in content and "<td>Alex</td>" in content
    assert f'action="/group/members/{member.pk}/remove/"' in content


def test_rename_the_group(client):
    client.post("/group/rename/", {"name": "  Sam and Alex  "})
    assert home_group().name == "Sam and Alex"
    client.post("/group/rename/", {"name": "   "})
    assert home_group().name == "Sam and Alex"


def test_removing_a_member_gives_them_a_fresh_group_and_keeps_their_comments(client, member):
    listing = make_listing()
    add_comment(listing, home_group(), member, "Alex was here")
    set_vote(listing, home_group(), member, Vote.Value.UP)
    assert client.post(f"/group/members/{member.pk}/remove/").status_code == 302
    member.profile.refresh_from_db()
    assert member.profile.group != home_group() and member.profile.group.name == "Alex's search"
    assert Comment.objects.get().group == home_group() and Comment.objects.get().by == "Alex"
    assert not Vote.objects.exists()


def test_remove_does_not_work_on_yourself(client, owner):
    assert client.post(f"/group/members/{owner.pk}/remove/").status_code == 400


def test_cannot_remove_someone_from_another_group(client):
    pat = make_user("pat@example.com", "Pat", group=new_group("Pat's search"))
    assert client.post(f"/group/members/{pat.pk}/remove/").status_code == 404
    pat.profile.refresh_from_db()
    assert pat.profile.group.name == "Pat's search"


def test_leaving(member_client, member):
    member_client.post("/group/leave/")
    member.profile.refresh_from_db()
    assert member.profile.group != home_group()


def test_the_only_member_cannot_leave(client, owner):
    content = client.post("/group/leave/", follow=True).content.decode()
    assert "You are the only member" in content
    owner.profile.refresh_from_db()
    assert owner.profile.group == home_group()


def test_change_password_keeps_you_logged_in(client, owner):
    response = client.post("/account/password/", {
        "old_password": "pw", "new_password1": "a much longer secret", "new_password2": "a much longer secret",
    })
    assert response.status_code == 302 and response.url == "/group/"
    owner.refresh_from_db()
    assert owner.check_password("a much longer secret")
    assert client.get("/").status_code == 200
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_group_settings.py -q`
Expected: FAIL (404 for `/group/`).

- [ ] **Step 3: Password validators**

In `condofinder/settings.py`, after `LOGOUT_REDIRECT_URL`:

```python
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
```

- [ ] **Step 4: Views and URLs**

`accounts/views.py`:

```python
from django.contrib import messages
from django.contrib.auth.views import PasswordChangeView
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST

from .groups import move_to_group, new_group
from .models import Profile


def group_settings(request):
    group = request.group
    return render(request, "accounts/group.html", {
        "group": group,
        "members": group.members.select_related("user"),
        "can_leave": group.members.count() > 1,
    })


@require_POST
def rename_group(request):
    name = request.POST.get("name", "").strip()[:100]
    if name:
        request.group.name = name
        request.group.save(update_fields=["name"])
        messages.success(request, "Group renamed.")
    return redirect("group_settings")


def _to_solo_group(profile):
    """Leaving or removal: a fresh, empty group of their own. Their comments stay behind; votes go."""
    move_to_group(profile.user, new_group(f"{profile.display_name}'s search"))


@require_POST
def remove_member(request, user_id):
    profile = get_object_or_404(Profile, user_id=user_id, group=request.group)
    if profile.user_id == request.user.pk:
        return HttpResponseBadRequest("Use Leave group to leave.")
    _to_solo_group(profile)
    messages.success(request, f"{profile.display_name} is no longer in {request.group.name}.")
    return redirect("group_settings")


@require_POST
def leave_group(request):
    group = request.group
    if group.members.count() <= 1:
        messages.info(request, "You are the only member, so there is no group to leave.")
    else:
        _to_solo_group(request.profile)
        messages.success(request, f"You left {group.name}. This is your own search now.")
    return redirect("group_settings")


class PasswordChange(PasswordChangeView):
    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("group_settings")

    def form_valid(self, form):
        messages.success(self.request, "Password changed.")
        return super().form_valid(form)
```

`accounts/urls.py`: add `from . import views` and:

```python
    path("group/", views.group_settings, name="group_settings"),
    path("group/rename/", views.rename_group, name="rename_group"),
    path("group/members/<int:user_id>/remove/", views.remove_member, name="remove_member"),
    path("group/leave/", views.leave_group, name="leave_group"),
    path("account/password/", views.PasswordChange.as_view(), name="password_change"),
```

- [ ] **Step 5: Templates**

`accounts/templates/accounts/group.html`:

```html
{% extends "listings/base.html" %}
{% block title %}{{ group.name }} · Condo Finder{% endblock %}
{% block content %}
<h1>{{ group.name }}</h1>
<p class="muted">Everyone here shares statuses, comments, votes, default filters, Trends and the Feed.</p>
<div class="group-page">
  <section class="panel">
    <h3>Name</h3>
    <form method="post" action="{% url 'rename_group' %}" class="inline-form">
      {% csrf_token %}
      <input type="text" name="name" value="{{ group.name }}" maxlength="100" required aria-label="Group name">
      <button type="submit">Rename</button>
    </form>
  </section>
  <section class="panel">
    <h3>Members</h3>
    <div class="table-wrap"><table class="members">
      {% for member in members %}
      <tr>
        <td>{{ member.display_name }}{% if member.user_id == user.pk %} <span class="muted">(you)</span>{% endif %}</td>
        <td class="muted">{{ member.user.email }}</td>
        <td class="muted nowrap">joined {{ member.joined_at|date:"M j, Y" }}</td>
        <td>{% if member.user_id != user.pk %}
          <form method="post" action="{% url 'remove_member' member.user_id %}"
                onsubmit="return confirm('Remove {{ member.display_name|escapejs }}? They start a new search of their own; their comments stay here.')">
            {% csrf_token %}<button type="submit" class="link danger">Remove</button></form>{% endif %}</td>
      </tr>
      {% endfor %}
    </table></div>
    {% if can_leave %}
    <form method="post" action="{% url 'leave_group' %}" onsubmit="return confirm('Leave {{ group.name|escapejs }}? You start a new search of your own; your comments stay here and your votes are removed.')">
      {% csrf_token %}<button type="submit" class="link danger">Leave {{ group.name }}</button></form>
    {% endif %}
  </section>
  {% block invites %}{% endblock %}
  <section class="panel">
    <h3>Your account</h3>
    <p>{{ request.profile.display_name }} · {{ user.email }}</p>
    <p><a href="{% url 'password_change' %}">Change password</a></p>
  </section>
</div>
{% endblock %}
```

(Task 16 replaces the `{% block invites %}{% endblock %}` placeholder with the invites panel.)

`accounts/templates/accounts/password_change.html`:

```html
{% extends "listings/base.html" %}
{% block title %}Change password · Condo Finder{% endblock %}
{% block content %}
<div class="panel auth-card">
  <h1>Change password</h1>
  <form method="post">
    {% csrf_token %}
    {% for field in form %}
    <label class="stack">{{ field.label }} {{ field }}
      {% for error in field.errors %}<span class="form-error">{{ error }}</span>{% endfor %}</label>
    {% endfor %}
    <button type="submit">Change password</button>
  </form>
  <p class="small"><a href="{% url 'group_settings' %}">Back</a></p>
</div>
{% endblock %}
```

`base.html`: in `<nav>`, after the Feed link, add `<a href="{% url 'group_settings' %}">Group</a>`. CSS:

```css
    .group-page { max-width:760px; } .group-page h3 { margin-top:0; }
    .inline-form { display:flex; flex-wrap:wrap; gap:8px; align-items:center; }
    .inline-form input[type=text] { flex:1; min-width:0; padding:7px 10px; border:1px solid var(--line); border-radius:8px; font:inherit; }
    .members form { margin:0; }
```

- [ ] **Step 6: Run the tests and the suite**

Run: `uv run pytest tests/test_group_settings.py -q` → 10 passed.
Run: `uv run pytest -q` → all pass.

- [ ] **Step 7: Commit**

```bash
git add accounts condofinder/settings.py listings/templates/listings/base.html tests/test_group_settings.py
git commit -m "feat: group settings page with members, leave, remove and password change"
```

### Task 16: Invite links and signup

**Files:**
- Modify: `accounts/models.py`, `accounts/views.py`, `accounts/urls.py`, `accounts/admin.py`, `accounts/forms.py`, `accounts/templates/accounts/group.html`, `condofinder/settings.py`, `tests/conftest.py`, `.env.example`, `CLAUDE.md`
- Create: `accounts/migrations/0006_invite.py` (generated), `accounts/invites.py`, `accounts/templates/accounts/signup.html`, `accounts/templates/accounts/invite_gone.html`, `accounts/templates/accounts/invite_existing.html`
- Test: `tests/test_invites.py`

**Interfaces:**
- Consumes: `new_group`, `move_to_group`, `Profile` (Task 1); `group_settings` (Task 15).
- Produces:
  - `accounts.models.Invite(token, kind ∈ {new_group, join}, group, created_by, created_at, expires_at, used_at, used_by)` with the property `is_usable`.
  - `accounts.invites.create_invite(kind, by, group=None) -> Invite`, `invite_url(request, invite) -> str`, `claim(invite, user) -> bool`.
  - URL names `invite` (`/invite/<token>/`, login not required), `create_invite` (`/group/invites/new/`), `revoke_invite` (`/group/invites/<pk>/revoke/`).
  - Settings `PUBLIC_URL`, `INVITE_DAYS`.

- [ ] **Step 1: Settings and conftest**

`condofinder/settings.py`, in the Condo finder section:

```python
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").rstrip("/")  # e.g. https://mac-mini.tail1234.ts.net; invite links use it
INVITE_DAYS = 7
```

`.env.example`, add:

```
# The HTTPS address people use (Tailscale Funnel). Invite links are built from it.
PUBLIC_URL=
```

`tests/conftest.py`, in `condo_settings`, add `settings.PUBLIC_URL = ""`.

- [ ] **Step 2: Write the failing tests**

`tests/test_invites.py`:

```python
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from accounts.groups import new_group
from accounts.invites import claim
from accounts.models import Invite
from listings.forms import app_default_filters, default_filter_data
from tests.helpers import home_group, make_user

pytestmark = pytest.mark.django_db
User = get_user_model()


def make_invite(kind="join", group=None, **extra):
    group = (group or home_group()) if kind == "join" else None
    return Invite.objects.create(kind=kind, group=group, **extra)


def signup(browser, invite, **data):
    fields = {"display_name": "Jo", "email": "jo@example.com",
              "password1": "correct horse battery", "password2": "correct horse battery"}
    fields.update(data)
    return browser.post(f"/invite/{invite.token}/", fields)


def test_join_link_signs_up_into_the_group(anon_client):
    invite = make_invite()
    assert "<h1>Join Our search</h1>" in anon_client.get(f"/invite/{invite.token}/").content.decode()
    response = signup(anon_client, invite, email="Jo@Example.com")
    assert response.status_code == 302 and response.url == "/"
    user = User.objects.get(email="jo@example.com")
    assert user.username == "jo@example.com" and not user.is_staff
    assert user.profile.group == home_group() and user.profile.display_name == "Jo"
    assert anon_client.get("/feed/").status_code == 200
    invite.refresh_from_db()
    assert invite.used_by == user and invite.used_at is not None


def test_new_household_link_gives_a_group_of_their_own(anon_client):
    signup(anon_client, make_invite("new_group"))
    group = User.objects.get(email="jo@example.com").profile.group
    assert group != home_group() and group.name == "Jo's search"
    assert default_filter_data(group) == app_default_filters()


def test_invite_is_single_use(anon_client):
    invite = make_invite()
    signup(anon_client, invite)
    response = signup(Client(), invite, email="kim@example.com")
    assert response.status_code == 410 and "expired or was already used" in response.content.decode()
    assert not User.objects.filter(email="kim@example.com").exists()


def test_claim_succeeds_only_once(owner, member):
    invite = make_invite()
    assert claim(invite, owner) is True
    assert claim(invite, member) is False


def test_signup_rolls_back_if_the_link_was_used_meanwhile(anon_client, monkeypatch):
    monkeypatch.setattr("accounts.views.claim", lambda invite, user: False)
    assert signup(anon_client, make_invite()).status_code == 410
    assert not User.objects.filter(email="jo@example.com").exists()


def test_expired_invite_is_refused(anon_client):
    invite = make_invite(expires_at=timezone.now() - timedelta(minutes=1))
    assert anon_client.get(f"/invite/{invite.token}/").status_code == 410
    assert anon_client.get("/invite/not-a-token/").status_code == 410


def test_signup_checks_email_and_passwords(anon_client):
    make_user("taken@example.com", "Taken")
    content = signup(anon_client, make_invite(), email="Taken@Example.com", password2="different words here").content.decode()
    assert "An account with this email already exists. Log in instead." in content
    assert "The passwords do not match." in content
    content = signup(anon_client, make_invite(), password1="short", password2="short").content.decode()
    assert "This password is too short." in content


def test_a_logged_in_person_can_switch_groups_with_a_join_link():
    pat = make_user("pat@example.com", "Pat", group=new_group("Pat's search"))
    browser = Client()
    browser.force_login(pat)
    invite = make_invite()
    assert "<h1>Join Our search?</h1>" in browser.get(f"/invite/{invite.token}/").content.decode()
    assert browser.post(f"/invite/{invite.token}/").url == "/group/"
    pat.profile.refresh_from_db()
    assert pat.profile.group == home_group()


def test_a_logged_in_person_is_told_to_pass_on_a_household_link(client):
    invite = make_invite("new_group")
    assert "<h1>You already have an account</h1>" in client.get(f"/invite/{invite.token}/").content.decode()
    invite.refresh_from_db()
    assert invite.used_at is None


def test_members_make_join_links_and_only_staff_make_household_links(client, member_client):
    member_client.post("/group/invites/new/", {"kind": "join"})
    assert Invite.objects.get().group == home_group()
    assert member_client.post("/group/invites/new/", {"kind": "new_group"}).status_code == 403
    client.post("/group/invites/new/", {"kind": "new_group"})
    content = client.get("/group/").content.decode()
    assert content.count('aria-label="Invite link"') == 2
    assert 'value="http://testserver/invite/' in content


def test_invite_links_use_the_public_url(client, settings):
    settings.PUBLIC_URL = "https://mac-mini.tail1234.ts.net"
    client.post("/group/invites/new/", {"kind": "join"})
    assert 'value="https://mac-mini.tail1234.ts.net/invite/' in client.get("/group/").content.decode()


def test_cannot_revoke_another_groups_invite(client):
    theirs = make_invite(group=new_group("Pat's search"))
    assert client.post(f"/group/invites/{theirs.pk}/revoke/").status_code == 404
    assert Invite.objects.filter(pk=theirs.pk).exists()
    mine = make_invite()
    client.post(f"/group/invites/{mine.pk}/revoke/")
    assert not Invite.objects.filter(pk=mine.pk).exists()
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_invites.py -q`
Expected: FAIL with `ImportError: cannot import name 'claim'`.

- [ ] **Step 4: Model, migration, admin**

`accounts/models.py`: add `import secrets` and `from datetime import timedelta`, then:

```python
def new_token():
    return secrets.token_urlsafe(24)


def invite_expiry():
    return timezone.now() + timedelta(days=settings.INVITE_DAYS)


class Invite(models.Model):
    """A copy-paste signup link: into a new household of its own (made by the site admin) or into the
    group of the member who made it. Single use; expires."""

    class Kind(models.TextChoices):
        NEW_GROUP = "new_group", "New household"
        JOIN = "join", "Join a group"

    token = models.CharField(max_length=64, unique=True, default=new_token)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    group = models.ForeignKey(SearchGroup, on_delete=models.CASCADE, null=True, blank=True, related_name="invites")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(default=invite_expiry)
    used_at = models.DateTimeField(null=True, blank=True)
    used_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    def __str__(self):
        return f"{self.get_kind_display()} invite ({'used' if self.used_at else 'open'})"

    @property
    def is_usable(self):
        return self.used_at is None and self.expires_at > timezone.now()
```

Run: `uv run python manage.py makemigrations accounts --name invite` → `0006_invite.py`.

`accounts/admin.py`: register `Invite`:

```python
@admin.register(Invite)
class InviteAdmin(admin.ModelAdmin):
    list_display = ("kind", "group", "created_by", "created_at", "expires_at", "used_by")
    list_filter = ("kind",)
    readonly_fields = ("token", "used_at", "used_by")
```

- [ ] **Step 5: Invite helpers and signup form**

`accounts/invites.py`:

```python
from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from .models import Invite


def create_invite(kind, by, group=None):
    return Invite.objects.create(kind=kind, created_by=by, group=group if kind == Invite.Kind.JOIN else None)


def invite_url(request, invite):
    """The full link to send. PUBLIC_URL wins, because the request may have come in on a local address."""
    path = reverse("invite", args=[invite.token])
    return f"{settings.PUBLIC_URL}{path}" if settings.PUBLIC_URL else request.build_absolute_uri(path)


def usable_invites():
    return Invite.objects.filter(used_at__isnull=True, expires_at__gt=timezone.now())


def claim(invite, user):
    """Marks the invite used by `user`. One conditional UPDATE, so it succeeds once even if two people
    submit at the same moment. False when it was used or expired in the meantime."""
    now = timezone.now()
    return bool(usable_invites().filter(pk=invite.pk).update(used_at=now, used_by=user))
```

`accounts/forms.py`: add the imports `from django.contrib.auth import get_user_model`, `from django.contrib.auth.password_validation import validate_password`, `from django.core.exceptions import ValidationError` and `from django.db.models import Q`, then:

```python
class SignupForm(forms.Form):
    display_name = forms.CharField(max_length=60, label="Your name",
                                   help_text="Shown on your comments and votes, and in the Feed.")
    email = forms.EmailField(label="Email", widget=forms.EmailInput(attrs={"autocomplete": "email"}))
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    password2 = forms.CharField(label="Password again", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    def clean_display_name(self):
        return self.cleaned_data["display_name"].strip()

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if get_user_model().objects.filter(Q(username__iexact=email) | Q(email__iexact=email)).exists():
            raise ValidationError("An account with this email already exists. Log in instead.")
        return email

    def clean(self):
        cleaned = super().clean()
        first, second = cleaned.get("password1"), cleaned.get("password2")
        if first and second and first != second:
            self.add_error("password2", "The passwords do not match.")
        elif first:
            email = cleaned.get("email", "")
            try:
                validate_password(first, user=get_user_model()(username=email, email=email))
            except ValidationError as error:
                self.add_error("password1", error)
        return cleaned
```

- [ ] **Step 6: Views and URLs**

Add to `accounts/views.py`. The imports are `from django.conf import settings`, `from django.contrib.auth import get_user_model, login`, `from django.contrib.auth.decorators import login_not_required`, `from django.db import transaction`, `from django.db.models import Q` and `from django.http import HttpResponseForbidden`, plus:

```python
from .forms import SignupForm
from .invites import claim, create_invite, invite_url, usable_invites
from .models import Invite, Profile
```

Code:

```python
class InviteUsed(Exception):
    pass


@login_not_required
def invite(request, token):
    """An invite link: sign up (logged out), or join the group (logged in, join links only)."""
    invite = Invite.objects.select_related("group").filter(token=token).first()
    if invite is None or not invite.is_usable:
        return render(request, "accounts/invite_gone.html", status=410)
    if request.user.is_authenticated:
        return _invite_existing_user(request, invite)
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            user = _sign_up(invite, form.cleaned_data)
        except InviteUsed:
            return render(request, "accounts/invite_gone.html", status=410)
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(request, f"Welcome, {user.profile.display_name}.")
        return redirect("listing_list")
    return render(request, "accounts/signup.html", {"form": form, "invite": invite})


def _sign_up(invite, data):
    with transaction.atomic():
        user = get_user_model().objects.create_user(username=data["email"], email=data["email"], password=data["password1"])
        if not claim(invite, user):
            raise InviteUsed  # rolls back the new account
        group = invite.group or new_group(f"{data['display_name']}'s search")
        Profile.objects.create(user=user, group=group, display_name=data["display_name"])
    return user


def _invite_existing_user(request, invite):
    if invite.kind == Invite.Kind.NEW_GROUP:
        return render(request, "accounts/invite_existing.html", {"invite": invite, "reason": "new_group"})
    if invite.group_id == request.group.pk:
        messages.info(request, f"You are already in {invite.group.name}.")
        return redirect("group_settings")
    if request.method == "POST":
        if not claim(invite, request.user):
            return render(request, "accounts/invite_gone.html", status=410)
        move_to_group(request.user, invite.group)
        messages.success(request, f"You joined {invite.group.name}.")
        return redirect("group_settings")
    return render(request, "accounts/invite_existing.html", {"invite": invite, "reason": "join"})


def _open_invites(request):
    """The invites this person may see and revoke: their group's join links, plus (staff) the
    new-household links they made."""
    mine = Q(group=request.group)
    if request.user.is_staff:
        mine |= Q(kind=Invite.Kind.NEW_GROUP, created_by=request.user)
    return usable_invites().filter(mine).order_by("-created_at")


@require_POST
def create_invite_view(request):
    kind = request.POST.get("kind")
    if kind not in Invite.Kind.values:
        return HttpResponseBadRequest("invalid invite")
    if kind == Invite.Kind.NEW_GROUP and not request.user.is_staff:
        return HttpResponseForbidden("Only the site admin can invite a new household.")
    create_invite(kind, request.user, request.group)
    messages.success(request, "Invite link created. Copy it below and send it.")
    return redirect("group_settings")


@require_POST
def revoke_invite(request, pk):
    get_object_or_404(_open_invites(request), pk=pk).delete()
    messages.success(request, "Invite link revoked.")
    return redirect("group_settings")
```

Update `group_settings` to also pass:

```python
        "invites": [(invite, invite_url(request, invite)) for invite in _open_invites(request)],
        "invite_days": settings.INVITE_DAYS,
```

`accounts/urls.py`:

```python
    path("invite/<str:token>/", views.invite, name="invite"),
    path("group/invites/new/", views.create_invite_view, name="create_invite"),
    path("group/invites/<int:pk>/revoke/", views.revoke_invite, name="revoke_invite"),
```

- [ ] **Step 7: Templates**

In `accounts/templates/accounts/group.html`, replace `{% block invites %}{% endblock %}` with:

```html
  <section class="panel">
    <h3>Invite links</h3>
    <p class="muted">Each link works once and expires after {{ invite_days }} days. The app sends no email: copy a link and send it yourself.</p>
    <form method="post" action="{% url 'create_invite' %}" class="inline-form">
      {% csrf_token %}
      <button type="submit" name="kind" value="join">New link to join {{ group.name }}</button>
      {% if user.is_staff %}<button type="submit" name="kind" value="new_group">New link for another household</button>{% endif %}
    </form>
    {% for invite, url in invites %}
    <div class="invite">
      <span class="muted">{% if invite.kind == "join" %}Joins {{ group.name }}{% else %}New household{% endif %} · expires {{ invite.expires_at|date:"M j" }}</span>
      <div class="inline-form">
        <input type="text" readonly value="{{ url }}" aria-label="Invite link" onclick="this.select()">
        <button type="button" data-copy="{{ url }}">Copy</button>
        <form method="post" action="{% url 'revoke_invite' invite.pk %}">{% csrf_token %}<button type="submit" class="link danger">Revoke</button></form>
      </div>
    </div>
    {% empty %}
    <p class="muted">No open invite links.</p>
    {% endfor %}
  </section>
```

And add at the end of the file:

```html
{% block scripts %}
<script>
  document.querySelectorAll("[data-copy]").forEach(button => button.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(button.dataset.copy);
      button.textContent = "Copied ✓";
    } catch {
      button.previousElementSibling.select();  // no clipboard access: select it for a manual copy
    }
  }));
</script>
{% endblock %}
```

`accounts/templates/accounts/signup.html`:

```html
{% extends "listings/base.html" %}
{% block title %}Join Condo Finder{% endblock %}
{% block content %}
<div class="panel auth-card">
  <h1>{% if invite.group %}Join {{ invite.group.name }}{% else %}Start your search{% endif %}</h1>
  <p class="muted">{% if invite.group %}You'll share statuses, comments, votes and the Feed with everyone in {{ invite.group.name }}.{% else %}You'll get a search of your own, and can invite others to it.{% endif %}</p>
  <form method="post">
    {% csrf_token %}
    {% for field in form %}
    <label class="stack">{{ field.label }} {{ field }}
      {% if field.help_text %}<span class="muted small">{{ field.help_text }}</span>{% endif %}
      {% for error in field.errors %}<span class="form-error">{{ error }}</span>{% endfor %}</label>
    {% endfor %}
    <button type="submit">Create account</button>
  </form>
  <p class="muted small">Already have an account? <a href="{% url 'login' %}?next={{ request.path|urlencode }}">Log in</a>, then open this link again.</p>
</div>
{% endblock %}
```

`accounts/templates/accounts/invite_gone.html`:

```html
{% extends "listings/base.html" %}
{% block title %}Invite link · Condo Finder{% endblock %}
{% block content %}
<div class="panel auth-card">
  <h1>This link doesn't work anymore</h1>
  <p>This invite link has expired or was already used. Ask whoever sent it for a new one.</p>
  <p class="small"><a href="{% url 'login' %}">Log in</a></p>
</div>
{% endblock %}
```

`accounts/templates/accounts/invite_existing.html`:

```html
{% extends "listings/base.html" %}
{% block title %}Invite link · Condo Finder{% endblock %}
{% block content %}
<div class="panel auth-card">
  {% if reason == "join" %}
  <h1>Join {{ invite.group.name }}?</h1>
  <p>You're in {{ request.group.name }} now. Joining moves you: your comments stay in {{ request.group.name }}, and your votes there are removed.</p>
  <form method="post">{% csrf_token %}<button type="submit">Join {{ invite.group.name }}</button></form>
  <p class="small"><a href="{% url 'listing_list' %}">Stay where I am</a></p>
  {% else %}
  <h1>You already have an account</h1>
  <p>This link is for someone new starting their own search. Pass it on, or <a href="{% url 'group_settings' %}">invite people to your group</a>.</p>
  {% endif %}
</div>
{% endblock %}
```

`base.html` CSS: `.invite { margin-top:10px; } .invite .inline-form form { margin:0; }`.

- [ ] **Step 8: Run the tests and the suite**

Run: `uv run pytest tests/test_invites.py -q` → 13 passed.
Run: `uv run pytest -q` → all pass.

- [ ] **Step 9: Check it in a browser**

As the owner, open Group and create a join link. Open it in a private window, sign up, and confirm you land on Listings in the owner's group. Reopen the same link: it should say it was already used. Try the Copy button. Create a "new household" link and sign up with it; the result is a separate group whose defaults are the app defaults. Try a join link while logged in as someone from another group. Test Remove and Leave. Check phone width on the Group page (the invite input must not overflow) and the console. Delete the test accounts in admin afterwards.

- [ ] **Step 10: Update CLAUDE.md and commit**

Extend the `accounts/` bullet: "`Invite` links (`accounts/invites.py`) are single-use (`claim()` is one conditional UPDATE) and expire after `INVITE_DAYS` (7). Any member makes join links; staff also make new-household links. Links use `PUBLIC_URL`. The Group page (`/group/`) renames the group, lists members, removes a member or leaves (either gives that person a fresh solo group; comments stay, votes go), manages invite links and changes the password."

```bash
git add accounts condofinder/settings.py .env.example listings/templates/listings/base.html tests CLAUDE.md
git commit -m "feat: invite links for new households and for joining a group"
git push -u origin accounts-9-invites
gh pr create --base accounts-8-group-trends --title "[Accounts 9/10] Invites and group settings" --body "<stack list, this PR marked>"
```

---
# PR 10 — `[Accounts 10/10] Public HTTPS and docs`

Branch: `git checkout -b accounts-10-public-https` (from `accounts-9-invites`)

### Task 17: HTTPS settings, localhost-only gunicorn, Funnel runbook

**Files:**
- Modify: `condofinder/settings.py`, `deploy/gunicorn.conf.py`, `deploy/install.sh`, `README.md`, `tests/test_views.py`
- Test: `tests/test_public_url.py`

**Interfaces:**
- Produces: `condofinder.settings.web_security(public_url) -> dict` with keys `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`.

- [ ] **Step 1: Write the failing tests**

`tests/test_public_url.py`:

```python
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
```

In `tests/test_views.py`, delete `TAILSCALE_HOST`, `test_pages_load_over_a_tailscale_hostname` and `test_status_buttons_pass_csrf_over_tailscale`. The port-8000 URL is retired; `tests/test_public_url.py` covers the HTTPS one.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_public_url.py -q`
Expected: FAIL with `ImportError: cannot import name 'web_security'`.

- [ ] **Step 3: Settings**

In `condofinder/settings.py`, add `from urllib.parse import urlsplit`. Replace `ALLOWED_HOSTS = ["*"]  # LAN-only app` with nothing: it is set below. Move the `PUBLIC_URL = …` line up next to `DEBUG`, and add:

```python
def web_security(public_url):
    """Hosts, CSRF origins and cookie flags. Without a public URL (local development) anything goes;
    with one (Tailscale Funnel), only that host, plus localhost for install.sh's health check."""
    if not public_url:
        return {"ALLOWED_HOSTS": ["*"], "CSRF_TRUSTED_ORIGINS": [], "SESSION_COOKIE_SECURE": False, "CSRF_COOKIE_SECURE": False}
    secure = public_url.startswith("https://")
    return {
        "ALLOWED_HOSTS": [urlsplit(public_url).hostname, "localhost", "127.0.0.1"],
        "CSRF_TRUSTED_ORIGINS": [public_url],
        "SESSION_COOKIE_SECURE": secure,
        "CSRF_COOKIE_SECURE": secure,
    }


_web = web_security(PUBLIC_URL)
ALLOWED_HOSTS = _web["ALLOWED_HOSTS"]
CSRF_TRUSTED_ORIGINS = _web["CSRF_TRUSTED_ORIGINS"]
SESSION_COOKIE_SECURE = _web["SESSION_COOKIE_SECURE"]
CSRF_COOKIE_SECURE = _web["CSRF_COOKIE_SECURE"]
```

(Funnel terminates TLS and forwards to gunicorn on 127.0.0.1. gunicorn trusts `X-Forwarded-Proto` from 127.0.0.1 by default, so Django sees HTTPS requests as secure without `SECURE_PROXY_SSL_HEADER`.)

- [ ] **Step 4: gunicorn and install.sh**

`deploy/gunicorn.conf.py`:

```python
# Exactly one worker: the in-process scheduler must exist once.
# Localhost only: people reach the app through Tailscale Funnel (HTTPS), never port 8000 directly.
bind = "127.0.0.1:8000"
```

(The other settings are unchanged.)

`deploy/install.sh`: replace everything from `echo "Condo Finder is running."` to the end with:

```bash
echo "Condo Finder is running on 127.0.0.1:8000. People reach it through Tailscale Funnel."
PUBLIC_URL="$(grep -E '^PUBLIC_URL=' .env 2>/dev/null | cut -d= -f2- || true)"
if [ -n "$PUBLIC_URL" ]; then
  echo "  $PUBLIC_URL"
else
  echo "  PUBLIC_URL isn't set in .env. See README: Going public with Tailscale Funnel." >&2
fi
```

- [ ] **Step 5: README runbook**

Replace the README section "## Access from anywhere (Tailscale)" (through the paragraph ending "`changepassword <user>`)."). Its replacement follows below as a nested fence.

In "## Run on the Mac mini", change step 5 to: "5. Create the site admin's account: `uv run python manage.py create_owner --email you@example.com --name \"Your name\"`." Change step 4 to: "4. No firewall prompt is needed: gunicorn listens on localhost only."

In "## Develop", change `runserver 0.0.0.0:8000` to `runserver 127.0.0.1:8000`. Add a line after it: `uv run python manage.py create_owner --email you@example.com --name You   # once per dev database`. (That code block is for developers reading the README, not for pasting, so the comment is acceptable there. Match the existing block's style.)

`````markdown
## Going public with Tailscale Funnel

The app stays on the Mac mini, so scrapers keep a home IP (Zillow and Redfin block most cloud IPs).
Tailscale Funnel gives it a public HTTPS address, `https://<mac-mini>.<tailnet>.ts.net`, with an
automatic certificate. Anyone with an account can use it from any browser, with no Tailscale app
needed. Every page requires a login, and gunicorn listens only on `127.0.0.1:8000`, so Funnel is the
only way in.

Do these once, in order. Run each command in its own step: the site is briefly unreachable
between the install and turning on Funnel.

1. **Pull and set the public address.** Find the Mac mini's full Tailscale name in the
   [admin console](https://login.tailscale.com/admin/machines) (for example
   `mac-mini.tail1234.ts.net`). In `.env`, set `PUBLIC_URL=https://` followed by that name.

   ```bash
   git pull
   ```

2. **Install.** This migrates the database (statuses, notes, priorities and Trends reports move to
   the owners' group) and restarts gunicorn on localhost only.

   ```bash
   ./deploy/install.sh
   ```

3. **Create your account.** This makes you the site admin in the owners' group, and claims your old
   notes (now comments). It asks for a password.

   ```bash
   uv run python manage.py create_owner --email you@example.com --name "Your name"
   ```

4. **Try it privately first.** This serves HTTPS to devices on your tailnet only:

   ```bash
   tailscale serve --bg 8000
   ```

   Open `https://<mac-mini>.<tailnet>.ts.net` on a device signed in to Tailscale and log in. (On the
   App Store build the CLI is `/Applications/Tailscale.app/Contents/MacOS/Tailscale`.)

5. **Allow Funnel for the Mac mini.** In the admin console, go to **Access controls** and add the
   `funnel` node attribute. The `tailscale funnel` command prints a link to the exact setting if
   it's missing.

6. **Open it to the internet.**

   ```bash
   tailscale funnel --bg 8000
   ```

   Check with `tailscale funnel status`. To turn it off: `tailscale funnel reset`. If the CLI
   rejects these flags, see `tailscale funnel --help`; the syntax has changed between versions.

7. **Check from outside.** Turn off Wi-Fi on a phone and open the address over cellular: you should
   get the login page. From a terminal, this should print a `302` redirect to `/login/`:

   ```bash
   curl -sI https://<mac-mini>.<tailnet>.ts.net/
   ```

8. **Invite your partner.** Open **Group**, click **New link to join**, copy the link and send it. For
   another household, click **New link for another household** (site admin only).

Passwords: people change their own on the Group page. To reset someone's, run
`uv run python manage.py changepassword <their email>`. There's no lockout after failed logins yet;
add one (django-axes) before opening signup to the public.
`````

- [ ] **Step 6: Run the tests and the suite**

Run: `uv run pytest -q` → all pass.

- [ ] **Step 7: Commit**

```bash
git add condofinder deploy README.md tests
git commit -m "feat: HTTPS-only settings for the public URL and a localhost-only gunicorn"
```

### Task 18: Docs: INTENT, CLAUDE.md, architecture diagrams

**Files:**
- Modify: `INTENT.md`, `CLAUDE.md`, `docs/architecture.html`

- [ ] **Step 1: INTENT.md**

- In "## The problem", change "Two of us are looking for a place to rent together" to "We (two of us, and now a few friends) are looking for places to rent".
- Replace the "**Shared tracking.**" bullet with:

```markdown
- **Shared tracking, per household.** Each household is a search group with its own status on each
  listing (who set it and when), a comment thread, each person's 👍/👎, default filters, Trends
  report and Feed. Partners see each other's activity; other households never do.
```

- Replace the "## Who it's for" paragraph with:

```markdown
The two of us first, and a handful of invited households, on laptops and phones. Everyone logs in
with an email and password and belongs to exactly one search group; invites are copy-paste links.
The site admin (staff) alone edits shared scraped data: price history, refreshes, sources and
overrides. Keep choices compatible with open signup later, but don't build for it yet.
```

- Replace the "**Runs at home on a Mac mini, reached over Tailscale.**" bullet with:

```markdown
- **Runs at home on a Mac mini, published with Tailscale Funnel.** A residential IP keeps Zillow and
  Redfin scraping workable; cloud IPs get blocked. Funnel gives a public HTTPS address with an
  automatic certificate, and gunicorn listens on localhost only, so every request passes the login.
```

- In "## Non-goals", replace "A public or multi-user product." with "Open public signup (for now), outgoing email, or accounts in more than one group."

- [ ] **Step 2: CLAUDE.md**

- **Current state**: set the merged/open lines to match GitHub at the time. Change **Production** to: "Both owners (and invited households) reach it at `https://<mac-mini>.<tailnet>.ts.net` through Tailscale Funnel; gunicorn listens on 127.0.0.1:8000 only." After the stack deploys, add "Recently shipped: accounts and collaboration (logins, groups, comments, votes, per-group defaults, Trends and Feed)." Remove the port-8000 reference.
- **Deploy**: add "`PUBLIC_URL` in `.env` must be the Funnel address (README: Going public with Tailscale Funnel)."
- **Commands**: add `uv run python manage.py create_owner --email you@example.com --name You` after `migrate` (once per database; every page needs a login).
- **Conventions → Verify in a browser**: add "Log in first (`create_owner` on your dev database). Check group features with two accounts in two browsers."
- **Gotchas**: add "Group state (status, comments, votes) isn't on `Listing`. Use `collab.decorate()` before rendering listings, and pass the group to `apply_filters`." and "Data migrations that need the owners' group take the oldest `SearchGroup`."

- [ ] **Step 3: docs/architecture.html**

Open the file and update these sections, matching their existing SVG and prose style:

- **"The whole system"** (the lede at line ~90, the SVG at ~102, the figcaption at ~235):
  - Replace the "Tailscale" link label with "Tailscale Funnel (HTTPS)".
  - Change the gunicorn subtitle from "port 8000" to "127.0.0.1:8000".
  - Add a small "Login required" box between the browser arrow and "web views".
  - Change "you two browse over Tailscale" to "each household browses through Tailscale Funnel after logging in".
  - Rewrite the figcaption's access sentence: "People reach it at `https://<mac-mini>.<tailnet>.ts.net`; Funnel terminates HTTPS and forwards to gunicorn on localhost, and every page needs a login."
- **"What's stored"**:
  - Add an `accounts` group of boxes: `SearchGroup` (name, default_filters), `Profile` (user, group, display_name, feed_seen_at) and `Invite`.
  - Add group-owned boxes, drawn in the amber "yours" colour and linked to both `Listing` and `SearchGroup`: `ListingState` (status, status_by, status_at), `Comment` and `Vote`.
  - Remove `status` and `notes` from `Listing`.
  - Mark `TrendReport.group`, `SearchPriorities.group`, `FeedEvent.group/actor/comment`.
  - Rewrite the figcaption: "Scraped data is global and shared by every group; everything amber belongs to one search group."
- **"The pages"**: add Login, Invite/signup and Group, and note that Sources and history editing are staff-only.
- **"Rules the design depends on"**: add "Group state never leaves its group; scraped data is shared" and "One user, one group".

Open the file in a browser, and check both light and dark themes and phone width.

- [ ] **Step 4: Republish the architecture artifact**

Publish `docs/architecture.html` to the existing artifact with the Artifact tool: `action: "publish"`, `url: "https://claude.ai/artifact/MASfMv25dYKcHeYTx6eUgq"`, `file_path: "docs/architecture.html"`. Read it first (`action: "read"`) if this session hasn't published it.

- [ ] **Step 5: Final full check**

Run: `uv run pytest -q`
Expected: all pass. Report the count.

Run: `uv run python manage.py makemigrations --check --dry-run`
Expected: "No changes detected".

- [ ] **Step 6: Commit and open PR 10**

```bash
git add INTENT.md CLAUDE.md docs/architecture.html
git commit -m "docs: accounts, groups and Funnel in INTENT, CLAUDE.md and the architecture diagrams"
git push -u origin accounts-10-public-https
gh pr create --base accounts-9-invites --title "[Accounts 10/10] Public HTTPS and docs" --body "<stack list, this PR marked; plus: after merging the whole stack, deploy with the README runbook 'Going public with Tailscale Funnel'>"
```
