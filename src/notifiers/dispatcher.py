import inspect
import logging
from typing import Any, Optional

import httpx

from src.models import JobOpening
from src.notifiers.console import ConsoleNotifier
from src.notifiers.fcm import FcmNotifier
from src.notifiers.telegram import TelegramNotifier

logger = logging.getLogger(__name__)


class NotificationDispatcher:
    """Dispatches notifications across configured channels (Telegram, FCM) with console fallback."""

    def __init__(
        self,
        telegram_notifier: Optional[TelegramNotifier] = None,
        console_notifier: Optional[ConsoleNotifier] = None,
        fcm_notifier: Optional[FcmNotifier] = None,
    ) -> None:
        self.telegram_notifier = telegram_notifier
        self.console_notifier = console_notifier or ConsoleNotifier()
        self.fcm_notifier = fcm_notifier

    async def notify(
        self,
        job: JobOpening,
        client: Optional[httpx.AsyncClient] = None,
        user_id: Optional[str] = None,
        **kwargs: Any,
    ) -> bool:
        """Dispatches job alerts to all configured channels. Falls back to console if none notified."""
        notified = False

        if self.telegram_notifier and self.telegram_notifier.is_configured:
            try:
                tg_success = await self.telegram_notifier.notify(job, client=client, **kwargs)
                if tg_success:
                    notified = True
            except Exception as exc:
                logger.error(f"Telegram notification dispatch error: {exc}")

        if self.fcm_notifier and self.fcm_notifier.is_configured:
            try:
                fcm_success = await self.fcm_notifier.notify(job, client=client, user_id=user_id, **kwargs)
                if fcm_success:
                    notified = True
            except Exception as exc:
                logger.error(f"FCM notification dispatch error: {exc}")

        # Fallback to console if no active remote channel successfully notified
        if not notified and self.console_notifier:
            try:
                res = self.console_notifier.notify(job, client=client, **kwargs)
                if inspect.isawaitable(res):
                    await res
                notified = True
            except Exception as exc:
                logger.error(f"Console notifier error: {exc}")

        return notified
