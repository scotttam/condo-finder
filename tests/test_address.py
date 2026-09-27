import pytest

from listings.address import is_target_city, parse_address


def test_parse_appfolio_address_with_hash_unit():
    parsed = parse_address("937 NW Glisan Street #435, Portland, OR 97209")
    assert parsed.street == "937 NW Glisan Street"
    assert parsed.unit == "435"
    assert parsed.city == "Portland"
    assert parsed.state == "OR"
    assert parsed.zip_code == "97209"
    assert parsed.key == "937 nw glisan st|435|97209"
    assert parsed.display == "937 NW Glisan Street #435, Portland, OR 97209"


@pytest.mark.parametrize(
    "raw,street,unit",
    [
        ("4775 SW FRANKLIN AVE APT 321, Beaverton, OR 97005", "4775 SW FRANKLIN AVE", "321"),
        ("13000 NW Cornell Road Unit 15, Portland, OR 97229", "13000 NW Cornell Road", "15"),
        ("515 S Tamarind Ave - 515, Portland, OR 97220", "515 S Tamarind Ave", "515"),
        ("2655 NE 205th Ave Unit 303-A, Portland, OR 97024", "2655 NE 205th Ave", "303-A"),
        ("123 Main St, Unit 4, Portland, OR 97201", "123 Main St", "4"),
        (" 2908 NE Skidmore St, Portland, OR 97211", "2908 NE Skidmore St", ""),
    ],
)
def test_parse_units(raw, street, unit):
    parsed = parse_address(raw)
    assert (parsed.street, parsed.unit) == (street, unit)


def test_zip_plus_four_and_country_suffix():
    parsed = parse_address("4775 SW Franklin Ave, Beaverton, OR 97005-2943, US")
    assert parsed.zip_code == "97005"
    assert parsed.city == "Beaverton"


def test_multiword_city_is_title_cased():
    assert parse_address("16849 Lakeridge Drive, LAKE OSWEGO, OR 97034").city == "Lake Oswego"


def test_equivalent_addresses_share_key():
    a = parse_address("937 NW Glisan St. #435, Portland, OR 97209")
    b = parse_address("937 Northwest Glisan Street Unit 435, Portland, OR 97209")
    assert a.key == b.key


def test_unparseable_address_returns_none():
    assert parse_address("Contact us for address") is None
    assert parse_address("") is None


def test_is_target_city():
    assert is_target_city("Portland")
    assert is_target_city("lake oswego")
    assert not is_target_city("Gresham")


@pytest.mark.parametrize(
    "street,city,expected",
    [
        ("937 NW Glisan Street", "Portland", "NW"),
        ("14950 NE Rose Pkwy", "Portland", "NE"),
        ("5720 SE Duke St", "Portland", "SE"),
        ("3820 SW Garden View Ave", "Portland", "SW"),
        ("1534 N Blandena St", "Portland", "N"),
        ("3820 S River Pkwy", "Portland", "S"),
        ("937 Northwest Glisan Street", "Portland", "NW"),
        ("1500 N.E. 15th Ave", "Portland", "NE"),
        ("5681-5687 NE Glisan St", "Portland", "NE"),  # address ranges (whole buildings)
        ("3410-3414 SE 143rd Ave", "Portland", "SE"),
        ("8426 E Burnside St", "Portland", ""),  # Burnside splits NE/SE; no quadrant prefix
        ("123 Main St", "Portland", ""),
        ("4775 SW Franklin Ave", "Beaverton", ""),  # Washington County grid, not Portland's SW
        ("16849 Lakeridge Drive", "Lake Oswego", ""),
    ],
)
def test_portland_quadrant(street, city, expected):
    from listings.address import portland_quadrant

    assert portland_quadrant(street, city) == expected
