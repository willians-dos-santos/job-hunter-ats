import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any, List, Optional
import httpx
from src.models import JobOpening, TargetCompany

logger = logging.getLogger(__name__)


class BaseCollector(ABC):
    """Abstract base collector for ATS endpoints with rate limiting and fault isolation."""

    def __init__(self, max_retries: int = 3, backoff_factor: float = 0.5) -> None:
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor

    @abstractmethod
    def build_url(self, target: TargetCompany) -> str:
        """Constructs the API endpoint URL for a given target company."""
        pass

    @abstractmethod
    def parse_jobs(self, target: TargetCompany, raw_data: Any) -> List[JobOpening]:
        """Parses the raw API response into a list of JobOpening models."""
        pass

    def get_headers(self) -> dict:
        """Returns optional HTTP headers for requests."""
        return {}

    def build_params(self, target: TargetCompany) -> Optional[dict]:
        """Returns optional query parameters for requests."""
        return None

    async def fetch_jobs_from_url(
        self,
        url: str,
        target: TargetCompany,
        client: Optional[httpx.AsyncClient] = None,
        params: Optional[dict] = None,
    ) -> List[JobOpening]:
        """Fetches and parses job openings from a specific URL with retry logic and error isolation."""
        headers = self.get_headers()
        should_close = False
        if client is None:
            client = httpx.AsyncClient(timeout=15.0)
            should_close = True

        try:
            for attempt in range(self.max_retries + 1):
                try:
                    response = await client.get(url, headers=headers, params=params)
                    if response.status_code == 200:
                        raw_data = response.json()
                        return self.parse_jobs(target, raw_data)
                    elif response.status_code == 429:
                        if attempt < self.max_retries:
                            retry_after = response.headers.get("Retry-After")
                            delay = float(retry_after) if retry_after else self.backoff_factor * (2**attempt)
                            logger.warning(
                                f"Rate limited (429) for {target.name} on {target.source}. Backing off {delay:.2f}s..."
                            )
                            await asyncio.sleep(delay)
                            continue
                        else:
                            logger.error(f"Rate limit exceeded (429) for {target.name} after {self.max_retries} retries.")
                            return []
                    elif response.status_code == 404:
                        logger.warning(f"Target company board not found (404): {target.name} ({url})")
                        return []
                    else:
                        logger.warning(
                            f"Received HTTP {response.status_code} for {target.name} on {target.source}"
                        )
                        return []
                except (httpx.RequestError, httpx.HTTPStatusError) as exc:
                    if attempt < self.max_retries:
                        delay = self.backoff_factor * (2**attempt)
                        logger.warning(
                            f"Network error querying {url}: {exc}. Retrying in {delay:.2f}s..."
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(f"Failed to fetch {url} after {self.max_retries} attempts: {exc}")
                        return []
            return []
        finally:
            if should_close:
                await client.aclose()

    async def fetch_jobs(
        self, target: TargetCompany, client: Optional[httpx.AsyncClient] = None
    ) -> List[JobOpening]:
        """Fetches and parses job openings from the target ATS with retry logic and error isolation."""
        url = self.build_url(target)
        params = self.build_params(target)
        return await self.fetch_jobs_from_url(url, target, client=client, params=params)
