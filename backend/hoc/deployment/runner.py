"""Request-bound queue handlers: one company per invocation, then one synthesis."""

from __future__ import annotations

import logging
import time

from hoc.contract import (
    AnalysisResponse,
    CompanyExposure,
    CompanyRunStatus,
    DependencyCounts,
    DependencyJob,
    DependencyRequest,
    DependencyResult,
    ErrorBody,
    ResearchFinding,
    ResearchJob,
    ResearchRequest,
    VerifiedEdge,
)
from hoc.deployment.jobs import WORK_TOPIC, JobStore, run_path
from hoc.deployment.storage import encode, read_json
from hoc.jobs import (
    DependencyJobs,
    Extraction,
    InlineExecutor,
    _coverage,
    _Job,
    _resolve_and_flag,
    _with_importance,
)

log = logging.getLogger(__name__)


class ReportingJobs(DependencyJobs):
    """Publish meaningful company transitions without changing the local runner."""

    def __init__(self, *args, report, **kwargs):
        super().__init__(*args, **kwargs)
        self.report = report

    def _set_company(self, job, index, **changes):
        previous = job.companies[index].status
        super()._set_company(job, index, **changes)
        current = job.companies[index]
        if current.status != previous and current.status in ("fetching", "extracting", "researching"):
            self.report(current)


