def listings_nav(request):
    """Link back to the listings page as the viewer last left it (view, filters, sort, page)."""
    session = getattr(request, "session", None)
    query = session.get("listing_query", "") if session is not None else ""
    return {"listings_url": f"/{query}"}
