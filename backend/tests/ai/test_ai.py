"""Offline unit tests for package G-AI & V-INT (`hoc.ai`: client, verifier, interpretation, cache, extractor).

All tests use synthetic `ZZ` fixtures and `FakeHttpClient` / `FakeGeminiClient` (no network).
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from hoc.ai import (
    DEFAULT_EXTRACTOR_MODEL,
    DEFAULT_ORCHESTRATOR_MODEL,
    EXTRACTION_SCHEMA,
    GEMINI_INTERACTIONS_URL,
    JUDGE_PROMPT_VERSION,
    JUDGE_SCHEMA,
    MAX_PACKED_CHARS,
    MAX_REVERSE_HITS,
    PROMPT_VERSION,
    CompanyUnavailable,
    DependencyExtractor,
    EdgeInterpretation,
    ExtractionCache,
    FakeGeminiClient,
    GeminiClient,
    GeminiMissingKeyError,
    check_interpretation_rules,
    decide_interpretation_from_judge,
    dedupe_edges,
    extract_quote_context,
    is_generic_company_target,
    make_edge_id,
    pack_filing_sections,
    resolve_quote_section,
    should_sample_unflagged_edge,
    verify_and_build_edges,
    verify_company_interpretations,
    verify_edge_interpretation,
    verify_quote,
)
from hoc.config import Settings
from hoc.contract import CompanyExposure, FilingRef, VerifiedEdge
from hoc.core.cache import DiskCache
from hoc.core.http import CachedResponse, FakeHttpClient

SYNTHETIC_FILING_TEXT = (
    "Item 1. Business. ZZAlpha Corp designs advanced processors. "
    "We rely on Taiwan Semiconductor Manufacturing Co., Ltd. (TSMC) and ZZFAB Corp as our primary "
    "wafer foundries for all leading-edge nodes, and we purchase high-bandwidth memory from "
    "SK Hynix Inc. and Micron Technology, Inc. "
    "During fiscal 2026, one direct customer accounted for 22% of total revenue across our data center segment. "
    "Item 2. Properties. Our principal assembly and test operations are located in Taiwan and Arizona, "
    "where we lease 450,000 square feet of cleanroom facilities."
)


@dataclass(frozen=True)
class SyntheticFiling:
    company_key: str
    form: str
    accession: str
    filed: date
    url: str
    canonical_text: str
    sections: dict[str, tuple[int, int]]
    extraction_quality: str = "sections"


def _make_filing(text: str = SYNTHETIC_FILING_TEXT) -> SyntheticFiling:
    item2_idx = text.find("Item 2.")
    sections = (
        {"1": (0, item2_idx), "2": (item2_idx, len(text))}
        if item2_idx != -1
        else {"1": (0, len(text))}
    )
    return SyntheticFiling(
        company_key="CIK:0009990001",
        form="10-K",
        accession="0009990001-26-000001",
        filed=date(2026, 10, 15),
        url="https://www.sec.gov/Archives/edgar/data/9990001/000999000126000001/zzalpha-10k.htm",
        canonical_text=text,
        sections=sections,
    )


def _make_filing_ref(company_key: str = "CIK:0009990001", accession: str = "0009990001-26-000001") -> FilingRef:
    return FilingRef(
        company_key=company_key,
        form="10-K",
        accession=accession,
        filed=date(2026, 10, 15),
        url=f"https://www.sec.gov/Archives/edgar/data/{accession}.htm",
    )


# ---------- 1. Quote Verifier ----------


def test_verify_quote_exact_and_normalised_typography():
    doc = "We purchase\u00a0memory from \u201cSK\u00adHynix Inc.\u201d \u2014 our key supplier in Korea."
    assert verify_quote(
        'We purchase memory from "SKHynix Inc." - our key supplier in Korea.',
        doc,
        target_name="SKHynix Inc.",
        target_kind="company",
    )


def test_verify_quote_allows_single_valid_ellipsis_splice():
    left = "We rely on Taiwan Semiconductor Manufacturing Co., Ltd. (TSMC)"
    right = "we purchase high-bandwidth memory from SK Hynix Inc."
    spliced = f"{left} ... {right}"
    assert len(left) >= 25 and len(right) >= 25
    assert verify_quote(
        spliced,
        SYNTHETIC_FILING_TEXT,
        target_name="TSMC",
        target_kind="company",
    )


def test_verify_quote_rejects_invalid_ellipsis_splices():
    # Short half (< 25 chars)
    assert not verify_quote(
        "We rely on TSMC ... for all leading-edge nodes in our processor lineup.",
        SYNTHETIC_FILING_TEXT,
        target_name="TSMC",
        target_kind="company",
    )
    # Two ellipses
    assert not verify_quote(
        "We rely on Taiwan Semiconductor Manufacturing ... for all leading-edge nodes ... and memory from SK Hynix.",
        SYNTHETIC_FILING_TEXT,
        target_name="TSMC",
        target_kind="company",
    )
    # Out-of-order halves
    assert not verify_quote(
        "where we lease 450,000 square feet of cleanroom ... We rely on Taiwan Semiconductor Manufacturing Co.",
        SYNTHETIC_FILING_TEXT,
        target_name="TSMC",
        target_kind="company",
    )
    # Halves > 300 chars apart
    padded_doc = (
        "We rely on Taiwan Semiconductor Manufacturing Co., Ltd. for wafer fabrication. "
        + ("X" * 350)
        + " We also purchase high-bandwidth memory from SK Hynix Inc. for packaging."
    )
    assert not verify_quote(
        "We rely on Taiwan Semiconductor Manufacturing Co., Ltd. ... We also purchase high-bandwidth memory from SK Hynix Inc.",
        padded_doc,
        target_name="TSMC",
        target_kind="company",
    )


def test_verify_quote_rejects_mutated_text_and_unmentioned_counterparty():
    # Quote mutated by 1 word
    assert not verify_quote(
        "We rely exclusively on Taiwan Semiconductor Manufacturing Co., Ltd. (TSMC) and ZZFAB Corp",
        SYNTHETIC_FILING_TEXT,
        target_name="TSMC",
        target_kind="company",
    )
    # True verbatim quote from the filing, but attached to a hallucinated counterparty not in the quote
    assert not verify_quote(
        "We rely on Taiwan Semiconductor Manufacturing Co., Ltd. (TSMC) and ZZFAB Corp as our primary wafer foundries",
        SYNTHETIC_FILING_TEXT,
        target_name="Intel Foundry Services",
        target_kind="company",
    )


def test_verify_quote_unnamed_customer_concentration():
    assert verify_quote(
        "During fiscal 2026, one direct customer accounted for 22% of total revenue across our data center segment.",
        SYNTHETIC_FILING_TEXT,
        target_name="Unnamed Customer",
        target_kind="unnamed_customer",
        qualifier="22% of total revenue",
    )


def test_rejects_generic_nouns_as_company_targets():
    doc = (
        "We rely on contract manufacturers and third-party wafer foundries for assembly, "
        "while Taiwan Semiconductor Manufacturing Co., Ltd. (TSMC) and GlobalFoundries Inc. "
        "fabricate our core processors."
    )
    for bad_target in (
        "contract manufacturers",
        "Contract Manufacturers",
        "third-party wafer foundries",
        "wafer foundries",
        "single-source suppliers",
        "Unnamed Supplier",
    ):
        assert is_generic_company_target(bad_target, doc)
        assert not verify_quote(doc, doc, target_name=bad_target, target_kind="company")

    for real_company in (
        "TSMC",
        "Taiwan Semiconductor Manufacturing Co., Ltd.",
        "GlobalFoundries",
        "SK Hynix Inc.",
        "Applied Materials",
    ):
        assert not is_generic_company_target(real_company, doc)


def test_section_set_in_python_from_section_spans_never_model_free_text():
    text = (
        "Item 1. Business. We rely on Taiwan Semiconductor Manufacturing Co., Ltd. (TSMC) for wafers. "
        "Item 2. Properties. Our cleanroom facilities are in Taiwan and Arizona. "
        "Note 19. One customer accounted for 18% of revenue in 2026. "
        "Appendix. Additional wafer testing is performed by ZZFAB Corp in Singapore."
    )
    idx_item2 = text.index("Item 2.")
    idx_note = text.index("Note 19.")
    idx_app = text.index("Appendix.")
    sections = {
        "1": (0, idx_item2),
        "2": (idx_item2, idx_note),
        "concentration_1": (idx_note, idx_app),
    }

    q1 = "We rely on Taiwan Semiconductor Manufacturing Co., Ltd. (TSMC) for wafers."
    q2 = "Our cleanroom facilities are in Taiwan and Arizona."
    q_conc = "One customer accounted for 18% of revenue in 2026."
    q_outside = "Additional wafer testing is performed by ZZFAB Corp in Singapore."

    assert resolve_quote_section(q1, text, sections) == "1"
    assert resolve_quote_section(q2, text, sections) == "2"
    assert resolve_quote_section(q_conc, text, sections) == "concentration_1"
    # Outside all section spans -> must be 'document', even if model claimed 'concentration_11'
    assert resolve_quote_section(q_outside, text, sections) == "document"

    filing_ref = _make_filing_ref()
    raw_edges = [
        {
            "edge_type": "foundry",
            "target_name": "TSMC",
            "target_kind": "company",
            "sole_source": True,
            "qualifier": "",
            "section": "Supply Chain & Manufacturing",  # model free-text ignored
            "evidence_quote": q1,
        },
        {
            "edge_type": "facility",
            "target_name": "Taiwan",
            "target_kind": "country",
            "sole_source": False,
            "qualifier": "",
            "section": "ITEM 2. PROPERTIES",  # model free-text ignored
            "evidence_quote": q2,
        },
        {
            "edge_type": "foundry",
            "target_name": "ZZFAB Corp",
            "target_kind": "company",
            "sole_source": False,
            "qualifier": "",
            "section": "concentration_11",  # model claimed wrong concentration span
            "evidence_quote": q_outside,
        },
        {
            "edge_type": "contract_manufacturer",
            "target_name": "contract manufacturers",  # generic noun -> rejected!
            "target_kind": "company",
            "sole_source": False,
            "qualifier": "",
            "section": "1",
            "evidence_quote": q1,
        },
    ]
    verified, rejected = verify_and_build_edges(
        raw_edges,
        source_company_key="CIK:0009990001",
        source_company_name="ZZAlpha Corp",
        canonical_text=text,
        filing_ref=filing_ref,
        sections=sections,
    )
    assert rejected == 1
    by_target = {e.target_name: e.section for e in verified}
    assert by_target == {
        "TSMC": "1",
        "Taiwan": "2",
        "ZZFAB Corp": "document",
    }


# ---------- 2. REST GeminiClient ----------


class RecordingHttpClient(FakeHttpClient):
    """Records headers, payloads, and concurrent in-flight requests."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[dict[str, Any]] = []
        self.status_queue: list[tuple[int, dict[str, Any]]] = []
        self._in_flight = 0
        self.peak_in_flight = 0
        self._lock = threading.Lock()
        self.sleep_seconds = 0.0

    def enqueue_json(self, body: dict[str, Any], *, status: int = 200) -> None:
        self.status_queue.append((status, body))

    def post_json(self, url, payload, *, source, ttl, headers=None) -> CachedResponse:
        with self._lock:
            self._in_flight += 1
            self.peak_in_flight = max(self.peak_in_flight, self._in_flight)
            self.calls.append({
                "url": url,
                "payload": payload,
                "source": source,
                "ttl": ttl,
                "headers": dict(headers or {}),
            })
            status, data = (
                self.status_queue.pop(0)
                if self.status_queue
                else (
                    200,
                    {
                        "object": "interaction",
                        "status": "completed",
                        "steps": [
                            {
                                "type": "model_output",
                                "content": [{"type": "text", "text": json.dumps({"edges": []})}],
                            }
                        ],
                    },
                )
            )
        try:
            if self.sleep_seconds > 0:
                time.sleep(self.sleep_seconds)
            return CachedResponse(
                url=url,
                status=status,
                content_type="application/json",
                body=json.dumps(data).encode("utf-8"),
                fetched_at=datetime.now(UTC),
            )
        finally:
            with self._lock:
                self._in_flight -= 1


