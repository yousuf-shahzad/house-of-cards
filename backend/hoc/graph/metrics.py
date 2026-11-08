"""Deterministic dependency graph metrics (package G-ORCH).

Rules (docs/hoc/PLAN-v2.md & docs/hoc/CONTRACT.md):
- Python owns every number: supplier dependency %, facility-country concentration,
  and shared single points of failure are computed deterministically with math.fsum (wsum).
- Union by (dependent_company_key, target) before summing portfolio exposure so a
  company with multiple verified edges to the same supplier or country is never
  double-counted.
- Every MetricFact carries its canonical metric_id, label, value, unit ('fraction' | 'count'),
  subject_key, and sorted supporting_edge_ids.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from hoc.contract.api import CompanyExposure
from hoc.contract.dependencies import MetricFact, MetricUnit, VerifiedEdge
from hoc.contract.units import wsum

SUPPLY_EDGE_TYPES: frozenset[str] = frozenset(
    {
        "supplier",
        "contract_manufacturer",
        "foundry",
        "key_input",
        "jv_partner",
    }
)

FACILITY_TARGET_KINDS: frozenset[str] = frozenset({"country", "region", "facility"})

# Canonical ISO-3166 (alpha-2 code, display name, deterministic alias/state/province/city list).
# Aliases are normalised with dotted abbreviations collapsed ("U.S." -> "us", "R.O.C." -> "roc").
_COUNTRY_DEFINITIONS: Mapping[str, tuple[str, tuple[str, ...]]] = {
    "TW": (
        "Taiwan",
        (
            "tw",
            "taiwan",
            "roc",
            "taiwan roc",
            "republic of china",
            "taipei",
            "new taipei",
            "taoyuan",
            "hsinchu",
            "taichung",
            "tainan",
            "kaohsiung",
            "miaoli",
            "linkou",
            "zhunan",
            "nanzih",
            "hsinchu science park",
            "central taiwan science park",
            "southern taiwan science park",
        ),
    ),
    "US": (
        "United States",
        (
            "us",
            "usa",
            "united states",
            "united states of america",
            # All 50 US states + DC
            "alabama",
            "alaska",
            "arizona",
            "arkansas",
            "california",
            "colorado",
            "connecticut",
            "delaware",
            "florida",
            "georgia",
            "hawaii",
            "idaho",
            "illinois",
            "indiana",
            "iowa",
            "kansas",
            "kentucky",
            "louisiana",
            "maine",
            "maryland",
            "massachusetts",
            "michigan",
            "minnesota",
            "mississippi",
            "missouri",
            "montana",
            "nebraska",
            "nevada",
            "new hampshire",
            "new jersey",
            "new mexico",
            "new york",
            "north carolina",
            "north dakota",
            "ohio",
            "oklahoma",
            "oregon",
            "pennsylvania",
            "rhode island",
            "south carolina",
            "south dakota",
            "tennessee",
            "texas",
            "utah",
            "vermont",
            "virginia",
            "washington",
            "west virginia",
            "wisconsin",
            "wyoming",
            "district of columbia",
            # Major US tech/manufacturing regions & cities
            "silicon valley",
            "bay area",
            "northern california",
            "southern california",
            "new york city",
            "los angeles",
            "chicago",
            "houston",
            "phoenix",
            "philadelphia",
            "san antonio",
            "san diego",
            "dallas",
            "san jose",
            "austin",
            "jacksonville",
            "fort worth",
            "columbus",
            "charlotte",
            "san francisco",
            "indianapolis",
            "seattle",
            "denver",
            "boston",
            "detroit",
            "portland",
            "las vegas",
            "memphis",
            "louisville",
            "baltimore",
            "milwaukee",
            "albuquerque",
            "tucson",
            "fresno",
            "sacramento",
            "mesa",
            "kansas city",
            "atlanta",
            "omaha",
            "colorado springs",
            "raleigh",
            "miami",
            "oakland",
            "minneapolis",
            "tulsa",
            "cleveland",
            "wichita",
            "arlington",
            "tampa",
            "new orleans",
            "honolulu",
            "santa clara",
            "cupertino",
            "sunnyvale",
            "mountain view",
            "palo alto",
            "menlo park",
            "redwood city",
            "fremont",
            "milpitas",
            "san mateo",
            "novato",
            "goleta",
            "el segundo",
            "lathrop",
            "walnut",
            "fontana",
            "poway",
            "taft",
            "irvine",
            "carlsbad",
            "burbank",
            "pasadena",
            "deer park",
            "richardson",
            "plano",
            "round rock",
            "boise",
            "manassas",
            "reston",
            "mclean",
            "clay",
            "fishkill",
            "poughkeepsie",
            "uniondale",
            "garden city",
            "old bridge",
            "mahwah",
            "edison",
            "florence",
            "breinigsville",
            "allentown",
            "pittsburgh",
            "fort collins",
            "broomfield",
            "boulder",
            "hillsboro",
            "beaverton",
            "chandler",
            "tempe",
            "scottsdale",
            "rio rancho",
            "provo",
            "lehi",
            "salt lake city",
            "redmond",
            "bellevue",
            "kirkland",
            "tacoma",
            "vernon hills",
            "edwardsville",
            "mounds",
            "greenfield",
            "rincon",
            "ochlocknee",
            "pendergrass",
            "blue mountain",
            "ripley",
            "bentonville",
            "waltham",
            "burlington",
            "andover",
            "lowell",
            "marlborough",
            "armonk",
            "yorktown heights",
            "campbell",
        ),
    ),
    "CN": (
        "China",
        (
            "cn",
            "china",
            "prc",
            "peoples republic of china",
            "people s republic of china",
            "mainland china",
            "china mainland",
            "shanghai",
            "nanjing",
            "shenzhen",
            "beijing",
            "suzhou",
            "wuxi",
            "chengdu",
            "chongqing",
            "xian",
            "wuhan",
            "hangzhou",
            "guangzhou",
            "dongguan",
            "tianjin",
            "dalian",
            "qingdao",
            "xiamen",
            "fuzhou",
            "hefei",
            "nanchang",
            "jiangxi",
            "zhengzhou",
            "kunshan",
            "ningbo",
            "changsha",
            "zhuhai",
            "foshan",
            "huizhou",
            "weifang",
            "yantai",
            "zhejiang",
            "jiangsu",
            "guangdong",
            "sichuan",
            "fujian",
            "shandong",
            "hubei",
            "anhui",
            "henan",
            "shaanxi",
            "liaoning",
        ),
    ),
    "KR": (
        "South Korea",
        (
            "kr",
            "korea",
            "south korea",
            "republic of korea",
            "rok",
            "seoul",
            "busan",
            "incheon",
            "daegu",
            "daejeon",
            "gwangju",
            "ulsan",
            "suwon",
            "icheon",
            "pyeongtaek",
            "cheongju",
            "paju",
            "gumi",
            "hwaseong",
            "yongin",
            "seongnam",
            "gyeonggi",
            "chungcheong",
        ),
    ),
    "JP": (
        "Japan",
        (
            "jp",
            "japan",
            "tokyo",
            "osaka",
            "yokohama",
            "nagoya",
            "kyoto",
            "kobe",
            "fukuoka",
            "sapporo",
            "hiroshima",
            "sendai",
            "kumamoto",
            "yokkaichi",
            "kitakami",
            "mie prefecture",
            "tsu city",
            "tsuruoka",
            "oita",
            "nagasaki",
            "iwate",
            "shiga",
            "kanagawa",
            "aichi",
            "chiba",
            "saitama",
            "hyogo",
            "shizuoka",
            "ibaraki",
            "tochigi",
            "gunma",
            "niigata",
            "toyama",
            "ishikawa",
            "fukui",
            "yamanashi",
            "nagano",
            "gifu",
            "wakayama",
            "okayama",
            "yamaguchi",
            "okinawa",
        ),
    ),
    "DE": (
        "Germany",
        (
            "de",
            "germany",
            "federal republic of germany",
            "berlin",
            "munich",
            "munchen",
            "aschheim",
            "frankfurt",
            "hamburg",
            "cologne",
            "koln",
            "stuttgart",
            "dusseldorf",
            "leipzig",
            "dresden",
            "nuremberg",
            "nurnberg",
            "hannover",
            "bremen",
            "bonn",
            "essen",
            "dortmund",
            "walldorf",
            "herzogenaurach",
            "ingolstadt",
            "wolfsburg",
            "ludwigshafen",
            "leverkusen",
            "jena",
            "erfurt",
            "regensburg",
            "burghausen",
            "bavaria",
            "saxony",
            "hesse",
            "baden wurttemberg",
        ),
    ),
    "NL": (
        "Netherlands",
        (
            "nl",
            "netherlands",
            "the netherlands",
            "holland",
            "amsterdam",
            "rotterdam",
            "the hague",
            "utrecht",
            "eindhoven",
            "veldhoven",
            "nijmegen",
            "almere",
            "groningen",
            "tilburg",
            "delft",
            "leiden",
        ),
    ),
    "VN": (
        "Vietnam",
        (
            "vn",
            "vietnam",
            "viet nam",
            "hanoi",
            "ho chi minh",
            "haiphong",
            "hai phong",
            "da nang",
            "bac ninh",
            "bac giang",
            "thai nguyen",
            "binh duong",
            "dong nai",
            "vinh phuc",
        ),
    ),
    "IN": (
        "India",
        (
            "in",
            "india",
            "republic of india",
            "mumbai",
            "delhi",
            "new delhi",
            "bengaluru",
            "bangalore",
            "hyderabad",
            "chennai",
            "kolkata",
            "pune",
            "ahmedabad",
            "gujarat",
            "sanand",
            "noida",
            "gurugram",
            "gurgaon",
            "tamil nadu",
            "karnataka",
            "maharashtra",
            "telangana",
            "andhra pradesh",
            "kerala",
            "uttar pradesh",
        ),
    ),
    "IE": (
        "Ireland",
        (
            "ie",
            "ireland",
            "republic of ireland",
            "dublin",
            "cork",
            "galway",
            "limerick",
            "waterford",
            "leixlip",
            "athlone",
            "shannon",
        ),
    ),
    "GB": (
        "United Kingdom",
        (
            "gb",
            "uk",
            "united kingdom",
            "great britain",
            "england",
            "scotland",
            "wales",
            "northern ireland",
            "london",
            "edinburgh",
            "belfast",
            "manchester",
            "birmingham",
            "glasgow",
            "liverpool",
            "bristol",
            "leeds",
            "sheffield",
            "newcastle",
            "nottingham",
            "southampton",
            "oxford",
            "reading",
            "swindon",
            "wisbech",
            "cardiff",
            "aberdeen",
        ),
    ),
    "SG": (
        "Singapore",
        (
            "sg",
            "singapore",
            "republic of singapore",
            "jurong",
            "woodlands",
            "tampines",
            "changi",
            "kallang",
            "tuas",
        ),
    ),
    "IL": (
        "Israel",
        (
            "il",
            "israel",
            "state of israel",
            "tel aviv",
            "jerusalem",
            "haifa",
            "kiryat gat",
            "herzliya",
            "petah tikva",
            "rehovot",
            "raanana",
            "netanya",
            "migdal haemek",
            "yokneam",
            "beersheba",
        ),
    ),
    "MY": (
        "Malaysia",
        (
            "my",
            "malaysia",
            "kuala lumpur",
            "penang",
            "kulim",
            "johor",
            "johor bahru",
            "selangor",
            "petaling jaya",
            "kota damansara",
            "damansara",
            "wangsa maju",
            "malacca",
            "melaka",
            "ipoh",
            "sarawak",
            "kuching",
            "cyberjaya",
            "shah alam",
            "bayan lepas",
            "perak",
            "kedah",
        ),
    ),
    "CA": (
        "Canada",
        (
            "ca",
            "canada",
            # All Canadian provinces and territories
            "alberta",
            "british columbia",
            "manitoba",
            "new brunswick",
            "newfoundland and labrador",
            "newfoundland",
            "nova scotia",
            "nunavut",
            "northwest territories",
            "ontario",
            "prince edward island",
            "quebec",
            "saskatchewan",
            "yukon",
            # Major Canadian cities
            "toronto",
            "montreal",
            "vancouver",
            "calgary",
            "edmonton",
            "ottawa",
            "winnipeg",
            "quebec city",
            "hamilton",
            "kitchener",
            "waterloo",
            "laval",
            "markham",
            "mississauga",
            "brampton",
            "surrey",
            "burnaby",
        ),
    ),
    "MX": (
        "Mexico",
        (
            "mx",
            "mexico",
            "united mexican states",
            "mexico city",
            "guadalajara",
            "monterrey",
            "tijuana",
            "juarez",
            "ciudad juarez",
            "ensenada",
            "tonala",
            "queretaro",
            "puebla",
            "chihuahua",
            "mexicali",
            "reynosa",
            "matamoros",
            "hermosillo",
            "saltillo",
            "aguascalientes",
            "guanajuato",
            "jalisco",
            "baja california",
            "nuevo leon",
        ),
    ),
    "PH": (
        "Philippines",
        (
            "ph",
            "philippines",
            "the philippines",
            "republic of the philippines",
            "manila",
            "metro manila",
            "quezon city",
            "makati",
            "taguig",
            "cebu",
            "davao",
            "baguio",
            "laguna",
            "cavite",
            "batangas",
            "clark",
            "subic",
        ),
    ),
    "IT": (
        "Italy",
        (
            "it",
            "italy",
            "italian republic",
            "rome",
            "milan",
            "milano",
            "naples",
            "turin",
            "torino",
            "bologna",
            "genoa",
            "venice",
            "verona",
            "padua",
            "catania",
            "bari",
            "agrate",
            "landriano",
            "interporto",
            "lombardy",
        ),
    ),
    "HK": ("Hong Kong", ("hk", "hong kong", "hong kong sar")),
    "ES": (
        "Spain",
        (
            "es",
            "spain",
            "kingdom of spain",
            "madrid",
            "barcelona",
            "valencia",
            "seville",
            "zaragoza",
            "malaga",
            "bilbao",
        ),
    ),
    "PT": (
        "Portugal",
        ("pt", "portugal", "portuguese republic", "lisbon", "porto", "braga", "coimbra", "aveiro"),
    ),
    "FR": (
        "France",
        (
            "fr",
            "france",
            "french republic",
            "paris",
            "lyon",
            "marseille",
            "toulouse",
            "nice",
            "nantes",
            "strasbourg",
            "montpellier",
            "bordeaux",
            "lille",
            "grenoble",
            "crolles",
            "rennes",
            "sophia antipolis",
            "saclay",
        ),
    ),
    "CH": (
        "Switzerland",
        (
            "ch",
            "switzerland",
            "swiss confederation",
            "zurich",
            "geneva",
            "basel",
            "lausanne",
            "bern",
            "zug",
            "lugano",
            "neuchatel",
        ),
    ),
    "SE": (
        "Sweden",
        ("se", "sweden", "kingdom of sweden", "stockholm", "gothenburg", "malmo", "uppsala", "lund"),
    ),
    "AT": (
        "Austria",
        ("at", "austria", "republic of austria", "vienna", "graz", "linz", "salzburg", "innsbruck", "villach"),
    ),
    "BE": (
        "Belgium",
        ("be", "belgium", "kingdom of belgium", "brussels", "antwerp", "ghent", "leuven", "liege"),
    ),
    "DK": ("Denmark", ("dk", "denmark", "kingdom of denmark", "copenhagen", "aarhus", "odense")),
    "FI": ("Finland", ("fi", "finland", "republic of finland", "helsinki", "espoo", "tampere", "oulu")),
    "NO": ("Norway", ("no", "norway", "kingdom of norway", "oslo", "bergen", "trondheim", "stavanger")),
    "PL": (
        "Poland",
        ("pl", "poland", "republic of poland", "warsaw", "krakow", "wroclaw", "poznan", "gdansk", "katowice"),
    ),
    "CZ": ("Czechia", ("cz", "czechia", "czech republic", "prague", "brno", "ostrava")),
    "HU": ("Hungary", ("hu", "hungary", "budapest", "debrecen")),
    "RO": ("Romania", ("ro", "romania", "bucharest", "cluj", "timisoara", "iasi")),
    "SI": ("Slovenia", ("si", "slovenia", "republic of slovenia", "ljubljana", "maribor")),
    "SK": ("Slovakia", ("sk", "slovakia", "slovak republic", "bratislava", "kosice")),
    "BG": ("Bulgaria", ("bg", "bulgaria", "sofia", "plovdiv")),
    "HR": ("Croatia", ("hr", "croatia", "zagreb")),
    "GR": ("Greece", ("gr", "greece", "hellenic republic", "athens", "thessaloniki")),
    "EE": ("Estonia", ("ee", "estonia", "tallinn", "tartu")),
    "LV": ("Latvia", ("lv", "latvia", "riga")),
    "LT": ("Lithuania", ("lt", "lithuania", "vilnius", "kaunas")),
    "LU": ("Luxembourg", ("lu", "luxembourg")),
    "MT": ("Malta", ("mt", "republic of malta")),
    "CY": ("Cyprus", ("cy", "cyprus", "nicosia", "limassol")),
    "IS": ("Iceland", ("is", "iceland", "reykjavik")),
    "TR": ("Turkey", ("tr", "turkey", "turkiye", "republic of turkey", "istanbul", "ankara", "izmir")),
    "AU": (
        "Australia",
        ("au", "australia", "commonwealth of australia", "sydney", "melbourne", "brisbane", "perth", "adelaide"),
    ),
    "NZ": ("New Zealand", ("nz", "new zealand", "auckland", "wellington", "christchurch")),
    "TH": (
        "Thailand",
        ("th", "thailand", "kingdom of thailand", "bangkok", "chonburi", "rayong", "ayutthaya", "pathum thani"),
    ),
    "ID": ("Indonesia", ("id", "indonesia", "republic of indonesia", "jakarta", "batam", "surabaya", "bandung")),
    "PK": ("Pakistan", ("pk", "pakistan", "islamic republic of pakistan", "karachi", "lahore", "islamabad")),
    "BD": ("Bangladesh", ("bd", "bangladesh", "dhaka", "chittagong")),
    "LK": ("Sri Lanka", ("lk", "sri lanka", "colombo")),
    "JM": ("Jamaica", ("jm", "jamaica", "kingston", "montego bay")),
    "NI": ("Nicaragua", ("ni", "nicaragua", "managua")),
    "HN": ("Honduras", ("hn", "honduras", "tegucigalpa", "san pedro sula")),
    "CR": ("Costa Rica", ("cr", "costa rica", "heredia", "alajuela")),
    "PA": ("Panama", ("pa", "panama", "panama city")),
    "GT": ("Guatemala", ("gt", "guatemala", "guatemala city")),
    "SV": ("El Salvador", ("sv", "el salvador", "san salvador")),
    "DO": ("Dominican Republic", ("do", "dominican republic", "santo domingo")),
    "PR": ("Puerto Rico", ("pr", "puerto rico", "san juan")),
    "BR": (
        "Brazil",
        ("br", "brazil", "federative republic of brazil", "sao paulo", "rio de janeiro", "campinas", "manaus"),
    ),
    "AR": ("Argentina", ("ar", "argentina", "argentine republic", "buenos aires", "cordoba")),
    "CL": ("Chile", ("cl", "chile", "republic of chile", "santiago")),
    "CO": ("Colombia", ("co", "colombia", "republic of colombia", "bogota", "medellin", "cali")),
    "PE": ("Peru", ("pe", "peru", "republic of peru", "lima")),
    "UY": ("Uruguay", ("uy", "uruguay", "montevideo")),
    "ZA": ("South Africa", ("za", "south africa", "republic of south africa", "johannesburg", "cape town")),
    "EG": ("Egypt", ("eg", "egypt", "arab republic of egypt", "cairo", "alexandria")),
    "MA": ("Morocco", ("ma", "morocco", "kingdom of morocco", "casablanca", "rabat", "tangier")),
    "NG": ("Nigeria", ("ng", "nigeria", "lagos", "abuja")),
    "KE": ("Kenya", ("ke", "kenya", "nairobi")),
    "AE": ("United Arab Emirates", ("ae", "uae", "united arab emirates", "dubai", "abu dhabi", "sharjah")),
    "SA": ("Saudi Arabia", ("sa", "saudi arabia", "kingdom of saudi arabia", "riyadh", "jeddah", "dammam")),
    "QA": ("Qatar", ("qa", "qatar", "doha")),
    "KW": ("Kuwait", ("kw", "kuwait", "kuwait city")),
    "BH": ("Bahrain", ("bh", "bahrain", "manama")),
    "OM": ("Oman", ("om", "oman", "muscat")),
    "JO": ("Jordan", ("jo", "jordan", "amman")),
    "UA": ("Ukraine", ("ua", "ukraine", "kyiv", "kiev", "lviv", "kharkiv")),
    "RU": ("Russia", ("ru", "russia", "russian federation", "moscow", "saint petersburg")),
    "KZ": ("Kazakhstan", ("kz", "kazakhstan", "almaty", "astana")),
    "RS": ("Serbia", ("rs", "serbia", "belgrade", "novi sad")),
    "MO": ("Macau", ("mo", "macau", "macao")),
}

# Short country abbreviations that are unambiguous as whole words in English prose.
# Two-letter ISO codes like "CA" (California vs Canada) or "IL" (Illinois vs Israel)
# are matched only when the entire field is that code (via _COUNTRY_MAP), while
# "U.S.", "U.K.", "R.O.C.", "P.R.C.", "U.S.A.", "U.A.E.", "R.O.K." match in prose.
_SAFE_SHORT_COUNTRY_TOKENS: frozenset[str] = frozenset(
    {
        "us",
        "uk",
        "roc",
        "prc",
        "usa",
        "uae",
        "rok",
    }
)

# Multi-country macro-regions that must never be coerced into a single country via quote fallback.
_MACRO_REGIONS: frozenset[str] = frozenset(
    {
        "asia",
        "asia pacific",
        "apac",
        "europe",
        "european union",
        "eu",
        "emea",
        "latin america",
        "latam",
        "north america",
        "south america",
        "americas",
        "middle east",
    }
)
_TRAILING_PAREN_RE = re.compile(r"\(([^()]+)\)\s*$")


def _build_country_tables() -> tuple[
    dict[str, tuple[str, str]],
    list[tuple[re.Pattern[str], str, str, str]],
]:
    exact_map: dict[str, tuple[str, str]] = {}
    phrase_entries: list[tuple[str, str, str]] = []
    for code, (display_name, aliases) in _COUNTRY_DEFINITIONS.items():
        exact_map[code.lower()] = (code, display_name)
        exact_map[display_name.lower()] = (code, display_name)
        for alias in aliases:
            exact_map[alias] = (code, display_name)
            if len(alias) >= 4 or alias in _SAFE_SHORT_COUNTRY_TOKENS:
                phrase_entries.append((alias, code, display_name))

    # Longest phrases first so "northern ireland" -> GB before "ireland" -> IE
    # and "new mexico" -> US before "mexico" -> MX.
    phrase_entries.sort(key=lambda item: (-len(item[0]), item[0]))
    compiled = [
        (re.compile(rf"\b{re.escape(alias)}\b"), code, display_name, alias)
        for alias, code, display_name in phrase_entries
    ]
    return exact_map, compiled


_COUNTRY_MAP, _COMPILED_COUNTRY_PHRASES = _build_country_tables()

_DOTTED_ABBREV_RE = re.compile(r"\b(?:[A-Za-z]\.){2,}")
_US_STATE_POSTAL_RE = re.compile(
    r"(?:,\s*(AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC)\b"
    r"|\b(AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC)\s*,?\s*\d{5}(?:-\d{4})?\b)"
)


def _normalise_place_text(text: str) -> str:
    """Normalise place text after stripping dots from dotted abbreviations (U.S. -> us, R.O.C. -> roc)."""
    collapsed = _DOTTED_ABBREV_RE.sub(lambda m: m.group(0).replace(".", ""), text)
    return re.sub(r"[^a-z0-9]+", " ", collapsed.lower()).strip()


def _find_countries_in_text(raw_text: str) -> list[tuple[str, str]]:
    """Return distinct (country_code, country_name) matches found deterministically in raw_text."""
    if not raw_text or not raw_text.strip():
        return []
    norm = _normalise_place_text(raw_text)
    if not norm:
        return []
    if norm in _COUNTRY_MAP:
        return [_COUNTRY_MAP[norm]]

    found: list[tuple[int, str, str]] = []
    occupied: list[tuple[int, int]] = []

    for m in _US_STATE_POSTAL_RE.finditer(raw_text):
        found.append((m.start(), "US", "United States"))

    for pattern, code, display_name, _alias in _COMPILED_COUNTRY_PHRASES:
        for m in pattern.finditer(norm):
            start, end = m.span()
            if any(not (end <= occ_s or start >= occ_e) for occ_s, occ_e in occupied):
                continue
            occupied.append((start, end))
            found.append((start, code, display_name))

    found.sort(key=lambda item: item[0])
    unique_countries: list[tuple[str, str]] = []
    seen_codes: set[str] = set()
    for _, code, display_name in found:
        if code not in seen_codes:
            seen_codes.add(code)
            unique_countries.append((code, display_name))
    return unique_countries


def slugify_metric_token(text: str) -> str:
    """Turn an arbitrary key or name into a stable metric_id token."""
    cleaned = re.sub(r"[^A-Za-z0-9:_\-]+", "-", text.strip()).strip("-")
    return cleaned or "unknown"


def canonical_country_info(
    raw_name: str,
    target_key: str | None = None,
    qualifier: str | None = None,
    evidence_quote: str | None = None,
) -> tuple[str, str] | None:
    """Return (country_code, country_display_name) for a facility/country edge, or None if unplaced.

    Order:
    1. target_key
    2. target_name
    3. qualifier
    4. evidence_quote (ONLY when the quote names a single country).
    Never falls back to the facility's own name as a country.
    """
    if target_key and str(target_key).strip():
        clean_key = str(target_key).strip()
        tail = clean_key.split(":", 1)[-1].strip()
        key_hits = _find_countries_in_text(tail)
        if len(key_hits) == 1:
            return key_hits[0]

    if _normalise_place_text(raw_name) in _MACRO_REGIONS:
        return None

    paren_match = _TRAILING_PAREN_RE.search(raw_name)
    if paren_match:
        paren_hits = _find_countries_in_text(paren_match.group(1))
        if len(paren_hits) == 1:
            return paren_hits[0]

    for candidate in (raw_name, qualifier or ""):
        if not candidate or not candidate.strip():
            continue
        hits = _find_countries_in_text(candidate)
        if len(hits) == 1:
            norm_cand = _normalise_place_text(candidate)
            # Disambiguate "Ontario" (city in California vs province in Canada) when quote is US-only
            if (
                hits[0][0] == "CA"
                and "ontario" in norm_cand
                and "canada" not in norm_cand
                and evidence_quote
            ):
                quote_hits = _find_countries_in_text(evidence_quote)
                if quote_hits == [("US", "United States")]:
                    return ("US", "United States")
            return hits[0]
        if len(hits) > 1:
            return None

    if evidence_quote and evidence_quote.strip():
        quote_hits = _find_countries_in_text(evidence_quote)
        if len(quote_hits) == 1:
            return quote_hits[0]

    return None


def canonical_target_identity(edge: VerifiedEdge) -> tuple[str, str]:
    """Return (target_id, display_name) for an edge's target."""
    if edge.edge_type == "facility" or edge.target_kind in FACILITY_TARGET_KINDS:
        resolved = canonical_country_info(
            edge.target_name, edge.target_key, edge.qualifier, edge.evidence_quote
        )
        if resolved is not None:
            return resolved
        return "UNPLACED", edge.target_name.strip() or "Unplaced"

    if edge.target_key and edge.target_key.strip():
        clean_key = edge.target_key.strip()
        return clean_key, edge.target_name.strip() or clean_key

    slug = re.sub(r"[^a-z0-9]+", "-", edge.target_name.strip().lower()).strip("-") or "unknown"
    return f"NAME:{slug}", edge.target_name.strip() or slug


