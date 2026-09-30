"""The Trends analysis: Claude reads the current candidates, our comments and the market statistics,
and picks the best options right now, with a negotiation angle for each.

Two passes keep it affordable. Pass 1 sees compact facts for every candidate and returns a
shortlist. Pass 2 sees the shortlist's full descriptions and returns the ranked picks and a read on
the market. A report runs in a background thread, one at a time.
"""

import json
import logging
import os
import threading
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import close_old_connections
from django.db.models import Q
from django.utils import timezone

from accounts.groups import owners_group
from accounts.models import display_name

from . import trend_stats
from .collab import attach_comments, decorate
from .filters import apply_filters
from .forms import ListingFilterForm, default_filter_data
from .models import Listing, ListingState, SearchPriorities, Status, TrendReport, Vote

log = logging.getLogger(__name__)

MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_TOKENS = 32000
SHORTLIST_SIZE = 25
PICKS = 5
DESCRIPTION_LIMIT = 4000
STALE_AFTER = timedelta(minutes=30)  # a "running" report older than this was interrupted
# USD per million tokens, Claude Opus 5.5
RATES = {"input": Decimal("4"), "output": Decimal("20"), "cache_read": Decimal("0.20"), "cache_write": Decimal("5")}
TRACKED = (Status.INTERESTED, Status.TOURED, Status.APPLIED)

_lock = threading.Lock()


class AnalystError(Exception):
    pass


# --- What Claude sees ---


def _prepare(listings, group):
    """The group's view of these listings (status and comments), as compact_facts reads it."""
    return attach_comments(decorate(listings, group), group)


def candidates(group):
    """Listings that pass the default filters, plus active listings the group marked as interesting."""
    form = ListingFilterForm(default_filter_data(group))
    form.is_valid()
    matching = apply_filters(Listing.objects.all(), form.cleaned_data, group).values("pk")
    tracked = ListingState.objects.filter(group=group, status__in=TRACKED, listing__is_active=True).values("listing")
    pool = (
        Listing.objects.filter(Q(pk__in=matching) | Q(pk__in=tracked))
        .prefetch_related("price_changes", "source_listings__source")
        .order_by("price", "pk")
    )
    return _prepare(pool, group)


def passed_on(group, limit=40):
    """Listings the group rejected, most recent first: they show what it doesn't want."""
    ids = list(
        ListingState.objects.filter(group=group, status=Status.REJECTED)
        .order_by("-status_at", "-pk").values_list("listing_id", flat=True)[:limit]
    )
    by_id = Listing.objects.prefetch_related("price_changes").in_bulk(ids)
    return _prepare([by_id[pk] for pk in ids if pk in by_id], group)


def _yes_no(value):
    return "unknown" if value is None else "yes" if value else "no"


def _parking(listing):
    if listing.parking_spaces is not None:
        return f"{listing.parking_spaces} spaces" if listing.parking_spaces else "none"
    if listing.has_parking:
        return "yes, number of spaces not stated"
    return "none" if listing.has_parking is False else "unknown"


def compact_facts(listing):
    return {
        "id": listing.pk,
        "address": f"{listing.street} #{listing.unit}" if listing.unit else listing.street,
        "area": listing.location_label,
        "type": listing.get_property_type_display(),
        "price": listing.price,
        "beds": listing.beds,
        "baths": float(listing.baths) if listing.baths is not None else None,
        "sqft": listing.sqft,
        "price_per_sqft": listing.price_per_sqft,
        "parking": _parking(listing),
        "wd": _yes_no(listing.has_washer_dryer),
        "ac": _yes_no(listing.has_ac),
        "outdoor": _yes_no(listing.has_outdoor_space),
        "furnished": _yes_no(listing.is_furnished),
        "available": listing.available,
        "special_offer": listing.special_offer,
        "effective_rent_12mo": listing.effective_rent,
        "days_on_market": listing.days_on_market,
        "on_market": listing.is_active,
        "price_history": [
            [timezone.localdate(change.seen_at).isoformat(), change.price, change.event]
            for change in list(listing.price_changes.all())[-8:]
        ],
        "status": listing.group_status,
        "votes": {display_name(vote.user): "like" if vote.value == Vote.Value.UP else "dislike" for vote in listing.group_votes},
        "comments": [
            {"by": comment.by, "date": timezone.localdate(comment.created_at).isoformat(), "text": comment.body}
            for comment in listing.group_comments
        ],
    }


