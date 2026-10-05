from dotenv import load_dotenv

load_dotenv()

import argparse
import asyncio
import inspect
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import httpx
import yaml

from src.collectors.base import BaseCollector
from src.collectors.greenhouse import GreenhouseCollector
from src.collectors.lever import LeverCollector
from src.collectors.gupy import GupyCollector
from src.config import load_config
from src.filters import JobFilter
from src.models import JobOpening, TargetCompany
from src.notifiers import ConsoleNotifier, NotificationDispatcher, TelegramNotifier
from src.storage import SQLiteStorage, SupabaseStorage

logger = logging.getLogger("job_hunter_ats")


class CrawlerOrchestrator:
    """Async orchestrator for crawling multiple ATS platforms with concurrency control and fault isolation."""

    def __init__(
        self,
        targets: List[TargetCompany],
        job_filter: JobFilter,
        storage: Union[SQLiteStorage, SupabaseStorage, Any],
        dispatcher: NotificationDispatcher,
        concurrency_limit: int = 5,
    ) -> None:
        self.targets = targets
        self.job_filter = job_filter
        self.storage = storage
        self.dispatcher = dispatcher
        self.concurrency_limit = concurrency_limit
        gupy_collector = GupyCollector()
        self.collectors: Dict[str, BaseCollector] = {
            "greenhouse": GreenhouseCollector(),
            "lever": LeverCollector(),
            "Gupy": gupy_collector,
            "gupy": gupy_collector,
            "gupy_global": gupy_collector,
        }

    @classmethod
    def from_config_file(cls, config_path: str = "config.yaml") -> "CrawlerOrchestrator":
        config = load_config(config_path)

        targets = [TargetCompany(**t) for t in config.get("targets", [])]
        filters_cfg = config.get("filters", {})
        job_filter = JobFilter(**filters_cfg)

        # Storage resolution: Check environment or config for Supabase, with safe fallback to SQLite
        storage_type = config.get("storage_type") or os.getenv("STORAGE_TYPE")
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")

        storage: Union[SQLiteStorage, SupabaseStorage]
        if storage_type == "supabase" or (storage_type != "sqlite" and supabase_url and supabase_key):
            try:
                storage = SupabaseStorage(url=supabase_url, key=supabase_key)
                logger.info("Configured SupabaseStorage as primary persistence adapter.")
            except Exception as exc:
                logger.warning(
                    f"Failed to initialize SupabaseStorage ({exc}). Falling back to SQLiteStorage."
                )
                db_path = config.get("database_path", "jobs.db")
                storage = SQLiteStorage(db_path=db_path)
        else:
            db_path = config.get("database_path", "jobs.db")
            storage = SQLiteStorage(db_path=db_path)

        # Telegram configuration (respecting env vars and config)
        tg_cfg = config.get("telegram", {})
        tg_enabled = tg_cfg.get("enabled", False)
        tg_token = tg_cfg.get("bot_token") or os.getenv("TELEGRAM_BOT_TOKEN")
        tg_chat_id = tg_cfg.get("chat_id") or os.getenv("TELEGRAM_CHAT_ID")

        telegram_notifier = (
            TelegramNotifier(bot_token=tg_token, chat_id=tg_chat_id)
            if tg_enabled and (tg_token and tg_chat_id)
            else None
        )
        dispatcher = NotificationDispatcher(
            telegram_notifier=telegram_notifier,
            console_notifier=ConsoleNotifier(),
        )

        concurrency_limit = int(config.get("concurrency_limit", 5))

        return cls(
            targets=targets,
            job_filter=job_filter,
            storage=storage,
            dispatcher=dispatcher,
            concurrency_limit=concurrency_limit,
        )

    async def _crawl_target(
        self,
        target: TargetCompany,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
    ) -> List[JobOpening]:
        collector = self.collectors.get(target.source)
        if not collector:
            logger.warning(f"No collector registered for source: {target.source}")
            return []

        async with semaphore:
            try:
                logger.info(f"Crawling {target.name} ({target.source})...")
                jobs = await collector.fetch_jobs(target, client=client)
                logger.info(f"Fetched {len(jobs)} jobs from {target.name}.")
                return jobs
            except Exception as exc:
                logger.error(
                    f"Unexpected error while crawling {target.name} ({target.source}): {exc}",
                    exc_info=True,
                )
                return []

    async def run(self) -> List[JobOpening]:
        """Runs a complete crawl, filter, persistence and notification cycle."""
        semaphore = asyncio.Semaphore(self.concurrency_limit)
        notified_jobs: List[JobOpening] = []

        limits = httpx.Limits(max_keepalive_connections=10, max_connections=self.concurrency_limit * 2)
        async with httpx.AsyncClient(limits=limits, timeout=15.0) as client:
            tasks = [self._crawl_target(target, client, semaphore) for target in self.targets]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            all_jobs: List[JobOpening] = []
            for res in results:
                if isinstance(res, list):
                    all_jobs.extend(res)
                elif isinstance(res, Exception):
                    logger.error(f"Target crawling raised an unhandled exception: {res}")

            logger.info(f"Total jobs collected across all targets: {len(all_jobs)}")

            # Apply deterministic filters
            matching_jobs = self.job_filter.filter_jobs(all_jobs)
            logger.info(f"Jobs matching filter criteria: {len(matching_jobs)}")

            # Filter out seen jobs (deduplication & idempotency)
            if inspect.iscoroutinefunction(self.storage.filter_new_jobs):
                new_jobs = await self.storage.filter_new_jobs(matching_jobs)
            elif hasattr(self.storage, "filter_new_jobs"):
                new_jobs = self.storage.filter_new_jobs(matching_jobs)
            else:
                new_jobs = []
                for job in matching_jobs:
                    job_id = getattr(job, "id", None) or getattr(job, "job_id", "")
                    seen = (
                        await self.storage.is_seen(job_id)
                        if inspect.iscoroutinefunction(self.storage.is_seen)
                        else self.storage.is_seen(job_id)
                    )
                    if not seen:
                        new_jobs.append(job)

            logger.info(f"New unseen jobs to notify: {len(new_jobs)}")

            for job in new_jobs:
                if inspect.iscoroutinefunction(self.storage.mark_as_seen):
                    await self.storage.mark_as_seen(job)
                elif hasattr(self.storage, "mark_as_seen"):
                    self.storage.mark_as_seen(job)
                elif hasattr(self.storage, "save_job"):
                    if inspect.iscoroutinefunction(self.storage.save_job):
                        await self.storage.save_job(job)
                    else:
                        self.storage.save_job(job)

                await self.dispatcher.notify(job, client=client)
                notified_jobs.append(job)

        return notified_jobs


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def cli() -> None:
    parser = argparse.ArgumentParser(description="Job Hunter ATS Crawler Core")
    parser.add_argument(
        "--config",
        "-c",
        default="config.yaml",
        help="Path to YAML configuration file (default: config.yaml)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose debug logging",
    )
    args = parser.parse_args()
    setup_logging(args.verbose)

    try:
        orchestrator = CrawlerOrchestrator.from_config_file(args.config)
        new_jobs = asyncio.run(orchestrator.run())
        logger.info(f"Crawl cycle completed successfully. Notified {len(new_jobs)} jobs.")
    except Exception as exc:
        logger.critical(f"Crawler encountered a fatal error: {exc}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    cli()