def format_metric_value(metric: MetricFact) -> str:
    """Format a MetricFact value deterministically for {{metric:<id>}} placeholder expansion."""
    if metric.unit == "count":
        return str(round(metric.value))
    if metric.unit == "days":
        return f"{round(metric.value)} days"
    if metric.unit == "ratio":
        return f"{metric.value:.2f}x"
    # Default: 'fraction' (0.58 -> '58.00%')
    pct = metric.value * 100.0
    if abs(pct) < 0.005:
        pct = 0.0
    return f"{pct:.2f}%"


@dataclass(frozen=True)
class SupplierDependencySummary:
    """Deterministic summary for one supplier, foundry, contract manufacturer, or input."""

    target_id: str
    target_name: str
    dependent_weight: float
    dependent_company_keys: tuple[str, ...]
    dependent_company_names: tuple[str, ...]
    etf_tickers: tuple[str, ...]
    sole_source: bool
    target_in_portfolio: bool
    edge_types: tuple[str, ...]
    supporting_edge_ids: tuple[str, ...]


@dataclass(frozen=True)
class FacilityCountrySummary:
    """Deterministic summary for portfolio exposure with verified facilities in a country/region."""

    country_code: str
    country_name: str
    dependent_weight: float
    company_keys: tuple[str, ...]
    company_names: tuple[str, ...]
    etf_tickers: tuple[str, ...]
    supporting_edge_ids: tuple[str, ...]


