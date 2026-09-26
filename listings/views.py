from django.contrib import messages
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .filters import apply_filters
from .forms import ListingFilterForm, TrackingForm, default_filter_data
from .models import Listing, Source, SourceRun, Status
from .runner import is_running, run_all_in_background, sync_sources

MAX_RESULTS = 500


def listing_list(request):
    form = ListingFilterForm(request.GET or default_filter_data())
    queryset = Listing.objects.all()
    if form.is_valid():
        queryset = apply_filters(queryset, form.cleaned_data)
    listings = list(queryset[:MAX_RESULTS])
    map_points = [
        {
            "id": listing.pk,
            "lat": listing.latitude,
            "lng": listing.longitude,
            "label": f"${listing.price:,} · {listing.beds}bd · {listing.street}" if listing.price else listing.street,
            "url": listing.get_absolute_url(),
        }
        for listing in listings
        if listing.latitude is not None
    ]
    return render(request, "listings/list.html", {"form": form, "listings": listings, "map_points": map_points})


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
    })


@require_POST
def scrape_now(request):
    if is_running():
        messages.info(request, "A scrape is already running.")
    else:
        run_all_in_background()
        messages.success(request, "Scrape started. Refresh this page in a few minutes.")
    return redirect("sources")
