"""Move-in specials in listing text: "4 weeks free", "$500 off first month's rent", "Move-in special!".

extract_special finds the sentence that states the offer; special_value reads how much it's worth
(free days of rent and dollars off) so we can show an effective monthly rent.
"""

import re

from .parsing import WORD_NUMBERS

_NUMBERS = {**WORD_NUMBERS, "five": 5, "six": 6, "eight": 8}
_NUM = r"(\d{1,2}|one|two|three|four|five|six|eight)"
_MONTHS = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
_NOT_RENT = r"(?!\s+(?:storage|parking|wi-?fi|internet|membership|gym|cable|utilities))"

_FREE_PERIOD = re.compile(
    rf"\b(?:up\s+to\s+)?{_NUM}\s*(weeks?|wks?|months?|mos?)\.?\s+(?:of\s+)?(?:rent\s+)?(?:free|off)\b(?:\s+rent\b)?{_NOT_RENT}", re.I
)
_FREE_MONTH = re.compile(
    rf"\b(?:rent[- ]free|free\s+rent|free\s+month|(?:(?:first|1st|second|2nd|last|full|{_MONTHS})\s+)+(?:month'?s?\s+)?rent\s+(?:is\s+)?free"
    rf"|month'?s?\s+rent\s+free)\b",
    re.I,
)
_HALF_MONTH = re.compile(
    r"(?:\b(?:half|1/2)|½)\s+(?:off\s+(?:your\s+|the\s+)?(?:(?:first|1st|second|2nd)\s+)?months?'?s?\s+rent|(?:a\s+)?month\s+free)", re.I
)
_DOLLARS_OFF = re.compile(
    r"\$\s?(\d[\d,]*)(?:\.\d\d)?\s*(?:off\b|concession|rent\s+credit|(?:move[- ]?in|leasing|rent)\s+special)", re.I
)
_DOLLAR_CONTEXT = re.compile(r"\brent\b|special|move[- ]?in|\blease\b|concession|\b(?:first|1st|second|2nd)\s+month", re.I)
_GENERIC = re.compile(
    rf"\b(?:move[- ]?in|leasing|lease|rent|rental|holiday|fall|summer|winter|spring|{_MONTHS})\s+specials?\b|\bspecial\s+offer\b",
    re.I,
)
# Sentence breaks, plus the bullet separators listings use in place of sentences.
_BREAKS = re.compile(r"(?<=[.!?])[*\s]+(?=[A-Z0-9$*(])|\n+|\s+[|•✩❖✓+]\s+|\s*\*\*\s*")
MAX_SNIPPET = 160


def _is_offer(sentence):
    if _FREE_PERIOD.search(sentence) or _FREE_MONTH.search(sentence) or _HALF_MONTH.search(sentence):
        return True
    if _DOLLARS_OFF.search(sentence) and _DOLLAR_CONTEXT.search(sentence):
        return True
    return bool(_GENERIC.search(sentence))


def _trim(sentence):
    sentence = sentence.strip(" *-–:")
    return sentence if len(sentence) <= MAX_SNIPPET else sentence[: MAX_SNIPPET - 1].rstrip() + "…"


def extract_special(text):
    """The sentence stating a rent special, or None. One with a stated value wins over a bare
    'Move-in special!'."""
    offers = [s for s in _BREAKS.split(text or "") if s and _is_offer(s)]
    if not offers:
        return None
    valued = [s for s in offers if any(special_value(s).values())]
    return _trim((valued or offers)[0])


def special_value(snippet):
    """{"days": free days of rent, "dollars": dollars off}; both 0 when the offer doesn't say."""
    snippet = snippet or ""
    days = 0
    if match := _FREE_PERIOD.search(snippet):
        count = match.group(1).lower()
        count = int(count) if count.isdigit() else _NUMBERS[count]
        days = count * (7 if match.group(2).lower().startswith("w") else 30)
    elif _FREE_MONTH.search(snippet):
        days = 30
    elif _HALF_MONTH.search(snippet):
        days = 15
    dollars = 0
    if _DOLLAR_CONTEXT.search(snippet):
        dollars = max((int(m.group(1).replace(",", "")) for m in _DOLLARS_OFF.finditer(snippet)), default=0)
    return {"days": days, "dollars": dollars}


def special_label(snippet):
    """Short badge text: '4 wks free', '1 mo free', '$500 off' or 'Special'."""
    value = special_value(snippet)
    if value["days"]:
        days = value["days"]
        if days == 15:
            return "½ mo free"
        return f"{days // 30} mo free" if days % 30 == 0 else f"{days // 7} wks free"
    if value["dollars"]:
        return f"${value['dollars']:,} off"
    return "Special"


def effective_rent(price, snippet, lease_months=12):
    """Average monthly rent over a lease once the special is applied, or None if it doesn't say."""
    value = special_value(snippet)
    if not price or not any(value.values()):
        return None
    total = price * lease_months - price * value["days"] / 30.4 - value["dollars"]
    return round(total / lease_months)
