def listings_nav(request):
    """Link back to the listings page as the viewer last left it (view, filters, sort, page)."""
    session = getattr(request, "session", None)
    query = session.get("listing_query", "") if session is not None else ""
    from . import feed

    on_feed = getattr(getattr(request, "resolver_match", None), "url_name", None) == "feed"
    return {"listings_url": f"/{query}", "feed_unread": 0 if on_feed else feed.unread_count(request)}
