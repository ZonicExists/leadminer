"""
Global Geo-Expander & Sub-Query Generator for scaling Google Maps scraping.
Supports worldwide cities across 90+ countries with automatic country detection,
postal code lookups (pgeocode), and district/neighborhood expansion for non-postal hubs (e.g. UAE/Dubai).
"""
import re
from typing import List, Optional, Tuple, Dict
import pgeocode

# Cache Nominatim country datasets in memory for fast repeated lookups
_NOMINATIM_CACHE: Dict[str, pgeocode.Nominatim] = {}

# ── Comprehensive Country Aliases ─────────────────────────────────────────────
GLOBAL_COUNTRY_ALIASES: Dict[str, str] = {
    # Americas
    "united states": "us", "usa": "us", "us": "us", "america": "us",
    "canada": "ca", "ca": "ca",
    "mexico": "mx", "mx": "mx",
    "brazil": "br", "brasil": "br", "br": "br",
    "argentina": "ar", "ar": "ar",
    "chile": "cl", "cl": "cl",
    "colombia": "co", "co": "co",
    # Europe
    "united kingdom": "gb", "uk": "gb", "gb": "gb", "great britain": "gb",
    "england": "gb", "scotland": "gb", "wales": "gb", "northern ireland": "gb",
    "germany": "de", "deutschland": "de", "de": "de",
    "france": "fr", "fr": "fr",
    "spain": "es", "españa": "es", "es": "es",
    "italy": "it", "italia": "it", "it": "it",
    "netherlands": "nl", "holland": "nl", "nl": "nl",
    "ireland": "ie", "ie": "ie",
    "switzerland": "ch", "ch": "ch",
    "austria": "at", "at": "at",
    "belgium": "be", "be": "be",
    "sweden": "se", "se": "se",
    "norway": "no", "no": "no",
    "denmark": "dk", "dk": "dk",
    "finland": "fi", "fi": "fi",
    "poland": "pl", "pl": "pl",
    "portugal": "pt", "pt": "pt",
    "czech republic": "cz", "czechia": "cz", "cz": "cz",
    "turkey": "tr", "türkiye": "tr", "tr": "tr",
    # Asia & Middle East
    "india": "in", "in": "in",
    "japan": "jp", "jp": "jp",
    "australia": "au", "au": "au",
    "new zealand": "nz", "nz": "nz",
    "singapore": "sg", "sg": "sg",
    "malaysia": "my", "my": "my",
    "philippines": "ph", "ph": "ph",
    "thailand": "th", "th": "th",
    "indonesia": "id", "id": "id",
    "south africa": "za", "za": "za",
    "united arab emirates": "ae", "uae": "ae", "ae": "ae", "dubai": "ae",
    "saudi arabia": "sa", "sa": "sa",
    "qatar": "qa", "qa": "qa",
    "hong kong": "hk", "hk": "hk",
}

# ── Major US States ───────────────────────────────────────────────────────────
US_STATES: Dict[str, str] = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA",
    "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV", "new hampshire": "NH",
    "new jersey": "NJ", "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "rhode island": "RI", "south carolina": "SC", "south dakota": "SD", "tennessee": "TN",
    "texas": "TX", "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY", "district of columbia": "DC",
}

# ── Canadian Provinces ────────────────────────────────────────────────────────
CA_PROVINCES: Dict[str, str] = {
    "ontario": "ON", "quebec": "QC", "british columbia": "BC", "alberta": "AB",
    "manitoba": "MB", "saskatchewan": "SK", "nova scotia": "NS", "new brunswick": "NB",
    "newfoundland": "NL", "prince edward island": "PE",
}

# ── Australian States ─────────────────────────────────────────────────────────
AU_STATES: Dict[str, str] = {
    "new south wales": "NSW", "victoria": "VIC", "queensland": "QLD",
    "western australia": "WA", "south australia": "SA", "tasmania": "TAS",
    "australian capital territory": "ACT", "northern territory": "NT",
}

