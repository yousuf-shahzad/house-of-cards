"""Durable job pointers and fan-out, keeping the existing public API models."""

from __future__ import annotations

import os
import time
import uuid
from typing import Protocol

from hoc.contract import (
    AnalysisResponse,
    CompanyRunStatus,
    DependencyJob,
    DependencyRequest,
    DependencyResult,
    ErrorBody,
    JobNotFoundError,
    PortfolioRequest,
    PortfolioValidationError,
    ResearchJob,
    ResearchNotFoundError,
    ResearchRequest,
    SourcesUnavailableError,
)
from hoc.deployment.storage import ObjectStore, encode, read_json
from hoc.jobs import JOB_RETENTION_SECONDS, job_id_for, research_id_for

WORK_TOPIC = "hoc-work"
PROGRESS_TOPIC = "hoc-progress"
MAX_RUN_SECONDS = 1800


class Publisher(Protocol):
    def send(self, topic: str, payload: dict, *, key: str) -> None: ...


class QueuePublisher:
    def send(self, topic: str, payload: dict, *, key: str) -> None:
        from vercel.queue import DuplicateIdempotencyKeyError
        from vercel.queue.sync import QueueClient

        try:
            deployment = os.getenv("VERCEL_DEPLOYMENT_ID", "local")
            QueueClient().send(topic, payload, idempotency_key=f"{deployment}:{key}", retention=3600)
        except DuplicateIdempotencyKeyError:
            pass


def run_path(record: dict, suffix: str) -> str:
    return f"runs/{record['run_id']}/{suffix}.json"


class JobStore:
    def __init__(self, objects: ObjectStore, publisher: Publisher) -> None:
        self.objects, self.publisher = objects, publisher

    @staticmethod
    def pointer(kind: str, job_id: str) -> str:
        return f"jobs/{kind}/{job_id}.json"

    def read(self, kind: str, job_id: str) -> dict | None:
        record = read_json(self.objects, self.pointer(kind, job_id))
        if record is None:
            return None
        final = read_json(self.objects, run_path(record, "final"))
        if final is not None:
            record["snapshot"] = final
        elif time.time() - record["created_at"] > MAX_RUN_SECONDS:
            # A killed/exhausted delivery must not leave the UI polling forever.
            snapshot = dict(record["snapshot"])
            snapshot.update(
                status="error",
                error=ErrorBody(
                    code="INTERNAL_ERROR",
                    message="This scan could not finish. Run it again to reuse cached work.",
                ).model_dump(mode="json"),
            )
            record["snapshot"] = snapshot
        return record

    def start(self, kind: str, job_id: str, payload: dict, snapshot: dict) -> dict:
        path = self.pointer(kind, job_id)
        for _ in range(3):
            previous = self.objects.get(path)
            if previous:
                existing = self.read(kind, job_id)
                expired = (
                    existing["snapshot"]["status"] in ("done", "error")
                    and time.time() - existing["created_at"] > JOB_RETENTION_SECONDS
                )
                if existing["snapshot"]["status"] != "error" and not expired:
                    # Re-dispatch repairs a submit interrupted between its Blob write
                    # and queue publication. The queue key prevents duplicate work.
                    self._dispatch(existing)
                    return existing
                try:
                    self.objects.delete(path, etag=previous.etag)
                except Exception:
                    if self.objects.get(path) is not None:
                        continue
                    raise
            record = {
                **payload,
                "kind": kind,
                "job_id": job_id,
                "run_id": uuid.uuid4().hex,
                "created_at": time.time(),
                "snapshot": snapshot,
            }
            # Write the immutable payload first; workers never receive portfolio data
            # or secrets in queue messages, only this opaque run reference.
            self.objects.put(run_path(record, "manifest"), encode(record), overwrite=False)
            if self.objects.put(path, encode(record), overwrite=False):
                self._dispatch(record)
                return record
        raise SourcesUnavailableError("The scan is busy. Please try again.")

    def _dispatch(self, record: dict) -> None:
        try:
            self.publisher.send(
                WORK_TOPIC,
                {"run_id": record["run_id"], "task": "dispatch"},
                key=f"{record['run_id']}:dispatch",
            )
        except Exception as exc:
            raise SourcesUnavailableError("The scan service is unavailable. Please try again.") from exc

    def progress(self, record: dict) -> None:
        self.publisher.send(
            PROGRESS_TOPIC,
            {"run_id": record["run_id"]},
            key=f"{record['run_id']}:progress:{uuid.uuid4().hex}",
        )


