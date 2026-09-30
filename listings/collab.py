"""What a search group says about listings: its shared status (later also votes and comments).
Scraped data on Listing is global; everything here is per group."""

from django.db import models
from django.db.models import OuterRef, Subquery, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from accounts.models import display_name

from . import feed
from .models import FeedEvent, ListingState, Status

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
    if user is not None:
        feed.record_activity(listing, group, user, FeedEvent.Kind.STATUS,
                             f"{display_name(user)} marked it {STATUS_LABELS[status]}")
    return state
