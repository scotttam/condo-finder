from django.contrib import messages
from django.core.paginator import Paginator
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .filters import apply_filters
from .forms import ListingFilterForm, TrackingForm, default_filter_data
from .models import Listing, Source, SourceRun, Status
from .runner import is_running, run_all_in_background, sync_sources
from .scheduler import next_run_time

PAGE_SIZE = 50
MAX_MAP_POINTS = 3000
VIEWS = ("map", "list")
NON_FILTER_PARAMS = {"view", "page"}


def listing_list(request):
    requested = request.GET.get("view")
    view = requested if requested in VIEWS else request.session.get("listing_view", "map")
    request.session["listing_view"] = view
    request.session["listing_query"] = f"?{request.GET.urlencode()}" if request.GET else ""
    has_filters = any(key not in NON_FILTER_PARAMS for key in request.GET)
    form = ListingFilterForm(request.GET if has_filters else default_filter_data())
    queryset = Listing.objects.all()
    if form.is_valid():
        queryset = apply_filters(queryset, form.cleaned_data)
    page_obj = Paginator(queryset.prefetch_related("source_listings__source"), PAGE_SIZE).get_page(
        request.GET.get("page")
    )
    return render(request, "listings/list.html", {
        "form": form,
        "view": view,
        "page_obj": page_obj,
        "listings": page_obj.object_list,
        "map_points": _map_points(queryset) if view == "map" else [],
        "prev_url": _url_with(request, page=page_obj.previous_page_number()) if page_obj.has_previous() else "",
        "next_url": _url_with(request, page=page_obj.next_page_number()) if page_obj.has_next() else "",
        "map_url": _url_with(request, view="map"),
        "list_url": _url_with(request, view="list"),
    })


def _map_points(queryset):
    """Pins for every matching listing (not just the current page)."""
    rows = queryset.filter(latitude__isnull=False).values("pk", "latitude", "longitude", "price", "beds", "street")
    return [
        {
            "id": row["pk"],
            "lat": row["latitude"],
            "lng": row["longitude"],
            "label": f"${row['price']:,} · {row['beds']}bd · {row['street']}" if row["price"] else row["street"],
            "url": reverse("listing_detail", args=[row["pk"]]),
        }
        for row in rows[:MAX_MAP_POINTS]
    ]


def _url_with(request, **params):
    query = request.GET.copy()
    for key, value in params.items():
        query[key] = value
    return f"?{query.urlencode()}"


def listing_detail(request, pk):
    listing = get_object_or_404(
        Listing.objects.prefetch_related("source_listings__source", "price_changes"), pk=pk
    )
    return render(request, "listings/detail.html", {"listing": listing, "tracking_form": TrackingForm(instance=listing)})


@require_POST
def update_tracking(request, pk):
    listing = get_object_or_404(Listing, pk=pk)
    form = TrackingForm(request.POST, instance=listing)
    saved = form.is_valid()
    if saved:
        form.save()
    if request.headers.get("HX-Request"):
        return render(request, "listings/_tracking.html", {"listing": listing, "tracking_form": form, "saved": saved})
    return redirect(listing)


@require_POST
def set_status(request, pk):
    listing = get_object_or_404(Listing, pk=pk)
    status = request.POST.get("status")
    if status not in Status.values:
        return HttpResponseBadRequest("invalid status")
    listing.status = status
    listing.save(update_fields=["status", "updated_at"])
    if request.headers.get("HX-Request"):
        return render(request, "listings/_status.html", {"listing": listing})
    referer = request.META.get("HTTP_REFERER", "")
    if url_has_allowed_host_and_scheme(referer, allowed_hosts={request.get_host()}):
        return redirect(referer)
    return redirect("listing_list")


def sources(request):
    sync_sources()
    return render(request, "listings/sources.html", {
        "sources": Source.objects.all(),
        "runs": SourceRun.objects.select_related("source")[:40],
        "running": is_running(),
        "next_run": next_run_time(),
    })


@require_POST
def scrape_now(request):
    if is_running():
        messages.info(request, "A scrape is already running.")
    else:
        run_all_in_background()
        messages.success(request, "Scrape started. Refresh this page in a few minutes.")
    return redirect("sources")