class Worker:
    def __init__(self, service, store: JobStore) -> None:
        self.service, self.store = service, store

    def manifest(self, run_id: str) -> dict | None:
        record = read_json(self.store.objects, f"runs/{run_id}/manifest.json")
        if record is None:
            return None
        current = read_json(self.store.objects, self.store.pointer(record["kind"], record["job_id"]))
        return record if current and current["run_id"] == run_id else None

    def send(self, record: dict, task: str, **extra) -> None:
        self.store.publisher.send(
            WORK_TOPIC,
            {"run_id": record["run_id"], "task": task, **extra},
            key=f"{record['run_id']}:{task}:{extra.get('index', '')}",
        )

    def handle(self, payload: dict) -> None:
        record = self.manifest(payload["run_id"])
        if record is None or read_json(self.store.objects, run_path(record, "final")):
            return
        task = payload["task"]
        if task == "dispatch":
            if record["kind"] == "dependencies":
                for index in range(len(record["top"])):
                    self.send(record, "company", index=index)
                if not record["top"]:
                    self.send(record, "finish")
            else:
                self.send(record, record["kind"])
        elif task == "company":
            self.company(record, payload["index"])
        elif task == "finish":
            self.finish(record)
        elif task == "research":
            self.research(record)
        elif task == "ideas":
            self.ideas(record)
        else:
            raise ValueError("Unknown queued task")

    def company(self, record: dict, index: int) -> None:
        final_key = run_path(record, f"companies/{index}/result")
        if read_json(self.store.objects, final_key) is not None:
            self.store.progress(record)
            return
        analysis = AnalysisResponse.model_validate(record["analysis"])
        request = DependencyRequest.model_validate(record["request"])
        company = CompanyExposure.model_validate(record["top"][index])
        status = CompanyRunStatus(
            company_key=company.company_key,
            company_name=company.company_name,
            exposure=company.exposure,
            status="fetching",
        )
        progress_key = run_path(record, f"companies/{index}/progress")
        self.store.objects.put(progress_key, encode({"company": status.model_dump(mode="json")}))
        self.store.progress(record)
        # All work below is awaited by the queue invocation. InlineExecutor here
        # supplies the existing helper seam; it never launches a detached job.
        inline = InlineExecutor()

        def report(current):
            self.store.objects.put(progress_key, encode({"company": current.model_dump(mode="json")}))
            self.store.progress(record)

        local = ReportingJobs(
            lambda _: analysis,
            self.service.dependency_pipeline,
            runner=inline,
            workers=inline,
            research_workers=inline,
            report=report,
        )
        job = _Job(
            job_id=record["job_id"],
            request=request,
            analysis=analysis,
            top=[company],
            cache_only=record["cache_only"],
            companies=[status],
        )
        started = time.monotonic()
        forward = local._forward(job, 0, company)
        reverse = local._reverse(job, 0, company, started)
        extraction = local._finish(job, 0, forward, reverse)
        extractions, findings, researched = local._research_phase(job, [forward], [extraction])
        extraction = extractions[0]
        value = {
            "company": job.companies[0].model_dump(mode="json"),
            "research": [f.model_dump(mode="json") for f in findings],
            "researched": researched,
            "extraction": None
            if extraction is None
            else {
                "edges": [e.model_dump(mode="json") for e in extraction.edges],
                "rejected": extraction.rejected,
                "quality": extraction.quality,
                "cached": extraction.cached,
                "interpretation_rejected": extraction.interpretation_rejected,
            },
        }
        self.store.objects.put(final_key, encode(value), overwrite=False)
        self.store.progress(record)

    def aggregate(self, payload: dict) -> None:
        """The progress subscriber is serialized; company workers never race on a snapshot."""
        record = self.manifest(payload["run_id"])
        if record is None:
            return
        final = read_json(self.store.objects, run_path(record, "final"))
        if final is not None:
            record["snapshot"] = final
        elif record["kind"] == "dependencies":
            companies, findings, done = [], [], 0
            for index, original in enumerate(record["snapshot"]["companies"]):
                value = read_json(self.store.objects, run_path(record, f"companies/{index}/result"))
                if value is not None:
                    done += 1
                    findings.extend(value["research"])
                else:
                    value = read_json(self.store.objects, run_path(record, f"companies/{index}/progress"))
                companies.append(value["company"] if value else original)
            total = len(companies)
            record["snapshot"] = DependencyJob(
                job_id=record["job_id"],
                status="running",
                companies=companies,
                progress_done=done,
                progress_total=total,
                research=findings,
                phase=(
                    "synthesising"
                    if done == total
                    else "researching"
                    if any(c["status"] == "researching" for c in companies)
                    else "reading"
                ),
                steps_done=done,
                steps_total=total + 1,
            ).model_dump(mode="json")
            if done == total:
                self.send(record, "finish")
        else:
            return
        self.store.objects.put(self.store.pointer(record["kind"], record["job_id"]), encode(record))

    def finish(self, record: dict) -> None:
        rows = [
            read_json(self.store.objects, run_path(record, f"companies/{i}/result"))
            for i in range(len(record["top"]))
        ]
        if any(row is None for row in rows):
            return
        analysis = AnalysisResponse.model_validate(record["analysis"])
        companies = [CompanyRunStatus.model_validate(row["company"]) for row in rows]
        extractions = [
            Extraction(
                **{
                    **row["extraction"],
                    "edges": [VerifiedEdge.model_validate(e) for e in row["extraction"]["edges"]],
                }
            )
            for row in rows
            if row["extraction"]
        ]
        pipeline = self.service.dependency_pipeline
        resolver_for = getattr(pipeline, "resolver_for", None)
        edges = _with_importance(
            _resolve_and_flag(
                analysis,
                list({e.edge_id: e for x in extractions for e in x.edges}.values()),
                resolver_for(analysis.exposures) if resolver_for else None,
            )
        )
        metrics, insights = pipeline.insights(analysis, edges, cache_only=record["cache_only"])
        findings = [ResearchFinding.model_validate(f) for row in rows for f in row["research"]]
        analysed = sum(c.status in ("cached", "done") for c in companies)
        result = DependencyResult(
            as_of_date=analysis.as_of_date,
            request=DependencyRequest.model_validate(record["request"]),
            companies=companies,
            edges=edges,
            metrics=metrics,
            insights=insights,
            counts=DependencyCounts(
                companies_requested=len(companies),
                companies_analysed=analysed,
                companies_skipped=len(companies) - analysed,
                verified_edges=len(edges),
                rejected_edges=sum(c.rejected_edges for c in companies),
                interpretation_rejected=sum(x.interpretation_rejected for x in extractions),
                unresolved_counterparties=len(
                    {
                        e.target_name.casefold()
                        for e in edges
                        if e.target_key is None and e.target_kind == "company"
                    }
                ),
            ),
            coverage=_coverage(analysis, companies, edges),
            research=findings,
            research_depth=record["request"]["depth"] if any(r["researched"] for r in rows) else "none",
        )
        snapshot = DependencyJob(
            job_id=record["job_id"],
            status="done",
            phase="done",
            companies=companies,
            progress_done=len(companies),
            progress_total=len(companies),
            result=result,
            research=findings,
            steps_done=len(companies) + 1,
            steps_total=len(companies) + 1,
        )
        self.store.objects.put(
            run_path(record, "final"), snapshot.model_dump_json().encode(), overwrite=False
        )
        self.store.progress(record)

    def research(self, record: dict) -> None:
        analysis = AnalysisResponse.model_validate(record["analysis"])
        result = DependencyResult.model_validate(record["result"])
        snapshot = ResearchJob.model_validate(record["snapshot"])
        snapshot.status = "running"

        def progress(done, total, findings):
            snapshot.progress_done, snapshot.progress_total, snapshot.findings = done, total, list(findings)
            update = {**record, "snapshot": snapshot.model_dump(mode="json")}
            self.store.objects.put(self.store.pointer("research", record["job_id"]), encode(update))

        try:
            findings, merged = self.service.research_runner.run(
                result,
                analysis,
                max_items=ResearchRequest.model_validate(record["request"]).max_items,
                cache_only=record["cache_only"],
                progress=progress,
            )
            snapshot.status, snapshot.result, snapshot.findings = "done", merged, list(findings)
            snapshot.progress_done = snapshot.progress_total = max(snapshot.progress_total, len(findings))
        except Exception:
            log.exception("Queued research failed")
            snapshot.status = "error"
            snapshot.error = ErrorBody(code="INTERNAL_ERROR", message="Research failed. Please try again.")
        self.store.objects.put(
            run_path(record, "final"), snapshot.model_dump_json().encode(), overwrite=False
        )

    def ideas(self, record: dict) -> None:
        from hoc.contract import ChangeIdeasRequest
        from hoc.graph.idea_proposer import build_portfolio_issues
        from hoc.portfolio.ideas import baseline_idea_metrics

        request = ChangeIdeasRequest.model_validate(record["request"])
        rules = self.service._compute_change_ideas(request)
        holdings_key = (tuple(sorted((h.ticker, h.allocation) for h in request.holdings)), request.top_n)
        context = self.service._idea_contexts[holdings_key]
        facts = baseline_idea_metrics(request, context.baseline, context.cached, aliases=self.service.aliases)
        issues = build_portfolio_issues(context.baseline, facts)
        proposer = self.service.idea_proposer
        cached = proposer.read_cached(
            request.holdings,
            issues,
            universe=self.service._read_idea_universe(proposer),
            analysis=context.baseline,
            edges=[e for edges in context.cached.values() for e in edges],
        )
        response = self.service._compute_ai_ideas(request, context, rules, issues, cached)
        self.store.objects.put(
            run_path(record, "final"),
            encode({"status": "done", "result": response.model_dump(mode="json")}),
            overwrite=False,
        )