# ── District / Area Fallback for Hubs Without Postal Codes or Regional Metros ─
GLOBAL_DISTRICT_HUBS: Dict[str, List[str]] = {
    # India Regional & Metro Hubs
    "dnh": [
        "Silvassa", "Dadra", "Naroli", "Samarvarni", "Khanvel",
        "Rakholi", "Masat", "Athal", "Galonda", "Kilvani",
        "Dapada", "Sili", "396230", "396235", "396240",
    ],
    "dadra and nagar haveli": [
        "Silvassa", "Dadra", "Naroli", "Samarvarni", "Khanvel",
        "Rakholi", "Masat", "Athal", "Galonda", "Kilvani",
        "Dapada", "Sili", "396230", "396235",
    ],
    "daman and diu": [
        "Nani Daman", "Moti Daman", "Daman", "Diu", "Ghoghla",
        "Dunetha", "Devka Beach", "Kadaiya", "396210", "362520",
    ],
    "delhi ncr": [
        "Connaught Place", "South Extension", "Hauz Khas", "Saket", "Karol Bagh",
        "Lajpat Nagar", "Dwarka", "Rohini", "Cyber City Gurgaon", "Golf Course Road Gurgaon",
        "Sector 29 Gurgaon", "Noida Sector 18", "Noida Sector 62", "Greater Noida", "Faridabad", "Ghaziabad",
    ],
    "ncr": [
        "Connaught Place", "South Extension", "Hauz Khas", "Saket", "Karol Bagh",
        "Lajpat Nagar", "Dwarka", "Rohini", "Gurgaon", "Noida", "Faridabad", "Ghaziabad",
    ],
    "delhi": [
        "Connaught Place", "Hauz Khas", "Saket", "Karol Bagh", "Lajpat Nagar",
        "Dwarka", "Rohini", "Chandni Chowk", "Vasant Kunj", "South Extension",
        "Pitampura", "Janakpuri", "Rajouri Garden", "Chanakyapuri", "Nehru Place",
    ],
    "goa": [
        "Panaji", "Margao", "Vasco da Gama", "Mapusa", "Calangute",
        "Candolim", "Ponda", "Porvorim", "Baga", "Anjuna",
        "Morjim", "Assagao", "Colva", "Benaulim",
    ],
    "mumbai": [
        "Andheri West", "Andheri East", "Bandra West", "Juhu", "Colaba",
        "Powai", "Dadar", "Borivali West", "Goregaon", "Malad West",
        "Lower Parel", "BKC", "Thane West", "Navi Mumbai", "Worli", "Fort",
    ],
    "bangalore": [
        "Koramangala", "Indiranagar", "Whitefield", "HSR Layout", "Jayanagar",
        "JP Nagar", "Electronic City", "MG Road", "Marathahalli", "BTM Layout",
        "Hebbal", "Yelahanka", "Bellandur", "Malleshwaram",
    ],
    "bengaluru": [
        "Koramangala", "Indiranagar", "Whitefield", "HSR Layout", "Jayanagar",
        "JP Nagar", "Electronic City", "MG Road", "Marathahalli", "BTM Layout",
        "Hebbal", "Yelahanka", "Bellandur",
    ],
    "hyderabad": [
        "Hitec City", "Gachibowli", "Jubilee Hills", "Banjara Hills", "Madhapur",
        "Kondapur", "Kukatpally", "Secunderabad", "Begumpet", "Ameerpet", "Dilsukhnagar",
    ],
    "pune": [
        "Kothrud", "Baner", "Hinjewadi", "Viman Nagar", "Koregaon Park",
        "Aundh", "Wakad", "Hadapsar", "Shivajinagar", "Magarpatta", "Kalyani Nagar",
    ],
    "chennai": [
        "T Nagar", "Adyar", "Anna Nagar", "Velachery", "Alwarpet",
        "Nungambakkam", "Mylapore", "OMR", "Guindy", "Besant Nagar",
    ],
    "kolkata": [
        "Park Street", "Salt Lake", "New Town", "Ballygunge", "Alipore",
        "Gariahat", "Howrah", "Dum Dum", "Behala", "Jadavpur",
    ],
    "ahmedabad": [
        "Navrangpura", "Satellite", "Bodakdev", "SG Highway", "Prahlad Nagar",
        "Maninagar", "Vastrapur", "Thaltej", "C.G. Road", "Bopal",
    ],
    "surat": [
        "Athwa", "Vesu", "Adajan", "Varachha", "Piplod",
        "Katargam", "Rander", "Dumas Road", "Pal",
    ],
    "chandigarh": [
        "Sector 17", "Sector 35", "Sector 22", "Sector 8", "Sector 9",
        "Sector 26", "Sector 43", "Mohali Phase 7", "Panchkula Sector 8", "Zirakpur",
    ],
    "jaipur": [
        "Malviya Nagar", "Vaishali Nagar", "C Scheme", "Mansarovar", "Raja Park",
        "Tonk Road", "MI Road", "Jagatpura", "Civil Lines",
    ],
    # Middle East Hubs
    "dubai": [
        "Downtown Dubai", "Dubai Marina", "Deira", "Bur Dubai", "Business Bay",
        "Jumeirah", "Al Barsha", "JBR", "Palm Jumeirah", "Al Quoz", "Mirdif",
        "Karama", "JLT", "Dubai Silicon Oasis", "Motor City", "Al Nahda",
    ],
    "abu dhabi": [
        "Al Danah", "Al Reem Island", "Khalidiya", "Yas Island", "Saadiyat Island",
        "Al Zahiyah", "Al Bateen", "Mohammed Bin Zayed City", "Al Mushrif", "Corniche",
    ],
    "doha": [
        "West Bay", "The Pearl", "Al Sadd", "Al Dafna", "Lusail", "Msheireb",
        "Al Wakrah", "Al Rayyan", "Al Mansoura",
    ],
    "riyadh": [
        "Al Olaya", "Al Malaz", "Al Nakheel", "Al Yasmin", "Al Sahafa",
        "Al Sulaimaniyah", "Al Murabba", "Al Wurud", "Diplomatic Quarter",
    ],
    # Asia-Pacific Hubs
    "hong kong": [
        "Central", "Tsim Sha Tsui", "Causeway Bay", "Mong Kok", "Wan Chai",
        "Kowloon", "Sham Shui Po", "Admiralty", "North Point", "Sheung Wan",
    ],
    "singapore": [
        "Orchard", "Jurong", "Tampines", "Woodlands", "Bedok", "Novena",
        "Marina Bay", "Bugis", "Toa Payoh", "Ang Mo Kio", "Geylang", "Yishun",
    ],
    # US & Global Metros
    "nyc": [
        "Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island",
        "Midtown", "Lower Manhattan", "Upper East Side", "Williamsburg", "Astoria", "SoHo",
    ],
    "bay area": [
        "San Francisco", "San Jose", "Oakland", "Palo Alto", "Mountain View",
        "Sunnyvale", "Fremont", "Berkeley", "Santa Clara",
    ],
    "london": [
        "Westminster", "Camden", "Islington", "Kensington", "Chelsea",
        "City of London", "Hackney", "Southwark", "Tower Hamlets", "Greenwich", "Mayfair", "Soho",
    ],
    "sydney": [
        "Sydney CBD", "Surry Hills", "Bondi", "Parramatta", "Manly",
        "Paddington", "Newtown", "Chatswood", "North Sydney",
    ],
}


