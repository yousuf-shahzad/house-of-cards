"""Build-discovered private Vercel Queue subscribers (not public HTTP routes)."""

import asyncio

from vercel.queue import Message, subscribe


def _work(payload: dict) -> None:
    from hoc.deployment.runner import Worker
    from hoc.deployment.runtime import create_service, deployment_settings

    service = create_service(deployment_settings(), budget_seconds=180)
    Worker(service, service.job_store).handle(payload)


@subscribe(topic="hoc-work", max_concurrency=4, max_attempts=3)
async def process_work(message: Message[dict[str, object]]) -> None:
    await asyncio.to_thread(_work, message.payload)