def test_rest_gemini_client_request_shape_and_key_hygiene():
    http = RecordingHttpClient()
    secret_key = "AIzaSyFAKE-SECRET-TEST-KEY-DO-NOT-LOG"
    settings = Settings(gemini_api_key=secret_key)
    assert secret_key not in repr(settings)

    client = GeminiClient(http, settings)
    parsed, used_model = client.generate_json(
        "Extract edges",
        EXTRACTION_SCHEMA,
        system_instruction="Be accurate",
        thinking_level="low",
    )
    assert parsed == {"edges": []}
    assert used_model == DEFAULT_EXTRACTOR_MODEL
    assert len(http.calls) == 1
    call = http.calls[0]
    assert call["url"] == GEMINI_INTERACTIONS_URL
    assert secret_key not in call["url"]
    assert secret_key not in json.dumps(call["payload"])
    assert call["headers"]["x-goog-api-key"] == secret_key
    assert call["headers"]["Api-Revision"] == "2026-05-20"
    assert call["payload"]["store"] is False
    assert call["payload"]["model"] == "gemini-3.8-flash"
    assert call["payload"]["response_format"] == {
        "type": "text",
        "mime_type": "application/json",
        "schema": EXTRACTION_SCHEMA,
    }
    assert "temperature" not in call["payload"]["generation_config"]
    assert call["payload"]["generation_config"]["thinking_level"] == "low"


