"""Vercel-specific wiring. No detached work is required after an HTTP response."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from hoc.config import Settings
from hoc.contract import ChangeIdeasResponse, EtfHoldings, SourcesUnavailableError
from hoc.core.cache import DiskCache
from hoc.core.http import CachedHttpClient
from hoc.deployment.jobs import (
    JobStore,
    QueuedDependencyJobs,
    QueuedResearchJobs,
    QueuePublisher,
)
from hoc.deployment.storage import BlobStore
from hoc.service import EtfService


def deployment_settings() -> Settings:
    os.environ.setdefault("HOC_CACHE_BACKEND", "vercel")
    configured = Settings.from_env()
    # Vercel's application directory is read-only. Shared Blob is authoritative;
    # this writable directory is only a disposable accelerator.
    return replace(configured, cache_dir=Path(tempfile.gettempdir()) / "house-of-cards")


class _DeadlineClient:
    def __init__(self, client, budget_seconds: float | None) -> None:
        self.client = client
        self.deadline = time.monotonic() + budget_seconds if budget_seconds else None

    def request(self, *args, **kwargs):
        remaining = self.deadline - time.monotonic() if self.deadline is not None else 45.0
        if remaining <= 0:
            raise httpx.ReadTimeout("This queued step has reached its request budget.")
        kwargs["timeout"] = min(float(kwargs.get("timeout", 45)), 45.0, remaining)
        return self.client.request(*args, **kwargs)


class BudgetedHttp(CachedHttpClient):
    def __init__(self, settings, cache, budget_seconds=None) -> None:
        super().__init__(settings, cache)
        self._client = _DeadlineClient(self._client, budget_seconds)


class VercelService(EtfService):
    job_store: JobStore

    @property
    def dependency_jobs(self):
        with self._locks_guard:
            if self._jobs is None:
                self._jobs = QueuedDependencyJobs(self.analyse, self.dependency_pipeline, self.job_store)
            return self._jobs

    @property
    def research_jobs(self):
        dependencies = self.dependency_jobs
        with self._locks_guard:
            if self._research is None:
                self._research = QueuedResearchJobs(dependencies, self.research_runner, self.job_store)
            return self._research

    def load_etf(self, ticker, source=None):
        cache = DiskCache(self.settings.cache_dir)
        revision = os.getenv("VERCEL_GIT_COMMIT_SHA", "local")[:12]
        key = f"{revision}:{ticker.upper()}:{source or 'auto'}:{','.join(self.settings.source_order)}"
        entry = cache.get("normalised", key)
        if entry and (self.settings.offline or datetime.now(UTC) - entry.fetched_at < timedelta(hours=24)):
            try:
                return EtfHoldings.model_validate_json(entry.body)
            except ValueError:
                pass
        loaded = super().load_etf(ticker, source)
        if isinstance(loaded, EtfHoldings):
            cache.put(
                "normalised",
                key,
                loaded.model_dump_json().encode(),
                {"status": 200, "content_type": "application/json"},
            )
        return loaded

    def change_ideas(self, request):
        # Rules complete within this request; AI proposals use the same queue as
        # dependency work and are polled through the existing response contract.
        from hoc.graph.idea_proposer import build_portfolio_issues
        from hoc.portfolio.ideas import baseline_idea_metrics

        rules = self._compute_change_ideas(request)
        if not self.settings.gemini_api_key or self.settings.offline:
            rules.ai_status = "missing_api_key" if not self.settings.gemini_api_key else "not_used"
            return rules
        holdings_key = (tuple(sorted((h.ticker, h.allocation) for h in request.holdings)), request.top_n)
        context = self._idea_contexts[holdings_key]
        if context.baseline.coverage.missing_allocation > 0:
            return rules
        facts = baseline_idea_metrics(request, context.baseline, context.cached, aliases=self.aliases)
        issues = build_portfolio_issues(context.baseline, facts)
        identity = {
            "request": request.model_dump(mode="json"),
            "issues": [(i.issue_id, i.metric_id, i.value) for i in issues],
            "model": self.settings.gemini_orchestrator_model,
            "prompt": self.idea_proposer.prompt_version,
            "date": str(context.baseline.as_of_date),
        }
        key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        try:
            record = self.job_store.start(
                "ideas", key, {"request": request.model_dump(mode="json")}, {"status": "queued"}
            )
        except SourcesUnavailableError:
            rules.ai_status = "failed"
            rules.notes.append("AI suggestions are temporarily unavailable. Calculated change ideas are still available.")
            return rules
        if record["snapshot"]["status"] == "done":
            return ChangeIdeasResponse.model_validate(record["snapshot"]["result"])
        rules.ai_status = "failed" if record["snapshot"]["status"] == "error" else "pending"
        rules.model = self.settings.gemini_orchestrator_model
        rules.prompt_version = self.idea_proposer.prompt_version
        return rules


def create_service(settings: Settings, *, budget_seconds: float | None = None) -> VercelService:
    http = BudgetedHttp(settings, DiskCache(settings.cache_dir), budget_seconds)
    service = VercelService.from_settings(settings, http=http)
    service.job_store = JobStore(BlobStore(), QueuePublisher())
    return service
