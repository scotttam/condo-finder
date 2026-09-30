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


def test_leaving(member_client, member, owner):
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