def full_facts(listing):
    return {**compact_facts(listing), "title": listing.title, "description": listing.description[:DESCRIPTION_LIMIT]}


# --- Prompts ---

SYSTEM = """You help a couple find a condo to rent in Portland, Lake Oswego or Beaverton, Oregon. They want \
a condo or townhome in a small building (not an apartment complex) with 2+ bedrooms, 2+ bathrooms and \
2 parking spaces, and treat in-unit washer/dryer, air conditioning and outdoor space as must-haves. \
Their budget reaches about $5,000 a month.

You are given listings gathered from property-manager sites, Zillow, Redfin and Craigslist. Parking and \
amenities were parsed from listing text: "unknown" means the listing didn't say, not that it's missing. \
Each listing's price history shows how its asking rent has moved, and special_offer quotes any \
move-in special (weeks free, dollars off), with effective_rent_12mo when its value is stated: count \
specials toward value, and note that a landlord already offering one may have more room to negotiate. Their own comments and statuses \
(interested, toured, applied, rejected) are the strongest signal of their taste: favor what they liked, \
steer away from what they rejected and why, and weigh what they wrote under "What we're looking for" \
above your own assumptions.

Be concrete and honest. Name the specific facts behind each judgment, and say when something is \
unknown and worth asking about rather than guessing."""

SHORTLIST_TASK = f"""Pick the {SHORTLIST_SIZE} listings most worth a closer look right now, best first. Only use ids \
from the candidates list. Give a few words on why for each."""

PICKS_TASK = f"""From the shortlist, choose the top {PICKS} options right now, ranked. For each:
- headline: one line on what makes it stand out.
- why: 2-3 sentences on why it fits them, citing specific facts.
- concerns: the real drawbacks and unknowns.
- questions: what to ask the landlord or check on a tour.
- leverage: their negotiating position, from price cuts, days on market and how its price compares to \
similar listings and the market medians.
- offer_low / offer_high: a monthly rent range worth proposing, in whole dollars, at or below the asking \
price. Use the asking price for both if there's no leverage.

Only pick ids from the shortlist, never one they rejected. Then write market_read: 2-4 short paragraphs \
on how rents are moving, where the negotiating room is, and what that means for their timing. Finish \
with summary: one sentence for the top of the page. Write plain text throughout, without Markdown."""

SHORTLIST_SCHEMA = {
    "type": "object",
    "properties": {
        "shortlist": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "integer"}, "reason": {"type": "string"}},
                "required": ["id", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["shortlist"],
    "additionalProperties": False,
}

PICKS_SCHEMA = {
    "type": "object",
    "properties": {
        "picks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "headline": {"type": "string"},
                    "why": {"type": "string"},
                    "concerns": {"type": "array", "items": {"type": "string"}},
                    "questions": {"type": "array", "items": {"type": "string"}},
                    "leverage": {"type": "string"},
                    "offer_low": {"type": "integer"},
                    "offer_high": {"type": "integer"},
                },
                "required": ["id", "headline", "why", "concerns", "questions", "leverage", "offer_low", "offer_high"],
                "additionalProperties": False,
            },
        },
        "market_read": {"type": "string"},
        "summary": {"type": "string"},
    },
    "required": ["picks", "market_read", "summary"],
    "additionalProperties": False,
}


def _section(title, value):
    body = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return f"<{title}>\n{body}\n</{title}>"


def _context(stats):
    priorities = SearchPriorities.get(owners_group()).text.strip() or "(nothing written yet)"
    return [
        f"Today is {timezone.localdate():%A, %B %-d, %Y}.",
        _section("what_we_are_looking_for", priorities),
        _section("market_statistics", stats),
    ]


def _shortlist_prompt(stats, pool):
    return "\n\n".join([*_context(stats), _section("candidates", [compact_facts(l) for l in pool]), SHORTLIST_TASK])


