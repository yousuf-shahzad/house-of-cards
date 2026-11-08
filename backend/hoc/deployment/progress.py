"""A separate subscriber keeps polling responsive while model workers are busy."""

import asyncio

from vercel.queue import Message, subscribe


def _publish(payload: dict) -> None:
    from hoc.deployment.runner import Worker
    from hoc.deployment.runtime import create_service, deployment_settings

    service = create_service(deployment_settings(), budget_seconds=180)
    Worker(service, service.job_store).aggregate(payload)


@subscribe(topic="hoc-progress", max_concurrency=1, max_attempts=3)
async def publish_progress(message: Message[dict[str, object]]) -> None:
    await asyncio.to_thread(_publish, message.payload)
