"""Keyword search over listings with SQLite FTS5.

listing_search indexes each listing's title, description, address and neighborhood; triggers from
migration 0023 keep it in step with listings_listing on every insert, update and delete. People type
Google-style queries ("quoted phrases", -exclude, OR, prefix*); parse() turns them into FTS5 syntax built
only from quoted terms, so no input can make a malformed query."""

import re
from dataclasses import dataclass

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