def _get_nominatim(country: str = "us") -> Optional[pgeocode.Nominatim]:
    """Get or initialize cached Nominatim instance for a country code."""
    country_code = country.strip().lower()
    if country_code not in _NOMINATIM_CACHE:
        try:
            _NOMINATIM_CACHE[country_code] = pgeocode.Nominatim(country_code)
        except Exception:
            return None
    return _NOMINATIM_CACHE[country_code]


def parse_location_input(location_str: str, default_country: str = "us") -> Tuple[str, Optional[str], str]:
    """
    Intelligently parse any global location string into (city, state_or_province, country_code).
    
    Examples:
      - "Austin, TX"               -> ("Austin", "TX", "us")
      - "Austin, TX, USA"          -> ("Austin", "TX", "us")
      - "London, UK"               -> ("London", None, "gb")
      - "Toronto, ON, Canada"      -> ("Toronto", "ON", "ca")
      - "Sydney, Australia"        -> ("Sydney", None, "au")
      - "Sydney, NSW, Australia"   -> ("Sydney", "NSW", "au")
      - "Berlin, Germany"          -> ("Berlin", None, "de")
      - "Paris, France"            -> ("Paris", None, "fr")
      - "Dubai, UAE"               -> ("Dubai", None, "ae")
      - "Mumbai, India"            -> ("Mumbai", None, "in")
      - "Tokyo, Japan"             -> ("Tokyo", None, "jp")
    """
    cleaned = location_str.strip()
    if not cleaned:
        return "", None, default_country

    parts = [p.strip() for p in cleaned.split(",") if p.strip()]

    # Case 1: 3 parts e.g. "Toronto, ON, Canada" or "Austin, TX, USA"
    if len(parts) >= 3:
        city = parts[0]
        state_candidate = parts[1]
        country_candidate = parts[2].lower()

        country_code = GLOBAL_COUNTRY_ALIASES.get(country_candidate, default_country)
        return city, state_candidate.upper() if len(state_candidate) <= 3 else state_candidate, country_code

    # Case 2: 2 parts e.g. "London, UK" or "Austin, TX" or "Sydney, Australia"
    if len(parts) == 2:
        city = parts[0]
        second = parts[1]
        second_lower = second.lower()

        # Check if second part is a known country
        if second_lower in GLOBAL_COUNTRY_ALIASES:
            return city, None, GLOBAL_COUNTRY_ALIASES[second_lower]

        # Check if second part is a US state (2-letter or name)
        if len(second) == 2 and second.upper() in US_STATES.values():
            return city, second.upper(), "us"
        if second_lower in US_STATES:
            return city, US_STATES[second_lower], "us"

        # Check if Canadian province
        if len(second) == 2 and second.upper() in CA_PROVINCES.values():
            return city, second.upper(), "ca"
        if second_lower in CA_PROVINCES:
            return city, CA_PROVINCES[second_lower], "ca"

        # Check if Australian state
        if len(second) <= 3 and second.upper() in AU_STATES.values():
            return city, second.upper(), "au"
        if second_lower in AU_STATES:
            return city, AU_STATES[second_lower], "au"

        return city, second, default_country

    # Case 3: 1 part e.g. "Dubai" or "London" or "Chicago"
    city = parts[0]
    c_lower = city.lower()

    if c_lower in GLOBAL_DISTRICT_HUBS:
        if c_lower in ["dubai", "abu dhabi"]:
            return city, None, "ae"
        if c_lower in ["doha"]:
            return city, None, "qa"
        if c_lower in ["riyadh"]:
            return city, None, "sa"
        if c_lower in ["hong kong"]:
            return city, None, "hk"
        if c_lower in ["singapore"]:
            return city, None, "sg"

    if c_lower in GLOBAL_COUNTRY_ALIASES:
        return city, None, GLOBAL_COUNTRY_ALIASES[c_lower]

    return city, None, default_country