def _picks_prompt(stats, shortlisted, rejected, previous):
    parts = [
        *_context(stats),
        _section("shortlist", [full_facts(l) for l in shortlisted]),
        _section("rejected_by_us", [compact_facts(l) for l in rejected]),
    ]
    if previous:
        earlier = [{"id": p["listing_id"], "rank": p["rank"], "headline": p["headline"]} for p in previous.picks]
        parts.append(_section(f"previous_picks_{timezone.localdate(previous.created_at).isoformat()}", earlier))
    parts.append(PICKS_TASK)
    return "\n\n".join(parts)


# --- Calling Claude ---


def is_configured():
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def _ask(client, prompt, schema, effort):
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        betas=[FALLBACK_BETA],
        fallbacks="default",  # a declined request is retried on Anthropic's recommended fallback model
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
    ) as stream:
        message = stream.get_final_message()
    if message.stop_reason == "refusal":
        category = getattr(message.stop_details, "category", None)
        raise AnalystError(f"Claude declined this request{f' ({category})' if category else ''}.")
    if message.stop_reason == "max_tokens":
        raise AnalystError("Claude's answer ran past the length limit.")
    text = next((block.text for block in message.content if block.type == "text"), None)
    if not text:
        raise AnalystError("Claude returned no answer.")
    return json.loads(text), message


def cost_of(usage):
    million = Decimal(1_000_000)
    total = (
        usage.input_tokens * RATES["input"]
        + usage.output_tokens * RATES["output"]
        + (usage.cache_read_input_tokens or 0) * RATES["cache_read"]
        + (usage.cache_creation_input_tokens or 0) * RATES["cache_write"]
    ) / million
    return total.quantize(Decimal("0.0001"))


def _add_usage(report, message):
    usage = message.usage
    report.input_tokens += usage.input_tokens
    report.output_tokens += usage.output_tokens
    report.cache_read_tokens += usage.cache_read_input_tokens or 0
    report.cache_write_tokens += usage.cache_creation_input_tokens or 0
    report.cost_usd = Decimal(report.cost_usd) + cost_of(usage)
    report.model = message.model


def _clean_picks(raw, by_id):
    picks, seen = [], set()
    for item in raw:
        listing = by_id.get(item.get("id"))
        if listing is None or listing.pk in seen or listing.group_status == Status.REJECTED:
            continue
        seen.add(listing.pk)
        picks.append({
            "listing_id": listing.pk,
            "rank": len(picks) + 1,
            "headline": item.get("headline", ""),
            "why": item.get("why", ""),
            "concerns": list(item.get("concerns") or []),
            "questions": list(item.get("questions") or []),
            "leverage": item.get("leverage", ""),
            "offer_low": item.get("offer_low"),
            "offer_high": item.get("offer_high"),
            "price_at_pick": listing.price,
            "address": f"{listing.street} #{listing.unit}" if listing.unit else listing.street,
            "photo_url": listing.photo_url,
        })
        if len(picks) == PICKS:
            break
    return picks


def diff_picks(previous_picks, picks, listings_by_id):
    """What changed since the previous report: new picks, dropped picks (and why, when we know),
    and price moves on picks that stayed."""
    before = {p["listing_id"]: p for p in previous_picks}
    now_ids = {p["listing_id"] for p in picks}
    dropped = []
    for pick in previous_picks:
        if pick["listing_id"] in now_ids:
            continue
        listing = listings_by_id.get(pick["listing_id"])
        why = ""
        if listing is None:
            why = "no longer in the database"
        elif listing.group_status == Status.REJECTED:
            why = "you rejected it"
        elif not listing.is_active:
            why = "off the market"
        dropped.append({"id": pick["listing_id"], "headline": pick.get("headline", ""), "address": pick.get("address", ""), "why": why})
    moves = [
        {"id": p["listing_id"], "address": p["address"], "from": before[p["listing_id"]]["price_at_pick"], "to": p["price_at_pick"]}
        for p in picks
        if p["listing_id"] in before and before[p["listing_id"]].get("price_at_pick") not in (None, p["price_at_pick"])
    ]
    return {"added": [p["listing_id"] for p in picks if p["listing_id"] not in before], "dropped": dropped, "price_moves": moves}


