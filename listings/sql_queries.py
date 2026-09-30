"""Starter queries for the SQL console, grouped by category. tests/test_sql_queries.py runs every one."""

from dataclasses import dataclass
from textwrap import dedent


@dataclass(frozen=True)
class CannedQuery:
    category: str
    title: str
    sql: str


LISTINGS = "Listings & market"
HISTORY = "Price history"
HEALTH = "Scraper health & data quality"
TRACKING = "Tracking & costs"


def _q(category, title, sql):
    return CannedQuery(category, title, dedent(sql).strip())


CANNED_QUERIES = [
    _q(LISTINGS, "Median rent by city and quadrant", """
        WITH priced AS (
          SELECT city, quadrant, price,
                 ROW_NUMBER() OVER (PARTITION BY city, quadrant ORDER BY price) AS rn,
                 COUNT(*) OVER (PARTITION BY city, quadrant) AS n
          FROM listings_listing
          WHERE is_active AND price IS NOT NULL
        )
        SELECT city, quadrant, n AS listings, CAST(ROUND(AVG(price)) AS INTEGER) AS median_price
        FROM priced
        WHERE rn IN ((n + 1) / 2, (n + 2) / 2)
        GROUP BY city, quadrant, n
        ORDER BY listings DESC
    """),
    _q(LISTINGS, "Price per square foot", """
        SELECT id AS listing_id, address, price, sqft, ROUND(1.0 * price / sqft, 2) AS price_per_sqft
        FROM listings_listing
        WHERE is_active AND price IS NOT NULL AND sqft > 0
        ORDER BY price_per_sqft
        LIMIT 100
    """),
    _q(LISTINGS, "Newest listings", """
        SELECT id AS listing_id, address, price, beds, baths, sqft, first_seen_at
        FROM listings_listing
        WHERE is_active
        ORDER BY first_seen_at DESC
        LIMIT 50
    """),
    _q(LISTINGS, "Longest on the market", """
        SELECT id AS listing_id, address, price, COALESCE(listed_at, date(first_seen_at)) AS since,
               CAST(julianday('now') - julianday(COALESCE(listed_at, first_seen_at)) AS INTEGER) AS days_on_market
        FROM listings_listing
        WHERE is_active
        ORDER BY days_on_market DESC
        LIMIT 50
    """),
    _q(LISTINGS, "Move-in specials", """
        SELECT id AS listing_id, address, price, special_offer
        FROM listings_listing
        WHERE is_active AND special_offer <> ''
        ORDER BY price
    """),
    _q(HISTORY, "Biggest price drops", """
        -- Current listing period only: history since each listing's latest "Listed for rent".
        WITH period AS (
          SELECT listing_id, MAX(CASE WHEN event = 'Listed for rent' THEN seen_at END) AS started
          FROM listings_pricechange
          GROUP BY listing_id
        )
        SELECT l.id AS listing_id, l.address, MAX(pc.price) AS highest_price, l.price AS current_price,
               MAX(pc.price) - l.price AS price_drop,
               ROUND(100.0 * (MAX(pc.price) - l.price) / MAX(pc.price), 1) AS drop_pct
        FROM listings_listing l
        JOIN period p ON p.listing_id = l.id
        JOIN listings_pricechange pc ON pc.listing_id = l.id AND (p.started IS NULL OR pc.seen_at >= p.started)
        WHERE l.is_active AND l.price IS NOT NULL
        GROUP BY l.id
        HAVING price_drop > 0
        ORDER BY price_drop DESC
        LIMIT 50
    """),
    _q(HISTORY, "Listings with several price cuts", """
        -- Current listing period only: history since each listing's latest "Listed for rent".
        WITH period AS (
          SELECT listing_id, MAX(CASE WHEN event = 'Listed for rent' THEN seen_at END) AS started
          FROM listings_pricechange
          GROUP BY listing_id
        ),
        steps AS (
          SELECT pc.listing_id, pc.price,
                 LAG(pc.price) OVER (PARTITION BY pc.listing_id ORDER BY pc.seen_at, pc.id) AS previous_price
          FROM listings_pricechange pc
          JOIN period p ON p.listing_id = pc.listing_id
          WHERE p.started IS NULL OR pc.seen_at >= p.started
        )
        SELECT l.id AS listing_id, l.address, l.price AS current_price, COUNT(*) AS cuts
        FROM steps
        JOIN listings_listing l ON l.id = steps.listing_id
        WHERE steps.price < steps.previous_price
        GROUP BY l.id
        HAVING cuts >= 2
        ORDER BY cuts DESC, l.price
    """),
    _q(HISTORY, "Recent price changes", """
        SELECT pc.listing_id, l.address, pc.price, pc.event, pc.source, pc.seen_at
        FROM listings_pricechange pc
        JOIN listings_listing l ON l.id = pc.listing_id
        ORDER BY pc.seen_at DESC, pc.id DESC
        LIMIT 100
    """),
    _q(HISTORY, "Hand-entered price history", """
        SELECT pc.listing_id, l.address, pc.price, pc.event, pc.seen_at
        FROM listings_pricechange pc
        JOIN listings_listing l ON l.id = pc.listing_id
        WHERE pc.source = ''
        ORDER BY pc.seen_at DESC
    """),
    _q(HEALTH, "Scrape runs by source (30 days)", """
        SELECT s.name AS source, COUNT(r.id) AS runs,
               COALESCE(SUM(r.ok), 0) AS ok,
               COALESCE(SUM(NOT r.ok AND r.finished_at IS NOT NULL), 0) AS failed,
               MAX(CASE WHEN r.ok THEN r.started_at END) AS last_ok,
               MAX(CASE WHEN NOT r.ok AND r.finished_at IS NOT NULL THEN r.started_at END) AS last_failure
        FROM listings_source s
        LEFT JOIN listings_sourcerun r ON r.source_id = s.id AND r.started_at >= datetime('now', '-30 days')
        GROUP BY s.id
        ORDER BY failed DESC, s.name
    """),
    _q(HEALTH, "Listings per source", """
        SELECT s.name AS source, s.platform,
               COUNT(CASE WHEN sl.is_active THEN 1 END) AS active,
               COUNT(sl.id) AS all_time
        FROM listings_source s
        LEFT JOIN listings_sourcelisting sl ON sl.source_id = s.id
        GROUP BY s.id
        ORDER BY active DESC, s.name
    """),
    _q(HEALTH, "Overlap between sites", """
        SELECT a.name AS site, b.name AS also_on, COUNT(*) AS listings
        FROM listings_sourcelisting x
        JOIN listings_sourcelisting y ON y.listing_id = x.listing_id AND y.source_id > x.source_id
        JOIN listings_source a ON a.id = x.source_id
        JOIN listings_source b ON b.id = y.source_id
        WHERE x.is_active AND y.is_active
        GROUP BY a.id, b.id
        ORDER BY listings DESC
    """),
    _q(HEALTH, "Missing geocode, sqft or beds", """
        SELECT id AS listing_id, address,
               latitude IS NULL AS no_geocode, sqft IS NULL AS no_sqft, beds IS NULL AS no_beds
        FROM listings_listing
        WHERE is_active AND (latitude IS NULL OR sqft IS NULL OR beds IS NULL)
        ORDER BY first_seen_at DESC
    """),
    _q(HEALTH, "Possible unit-number duplicates", """
        SELECT a.id AS listing_id, a.address, b.id AS with_unit_id, b.address AS with_unit_address,
               a.beds, a.baths, a.sqft, b.sqft AS with_unit_sqft, a.price, b.price AS with_unit_price
        FROM listings_listing a
        JOIN listings_listing b
          ON substr(b.address_key, 1, instr(b.address_key, '|') - 1) = substr(a.address_key, 1, instr(a.address_key, '|') - 1)
         AND b.zip_code = a.zip_code AND b.unit <> '' AND b.id <> a.id
        WHERE a.unit = '' AND instr(a.address_key, '|') > 0 AND a.is_active AND b.is_active
        ORDER BY a.address
    """),
    _q(TRACKING, "Listings by status, with notes", """
        SELECT id AS listing_id, address, status, price, is_active, notes, updated_at
        FROM listings_listing
        WHERE status <> 'new' OR notes <> ''
        ORDER BY CASE status WHEN 'applied' THEN 1 WHEN 'toured' THEN 2 WHEN 'interested' THEN 3
                             WHEN 'new' THEN 4 ELSE 5 END,
                 updated_at DESC
    """),
    _q(TRACKING, "Feed events by day and kind (30 days)", """
        SELECT date(created_at, 'localtime') AS day, kind, COUNT(*) AS events
        FROM listings_feedevent
        WHERE created_at >= datetime('now', '-30 days')
        GROUP BY day, kind
        ORDER BY day DESC, events DESC
    """),
    _q(TRACKING, "Trends report costs", """
        SELECT id, datetime(created_at, 'localtime') AS created, "trigger", status, model,
               input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, cost_usd
        FROM listings_trendreport
        ORDER BY created_at DESC
    """),
]


def by_category():
    groups = {}
    for query in CANNED_QUERIES:
        groups.setdefault(query.category, []).append(query)
    return list(groups.items())
