from abc import ABC, abstractmethod
from typing import Any, Optional

import httpx

from src.models import JobOpening


class BaseNotifier(ABC):
    """Abstract base class defining the contract for all alert and notification channels."""

    @property
    def is_configured(self) -> bool:
        """Indicates whether this notification channel is properly configured and ready."""
        return True

    @abstractmethod
    async def notify(
        self,
        job: JobOpening,
        client: Optional[httpx.AsyncClient] = None,
        **kwargs: Any,
    ) -> bool:
        """Asynchronously dispatches a notification for a newly discovered job opening.

        Args:
            job: Normalized JobOpening model.
            client: Optional shared HTTPX async client.
            **kwargs: Channel-specific parameters (e.g. user_id).

        Returns:
            bool: True if notification was successfully delivered or dispatched, False otherwise.
        """
        pass