def test_rest_gemini_client_argon_falls_back_to_flash_on_429():
    http = RecordingHttpClient()
    http.enqueue_json({"error": "rate limit"}, status=429)
    http.enqueue_json(
        {
            "steps": [
                {
                    "type": "model_output",
                    "content": [{"type": "text", "text": json.dumps({"ok": True})}],
                }
            ]
        },
        status=200,
    )
    client = GeminiClient(http, Settings(gemini_api_key="test-key"))
    parsed, used_model = client.generate_json(
        "Synthesize insights",
        {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]},
        model=DEFAULT_ORCHESTRATOR_MODEL,
        thinking_level="medium",
    )
    assert parsed == {"ok": True}
    assert used_model == DEFAULT_EXTRACTOR_MODEL
    assert [c["payload"]["model"] for c in http.calls] == [
        DEFAULT_ORCHESTRATOR_MODEL,
        DEFAULT_EXTRACTOR_MODEL,
    ]


def test_rest_gemini_client_enforces_concurrency_cap():
    http = RecordingHttpClient()
    http.sleep_seconds = 0.04
    client = GeminiClient(http, Settings(gemini_api_key="test-key"), max_concurrency=3)

    threads = [
        threading.Thread(target=lambda: client.generate_json("hi", EXTRACTION_SCHEMA))
        for _ in range(9)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(http.calls) == 9
    assert http.peak_in_flight <= 3


def test_rest_gemini_client_missing_key_raises(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    client = GeminiClient(RecordingHttpClient(), Settings(gemini_api_key=None))
    assert not client.has_api_key
    with pytest.raises(GeminiMissingKeyError):
        client.generate_json("hi", EXTRACTION_SCHEMA)


# ---------- 3. DependencyExtractor + FakeGeminiClient + Cache ----------


def test_extractor_verifies_valid_quotes_rejects_mutated_and_replays_cache(tmp_path: Path):
    cache = ExtractionCache(DiskCache(tmp_path))
    fake_ai = FakeGeminiClient(include_mutated_quotes=True)
    resolver = {
        "Taiwan Semiconductor Manufacturing": "ALIAS:TSMC",
        "TSMC": "ALIAS:TSMC",
        "SK Hynix": "SYM:000660.KR",
        "Micron Technology": "CIK:0000723125",
        "ZZFAB": "CIK:0009990002",
    }.get

    extractor = DependencyExtractor(
        fake_ai,
        cache,
        resolve_target_key=resolver,
        portfolio_company_keys={"CIK:0009990001", "ALIAS:TSMC", "CIK:0000723125"},
    )
    company = CompanyExposure(
        rank=1,
        company_key="CIK:0009990001",
        company_name="ZZAlpha Corp",
        identity_status="resolved",
        symbols=["ZZALP"],
        sector="information_technology",
        exposure=0.10,
        etf_count=1,
        contributions=[],
        securities=[],
    )
    filing = _make_filing()

    result = extractor.extract(company, filing, cache_only=False)
    assert not result.cached
    assert result.quality == "sections"
    assert len(result.edges) >= 3
    # FakeGeminiClient emits 2 mutated quotes by default; both must be rejected!
    assert result.rejected == 2
    assert result.interpretation_rejected == 0
    assert all(isinstance(e, VerifiedEdge) for e in result.edges)
    # V-INT sets edge.interpretation on every returned VerifiedEdge
    assert all(
        e.interpretation is not None and e.interpretation.status == "confirmed"
        for e in result.edges
    )
    # All sections come from Filing.sections keys ('1', '2'), never 'Item 1' or 'Item 2' from FakeGeminiClient
    assert {e.section for e in result.edges} <= {"1", "2"}
    tsmc_edges = [e for e in result.edges if e.target_key == "ALIAS:TSMC"]
    assert len(tsmc_edges) == 1
    assert tsmc_edges[0].target_in_portfolio is True
    assert tsmc_edges[0].section == "1"
    assert tsmc_edges[0].filing.accession == "0009990001-26-000001"

    # Second run with NO API key and cache_only=True must replay from disk cache without calling LLM
    keyless_extractor = DependencyExtractor(
        FakeGeminiClient(has_api_key=False),
        cache,
        resolve_target_key=resolver,
        portfolio_company_keys={"CIK:0009990001", "ALIAS:TSMC", "CIK:0000723125"},
    )
    cached_result = keyless_extractor.extract(company, filing, cache_only=True)
    assert cached_result.cached is True
    assert cached_result.rejected == result.rejected
    assert cached_result.interpretation_rejected == result.interpretation_rejected
    assert [e.edge_id for e in cached_result.edges] == [e.edge_id for e in result.edges]
    assert {e.section for e in cached_result.edges} <= {"1", "2"}
    assert all(e.interpretation is not None for e in cached_result.edges)


def test_extractor_raises_company_unavailable_when_uncached_and_keyless(tmp_path: Path):
    cache = ExtractionCache(DiskCache(tmp_path))
    extractor = DependencyExtractor(FakeGeminiClient(has_api_key=False), cache)
    filing = _make_filing()

    with pytest.raises(CompanyUnavailable) as exc_info:
        extractor.extract(("CIK:0009990001", "ZZAlpha Corp"), filing, cache_only=False)
    assert exc_info.value.status == "missing_api_key"


def test_pack_filing_sections_respects_160k_char_cap():
    huge_item_1a = "Risk factor sentence about supply chain concentration. " * 4000
    sections = {
        "Item 1": "Short business overview naming ZZFAB Corp as primary wafer foundry.",
        "Item 2": "Principal fabrication facilities in Taiwan and Arizona.",
        "Item 1A": huge_item_1a,
    }
    packed = pack_filing_sections("", sections, max_chars=MAX_PACKED_CHARS)
    assert len(packed) <= MAX_PACKED_CHARS
    # Item 1 and Item 2 are prioritised ahead of Item 1A
    assert packed.index("[SECTION: Item 1]") < packed.index("[SECTION: Item 2]") < packed.index("[SECTION: Item 1A]")


def test_extract_many_isolates_per_company_failure(tmp_path: Path):
    cache = ExtractionCache(DiskCache(tmp_path))
    fake_ai = FakeGeminiClient(fail_keys={"CIK:0009990099"})
    extractor = DependencyExtractor(fake_ai, cache, max_concurrency=2)
    filing_ok = _make_filing()
    filing_fail = SyntheticFiling(
        company_key="CIK:0009990099",
        form="10-K",
        accession="0009990099-26-000001",
        filed=date(2026, 10, 15),
        url="https://www.sec.gov/Archives/edgar/data/9990099/zzfail-10k.htm",
        canonical_text=SYNTHETIC_FILING_TEXT,
        sections={"1": (0, len(SYNTHETIC_FILING_TEXT))},
    )

    outcomes = extractor.extract_many([
        {"company_key": "CIK:0009990001", "company_name": "ZZAlpha Corp", "filing": filing_ok},
        {"company_key": "CIK:0009990099", "company_name": "ZZFail Corp", "filing": filing_fail},
        {"company_key": "SYM:005930.KR", "company_name": "Samsung Electronics", "filing_status": "no_sec_filing"},
    ])
    assert [o.status for o in outcomes] == ["done", "error", "no_sec_filing"]
    assert outcomes[0].verified_count >= 1
    assert outcomes[1].verified_count == 0
    assert PROMPT_VERSION == extractor.prompt_version


def test_extractor_resolves_filing_ref_via_filing_fetcher(tmp_path: Path):
    """When hoc/jobs.py passes a FilingRef (without .text), extractor resolves it via filing_fetcher._memo."""
    cache = ExtractionCache(DiskCache(tmp_path))
    fake_ai = FakeGeminiClient(include_mutated_quotes=True)
    filing_obj = _make_filing()

    class StubFilingFetcher:
        def __init__(self, f: SyntheticFiling) -> None:
            self._memo = {f.accession: f}

    extractor = DependencyExtractor(
        fake_ai,
        cache,
        filing_fetcher=StubFilingFetcher(filing_obj),
    )
    filing_ref = FilingRef(
        company_key=filing_obj.company_key,
        form="10-K",
        accession=filing_obj.accession,
        filed=filing_obj.filed,
        url=filing_obj.url,
    )
    result = extractor.extract(("CIK:0009990001", "ZZAlpha Corp"), filing_ref)
    assert result.quality == "sections"
    assert len(result.edges) >= 3
    assert result.rejected == 2


def test_extract_reverse_filters_to_top_n_caps_at_10_and_dedupes_forward(tmp_path: Path):
    """extract_reverse runs over other filers' sections, keeps only edges whose target_key
    resolves deterministically to a top-N company, caps at 10 hits, and dedupes with forward pass.
    """
    cache = ExtractionCache(DiskCache(tmp_path))
    fake_ai = FakeGeminiClient(include_mutated_quotes=True)
    # Only TSMC ("ALIAS:TSMC") and ZZAlpha ("CIK:0009990001") are top-N portfolio companies.
    # ZZFAB ("CIK:0009990002") resolves deterministically, but is NOT in top_n_company_keys.
    resolver = {
        "Taiwan Semiconductor Manufacturing": "ALIAS:TSMC",
        "TSMC": "ALIAS:TSMC",
        "ZZFAB": "CIK:0009990002",
    }.get
    top_n_keys = {"CIK:0009990001", "ALIAS:TSMC"}

    extractor = DependencyExtractor(
        fake_ai,
        cache,
        resolve_target_key=resolver,
        portfolio_company_keys=top_n_keys,
    )

    def _extraction_call_count() -> int:
        return sum(1 for c in fake_ai.calls if "edges" in c["schema"].get("properties", {}))

    # 1) Forward pass on filer CIK:0009990001 (which is also in top-N)
    filer_1 = _make_filing()
    forward_res = extractor.extract(("CIK:0009990001", "ZZAlpha Corp"), filer_1)
    ext_calls_after_forward = _extraction_call_count()
    assert ext_calls_after_forward == 1

    # 2) Build 12 reverse candidate filings (including filer_1 + 11 other filers).
    # extract_reverse must cap at MAX_REVERSE_HITS = 10.
    reverse_filings = [filer_1]
    for idx in range(2, 14):
        ck = f"CIK:{9990000 + idx:010d}"
        reverse_filings.append(
            SyntheticFiling(
                company_key=ck,
                form="10-K",
                accession=f"{9990000 + idx:010d}-26-000001",
                filed=date(2026, 10, 15),
                url=f"https://www.sec.gov/Archives/edgar/data/{9990000 + idx}/filing.htm",
                canonical_text=SYNTHETIC_FILING_TEXT,
                sections={"1": (0, len(SYNTHETIC_FILING_TEXT))},
            )
        )
    assert len(reverse_filings) == 13
    assert MAX_REVERSE_HITS == 10

    reverse_res = extractor.extract_reverse(("ALIAS:TSMC", "TSMC"), reverse_filings)
    # Only 10 reverse filings processed; filer_1 hit the disk cache from the forward pass,
    # so only 9 new extraction LLM calls were made.
    assert _extraction_call_count() - ext_calls_after_forward == 9
    assert len(reverse_res.edges) == 10
    # Every kept reverse edge must resolve deterministically to a top-N portfolio company ("ALIAS:TSMC"),
    # never to non-top-N "CIK:0009990002" or unresolved "SK Hynix" / geographic targets.
    assert all(e.target_key == "ALIAS:TSMC" for e in reverse_res.edges)
    assert all(e.target_in_portfolio is True for e in reverse_res.edges)
    assert all(e.interpretation is not None for e in reverse_res.edges)
    # And the edge connecting CIK:0009990001 -> ALIAS:TSMC in forward_res and reverse_res shares edge_id,
    # so dedupe_edges removes the duplicate.
    combined = dedupe_edges(forward_res.edges, reverse_res.edges)
    edge_ids = [e.edge_id for e in combined]
    assert len(edge_ids) == len(set(edge_ids))
    assert len(combined) == len(forward_res.edges) + len(reverse_res.edges) - 1


# ---------- 4. V-INT: Interpretation Verification (Rules + Independent Judge + Cache) ----------


def _make_edge(
    *,
    quote: str,
    target_name: str,
    edge_type: str = "supplier",
    target_kind: str = "company",
    sole_source: bool = False,
    source_company_key: str = "CIK:0009990001",
    source_company_name: str = "ZZAlpha Corp",
    source_in_portfolio: bool = True,
) -> VerifiedEdge:
    f_ref = _make_filing_ref(company_key=source_company_key)
    eid = make_edge_id(f_ref.accession, quote, edge_type, target_name)
    return VerifiedEdge(
        edge_id=eid,
        source_company_key=source_company_key,
        source_company_name=source_company_name,
        source_in_portfolio=source_in_portfolio,
        edge_type=edge_type,  # type: ignore[arg-type]
        target_name=target_name,
        target_kind=target_kind,  # type: ignore[arg-type]
        target_key=None,
        target_in_portfolio=False,
        sole_source=sole_source,
        qualifier=None,
        evidence_quote=quote,
        section="1",
        filing=f_ref,
    )


def test_v_int_rules_detect_all_six_flags_with_300_char_context():
    doc = (
        "Item 1. Business. ZZAlpha Corp designs data center accelerators.\n"
        "Competition: Our primary competitors in data center processors include ZZCompete Corp and ZZRival Ltd.\n"
        "Supply Chain: We rely on ZZFAB Corp as our sole wafer foundry for 3nm chips.\n"
        "We do not rely on ZZNegated Vendor Inc. for any critical components in our current generation.\n"
        "If we were to engage ZZHypo Foundry Corp in the future, we could potentially diversify wafer supply.\n"
        "Customers: We sell processors directly to ZZCloud Customer Corp, which accounted for 16% of our revenue.\n"
        "Suppliers: We purchase optical substrates from ZZOptics Supplier GmbH under a multi-year supply contract.\n"
        "Geography: We distribute products across various countries in Europe and Asia.\n"
        "Executive Officers: Prior to joining us in 2025, Mr. John Smith previously served as Senior Vice President "
        "at ZZBio Former Corp from 2019 to 2024.\n"
        "Industry Note: Third-party industry analysts report that ZZOther Corp purchases memory from ZZMystery Inc."
    )

    # 0) Clean factual dependency -> 0 flags
    e_clean = _make_edge(
        quote="We rely on ZZFAB Corp as our sole wafer foundry for 3nm chips.",
        target_name="ZZFAB Corp",
        edge_type="foundry",
        sole_source=True,
    )
    flags_clean, reason_clean, ctx_clean = check_interpretation_rules(e_clean, doc)
    assert flags_clean == []
    assert reason_clean is None
    assert "ZZFAB Corp" in ctx_clean

    # 1) competitor_mention (detected even if the word 'competitors' is just before the quote in the ±300-char context!)
    e_comp = _make_edge(
        quote="in data center processors include ZZCompete Corp and ZZRival Ltd.",
        target_name="ZZCompete Corp",
        edge_type="supplier",
    )
    flags_comp, _, _ = check_interpretation_rules(e_comp, doc)
    assert "competitor_mention" in flags_comp

    # 2) negated
    e_neg = _make_edge(
        quote="We do not rely on ZZNegated Vendor Inc. for any critical components in our current generation.",
        target_name="ZZNegated Vendor Inc.",
        edge_type="supplier",
    )
    flags_neg, _, _ = check_interpretation_rules(e_neg, doc)
    assert "negated" in flags_neg

    # 3) hypothetical
    e_hypo = _make_edge(
        quote="If we were to engage ZZHypo Foundry Corp in the future, we could potentially diversify wafer supply.",
        target_name="ZZHypo Foundry Corp",
        edge_type="foundry",
    )
    flags_hypo, _, _ = check_interpretation_rules(e_hypo, doc)
    assert "hypothetical" in flags_hypo

    # 4a) direction_mismatch: "we sell to X" labelled as supplier
    e_dir_sup = _make_edge(
        quote="We sell processors directly to ZZCloud Customer Corp, which accounted for 16% of our revenue.",
        target_name="ZZCloud Customer Corp",
        edge_type="supplier",
    )
    flags_dir_sup, _, _ = check_interpretation_rules(e_dir_sup, doc)
    assert "direction_mismatch" in flags_dir_sup

    # 4b) direction_mismatch: "we purchase from X" labelled as customer
    e_dir_cust = _make_edge(
        quote="We purchase optical substrates from ZZOptics Supplier GmbH under a multi-year supply contract.",
        target_name="ZZOptics Supplier GmbH",
        edge_type="customer",
    )
    flags_dir_cust, _, _ = check_interpretation_rules(e_dir_cust, doc)
    assert "direction_mismatch" in flags_dir_cust

    # 5) generic_reference
    e_gen = _make_edge(
        quote="We distribute products across various countries in Europe and Asia.",
        target_name="various countries",
        edge_type="facility",
        target_kind="country",
    )
    flags_gen, _, _ = check_interpretation_rules(e_gen, doc)
    assert "generic_reference" in flags_gen

    # 6a) subject_mismatch (biographical mention in near context)
    e_bio = _make_edge(
        quote="Mr. John Smith previously served as Senior Vice President at ZZBio Former Corp from 2019 to 2024.",
        target_name="ZZBio Former Corp",
        edge_type="supplier",
    )
    flags_bio, _, _ = check_interpretation_rules(e_bio, doc)
    assert "subject_mismatch" in flags_bio

    # 6b) subject_mismatch (reverse link where filer is not the subject in context)
    tail_only_doc = "Third-party industry analysts report that ZZOther Corp purchases memory from ZZMystery Inc."
    e_rev = _make_edge(
        quote=tail_only_doc,
        target_name="ZZMystery Inc.",
        edge_type="supplier",
        source_company_key="CIK:0008880008",
        source_company_name="ZZUnmentioned Filer Corp",
        source_in_portfolio=False,
    )
    flags_rev, _, _ = check_interpretation_rules(e_rev, tail_only_doc, is_reverse=True)
    assert "subject_mismatch" in flags_rev


def test_v_int_independent_judge_decisions_and_per_edge_cache(tmp_path: Path):
    doc = (
        "Item 1. Business. ZZAlpha Corp designs data center accelerators.\n"
        "We rely on ZZFAB Corp as our sole wafer foundry for 3nm chips.\n"
        "We compete with ZZCompete Corp in the server GPU market.\n"
        "We do not rely on ZZNegated Vendor Inc. for any critical components.\n"
        "We sell processors directly to ZZCloud Customer Corp, which accounted for 16% of our revenue.\n"
        "Prior to joining us, Ms. Jane Doe previously served as an officer at ZZBio Former Corp.\n"
        "If we were to engage ZZHypo Foundry Corp in the future, we could potentially diversify wafer supply.\n"
    )
    e_clean = _make_edge(
        quote="We rely on ZZFAB Corp as our sole wafer foundry for 3nm chips.",
        target_name="ZZFAB Corp",
        edge_type="foundry",
        sole_source=True,
    )
    e_comp = _make_edge(
        quote="We compete with ZZCompete Corp in the server GPU market.",
        target_name="ZZCompete Corp",
        edge_type="supplier",
    )
    e_neg = _make_edge(
        quote="We do not rely on ZZNegated Vendor Inc. for any critical components.",
        target_name="ZZNegated Vendor Inc.",
        edge_type="supplier",
    )
    e_dir = _make_edge(
        quote="We sell processors directly to ZZCloud Customer Corp, which accounted for 16% of our revenue.",
        target_name="ZZCloud Customer Corp",
        edge_type="supplier",
    )
    e_bio = _make_edge(
        quote="Prior to joining us, Ms. Jane Doe previously served as an officer at ZZBio Former Corp.",
        target_name="ZZBio Former Corp",
        edge_type="supplier",
    )
    e_hypo = _make_edge(
        quote="If we were to engage ZZHypo Foundry Corp in the future, we could potentially diversify wafer supply.",
        target_name="ZZHypo Foundry Corp",
        edge_type="foundry",
    )

    cache = ExtractionCache(DiskCache(tmp_path))
    fake_ai = FakeGeminiClient()

    res = verify_company_interpretations(
        [e_clean, e_comp, e_neg, e_dir, e_bio, e_hypo],
        doc,
        client=fake_ai,
        cache=cache,
        sample_rate=0.0,  # test flagged edges specifically first
    )

    # Exactly ONE Flash call made for the company batch with hoc-v3-judge-1
    assert len(fake_ai.calls) == 1
    judge_call = fake_ai.calls[0]
    assert judge_call["schema"] == JUDGE_SCHEMA
    assert JUDGE_PROMPT_VERSION in judge_call["prompt"]

    # 4 rejected (competitor, negated, direction_mismatch, subject_mismatch)
    assert res.interpretation_rejected == 4
    assert {e.target_name for e in res.rejected_edges} == {
        "ZZCompete Corp",
        "ZZNegated Vendor Inc.",
        "ZZCloud Customer Corp",
        "ZZBio Former Corp",
    }
    assert all(
        e.interpretation is not None and e.interpretation.status == "rejected"
        for e in res.rejected_edges
    )

    # 2 kept: ZZFAB Corp (confirmed) + ZZHypo Foundry Corp (flagged with hypothetical + judge_unclear)
    kept_by_target = {e.target_name: e for e in res.edges}
    assert set(kept_by_target) == {"ZZFAB Corp", "ZZHypo Foundry Corp"}

    clean_interp = kept_by_target["ZZFAB Corp"].interpretation
    assert clean_interp is not None
    assert clean_interp.status == "confirmed"
    assert clean_interp.method == "rules"
    assert clean_interp.flags == []

    hypo_interp = kept_by_target["ZZHypo Foundry Corp"].interpretation
    assert hypo_interp is not None
    assert hypo_interp.status == "flagged"
    assert hypo_interp.method == "rules+model"
    assert "hypothetical" in hypo_interp.flags
    assert "judge_unclear" in hypo_interp.flags
    assert hypo_interp.model == DEFAULT_EXTRACTOR_MODEL

    # Also verify that when the judge returns supports + clears a false-alarm flag, status becomes confirmed
    cleared_interp = decide_interpretation_from_judge(
        ["competitor_mention"],
        "Competitor cue near target",
        label="supports",
        cleared_flags=["competitor_mention"],
        judge_reason="Target is a confirmed supplier; 'compete' referred to end-market products.",
        model=DEFAULT_EXTRACTOR_MODEL,
    )
    assert cleared_interp == EdgeInterpretation(
        status="confirmed",
        method="rules+model",
        flags=[],
        reason="Target is a confirmed supplier; 'compete' referred to end-market products.",
        model=DEFAULT_EXTRACTOR_MODEL,
    )

    # Re-running with cache_only=True and a keyless client replays per-edge verdicts from ai/judge cache
    keyless_ai = FakeGeminiClient(has_api_key=False)
    cached_res = verify_company_interpretations(
        [e_clean, e_comp, e_neg, e_dir, e_bio, e_hypo],
        doc,
        client=keyless_ai,
        cache=cache,
        cache_only=True,
        sample_rate=0.0,
    )
    assert len(keyless_ai.calls) == 0
    assert cached_res.interpretation_rejected == 4
    assert [e.edge_id for e in cached_res.edges] == [e.edge_id for e in res.edges]
    assert cached_res.interpretations[e_hypo.edge_id].status == "flagged"


def test_v_int_deterministic_20_percent_unflagged_sampling():
    sampled = [
        should_sample_unflagged_edge(f"edge_{i:012x}", sample_rate=0.20)
        for i in range(500)
    ]
    rate = sum(sampled) / len(sampled)
    # Deterministic hash bucket (~20%)
    assert 0.14 <= rate <= 0.26
    # Deterministic across calls
    assert sampled == [
        should_sample_unflagged_edge(f"edge_{i:012x}", sample_rate=0.20)
        for i in range(500)
    ]


def test_extractor_populates_interpretation_and_counts_interpretation_rejected(tmp_path: Path):
    """End-to-end through DependencyExtractor.extract: quotes that are verbatim in the filing pass
    verify_quote, and V-INT then rejects competitor/negated mis-extractions while flagging hypotheticals.
    """
    doc = (
        "Item 1. Business. ZZAlpha Corp designs advanced processors. "
        "We rely on ZZFAB Corp as our sole wafer foundry for all 3nm processor designs. "
        "We compete intensely with ZZCompete Corp across all server processor segments. "
        "If we were to engage ZZHypo Foundry Corp in the future, we could potentially add backup capacity."
    )
    filing = _make_filing(doc)
    cache = ExtractionCache(DiskCache(tmp_path))
    fake_ai = FakeGeminiClient(include_mutated_quotes=False)
    fake_ai.add_response(
        "FILING TEXT:",
        {
            "edges": [
                {
                    "edge_type": "foundry",
                    "target_name": "ZZFAB Corp",
                    "target_kind": "company",
                    "sole_source": True,
                    "qualifier": "sole wafer foundry",
                    "section": "1",
                    "evidence_quote": "We rely on ZZFAB Corp as our sole wafer foundry for all 3nm processor designs.",
                },
                {
                    "edge_type": "supplier",
                    "target_name": "ZZCompete Corp",
                    "target_kind": "company",
                    "sole_source": False,
                    "qualifier": "",
                    "section": "1",
                    "evidence_quote": "We compete intensely with ZZCompete Corp across all server processor segments.",
                },
                {
                    "edge_type": "foundry",
                    "target_name": "ZZHypo Foundry Corp",
                    "target_kind": "company",
                    "sole_source": False,
                    "qualifier": "",
                    "section": "1",
                    "evidence_quote": (
                        "If we were to engage ZZHypo Foundry Corp in the future, "
                        "we could potentially add backup capacity."
                    ),
                },
            ]
        },
    )

    extractor = DependencyExtractor(fake_ai, cache)
    result = extractor.extract(("CIK:0009990001", "ZZAlpha Corp"), filing)

    # All 3 quotes are verbatim in `doc`, so quote verifier rejected 0, and V-INT rejected 1 (ZZCompete Corp)
    assert result.rejected == 0
    assert result.interpretation_rejected == 1
    by_target = {e.target_name: e for e in result.edges}
    assert set(by_target) == {"ZZFAB Corp", "ZZHypo Foundry Corp"}
    assert by_target["ZZFAB Corp"].interpretation is not None
    assert by_target["ZZFAB Corp"].interpretation.status == "confirmed"
    assert by_target["ZZHypo Foundry Corp"].interpretation is not None
    assert by_target["ZZHypo Foundry Corp"].interpretation.status == "flagged"

    # Also test single-edge helper verify_edge_interpretation + extract_quote_context
    single_interp = verify_edge_interpretation(
        by_target["ZZFAB Corp"].model_copy(update={"interpretation": None}),
        doc,
        client=fake_ai,
        cache=cache,
    )
    assert single_interp.status == "confirmed"
    ctx, (q_s, q_e) = extract_quote_context(by_target["ZZFAB Corp"].evidence_quote, doc)
    assert ctx[q_s:q_e] == by_target["ZZFAB Corp"].evidence_quote


def test_v_int_rules_do_not_spill_across_adjacent_sentences_in_300_char_window():
    """Competitor and negation cues in adjacent sentences within the ±300-char window must NOT
    flag a clean supplier/customer sentence, while the ±300-char context_window is preserved for the judge.
    """
    doc = (
        "We do not have long-term commitments with certain legacy vendors. "
        "We engage with independent subcontractors such as ZZHonHai Precision Co., Ltd. and ZZWistron Corp. "
        "to perform assembly, testing and packaging of our final products. "
        "Competition. We compete intensely with ZZRival Corp across all server segments."
    )
    edge = _make_edge(
        quote=(
            "We engage with independent subcontractors such as ZZHonHai Precision Co., Ltd. and ZZWistron Corp. "
            "to perform assembly, testing and packaging of our final products."
        ),
        target_name="ZZHonHai Precision Co., Ltd.",
        edge_type="contract_manufacturer",
    )
    flags, reason, ctx = check_interpretation_rules(edge, doc)
    assert flags == []
    assert reason is None
    # The ±300-char context window still includes the surrounding sentences for the judge
    assert "We compete intensely with ZZRival Corp" in ctx
    assert "We do not have long-term commitments" in ctx
