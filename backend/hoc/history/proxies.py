"""Which fund's price history stands in for an industry or a country (FIX-63, CONTRACT.md section 11)."""

from __future__ import annotations

# GICS sectors -> the SPDR Select Sector fund that tracks it.
SECTOR_PROXIES: dict[str, str] = {
    "information_technology": "XLK",
    "financials": "XLF",
    "health_care": "XLV",
    "consumer_discretionary": "XLY",
    "communication_services": "XLC",
    "industrials": "XLI",
    "consumer_staples": "XLP",
    "energy": "XLE",
    "utilities": "XLU",
    "real_estate": "XLRE",
    "materials": "XLB",
}

SECTOR_LABELS: dict[str, str] = {
    "information_technology": "Technology",
    "financials": "Financials",
    "health_care": "Health care",
    "consumer_discretionary": "Consumer discretionary",
    "communication_services": "Communication services",
    "industrials": "Industrials",
    "consumer_staples": "Consumer staples",
    "energy": "Energy",
    "utilities": "Utilities",
    "real_estate": "Real estate",
    "materials": "Materials",
    "unknown": "Unknown industry",
}

# ISO 3166-1 alpha-2 -> a US-listed single-country fund (iShares MSCI unless noted). US uses SPY.
COUNTRY_PROXIES: dict[str, str] = {
    "US": "SPY",
    "TW": "EWT",
    "CN": "MCHI",
    "HK": "EWH",
    "JP": "EWJ",
    "KR": "EWY",
    "IN": "INDA",
    "GB": "EWU",
    "DE": "EWG",
    "FR": "EWQ",
    "NL": "EWN",
    "CH": "EWL",
    "CA": "EWC",
    "AU": "EWA",
    "BR": "EWZ",
    "MX": "EWW",
    "ZA": "EZA",
    "SA": "KSA",
    "AE": "UAE",
    "PL": "EPOL",
    "MY": "EWM",
    "ID": "EIDO",
    "TH": "THD",
    "PH": "EPHE",
    "SG": "EWS",
    "IT": "EWI",
    "ES": "EWP",
    "SE": "EWD",
    "DK": "EDEN",
    "NO": "ENOR",
    "FI": "EFNL",
    "BE": "EWK",
    "IE": "EIRL",
    "IL": "EIS",
    "GR": "GREK",
    "KW": "KWT",
    "QA": "QAT",
    "TR": "TUR",
    "CL": "ECH",
    "PE": "EPU",
    "VN": "VNM",
}

COUNTRY_LABELS: dict[str, str] = {
    "US": "the US", "TW": "Taiwan", "CN": "China", "HK": "Hong Kong", "JP": "Japan", "KR": "South Korea",
    "IN": "India", "GB": "the UK", "DE": "Germany", "FR": "France", "NL": "the Netherlands", "CH": "Switzerland",
    "CA": "Canada", "AU": "Australia", "BR": "Brazil", "MX": "Mexico", "ZA": "South Africa", "SA": "Saudi Arabia",
    "AE": "the UAE", "PL": "Poland", "MY": "Malaysia", "ID": "Indonesia", "TH": "Thailand", "PH": "the Philippines",
    "SG": "Singapore", "IT": "Italy", "ES": "Spain", "SE": "Sweden", "DK": "Denmark", "NO": "Norway",
    "FI": "Finland", "BE": "Belgium", "IE": "Ireland", "IL": "Israel", "GR": "Greece", "KW": "Kuwait",
    "QA": "Qatar", "TR": "Turkey", "CL": "Chile", "PE": "Peru", "VN": "Vietnam",
}


def proxy_for(kind: str, key: str) -> str | None:
    """The proxy fund for a sector or country shock; None for suppliers and unmapped keys."""
    if kind == "sector":
        return SECTOR_PROXIES.get(key.strip().lower())
    if kind == "country":
        return COUNTRY_PROXIES.get(key.strip().upper())
    return None


def label_for(kind: str, key: str) -> str:
    if kind == "sector":
        return SECTOR_LABELS.get(key.strip().lower(), key)
    if kind == "country":
        return COUNTRY_LABELS.get(key.strip().upper(), key.strip().upper())
    return key
