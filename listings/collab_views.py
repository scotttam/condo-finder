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
