from datetime import date

from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from accounts.decorators import staff_required

from .filters import apply_filters
from .forms import HISTORY_EVENTS, ListingFilterForm, PriceEntryForm, TrackingForm, default_filter_data
from .models import Listing, PriceChange, SearchPriorities, Source, SourceRun, Status, TrendReport
from . import analyst, feed, trend_stats
from .charts import line_chart
from .ingest import refresh_source_listing
from .runner import is_running, run_all_in_background, sync_sources
from .scrapers.base import RefreshBlocked, Scraper
from .scrapers.registry import PLATFORMS, SOURCES, build_scraper
from .scheduler import next_run_time

PAGE_SIZE = 50
FEED_PAGE_SIZE = 100
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
    special = bool(listing.special_offer)
    classes = ["pin", drop and "pin-drop", special and "pin-special", status_class, not listing.is_active and "pin-off"]
    return {
        "label": f"{mark}{'↓' if drop else ''}{'★' if special else ''}{_short_price(listing.price)}",
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


def feed_page(request):
    """New listings and updates to listings you're tracking, newest first; unread since your last visit."""
    tab = request.GET.get("tab") if request.GET.get("tab") in ("new", "updates") else "all"
    show_apartments = request.GET.get("apartments") == "show"
    last_seen = feed.seen_at(request)
    page_obj = Paginator(feed.events(tab, show_apartments), FEED_PAGE_SIZE).get_page(request.GET.get("page"))
    today = timezone.localdate()
    rows = []
    for event in page_obj.object_list:
        day = timezone.localdate(event.created_at)
        happened = timezone.localdate(event.happened_at)
        rows.append({
            "event": event,
            "listing": event.listing,
            "label": feed.label(event),
            "unread": event.created_at > last_seen,
            "day": "Today" if day == today else "Yesterday" if (today - day).days == 1 else f"{day:%A, %b} {day.day}",
            "happened": happened if happened != day else None,
        })
    response = render(request, "listings/feed.html", {
        "rows": rows,
        "page_obj": page_obj,
        "tab": tab,
        "show_apartments": show_apartments,
        "unread": sum(row["unread"] for row in rows),
        "prev_url": _url_with(request, page=page_obj.previous_page_number()) if page_obj.has_previous() else "",
        "next_url": _url_with(request, page=page_obj.next_page_number()) if page_obj.has_next() else "",
    })
    response.set_cookie(feed.SEEN_COOKIE, timezone.now().isoformat(), max_age=60 * 60 * 24 * 365, samesite="Lax")
    return response


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
@staff_required
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
@staff_required
def history_add(request, pk):
    listing = get_object_or_404(Listing, pk=pk)
    form = PriceEntryForm(request.POST)
    if form.is_valid():
        PriceChange.objects.create(listing=listing, price=form.cleaned_data["price"], seen_at=form.seen_at(),
                                   event=form.cleaned_data["event"])
        return _history_response(request, listing)
    return _history_response(request, listing, add_form=form)


@staff_required
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
@staff_required
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
        template = "listings/_status_pills.html" if request.POST.get("variant") == "pills" else "listings/_status.html"
        return render(request, template, {"listing": listing})
    referer = request.META.get("HTTP_REFERER", "")
    if url_has_allowed_host_and_scheme(referer, allowed_hosts={request.get_host()}):
        return redirect(referer)
    return redirect("listing_list")


@staff_required
def sources(request):
    sync_sources()
    return render(request, "listings/sources.html", {
        "sources": Source.objects.all(),
        "runs": SourceRun.objects.select_related("source")[:40],
        "running": is_running(),
        "next_run": next_run_time(),
    })


@require_POST
@staff_required
def scrape_now(request):
    if is_running():
        messages.info(request, "A scrape is already running.")
    else:
        run_all_in_background()
        messages.success(request, "Scrape started. Refresh this page in a few minutes.")
    return redirect("sources")


def _trend_charts(weekly):
    weeks = weekly.get("weeks", [])
    return [
        {"title": "Median asking rent", "chart": line_chart(weekly.get("median_rent_by_city", {}), weeks, fmt="dollars")},
        {"title": "Listings with a price cut", "chart": line_chart({"Share": weekly.get("cut_share", [])}, weeks, fmt="percent")},
        {"title": "Median days on market", "chart": line_chart({"Days": weekly.get("median_dom", [])}, weeks, fmt="days")},
    ]


def trends_page(request):
    done = TrendReport.objects.filter(status=TrendReport.Status.DONE)
    newest = done.first()
    requested = request.GET.get("report", "")
    report = (done.filter(pk=requested).first() if requested.isdigit() else None) or newest
    latest = TrendReport.objects.first()
    stats = report.stats if report else {}
    snapshot = stats.get("now") or trend_stats.market_snapshot()
    weekly = stats.get("weekly") or trend_stats.weekly_series()
    picks = report.picks if report else []
    listings = Listing.objects.in_bulk([pick["listing_id"] for pick in picks])
    return render(request, "listings/trends.html", {
        "report": report,
        "is_latest": report == newest,
        "reports": done[:30],
        "changes": _trend_changes(report),
        "failed": latest if latest and latest.status == TrendReport.Status.FAILED else None,
        "picks": [{**pick, "listing": listings.get(pick["listing_id"])} for pick in picks],
        "snapshot": snapshot,
        "tracking_since": date.fromisoformat(weekly["tracking_since"]) if weekly.get("tracking_since") else None,
        "charts": _trend_charts(weekly),
        "priorities": SearchPriorities.get(),
        "configured": analyst.is_configured(),
        "running": analyst.is_running(),
        "runs_left": analyst.manual_runs_left(),
        "runs_per_day": settings.TRENDS_MANUAL_RUNS_PER_DAY,
    })


def _trend_changes(report):
    changes = report.changes if report else {}
    if not any(changes.get(key) for key in ("added", "dropped", "price_moves")):
        return None
    picks = {pick["listing_id"]: pick for pick in report.picks}
    return {
        "added": [picks[pk] for pk in changes.get("added", []) if pk in picks],
        "dropped": changes.get("dropped", []),
        "price_moves": changes.get("price_moves", []),
    }


@require_POST
def trends_run(request):
    if not analyst.is_configured():
        messages.error(request, "Add ANTHROPIC_API_KEY to .env and restart the app to run the analysis.")
    elif analyst.manual_runs_left() <= 0:
        limit = settings.TRENDS_MANUAL_RUNS_PER_DAY
        messages.info(request, f"You've used all {limit} re-runs for today. The daily report still runs after the morning scrape.")
    elif analyst.start_report(TrendReport.Trigger.MANUAL):
        messages.success(request, "Analysis started. It takes a minute or two.")
    else:
        messages.info(request, "An analysis is already running.")
    return redirect("trends")


@require_POST
def trends_priorities(request):
    priorities = SearchPriorities.get()
    priorities.text = request.POST.get("text", "")
    priorities.save()
    if request.headers.get("HX-Request"):
        return render(request, "listings/_priorities.html", {"priorities": priorities, "saved": True})
    return redirect("trends")


def trends_status(request):
    """Polled while an analysis runs; tells HTMX to reload the page once it's finished."""
    if analyst.is_running():
        return render(request, "listings/_trend_status.html")
    response = HttpResponse("")
    response["HX-Refresh"] = "true"
    return response