class QueuedDependencyJobs:
    def __init__(self, analyse, pipeline, store: JobStore) -> None:
        self._analyse, self.pipeline, self.store = analyse, pipeline, store

    def submit(self, request: DependencyRequest, *, cache_only=False, wait=0) -> DependencyJob:
        analysis = self._analyse(PortfolioRequest(holdings=request.holdings))
        top = [c for c in analysis.exposures if c.exposure > 0][: request.top_n]
        job_id = job_id_for(request, top, self.pipeline.prompt_version)
        companies = [
            CompanyRunStatus(
                company_key=c.company_key, company_name=c.company_name, exposure=c.exposure, status="queued"
            )
            for c in top
        ]
        snapshot = DependencyJob(
            job_id=job_id,
            status="queued",
            companies=companies,
            progress_total=len(top),
            steps_total=len(top) + 1,
        )
        record = self.store.start(
            "dependencies",
            job_id,
            {
                "analysis": analysis.model_dump(mode="json"),
                "request": request.model_dump(mode="json"),
                "cache_only": cache_only,
                "top": [c.model_dump(mode="json") for c in top],
            },
            snapshot.model_dump(mode="json"),
        )
        return DependencyJob.model_validate(record["snapshot"])

    def get(self, job_id: str) -> DependencyJob:
        record = self.store.read("dependencies", job_id)
        if record is None:
            raise JobNotFoundError("No dependency scan with this ID.", {"job_id": job_id})
        return DependencyJob.model_validate(record["snapshot"])

    def finished(self, job_id: str) -> tuple[AnalysisResponse, DependencyResult]:
        record = self.store.read("dependencies", job_id)
        if record is None:
            raise JobNotFoundError("No dependency scan with this ID.", {"job_id": job_id})
        snapshot = DependencyJob.model_validate(record["snapshot"])
        if snapshot.status != "done" or snapshot.result is None:
            raise PortfolioValidationError(
                "VALIDATION_ERROR",
                "Wait for the dependency scan to finish.",
                {"job_id": job_id, "status": snapshot.status},
            )
        return AnalysisResponse.model_validate(record["analysis"]), snapshot.result


class QueuedResearchJobs:
    def __init__(self, dependencies: QueuedDependencyJobs, runner, store: JobStore) -> None:
        self.dependency_jobs, self.runner, self.store = dependencies, runner, store

    def submit(self, dependency_job_id: str, request: ResearchRequest, *, cache_only=False, wait=0):
        analysis, result = self.dependency_jobs.finished(dependency_job_id)
        job_id = research_id_for(dependency_job_id, request, self.runner.prompt_version)
        snapshot = ResearchJob(
            research_id=job_id,
            dependency_job_id=dependency_job_id,
            status="queued",
            progress_total=request.max_items,
        )
        record = self.store.start(
            "research",
            job_id,
            {
                "analysis": analysis.model_dump(mode="json"),
                "result": result.model_dump(mode="json"),
                "request": request.model_dump(mode="json"),
                "cache_only": cache_only,
            },
            snapshot.model_dump(mode="json"),
        )
        return ResearchJob.model_validate(record["snapshot"])

    def get(self, research_id: str):
        record = self.store.read("research", research_id)
        if record is None:
            raise ResearchNotFoundError("No research scan with this ID.", {"research_id": research_id})
        return ResearchJob.model_validate(record["snapshot"])
