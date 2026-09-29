import pytest

from listings.specials import extract_special, special_value

# Phrases taken from real listings.
OFFERS = [
    ("4 Weeks Rent Free Special on all 2 bedrooms", {"days": 28, "dollars": 0}),
    ("Leasing Special! Up to 6 weeks free on select homes! Contact our leasing office", {"days": 42, "dollars": 0}),
    ("**$200 off of First Month's Rent!** Curious about this property?", {"days": 0, "dollars": 200}),
    ("**$1500 OFF SECOND MONTH'S RENT WITH A LEASE SIGNED BY 10/9/2026** Stunning home", {"days": 0, "dollars": 1500}),
    ("Save Up To $1,000 Off Towards 2nd Month's Rent - Look & Lease within 48 Hours!", {"days": 0, "dollars": 1000}),
    ("Free Rent Special! Sign the lease by 10/1 and get October rent free!", {"days": 30, "dollars": 0}),
    ("Apply now and get your first full month's rent free. Step inside", {"days": 30, "dollars": 0}),
    ("MOVE IN SPECIAL - 1/2 Off First Months Rent! Welcome home", {"days": 15, "dollars": 0}),
    ("MOVE-IN SPECIAL - $500 Concession if approved by 09/30! Cozy 2 BR/2 BA", {"days": 0, "dollars": 500}),
    ("SPECIAL: $200 OFF | Pet Friendly, Garage, W/D in Unit", {"days": 0, "dollars": 200}),
    ("Brand New 2 Bedroom Steps Away from Multnomah Village + Move in Special!", {"days": 0, "dollars": 0}),
    ("One month free with a 13-month lease.", {"days": 30, "dollars": 0}),
    ("2 months free rent on 14 month leases", {"days": 60, "dollars": 0}),
    ("$800 MOVE IN SPECIAL!!", {"days": 0, "dollars": 800}),
    ("$1,000.00 leasing special.", {"days": 0, "dollars": 1000}),
    ("$500 OFF first month! Pearl condo", {"days": 0, "dollars": 500}),
]

NOT_OFFERS = [
    "Moving Discounts: 2 Months Free Storage, $50 off local moves, $200 off out-of-state moves",
    "+ Natural Creek + Free Carport Parking + Park Style Setting",
    "Special Terms: No smoking is permitted on the premises.",
    "Listed prices reflects price after concession is applied.",
    "feel free to reach out to see what else we have available",
    "Smoke-free community. Free In-Unit WiFi.",
    "*Deposit Special: Security deposit can be split into two payments",
    "$500 REDUCED DEPOSIT on approved credit",
    "",
]


@pytest.mark.parametrize("text, value", OFFERS)
def test_finds_offers_and_their_value(text, value):
    snippet = extract_special(text)
    assert snippet, text
    assert special_value(snippet) == value


@pytest.mark.parametrize("text", NOT_OFFERS)
def test_ignores_things_that_are_not_rent_offers(text):
    assert extract_special(text) is None


def test_snippet_is_the_sentence_with_the_offer():
    text = "Lovely condo with views. MOVE-IN SPECIAL $500 Off 1st Month's Rent!! Welcome to this home. Pets ok."
    assert extract_special(text) == "MOVE-IN SPECIAL $500 Off 1st Month's Rent!!"


def test_prefers_an_offer_with_a_value_over_a_generic_special():
    text = "Move in Special! Great location near shops. Enjoy $1,000 off your first month's rent."
    assert special_value(extract_special(text))["dollars"] == 1000


def test_long_snippets_are_trimmed():
    text = "Get 4 weeks free " + "and so much more " * 20
    assert len(extract_special(text)) <= 160