def run_report(trigger=TrendReport.Trigger.MANUAL, client=None, report=None):
    """Runs both passes and saves the report. Never raises: a failure is saved on the report."""
    report = report or TrendReport.objects.create(trigger=trigger)
    try:
        group = owners_group()  # Task 14 makes reports per group
        previous = TrendReport.objects.filter(status=TrendReport.Status.DONE).exclude(pk=report.pk).first()
        pool = candidates(group)
        if not pool:
            raise AnalystError("No listings match the default filters yet, so there's nothing to analyze.")
        stats = {"now": trend_stats.market_snapshot(), "weekly": trend_stats.weekly_series()}
        report.stats = stats
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        by_id = {listing.pk: listing for listing in pool}

        answer, message = _ask(client, _shortlist_prompt(stats, pool), SHORTLIST_SCHEMA, effort="medium")
        _add_usage(report, message)
        shortlist = []
        for item in answer.get("shortlist", []):
            if item.get("id") in by_id and item["id"] not in shortlist:
                shortlist.append(item["id"])
        shortlist = shortlist[:SHORTLIST_SIZE]
        if not shortlist:
            raise AnalystError("Claude's shortlist didn't include any known listings.")
        report.shortlist = shortlist

        rejected = passed_on(group)
        prompt = _picks_prompt(stats, [by_id[pk] for pk in shortlist], rejected, previous)
        answer, message = _ask(client, prompt, PICKS_SCHEMA, effort="high")
        _add_usage(report, message)
        report.picks = _clean_picks(answer.get("picks", []), {pk: by_id[pk] for pk in shortlist})
        report.market_read = answer.get("market_read", "")
        report.summary = answer.get("summary", "")
        if previous:
            ids = {p["listing_id"] for p in previous.picks}
            listings = _prepare(Listing.objects.in_bulk(ids).values(), group)
            report.changes = diff_picks(previous.picks, report.picks, {l.pk: l for l in listings})
        report.status = TrendReport.Status.DONE
    except Exception as exc:  # a failed report is shown on the page; the scheduler must keep going
        log.exception("Trend report %s failed", report.pk)
        report.status = TrendReport.Status.FAILED
        report.error = str(exc) if isinstance(exc, AnalystError) else f"{type(exc).__name__}: {exc}"
    report.finished_at = timezone.now()
    report.save()
    return report


# --- Running in the background ---


def _running_reports():
    return TrendReport.objects.filter(status=TrendReport.Status.RUNNING)


def is_running():
    return _lock.locked() or _running_reports().filter(created_at__gte=timezone.now() - STALE_AFTER).exists()


def _launch(report):
    def target():
        try:
            run_report(report=report)
        finally:
            _lock.release()
            close_old_connections()

    threading.Thread(target=target, name="trend-report", daemon=True).start()


def start_report(trigger):
    """Starts a report in the background. False if one is already running."""
    if not _lock.acquire(blocking=False):
        return False
    try:
        if _running_reports().filter(created_at__gte=timezone.now() - STALE_AFTER).exists():
            _lock.release()
            return False
        # Reports left "running" by a restart never finished.
        _running_reports().update(
            status=TrendReport.Status.FAILED, error="Interrupted before it finished.", finished_at=timezone.now()
        )
        report = TrendReport.objects.create(trigger=trigger)
    except Exception:
        _lock.release()
        raise
    _launch(report)  # releases the lock when the report finishes
    return True


def _today_start():
    return timezone.make_aware(datetime.combine(timezone.localdate(), time.min))


def manual_runs_left():
    used = TrendReport.objects.filter(trigger=TrendReport.Trigger.MANUAL, created_at__gte=_today_start()).count()
    return max(settings.TRENDS_MANUAL_RUNS_PER_DAY - used, 0)


def run_daily_if_due():
    """Starts today's automatic report, once per day, if an API key is set."""
    if not is_configured():
        return False
    done_today = TrendReport.objects.filter(
        trigger=TrendReport.Trigger.AUTO, created_at__gte=_today_start()
    ).exclude(status=TrendReport.Status.FAILED)
    if done_today.exists():
        return False
    return start_report(TrendReport.Trigger.AUTO)
