def listings_nav(request):
    """Link back to the listings page as the viewer last left it (view, filters, sort, page)."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"listings_url": "/", "feed_unread": 0}
    session = getattr(request, "session", None)
    query = session.get("listing_query", "") if session is not None else ""
    from . import feed

    url_name = getattr(getattr(request, "resolver_match", None), "url_name", None)
    if url_name in ("feed", "feed_badge"):  # the Feed marks everything seen; the badge view counts itself
        return {"listings_url": f"/{query}", "feed_unread": 0}
    return {"listings_url": f"/{query}", "feed_unread": feed.unread_count(request.profile)}
