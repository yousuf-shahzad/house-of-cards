"""iShares issuer CSV adapter (package c, Yousuf's Codex).

Discover products at the issuer screener, then use only the product page's
JSON-LD latest-holdings.csv link. Issuer files must never be redistributed.
"""
from __future__ import annotations

import csv
import io
import json
import math
import re
from datetime import datetime, timedelta
from html.parser import HTMLParser
from typing import ClassVar
from urllib.parse import urlencode, urljoin, urlsplit

from hoc.contract import (
    RawEtfHoldings,
    RawHolding,
    SourceName,
    SourceParseError,
    SourceUnavailable,
    TickerNotFound,
)

ORIGIN = "https://www.ishares.com"
CATALOGUE_URL = ORIGIN + "/us/product-screener/product-screener-v3.1.jsn?" + urlencode({
    "dcrPath": "/templatedata/config/product-screener-v3/data/en/us-ishares/"
               "ishares-product-screener-backend-config",
    "siteEntryPassthrough": "true",
})
TTL = timedelta(hours=24)


class _JsonLd(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = False
        self.parts = []
        self.documents = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.active = dict(attrs).get("type", "").lower() == "application/ld+json"
            self.parts = []

    def handle_data(self, data):
        if self.active:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.active:
            self.documents.append("".join(self.parts))
            self.active = False


def _content_urls(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "contentUrl" and isinstance(child, str):
                yield child
            else:
                yield from _content_urls(child)
    elif isinstance(value, list):
        for child in value:
            yield from _content_urls(child)


def _issuer_url(base, value):
    url = urljoin(base, value)
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in {"www.ishares.com", "ishares.com"}:
        raise SourceParseError("iShares supplied an invalid issuer URL")
    return url


def _asset_class(row):
    labels = {row.get("asset class", "").lower(), row.get("type", "").lower()}
    if labels & {"fx", "foreign exchange", "forward", "forwards"}:
        return "fx"
    if labels & {"future", "futures", "index", "option", "options", "swap", "swaps", "warrant",
                 "warrants", "derivative", "derivatives"}:
        return "derivative"
    if labels & {"cash", "money market", "stif", "collateral", "cash collateral and margins"}:
        return "cash"
    if labels & {"preferred", "preferred stock", "preferred equity"}:
        return "preferred"
    if labels & {"fixed income", "bond", "bonds"}:
        return "fixed_income"
    if labels & {"fund", "funds", "mutual fund", "etf"}:
        return "fund"
    return "equity" if labels & {"equity", "equities"} else "other"


def _optional(value):
    value = (value or "").strip()
    return value if value not in {"", "-", "--", "N/A"} else None


def _number(value):
    value = value.strip().replace(",", "").removesuffix("%")
    if value.startswith("(") and value.endswith(")"):
        value = "-" + value[1:-1]
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("non-finite number")
    return result


def _parse_csv(text):
    if re.search(r"<\s*(?:!doctype|html|head|body|script)\b", text, re.IGNORECASE):
        raise SourceParseError("iShares returned HTML instead of holdings CSV")
    rows = list(csv.reader(io.StringIO(text), strict=True))
    as_of = None
    header_index = None
    for index, cells in enumerate(rows):
        cells = [cell.strip().lstrip("\ufeff") for cell in cells]
        if cells and cells[0].lower() in {"fund holdings as of", "holdings as of"}:
            if len(cells) < 2:
                raise ValueError("missing disclosure date")
            for fmt in ("%b %d, %Y", "%d/%b/%Y"):
                try:
                    as_of = datetime.strptime(cells[1], fmt).date()
                    break
                except ValueError:
                    continue
            else:
                raise ValueError("invalid disclosure date")
        names = [cell.lower() for cell in cells]
        if {"ticker", "name", "asset class"} <= set(names):
            if len(set(names)) != len(names):
                raise ValueError("duplicate columns")
            header_index, header = index, names
            break
    if header_index is None or as_of is None:
        raise ValueError("missing holdings header or disclosure date")
    if not {"weight (%)", "market weight"} & set(header):
        # Market-value normalisation would hide missing NAV and cash: require reported weights.
        raise ValueError("missing reported weights")
    holdings = []
    ended = False
    for cells in rows[header_index + 1:]:
        if not any(cell.strip() for cell in cells):
            ended = True
            continue
        if len(cells) == 1 and ended:
            continue  # issuer legal footer after the blank separator
        if ended or len(cells) != len(header):
            raise ValueError("invalid holdings row")
        row = dict(zip(header, (cell.strip() for cell in cells), strict=True))
        weight = _optional(row.get("weight (%)")) or _optional(row.get("market weight"))
        if weight is None or not _optional(row.get("name")):
            raise ValueError("missing holding name or weight")
        location = _optional(row.get("location"))
        currency = _optional(row.get("currency")) or _optional(row.get("market currency"))
        holdings.append(RawHolding(
            source_symbol=_optional(row.get("ticker")), name=row["name"],
            weight=_number(weight) / 100, asset_class=_asset_class(row),
            exchange=_optional(row.get("exchange")),
            country=location.upper() if location and re.fullmatch(r"[A-Za-z]{2}", location) else None,
            currency=currency, sector_label=_optional(row.get("sector")),
            isin=_optional(row.get("isin")), cusip=_optional(row.get("cusip")),
            sedol=_optional(row.get("sedol")),
            market_value_usd=(
                _number(row["market value"])
                if currency == "USD" and _optional(row.get("market value")) else None
            ),
        ))
    if not holdings:
        raise ValueError("empty holdings table")
    return as_of, holdings


class ISharesAdapter:
    name: ClassVar[SourceName] = "ishares"

    def __init__(self, http, settings) -> None:
        self.http = http
        self.settings = settings

    def supports(self, ticker: str) -> bool:
        """No network or fixed ticker allowlist: the issuer catalogue resolves membership."""
        return True

    def _get(self, url):
        response = self.http.get(
            url, source=self.name, ttl=TTL, headers={"User-Agent": self.settings.user_agent},
        )
        if response.status == 404:
            raise TickerNotFound("iShares resource not found")
        if not 200 <= response.status < 300:
            raise SourceUnavailable(f"iShares returned HTTP {response.status}")
        return response

    def fetch(self, ticker: str) -> RawEtfHoldings:
        ticker = ticker.strip().upper()
        catalogue = self._get(CATALOGUE_URL)
        try:
            products = catalogue.json()
            if not isinstance(products, dict) or not products:
                raise ValueError("invalid catalogue")
            if any(not isinstance(p, dict) or not isinstance(p.get("localExchangeTicker"), str)
                   for p in products.values()):
                raise ValueError("invalid catalogue product")
            matches = [p for p in products.values() if p["localExchangeTicker"].upper() == ticker]
            if not matches:
                raise TickerNotFound(f"iShares has no product for {ticker}")
            if len(matches) != 1:
                raise ValueError("ambiguous product ticker")
            product = matches[0]
            page_url = _issuer_url(ORIGIN, product["productPageUrl"])
        except (ValueError, KeyError, TypeError) as exc:
            raise SourceParseError("Invalid iShares product catalogue") from exc
        page = self._get(page_url)
        try:
            parser = _JsonLd()
            parser.feed(page.text())
            urls = set()
            for document in parser.documents:
                try:
                    value = json.loads(document)
                except ValueError:
                    continue  # unrelated malformed JSON-LD must not hide a valid dataset
                for content_url in _content_urls(value):
                    if urlsplit(content_url).path.endswith("/latest-holdings.csv"):
                        urls.add(_issuer_url(page_url, content_url))
            if len(urls) != 1:
                raise ValueError("missing or ambiguous CSV URL")
            csv_url = urls.pop()
        except (ValueError, UnicodeError) as exc:
            raise SourceParseError("Invalid iShares holdings JSON-LD") from exc
        response = self._get(csv_url)
        try:
            as_of, holdings = _parse_csv(response.body.decode("utf-8-sig"))
        except (ValueError, UnicodeError, csv.Error) as exc:
            raise SourceParseError("Invalid iShares holdings CSV") from exc
        return RawEtfHoldings(
            etf_ticker=ticker, etf_name=product.get("fundName"), source=self.name,
            source_layer="issuer", as_of=as_of, retrieved_at=response.fetched_at,
            source_url=csv_url, holdings=holdings,
            warnings=["iShares holdings served from stale cache"]
            if any(r.stale for r in (catalogue, page, response)) else [],
        )
