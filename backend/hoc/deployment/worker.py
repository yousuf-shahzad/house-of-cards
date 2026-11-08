"""Build-discovered private Vercel Queue subscribers (not public HTTP routes)."""

import asyncio

from vercel.queue import Message, subscribe


def _work(payload: dict, *, progress: bool = False) -> None:
    from hoc.deployment.runner import Worker
    from hoc.deployment.runtime import create_service, deployment_settings

    service = create_service(deployment_settings(), budget_seconds=180)
    worker = Worker(service, service.job_store)
    if progress:
        worker.aggregate(payload)
    else:
        worker.handle(payload)


@subscribe(topic="hoc-work", max_concurrency=4, max_attempts=3)
async def process_work(message: Message[dict[str, object]]) -> None:
    await asyncio.to_thread(_work, message.payload)


@subscribe(topic="hoc-progress", max_concurrency=1, max_attempts=3)
async def publish_progress(message: Message[dict[str, object]]) -> None:
    await asyncio.to_thread(_work, message.payload, progress=True)
