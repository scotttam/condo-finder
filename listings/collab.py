"""What a search group says about listings: its shared status, comments and votes.
Scraped data on Listing is global; everything here is per group."""

from django.db import models
from django.db.models import OuterRef, Subquery, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from accounts.models import display_name

from . import feed
from .models import Comment, FeedEvent, ListingState, Status, Vote

STATUS_LABELS = dict(Status.choices)


def status_expr(group):
    """The group's status for each listing in a queryset (New when it hasn't set one), to annotate with."""
    states = ListingState.objects.filter(group=group, listing=OuterRef("pk")).values("status")[:1]
    return Coalesce(Subquery(states), Value(Status.NEW), output_field=models.CharField())


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


def set_status(listing, group, user, status):
    """Sets the group's status and records who set it. Setting the same status again changes nothing."""
    state, _ = ListingState.objects.get_or_create(group=group, listing=listing)
    if state.status == status and state.status_at:
        return state
    state.status, state.status_by, state.status_at = status, user, timezone.now()
    state.save()
    if user is not None:
        feed.record_activity(listing, group, user, FeedEvent.Kind.STATUS,
                             f"{display_name(user)} marked it {STATUS_LABELS[status]}")
    return state


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
