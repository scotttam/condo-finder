# Plan decisions: Jev decision model for Trends, fit scores and parsing

Decided 2026-10-08 in a grill-me session.

## Problem

A Trends report costs about $1 per run (two Opus 5.5 calls in `listings/analyst.py`, no prompt caching;
#75's discovery set made both calls bigger). Trends is paused with `TRENDS_ENABLED=0` (#76).

## What Jev is (as described by the owner)

A discriminative transformer model for classification and regression. It does zero-shot prediction over
categories supplied at request time, needs no training, and returns typed values with probabilities and
confidence scores. It does not write prose, and its output is meant for software to consume.
Hosting and pricing are **not known yet**.

## Decisions

### Trends report
1. **Jev replaces both Claude passes.** Ranking the shortlist, the top 5 picks and the discoveries comes from
   Jev scores. The default engine makes no LLM call.
2. **Offer range is rule-based.** It's a plain Python formula: start at asking rent, then discount for days on
   market, price cuts so far, move-in specials and how far the rent sits above the comparable median
   (`trend_stats`). The output is `offer_low` / `offer_high`, and the leverage line names the facts behind it.
3. **Pick text comes from templates.** Jev labels each pick (which priorities it matches, with confidence).
   Python turns labels and facts into short "why" lines. Concerns and landlord questions come from unknown
   fields ("Parking not stated: ask") and the misses.
4. **Taste signal = priorities + labeled examples.** Each Jev request sends "What we're looking for" as the
   category descriptions, plus voted-up, toured, interested and applied listings as positive examples and
   rejected or voted-down listings as negative examples, with comment text.
5. **Market read = templated stat sentences.** It's 3–5 bullets from `trend_stats` (median moves by city,
   price-cut share, days on market). The summary line names the #1 pick and the market direction.
6. **Claude stays as an opt-in engine.** `TRENDS_ENGINE=jev|claude`, with `jev` the default. The Claude
   engine keeps today's behavior, `TRENDS_ENABLED` and the daily cap. Old reports stay viewable.

### Beyond Trends (in scope)
7. **Per-group fit score on every listing.** Stored per (group, listing): score, confidence, matched and
   missed labels, scored_at. The Trends top 5 reads from these scores.
   - **Rescoring:** after each scrape, score new or changed listings only. Once a night, rescore all active
     listings for each active group (someone logged in within 14 days) so votes, statuses and priorities
     take effect.
   - **Display:** a "Strong fit" / "Good fit" tier pill on cards, the table and map pins, and nothing for weak
     fits. The probability and top matched/missed reasons show on hover and on the listing page.
     Low-confidence scores show no pill. Add a "Best fit" sort, and the Feed highlights strong matches.
8. **Jev parsing fallback.** When regex leaves parking, W/D, AC, furnished or special offer unknown, ask
   Jev. Fill the field only if confidence ≥ a setting (e.g. 0.85). Store the source and confidence, show a
   subtle "inferred" hint, and let admin overrides win. Regex values are never overwritten.

### Infrastructure
9. **Client interface plus fake.** Hosting is undecided, so Jev sits behind a small client interface with a
   `FakeJev` for tests (like `FakeClient` in `tests/test_analyst.py`). Tests never call the real service.
   Configuration such as `JEV_API_KEY` waits until hosting is chosen.
10. **Guardrails.** Log every Jev call (purpose, item count, cost when known) and show totals on the Sources
    page. `JEV_DAILY_CALL_LIMIT` stops new work once reached. `JEV_ENABLED=0` turns Jev off entirely, and
    the app falls back to regex parsing and the rule-only heuristic score.

### Later (not in this plan)
- Scam or junk flags for Craigslist posts.
- Jev-assisted duplicate matching for pairs `merge.py` can't decide.

## Rollout: stacked PRs, Jev-free first
1. Trends engine setting (`TRENDS_ENGINE`) and the rule-based report: offer formula, stat sentences and
   templates over a simple heuristic score. Trends runs free right away.
2. Jev client interface, `FakeJev`, call log, daily cap and kill switch.
3. Per-group fit scores: model, scoring after each scrape and nightly, tier pill, tooltip and "Best fit" sort.
4. Trends ranks its picks and discoveries from fit scores, with Jev labels feeding the templates.
5. Jev parsing fallback with the confidence threshold and the "inferred" hint.

## Open questions
- Jev's hosting (hosted API vs. local on the Mac mini), pricing, batch size and rate limits. These decide
  the PR 2 client details and the cost numbers in the call log.


#TODO - do this but remove this from the doc first. 
Next steps, from CLAUDE.md:
1. Turn Superpowers on: run /plugin, enable superpowers, then /clear.
2. Run:

/superpowers:writing-plans docs/plan-decisions.md

claude-yolo --resume a200545c-6664-47fd-813c-1fb2ff538cdb