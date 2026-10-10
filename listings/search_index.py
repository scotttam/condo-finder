"""Keyword search over listings with SQLite FTS5.

listing_search indexes each listing's title, description, address and neighborhood; triggers from
migration 0023 keep it in step with listings_listing on every insert, update and delete. People type
Google-style queries ("quoted phrases", -exclude, OR, prefix*); parse() turns them into FTS5 syntax built
only from quoted terms, so no input can make a malformed query."""

import json
import re
from dataclasses import dataclass

from django.db import connection
from django.db.models import FloatField
from django.db.models.expressions import RawSQL
from django.utils.html import escape
from django.utils.safestring import mark_safe

_TOKEN = re.compile(r'(-?)"([^"]*)"?|(\S+)')
_WORD = re.compile(r"[^\W_]+", re.UNICODE)


@dataclass(frozen=True)
class Keywords:
    include: str  # FTS5 expression a listing must match ("" for none)
    exclude: str  # FTS5 expression a listing must not match ("" for none)


def _term(text, prefix=False):
    """A quoted FTS5 phrase from the words in text, or "" when it has none."""
    words = _WORD.findall(text)
    if not words:
        return ""
    return f'"{" ".join(words)}"' + ("*" if prefix else "")


def parse(text):
    """Keywords for a search box entry, or None when it has nothing to search for. Words are ANDed; OR joins
    the words on either side of it (it binds tighter than AND, as people expect); -word or -"phrase" excludes."""
    groups, excludes, join_next = [], [], False
    for negate, phrase, word in _TOKEN.findall(text or ""):
        if word in ("OR", "AND"):
            join_next = word == "OR" and bool(groups)
            continue
        if word.startswith("-") and len(word) > 1:
            negate, word = "-", word[1:]
        term = _term(phrase) if phrase or not word else _term(word, prefix=word.endswith("*"))
        if not term:
            join_next = False
            continue
        if negate:
            excludes.append(term)
        elif join_next:
            groups[-1].append(term)
        else:
            groups.append([term])
        join_next = False
    if not groups and not excludes:
        return None
    include = " AND ".join(f"({' OR '.join(group)})" for group in groups)
    return Keywords(include, " OR ".join(excludes))


_MATCHING_IDS = "SELECT rowid FROM listing_search WHERE listing_search MATCH %s"


def filter_listings(queryset, text):
    keywords = parse(text)
    if keywords is None:
        return queryset
    if keywords.include:
        queryset = queryset.filter(pk__in=RawSQL(_MATCHING_IDS, [keywords.include]))
    if keywords.exclude:
        queryset = queryset.exclude(pk__in=RawSQL(_MATCHING_IDS, [keywords.exclude]))
    return queryset


def rank_expr(keywords):
    """bm25 relevance (lower is better), weighting title over address and neighborhood over description. One
    MATCH ranks every hit; the ORDER BY looks each listing up in that JSON (a correlated MATCH per row took
    seconds on a prefix search)."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT rowid, bm25(listing_search, 10.0, 1.0, 4.0, 4.0) FROM listing_search "
                       "WHERE listing_search MATCH %s", [keywords.include])
        ranks = {str(rowid): score for rowid, score in cursor.fetchall()}
    return RawSQL("""json_extract(%s, '$."' || "listings_listing"."id" || '"')""", [json.dumps(ranks)],
                  output_field=FloatField())


_START, _END = "\x02", "\x03"  # placeholders FTS5 wraps matches in; swapped for <mark> after escaping


def _marked(text):
    if not text or _START not in text:
        return ""
    return mark_safe(escape(text).replace(_START, "<mark>").replace(_END, "</mark>"))


def highlights(listing_ids, text):
    """{listing id: {"title", "address", "snippet"}}: safe HTML with matched words in <mark> ("" where nothing
    matched), for one page of results."""
    keywords = parse(text)
    ids = list(listing_ids)
    if keywords is None or not keywords.include or not ids:
        return {}
    placeholders = ", ".join(["%s"] * len(ids))
    sql = ("SELECT rowid, highlight(listing_search, 0, %s, %s), highlight(listing_search, 2, %s, %s), "
           "snippet(listing_search, 1, %s, %s, '…', 18) "
           f"FROM listing_search WHERE listing_search MATCH %s AND rowid IN ({placeholders})")
    with connection.cursor() as cursor:
        cursor.execute(sql, [_START, _END] * 3 + [keywords.include, *ids])
        return {row[0]: {"title": _marked(row[1]), "address": _marked(row[2]), "snippet": _marked(row[3])}
                for row in cursor.fetchall()}
