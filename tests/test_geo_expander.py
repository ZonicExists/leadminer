"""
Unit tests for the Geo-Expander and Sub-Query generator across worldwide locations.
"""
from src.geo_expander import parse_location_input, get_city_postal_codes, generate_sub_queries


def test_parse_location_input():
    # 2-letter state code
    city, state, country = parse_location_input("Austin, TX")
    assert city == "Austin"
    assert state == "TX"
    assert country == "us"

    # Full state name
    city2, state2, country2 = parse_location_input("Miami, Florida")
    assert city2 == "Miami"
    assert state2 == "FL"
    assert country2 == "us"

    # City only
    city3, state3, country3 = parse_location_input("Chicago")
    assert city3 == "Chicago"
    assert state3 is None
    assert country3 == "us"


def test_get_city_postal_codes():
    zips = get_city_postal_codes("Austin", "TX", country="us", limit=5)
    assert len(zips) == 5
    assert all(len(z) == 5 for z in zips)
    assert any(z.startswith("787") for z in zips)


def test_generate_sub_queries():
    queries = generate_sub_queries(
        niche="Roofers",
        location="Miami, FL",
        country="us",
        limit=3,
    )
    assert len(queries) == 3
    assert all("Roofers in Miami, FL" in q for q in queries)
    assert any("331" in q for q in queries)


def test_global_location_parsing():
    city, state, country = parse_location_input("London, UK")
    assert city == "London"
    assert country == "gb"

    city, state, country = parse_location_input("Sydney, Australia")
    assert city == "Sydney"
    assert country == "au"

    city, state, country = parse_location_input("Dubai, UAE")
    assert city == "Dubai"
    assert country == "ae"

    city, state, country = parse_location_input("Toronto, ON, Canada")
    assert city == "Toronto"
    assert state == "ON"
    assert country == "ca"


def test_global_district_and_postal_generation():
    # London (UK postal codes)
    uk_queries = generate_sub_queries("Dentists", "London, UK", limit=3)
    assert len(uk_queries) == 3
    assert any("London" in q for q in uk_queries)

    # Dubai (District hub expansion)
    dubai_queries = generate_sub_queries("Digital Marketing", "Dubai, UAE", limit=3)
    assert len(dubai_queries) == 3
    assert any("Dubai Marina" in q or "Downtown Dubai" in q for q in dubai_queries)

    # Sydney (Australia postal codes)
    au_queries = generate_sub_queries("Roofers", "Sydney, Australia", limit=3)
    assert len(au_queries) == 3
    assert all("Sydney" in q for q in au_queries)


def test_regional_and_indian_abbreviation_expansion():
    # Test DNH (Dadra and Nagar Haveli) expansion
    dnh_queries = generate_sub_queries("Restaurents", "DNH, IN", limit=10)
    assert len(dnh_queries) == 10
    assert any("Silvassa" in q for q in dnh_queries)
    assert any("Dadra" in q for q in dnh_queries)
    assert any("Naroli" in q for q in dnh_queries)

    # Test Delhi NCR expansion
    ncr_queries = generate_sub_queries("Cafes", "Delhi NCR, IN", limit=5)
    assert len(ncr_queries) == 5
    assert any("Connaught Place" in q for q in ncr_queries)

    # Test Goa expansion
    goa_queries = generate_sub_queries("Hotels", "Goa, IN", limit=5)
    assert len(goa_queries) == 5
    assert any("Panaji" in q for q in goa_queries)
