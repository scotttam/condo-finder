"""The Search page: every filter, a configurable table, CSV, and the group's saved searches."""

import csv

from django.conf import settings
from django.core.paginator import Paginator
from django.http import HttpResponse, QueryDict
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

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


def column_keys(request):
    """Columns from the link (?cols=a,b) when it has them, else the person's own choice."""
    if request.GET.get("cols"):
        return search_columns.keys_from(request.GET["cols"].split(","))
    return search_columns.keys_from(request.profile.search_columns)


@require_POST
def save_columns(request):
    known = {column.key for column in search_columns.COLUMNS}
    keys = [] if request.POST.get("reset") else [key for key in request.POST.getlist("cols") if key in known]
    request.profile.search_columns = search_columns.keys_from(keys) if keys else []
    request.profile.save(update_fields=["search_columns"])
    target = f"{reverse('search')}?{query_string(QueryDict(request.POST.get('query', '')), cols=None, page=None)}"
    if request.headers.get("HX-Request"):
        response = HttpResponse("")
        response["HX-Redirect"] = target
        return response
    return redirect(target)


def search_page(request):
    form, queryset = searched(request)
    page_obj = Paginator(queryset.prefetch_related("source_listings__source", "price_changes"), PAGE_SIZE).get_page(
        request.GET.get("page"))
    listings = collab.decorate(page_obj.object_list, request.group, request.user)
    marks = search_index.highlights([listing.pk for listing in listings], form.cleaned_data.get("q"))
    for listing in listings:
        listing.hl = marks.get(listing.pk, {})
    keys = column_keys(request)
    current_sort = form.cleaned_data.get("sort") or ""
    return render(request, "listings/search.html", {
        "form": form,
        "page_obj": page_obj,
        "listings": listings,
        "column_keys": keys,
        "all_columns": search_columns.COLUMNS,
        "cols_param": request.GET.get("cols", ""),
        "headers": search_columns.headers(keys, current_sort, lambda sort: _url(form, sort=sort)),
        "query": query_string(form.data, page=None, cols=None),
        "filter_count": form.active_count(),
        "ignored": [f"{form[name].label}: {errors[0]}" for name, errors in form.errors.items()],
        "prev_url": _url(form, page=page_obj.previous_page_number()) if page_obj.has_previous() else "",
        "next_url": _url(form, page=page_obj.next_page_number()) if page_obj.has_next() else "",
        "clear_url": f"{reverse('search')}?q=",
    })


def _absolute(request, path):
    return f"{settings.PUBLIC_URL}{path}" if settings.PUBLIC_URL else request.build_absolute_uri(path)


def search_csv(request):
    _, queryset = searched(request)
    listings = collab.decorate(queryset.prefetch_related("source_listings__source", "price_changes"), request.group, request.user)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="search-{timezone.localtime():%Y%m%d-%H%M}.csv"'
    writer = csv.writer(response)
    writer.writerow([label for label, _ in search_columns.CSV_FIELDS] + ["Link"])
    for listing in listings:
        writer.writerow([search_columns.csv_cell(value(listing)) for _, value in search_columns.CSV_FIELDS]
                        + [_absolute(request, listing.get_absolute_url())])
    return response
