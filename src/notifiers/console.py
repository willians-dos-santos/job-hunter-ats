import logging
from typing import Any, Optional

import httpx

from src.models import JobOpening
from src.notifiers.base import BaseNotifier

logger = logging.getLogger(__name__)


class ConsoleNotifier(BaseNotifier):
    """Notifier that prints structured job details to stdout/console."""

    @property
    def is_configured(self) -> bool:
        return True

    def format_message(self, job: JobOpening) -> str:
        border = "=" * 60
        if job.published_at:
            published_at = job.published_at.strftime("%d/%m/%Y %H:%M")
        else:
            published_at = "Data não informada"
        return (
            f"\n{border}\n"
            f" [NOVA VAGA ENCONTRADA]\n"
            f" Empresa:     {job.company}\n"
            f" Cargo:       {job.title}\n"
            f" Local:       {job.location}\n"
            f" Publicada em: {published_at}\n"
            f" Plataforma:  {job.source}\n"
            f" Link Direto: {job.url}\n"
            f"{border}\n"
        )

    def notify(
        self,
        job: JobOpening,
        client: Optional[httpx.AsyncClient] = None,
        **kwargs: Any,
    ) -> bool:
        print(self.format_message(job))
        return True
