import logging
import os
from typing import Any, Optional

import httpx

from src.models import JobOpening
from src.notifiers.base import BaseNotifier

logger = logging.getLogger(__name__)


class TelegramNotifier(BaseNotifier):
    """Notifier that sends job alerts to a Telegram chat via Bot API."""

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        timeout: float = 10.0,
    ) -> None:
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
        self.timeout = timeout

    @property
    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def format_message(self, job: JobOpening) -> str:
        if job.published_at:
            published_at = job.published_at.strftime("%d/%m/%Y %H:%M")
        else:
            published_at = "Data não informada"
        return (
            f"🎯 *Nova Oportunidade Encontrada!*\n\n"
            f"🏢 *Empresa:* {job.company}\n"
            f"💼 *Cargo:* {job.title}\n"
            f"📍 *Localização:* {job.location}\n"
            f"📅 *Publicada em:* {published_at}\n"
            f"🌐 *Plataforma:* {job.source.capitalize()}\n"
            f"🔗 *Candidatura:* [Acessar Vaga]({job.url})\n"
        )

    async def notify(
        self,
        job: JobOpening,
        client: Optional[httpx.AsyncClient] = None,
        **kwargs: Any,
    ) -> bool:
        if not self.is_configured:
            logger.warning("TelegramNotifier is not configured (missing token or chat_id).")
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": self.format_message(job),
            "parse_mode": "Markdown",
            "disable_web_page_preview": False,
        }

        should_close = False
        if client is None:
            client = httpx.AsyncClient(timeout=self.timeout)
            should_close = True

        try:
            response = await client.post(url, json=payload)
            if response.status_code == 200:
                logger.info(f"Telegram notification sent for job {job.job_id}")
                return True
            else:
                logger.error(f"Failed to send Telegram notification: HTTP {response.status_code} - {response.text}")
                return False
        except httpx.RequestError as exc:
            logger.error(f"Network error sending Telegram notification: {exc}")
            return False
        finally:
            if should_close:
                await client.aclose()
