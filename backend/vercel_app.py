"""Vercel's web entrypoint. No process-local warm-up tasks after returning a response."""

from hoc.api.app import create_app
from hoc.deployment.runtime import create_service, deployment_settings

settings = deployment_settings()
app = create_app(service_factory=lambda: create_service(settings), settings=settings, warm=False)
