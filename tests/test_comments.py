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
