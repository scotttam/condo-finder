"""Keyword search: an FTS5 index over listings, kept in sync by triggers (so QuerySet.update is covered too)."""

from django.db import migrations

COLUMNS = "title, description, address, neighborhood"
NEW = "new.title, new.description, new.address, new.neighborhood"
OLD = "old.title, old.description, old.address, old.neighborhood"

FORWARD = [
    f"""CREATE VIRTUAL TABLE listing_search USING fts5({COLUMNS}, content='listings_listing', content_rowid='id',
        tokenize='porter unicode61 remove_diacritics 2')""",
    f"""CREATE TRIGGER listing_search_ai AFTER INSERT ON listings_listing BEGIN
        INSERT INTO listing_search(rowid, {COLUMNS}) VALUES (new.id, {NEW});
    END""",
    f"""CREATE TRIGGER listing_search_ad AFTER DELETE ON listings_listing BEGIN
        INSERT INTO listing_search(listing_search, rowid, {COLUMNS}) VALUES ('delete', old.id, {OLD});
    END""",
    f"""CREATE TRIGGER listing_search_au AFTER UPDATE OF {COLUMNS} ON listings_listing BEGIN
        INSERT INTO listing_search(listing_search, rowid, {COLUMNS}) VALUES ('delete', old.id, {OLD});
        INSERT INTO listing_search(rowid, {COLUMNS}) VALUES (new.id, {NEW});
    END""",
    "INSERT INTO listing_search(listing_search) VALUES ('rebuild')",  # index the listings already there
]

BACKWARD = [
    "DROP TRIGGER IF EXISTS listing_search_au",
    "DROP TRIGGER IF EXISTS listing_search_ad",
    "DROP TRIGGER IF EXISTS listing_search_ai",
    "DROP TABLE IF EXISTS listing_search",
]


class Migration(migrations.Migration):
    dependencies = [("listings", "0022_listing_effective_price")]

    operations = [migrations.RunSQL(FORWARD, BACKWARD)]
