import pytest

from listings.extract import (
    classify_property_type,
    extract_parking,
    has_parking,
    has_ac,
    has_outdoor_space,
    has_washer_dryer,
)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Amenities: 1 Reserved Parking Space, Concierge", 1),
        ("Attached 2-car garage", 2),
        ("two car garage plus driveway", 2),
        ("Double garage", 2),
        ("Includes 2 assigned spaces in secure garage", 2),
        ("Garage parking for 2 cars", 2),
        ("Tandem parking in building garage", 2),
        ("Off-street parking", None),
        ("Parking: garage, street parking", None),
        ("Parking: private driveway, street parking", None),
        ("Attached garage and long driveway", 2),
        ("An assigned parking spot is included", 1),
        ("The lease includes one designated parking space", 1),
        ("A dedicated off-street parking space", 1),
        ("One garage space", 1),
        ("Ample street parking", 0),
        ("Parking: Street", 0),
        ("Parking: Private shared road access. Parking Garage Access.", None),
        ("No parking available", 0),
        ("Beautiful 2 bedroom unit with 2 bathrooms", None),
    ],
)
def test_extract_parking(text, expected):
    assert extract_parking(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("In-unit washer/dryer", True),
        ("Appliances: Dishwasher, Washer/Dryer", True),
        ("W/D included", True),
        ("Washer and dryer in unit", True),
        ("Shared laundry on site", False),
        # Phrasings found in stored listings (2026-09-27 audit)
        ("Pets: Cats Parking: Attached garage Laundry: In Unit Deposit & fees", True),
        ("Laundry: Hookups", True),
        ("Appliances: Gas Oven/Range, Dishwasher, Microwave, Refrigerator, Washer, and Dryer", True),
        ("Refrigerator, stove, oven, dishwasher, washer, & dryer", True),
        ("Laundry: laundry in bldg", False),
        ("Laundry on site. Outdoor space included", False),
        ("No washer or dryer", False),
        ("Hardwood floors", None),
    ],
)
def test_has_washer_dryer(text, expected):
    assert has_washer_dryer(text) is expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Central air conditioning", True),
        ("Ductless mini-split heat pump", True),
        ("High efficiency heating & cooling systems", True),
        ("A/C in bedrooms", True),
        ("No air conditioning", False),
        ("Gas fireplace", None),
    ],
)
def test_has_ac(text, expected):
    assert has_ac(text) is expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Private balcony with views", True),
        ("Fenced backyard", True),
        ("Covered patio", True),
        ("Rooftop deck", True),
        ("No balcony", False),
        ("Granite counters", None),
    ],
)
def test_has_outdoor_space(text, expected):
    assert has_outdoor_space(text) is expected


@pytest.mark.parametrize(
    "hint,text,expected",
    [
        ("Condo", "", "condo"),
        ("Townhouse", "", "townhome"),
        ("Single Family Home", "", "house"),
        ("Apartment", "Nice unit", "apartment"),
        ("Apartment", "South facing condo in the Pearl", "condo"),
        ("", "937 Condos - 2 bed/2 bath", "condo"),
        ("", "HOA covers water", "unknown"),
        ("", "This home may have an HOA/COA which has additional charges", "unknown"),
        ("", "End-unit townhome", "townhome"),
        ("", "Visit our leasing office", "apartment"),
        ("", "Charming craftsman bungalow", "house"),
        ("Other", "Spacious unit", "other"),
        ("Duplex", "", "other"),
        ("", "Spacious unit", "unknown"),
    ],
)
def test_classify_property_type(hint, text, expected):
    assert classify_property_type(hint, text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Parking: Private shared road access. Parking Garage Access.", True),
        ("Parking: Attached garage", True),
        ("Off-street parking", True),
        ("Garage or carport included", True),
        ("Attached 2-car garage", True),
        ("1 Reserved Parking Space", True),
        ("Ample street parking", False),
        ("Parking: Street", False),
        ("No parking available", False),
        ("Parking: Contact manager", None),
        ("Hardwood floors", None),
    ],
)
def test_has_parking(text, expected):
    assert has_parking(text) is expected