@dataclass(frozen=True)
class SinglePointOfFailureSummary:
    """A supplier/foundry/input shared by >=2 holdings OR flagged sole_source."""

    target_id: str
    target_name: str
    dependent_weight: float
    dependent_company_keys: tuple[str, ...]
    dependent_company_names: tuple[str, ...]
    etf_tickers: tuple[str, ...]
    sole_source: bool
    target_in_portfolio: bool
    supporting_edge_ids: tuple[str, ...]


@dataclass(frozen=True)
class DependencyGraphSummary:
    """Rich deterministic breakdown alongside the flat MetricFact list."""

    metrics: list[MetricFact]
    metrics_by_id: dict[str, MetricFact]
    suppliers: list[SupplierDependencySummary]
    facilities_by_country: list[FacilityCountrySummary]
    single_points_of_failure: list[SinglePointOfFailureSummary]
    analysed_weight: float
    verified_edges_count: int


def _make_metric(
    metric_id: str,
    label: str,
    value: float,
    unit: MetricUnit,
    subject_key: str | None,
    supporting_edge_ids: Sequence[str],
) -> MetricFact:
    return MetricFact(
        metric_id=metric_id,
        label=label,
        value=round(value, 10) if unit == "fraction" else value,
        unit=unit,
        subject_key=subject_key,
        supporting_edge_ids=sorted(set(supporting_edge_ids)),
    )