def get_city_postal_codes(
    city: str,
    state: Optional[str] = None,
    country: str = "us",
    limit: int = 50,
) -> List[str]:
    """
    Lookup all postal/ZIP codes for any global city supported by pgeocode.
    """
    if not city or not city.strip():
        return []

    try:
        nomi = _get_nominatim(country)
        if not nomi:
            return []

        df = nomi._data
        if df is None or df.empty:
            return []

        c_lower = city.strip().lower()
        mask = df["place_name"].astype(str).str.lower() == c_lower

        if state:
            s_clean = state.strip().lower()
            if len(s_clean) <= 3:
                mask &= (df["state_code"].astype(str).str.lower() == s_clean)
            else:
                mask &= (df["state_name"].astype(str).str.lower() == s_clean)

        matches = df[mask]
        if matches.empty:
            # Multi-column fallback search across place, community, county/district, state
            multi_mask = False
            for col in ["place_name", "community_name", "county_name", "state_name"]:
                if col in df.columns:
                    multi_mask = multi_mask | df[col].fillna("").astype(str).str.lower().str.contains(c_lower, regex=False)
            matches = df[multi_mask]

        postal_codes = matches["postal_code"].dropna().unique().tolist()
        postal_codes.sort()

        if limit > 0:
            return postal_codes[:limit]
        return postal_codes

    except Exception:
        return []


def generate_sub_queries(
    niche: str,
    location: str,
    country: Optional[str] = None,
    limit: int = 20,
) -> List[str]:
    """
    Generate scaled Google Maps search queries for ANY country or city in the world.
    
    Flow:
      1. Parses location string into (city, state, country) automatically.
         Supports "Austin, TX", "London, UK", "Sydney, Australia", "Dubai, UAE", "DNH, IN", "Toronto, Canada", etc.
      2. If the city is a non-postal or district-based hub (e.g. Dubai, DNH, Delhi NCR), generates district sub-queries.
      3. If postal codes exist in pgeocode for that country/region, generates postal zone queries.
      4. Falls back cleanly to a single standard query if no sub-divisions exist.
    """
    niche_clean = niche.strip()
    def_country = country.strip().lower() if (country and country.strip()) else "us"
    city, state, detected_country = parse_location_input(location, default_country=def_country)

    # Use explicit country if provided by user override, otherwise use auto-detected
    active_country = country.strip().lower() if (country and country.strip() and country != "auto") else detected_country

    if not niche_clean or not city:
        return [f"{niche_clean} in {location}".strip()] if (niche_clean or location) else []

    loc_label = f"{city}, {state}" if state else city
    c_lower = city.lower()

    # ── Check 1: Non-Postal / District Hubs (Dubai, DNH, Delhi NCR, Goa, etc.) ─
    if c_lower in GLOBAL_DISTRICT_HUBS:
        districts = GLOBAL_DISTRICT_HUBS[c_lower]
        sub_list = districts[:limit] if limit > 0 else districts
        queries = []
        for d in sub_list:
            if d.isdigit():
                queries.append(f"{niche_clean} in {loc_label} {d}")
            elif city.lower() in d.lower():
                queries.append(f"{niche_clean} in {d}")
            else:
                queries.append(f"{niche_clean} in {d}, {loc_label}")
        return queries

    # ── Check 2: Postal Codes lookup via pgeocode ─────────────────────────────
    postal_codes = get_city_postal_codes(city=city, state=state, country=active_country, limit=limit)
    if postal_codes:
        queries = []
        for zip_code in postal_codes:
            queries.append(f"{niche_clean} in {loc_label} {zip_code}")
        return queries

    # ── Check 3: Clean Fallback ───────────────────────────────────────────────
    # If no sub-zones found, return formatted broad query
    country_suffix = f", {active_country.upper()}" if (active_country != "us" and active_country not in loc_label.lower()) else ""
    return [f"{niche_clean} in {loc_label}{country_suffix}"]
