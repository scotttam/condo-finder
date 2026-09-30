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


def test_removing_someone_closes_the_groups_open_join_links(client, member):
    old_link = make_invite()
    assert client.post(f"/group/members/{member.pk}/remove/", follow=True).status_code == 200
    back = Client()
    back.force_login(member)
    assert back.get(f"/invite/{old_link.token}/").status_code == 410
    back.post(f"/invite/{old_link.token}/")
    member.profile.refresh_from_db()
    assert member.profile.group != home_group()
