from django.contrib import messages
from django.core.paginator import Paginator
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .filters import apply_filters
from .forms import HISTORY_EVENTS, ListingFilterForm, PriceEntryForm, TrackingForm, default_filter_data
from .models import Listing, PriceChange, Source, SourceRun, Status
from .ingest import refresh_source_listing
from .runner import is_running, run_all_in_background, sync_sources
from .scrapers.base import RefreshBlocked, Scraper
from .scrapers.registry import PLATFORMS, SOURCES, build_scraper
from .scheduler import next_run_time

PAGE_SIZE = 50
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
    page_obj = Paginator(queryset.prefetch_related("source_listings__source", "price_changes"), PAGE_SIZE).get_page(
        request.GET.get("page")
    )
    return render(request, "listings/list.html", {
        "form": form,
        "filter_defaults": default_filter_data(),
        "view": view,
        "page_obj": page_obj,
        "listings": page_obj.object_list,
        "map_points": _map_points(page_obj.object_list) if view == "map" else [],
        "prev_url": _url_with(request, page=page_obj.previous_page_number()) if page_obj.has_previous() else "",
        "next_url": _url_with(request, page=page_obj.next_page_number()) if page_obj.has_next() else "",
        "map_url": _url_with(request, view="map"),
        "list_url": _url_with(request, view="list"),
    })


def _short_price(price):
    if not price:
        return "?"
    return f"${price // 1000}k" if price % 1000 == 0 else f"${price / 1000:.2f}".rstrip("0") + "k"


PIN_MARKS = {Status.INTERESTED: ("♥ ", "pin-liked"), Status.REJECTED: ("✕ ", "pin-rejected")}


def _pin_style(listing):
    mark, status_class = PIN_MARKS.get(listing.status, ("", ""))
    drop = listing.price_drop
    classes = ["pin", drop and "pin-drop", status_class, not listing.is_active and "pin-off"]
    return {
        "label": f"{mark}{'↓' if drop else ''}{_short_price(listing.price)}",
        "classes": " ".join(c for c in classes if c),
    }


def _map_points(listings):
    """Pins for the listings on this page, so every pin has a card beside it."""
    return [
        {
            "id": listing.pk,
            "lat": listing.latitude,
            "lng": listing.longitude,
            "short": _short_price(listing.price),
            "drop": bool(listing.price_drop),
            "status": listing.status,
            "active": listing.is_active,
            **_pin_style(listing),
            "url": listing.get_absolute_url(),
        }
        for listing in listings
        if listing.latitude is not None and listing.longitude is not None
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
    return render(request, "listings/detail.html", {
        **_history_context(listing),
        "listing": listing,
        "tracking_form": TrackingForm(instance=listing),
    })


REFRESHABLE_PLATFORMS = {
    name for name, scraper_class in PLATFORMS.items() if scraper_class.refresh_listing is not Scraper.refresh_listing
}


def _refreshable(listing):
    """This listing's pages on sites that can be re-fetched on demand (they publish price history)."""
    return [sl for sl in listing.source_listings.select_related("source") if sl.source.platform in REFRESHABLE_PLATFORMS]


@require_POST
def refresh_listing(request, pk):
    """'Refresh from sites': re-fetch this listing's pages now and report per site."""
    listing = get_object_or_404(Listing, pk=pk)
    configs = {config["key"]: config for config in SOURCES}
    for source_listing in _refreshable(listing):
        name = source_listing.source.name
        config = configs.get(source_listing.source.key)
        if config is None:
            continue
        scraper = build_scraper(config)
        try:
            summary = refresh_source_listing(source_listing, scraper.refresh_listing(source_listing.url), scraper.details_version)
        except RefreshBlocked:
            messages.warning(request, f"{name}: blocking requests right now; try again later.")
            continue
        except Exception as exc:  # report and carry on with the other sites
            messages.error(request, f"{name}: couldn't refresh ({type(exc).__name__}).")
            continue
        finally:
            getattr(scraper.fetcher, "close", lambda: None)()
        if summary["removed"]:
            messages.info(request, f"{name}: no longer listed.")
        else:
            entries = summary["new_entries"]
            text = f"{entries} new history entr{'y' if entries == 1 else 'ies'}" if entries else "no new history"
            price = f", price ${summary['price']:,}" if summary["price"] else ""
            messages.success(request, f"{name}: {text}{price}.")
    if request.headers.get("HX-Request"):
        response = render(request, "listings/_history.html", _history_context(listing))
        response["HX-Refresh"] = "true"  # price, features and sources may all have changed
        return response
    return redirect(listing)


def _history_context(listing, **extra):
    listing = Listing.objects.prefetch_related("price_changes").get(pk=listing.pk)
    return {
        "listing": listing,
        "add_form": PriceEntryForm(initial={"date": timezone.localdate(), "price": listing.price}),
        "history_events": HISTORY_EVENTS,
        "refreshable": bool(_refreshable(listing)),
        **extra,
    }


def _history_response(request, listing, add_form=None, editing=None, edit_form=None):
    """The price history panel (HTMX swaps it in place), or back to the listing without HTMX."""
    if not request.headers.get("HX-Request"):
        return redirect(listing)
    context = _history_context(listing, editing=editing, edit_form=edit_form)
    if add_form is not None:
        context["add_form"] = add_form
    return render(request, "listings/_history.html", context)


@require_POST
def history_add(request, pk):
    listing = get_object_or_404(Listing, pk=pk)
    form = PriceEntryForm(request.POST)
    if form.is_valid():
        PriceChange.objects.create(listing=listing, price=form.cleaned_data["price"], seen_at=form.seen_at(),
                                   event=form.cleaned_data["event"])
        return _history_response(request, listing)
    return _history_response(request, listing, add_form=form)


def history_edit(request, pk, change_pk):
    listing = get_object_or_404(Listing, pk=pk)
    change = get_object_or_404(PriceChange, pk=change_pk, listing=listing)
    if request.GET.get("cancel"):
        return _history_response(request, listing)
    if request.method == "POST":
        form = PriceEntryForm(request.POST)
        if form.is_valid():
            change.seen_at = form.seen_at()
            change.price = form.cleaned_data["price"]
            change.event = form.cleaned_data["event"]
            change.save(update_fields=["seen_at", "price", "event"])
            return _history_response(request, listing)
        return _history_response(request, listing, editing=change.pk, edit_form=form)
    return _history_response(request, listing, editing=change.pk, edit_form=PriceEntryForm.for_change(change))


@require_POST
def history_delete(request, pk, change_pk):
    listing = get_object_or_404(Listing, pk=pk)
    get_object_or_404(PriceChange, pk=change_pk, listing=listing).delete()
    return _history_response(request, listing)


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
