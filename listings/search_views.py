"""The Search page: every filter, a configurable table, CSV, and the group's saved searches."""

from django.core.paginator import Paginator
from django.http import QueryDict
from django.shortcuts import render
from django.urls import reverse

from . import collab, search_columns, search_index
from .filters import apply_filters
from .forms import ListingFilterForm, default_filter_data
from .models import Listing

PAGE_SIZE = 100
STATE_PARAMS = {"page", "cols", "saved"}  # not filters: a URL with only these starts from the group's defaults


def search_form(request):
    """The URL's search, or the group's defaults (sorted by best match) when the URL has no filters."""
    if any(key not in STATE_PARAMS for key in request.GET):
        return ListingFilterForm(request.GET)
    return ListingFilterForm({**default_filter_data(request.group), "sort": ""})


def query_string(data, **changes):
    """A URL query for a search's data (a QueryDict, or a dict of defaults whose values may be lists), with
    changes applied; a change of None removes that key. Links are built from this, not request.GET, so a page
    that started from the defaults keeps them."""
    query = QueryDict(mutable=True)
    for key in data:
        values = data.getlist(key) if isinstance(data, QueryDict) else data[key]
        values = values if isinstance(values, (list, tuple)) else [values]
        query.setlist(key, [str(value) for value in values])
    for key, value in changes.items():
        if value is None:
            query.pop(key, None)
        else:
            query[key] = value
    return query.urlencode()


def searched(request):
    form = search_form(request)
    form.is_valid()  # a bad value drops that one filter: cleaned_data keeps the rest
    return form, apply_filters(Listing.objects.all(), form.cleaned_data, request.group)


def _url(form, **changes):
    return f"{reverse('search')}?{query_string(form.data, **{'page': None, **changes})}"


def search_page(request):
    form, queryset = searched(request)
    page_obj = Paginator(queryset.prefetch_related("source_listings__source", "price_changes"), PAGE_SIZE).get_page(
        request.GET.get("page"))
    listings = collab.decorate(page_obj.object_list, request.group, request.user)
    marks = search_index.highlights([listing.pk for listing in listings], form.cleaned_data.get("q"))
    for listing in listings:
        listing.hl = marks.get(listing.pk, {})
    column_keys = search_columns.DEFAULT_KEYS
    current_sort = form.cleaned_data.get("sort") or ""
    return render(request, "listings/search.html", {
        "form": form,
        "page_obj": page_obj,
        "listings": listings,
        "column_keys": column_keys,
        "headers": search_columns.headers(column_keys, current_sort, lambda sort: _url(form, sort=sort)),
        "query": query_string(form.data, page=None),
        "filter_count": form.active_count(),
        "ignored": [f"{form[name].label}: {errors[0]}" for name, errors in form.errors.items()],
        "prev_url": _url(form, page=page_obj.previous_page_number()) if page_obj.has_previous() else "",
        "next_url": _url(form, page=page_obj.next_page_number()) if page_obj.has_next() else "",
        "clear_url": f"{reverse('search')}?q=",
    })