def compute_dependency_summary(
    exposures: Sequence[CompanyExposure],
    edges: Sequence[VerifiedEdge],
) -> DependencyGraphSummary:
    """Compute all deterministic dependency metrics without double-counting."""
    portfolio_by_key: dict[str, CompanyExposure] = {
        comp.company_key: comp for comp in exposures if comp.exposure > 0
    }

    # 1. Supply-side dependencies grouped by canonical target_id.
    #    Union by (dependent_company_key, target_id) so multiple edges between
    #    the same portfolio company and supplier never double-count exposure.
    supplier_names: dict[str, str] = {}
    supplier_companies: dict[str, set[str]] = {}
    supplier_edges: dict[str, set[str]] = {}
    supplier_edge_types: dict[str, set[str]] = {}
    supplier_sole_source: dict[str, bool] = {}

    # 2. Facility/country dependencies grouped by canonical country_code.
    country_names: dict[str, str] = {}
    country_companies: dict[str, set[str]] = {}
    country_edges: dict[str, set[str]] = {}
    unplaced_facility_edges: set[str] = set()

    # 3. Customer concentration edges grouped by canonical target_id.
    customer_names: dict[str, str] = {}
    customer_companies: dict[str, set[str]] = {}
    customer_edges: dict[str, set[str]] = {}

    # 4. Track portfolio companies with at least one verified edge.
    companies_with_edges: set[str] = set()
    all_edge_ids: list[str] = []

    for edge in edges:
        edge_id = edge.edge_id.strip()
        if not edge_id:
            continue
        all_edge_ids.append(edge_id)

        src_key = edge.source_company_key.strip()
        edge_type = edge.edge_type
        target_kind = edge.target_kind
        target_key = edge.target_key.strip() if edge.target_key else None

        if src_key in portfolio_by_key:
            companies_with_edges.add(src_key)
        if target_key and target_key in portfolio_by_key:
            companies_with_edges.add(target_key)

        # Facility / country edges
        if edge_type == "facility" or target_kind in FACILITY_TARGET_KINDS:
            if src_key in portfolio_by_key:
                resolved_country = canonical_country_info(
                    edge.target_name, target_key, edge.qualifier, edge.evidence_quote
                )
                if resolved_country is not None:
                    code, country_label = resolved_country
                    country_names.setdefault(code, country_label)
                    country_companies.setdefault(code, set()).add(src_key)
                    country_edges.setdefault(code, set()).add(edge_id)
                else:
                    unplaced_facility_edges.add(edge_id)
            continue

        # Supply-chain / operational dependency edges
        if edge_type in SUPPLY_EDGE_TYPES:
            if src_key in portfolio_by_key:
                target_id, target_label = canonical_target_identity(edge)
                if target_id in portfolio_by_key:
                    target_label = portfolio_by_key[target_id].company_name
                supplier_names.setdefault(target_id, target_label)
                supplier_companies.setdefault(target_id, set()).add(src_key)
                supplier_edges.setdefault(target_id, set()).add(edge_id)
                supplier_edge_types.setdefault(target_id, set()).add(edge_type)
                if edge.sole_source:
                    supplier_sole_source[target_id] = True
            continue

        # Customer edges:
        # (a) Filer (src_key) reports revenue concentration on a customer
        # (b) Reverse link: if src_key is a supplier and target_key is a portfolio company,
        #     then target_key depends on src_key as a supplier!
        if edge_type == "customer":
            target_id, target_label = canonical_target_identity(edge)
            if src_key in portfolio_by_key:
                customer_names.setdefault(target_id, target_label)
                customer_companies.setdefault(target_id, set()).add(src_key)
                customer_edges.setdefault(target_id, set()).add(edge_id)

            if target_key and target_key in portfolio_by_key and target_key != src_key:
                dep_comp_key = target_key
                sup_id = src_key
                sup_label = (
                    portfolio_by_key[src_key].company_name
                    if src_key in portfolio_by_key
                    else (edge.source_company_name or src_key)
                )
                supplier_names.setdefault(sup_id, sup_label)
                supplier_companies.setdefault(sup_id, set()).add(dep_comp_key)
                supplier_edges.setdefault(sup_id, set()).add(edge_id)
                supplier_edge_types.setdefault(sup_id, set()).add("supplier")
                if edge.sole_source:
                    supplier_sole_source[sup_id] = True

    # Build SupplierDependencySummary list
    suppliers: list[SupplierDependencySummary] = []
    for target_id, comp_keys in supplier_companies.items():
        sorted_comp_keys = tuple(
            sorted(
                comp_keys,
                key=lambda k: (-portfolio_by_key[k].exposure, k),
            )
        )
        dep_weight = wsum(portfolio_by_key[k].exposure for k in sorted_comp_keys)
        comp_names = tuple(portfolio_by_key[k].company_name for k in sorted_comp_keys)
        etfs = tuple(
            sorted(
                {
                    contrib.etf_ticker
                    for k in sorted_comp_keys
                    for contrib in portfolio_by_key[k].contributions
                    if contrib.contribution > 0
                }
            )
        )
        suppliers.append(
            SupplierDependencySummary(
                target_id=target_id,
                target_name=supplier_names[target_id],
                dependent_weight=dep_weight,
                dependent_company_keys=sorted_comp_keys,
                dependent_company_names=comp_names,
                etf_tickers=etfs,
                sole_source=supplier_sole_source.get(target_id, False),
                target_in_portfolio=target_id in portfolio_by_key,
                edge_types=tuple(sorted(supplier_edge_types.get(target_id, set()))),
                supporting_edge_ids=tuple(sorted(supplier_edges.get(target_id, set()))),
            )
        )

    suppliers.sort(
        key=lambda s: (
            -s.dependent_weight,
            -len(s.dependent_company_keys),
            s.target_id,
        )
    )

    # Build SinglePointOfFailureSummary list (shared across >=2 companies OR sole_source)
    spofs: list[SinglePointOfFailureSummary] = []
    for sup in suppliers:
        if len(sup.dependent_company_keys) >= 2 or sup.sole_source:
            spofs.append(
                SinglePointOfFailureSummary(
                    target_id=sup.target_id,
                    target_name=sup.target_name,
                    dependent_weight=sup.dependent_weight,
                    dependent_company_keys=sup.dependent_company_keys,
                    dependent_company_names=sup.dependent_company_names,
                    etf_tickers=sup.etf_tickers,
                    sole_source=sup.sole_source,
                    target_in_portfolio=sup.target_in_portfolio,
                    supporting_edge_ids=sup.supporting_edge_ids,
                )
            )

    # Build FacilityCountrySummary list
    facilities_by_country: list[FacilityCountrySummary] = []
    for code, comp_keys in country_companies.items():
        sorted_comp_keys = tuple(
            sorted(
                comp_keys,
                key=lambda k: (-portfolio_by_key[k].exposure, k),
            )
        )
        country_weight = wsum(portfolio_by_key[k].exposure for k in sorted_comp_keys)
        comp_names = tuple(portfolio_by_key[k].company_name for k in sorted_comp_keys)
        etfs = tuple(
            sorted(
                {
                    contrib.etf_ticker
                    for k in sorted_comp_keys
                    for contrib in portfolio_by_key[k].contributions
                    if contrib.contribution > 0
                }
            )
        )
        facilities_by_country.append(
            FacilityCountrySummary(
                country_code=code,
                country_name=country_names[code],
                dependent_weight=country_weight,
                company_keys=sorted_comp_keys,
                company_names=comp_names,
                etf_tickers=etfs,
                supporting_edge_ids=tuple(sorted(country_edges.get(code, set()))),
            )
        )

    facilities_by_country.sort(
        key=lambda f: (
            -f.dependent_weight,
            -len(f.company_keys),
            f.country_code,
        )
    )

    # Assemble flat MetricFact list matching C0 conventions (dep.<target_id>, facility.<code>, spof.count, etc.)
    metrics: list[MetricFact] = []
    analysed_weight = wsum(portfolio_by_key[k].exposure for k in sorted(companies_with_edges))
    sorted_all_edges = sorted(set(all_edge_ids))

    # 1. Supplier dependency metrics (matching synthetic-dependencies.json: dep.<target_id>)
    for sup in suppliers:
        metrics.append(
            _make_metric(
                metric_id=f"dep.{sup.target_id}",
                label=f"Portfolio exposure that depends on {sup.target_name}",
                value=sup.dependent_weight,
                unit="fraction",
                subject_key=sup.target_id,
                supporting_edge_ids=sup.supporting_edge_ids,
            )
        )
        metrics.append(
            _make_metric(
                metric_id=f"dep.{sup.target_id}.companies",
                label=f"Portfolio companies dependent on {sup.target_name}",
                value=float(len(sup.dependent_company_keys)),
                unit="count",
                subject_key=sup.target_id,
                supporting_edge_ids=sup.supporting_edge_ids,
            )
        )

    # 2. Facility concentration by country (matching synthetic-dependencies.json: facility.<code>)
    for fac in facilities_by_country:
        metrics.append(
            _make_metric(
                metric_id=f"facility.{fac.country_code}",
                label=f"Portfolio exposure with key facilities in {fac.country_name}",
                value=fac.dependent_weight,
                unit="fraction",
                subject_key=fac.country_code,
                supporting_edge_ids=fac.supporting_edge_ids,
            )
        )
        metrics.append(
            _make_metric(
                metric_id=f"facility.{fac.country_code}.companies",
                label=f"Portfolio companies with facilities in {fac.country_name}",
                value=float(len(fac.company_keys)),
                unit="count",
                subject_key=fac.country_code,
                supporting_edge_ids=fac.supporting_edge_ids,
            )
        )

    if unplaced_facility_edges:
        metrics.append(
            _make_metric(
                metric_id="facility.unplaced.count",
                label="Facility edges not mapped to a single country",
                value=float(len(unplaced_facility_edges)),
                unit="count",
                subject_key=None,
                supporting_edge_ids=sorted(unplaced_facility_edges),
            )
        )

    # 3. Single points of failure (matching synthetic-dependencies.json: spof.count + spof.<target_id>)
    shared_spof_count = sum(
        1 for spof in spofs if len(spof.dependent_company_keys) >= 2 or spof.sole_source
    )
    metrics.append(
        _make_metric(
            metric_id="spof.count",
            label="Suppliers shared by 2+ portfolio companies or sole-source",
            value=float(shared_spof_count),
            unit="count",
            subject_key=None,
            supporting_edge_ids=[eid for spof in spofs for eid in spof.supporting_edge_ids],
        )
    )
    for spof in spofs:
        metrics.append(
            _make_metric(
                metric_id=f"spof.{spof.target_id}",
                label=f"Single point of failure exposure on {spof.target_name}",
                value=spof.dependent_weight,
                unit="fraction",
                subject_key=spof.target_id,
                supporting_edge_ids=spof.supporting_edge_ids,
            )
        )

    # 4. Customer concentration metrics
    for cust_id in sorted(customer_companies):
        comp_keys = customer_companies[cust_id]
        cust_weight = wsum(portfolio_by_key[k].exposure for k in sorted(comp_keys))
        metrics.append(
            _make_metric(
                metric_id=f"customer.{cust_id}",
                label=f"Portfolio exposure reporting customer concentration ({customer_names[cust_id]})",
                value=cust_weight,
                unit="fraction",
                subject_key=cust_id,
                supporting_edge_ids=sorted(customer_edges[cust_id]),
            )
        )

    # 5. Summary metrics
    metrics.append(
        _make_metric(
            metric_id="summary.analysed_weight",
            label="Portfolio exposure with verified dependency disclosures",
            value=analysed_weight,
            unit="fraction",
            subject_key=None,
            supporting_edge_ids=sorted_all_edges,
        )
    )
    metrics.append(
        _make_metric(
            metric_id="summary.verified_edges",
            label="Verified filing dependency edges",
            value=float(len(sorted_all_edges)),
            unit="count",
            subject_key=None,
            supporting_edge_ids=sorted_all_edges,
        )
    )

    metrics_by_id = {m.metric_id: m for m in metrics}
    return DependencyGraphSummary(
        metrics=metrics,
        metrics_by_id=metrics_by_id,
        suppliers=suppliers,
        facilities_by_country=facilities_by_country,
        single_points_of_failure=spofs,
        analysed_weight=analysed_weight,
        verified_edges_count=len(sorted_all_edges),
    )


def compute_dependency_metrics(
    exposures: Sequence[CompanyExposure],
    edges: Sequence[VerifiedEdge],
) -> list[MetricFact]:
    """Return the deterministic list[MetricFact] for the dependency response contract."""
    return compute_dependency_summary(exposures, edges).metrics
