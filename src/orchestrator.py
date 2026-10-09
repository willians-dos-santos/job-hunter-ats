import asyncio
import inspect
import logging
import os
from typing import Any, Dict, List, Optional, Union
import httpx
from supabase import create_async_client

from src.collectors.base import BaseCollector
from src.collectors.greenhouse import GreenhouseCollector
from src.collectors.lever import LeverCollector
from src.collectors.gupy import GupyCollector
from src.config import load_config
from src.filters import JobFilter
from src.models import JobOpening, TargetCompany
from src.notifiers import ConsoleNotifier, NotificationDispatcher, TelegramNotifier
from src.storage import SQLiteStorage, SupabaseStorage, SearchConfigData, load_search_configs

logger = logging.getLogger("job_hunter_ats.orchestrator")


class CrawlerOrchestrator:
    """Async orchestrator for crawling multiple ATS platforms with concurrency control and fault isolation."""

    def __init__(
        self,
        targets: List[TargetCompany],
        job_filter: JobFilter,
        storage: Union[SQLiteStorage, SupabaseStorage, Any],
        dispatcher: NotificationDispatcher,
        concurrency_limit: int = 5,
        user_id: Optional[str] = None,
        supabase_client: Optional[Any] = None,
    ) -> None:
        self.targets = targets
        self.job_filter = job_filter
        self.storage = storage
        self.dispatcher = dispatcher
        self.concurrency_limit = concurrency_limit
        self.user_id = user_id
        self.supabase_client = supabase_client
        self._initial_targets = [t.model_copy() for t in targets]
        self._initial_job_filter = job_filter.model_copy(deep=True)
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

        user_id = (
            config.get("search_config_user_id")
            or config.get("SEARCH_CONFIG_USER_ID")
            or os.getenv("SEARCH_CONFIG_USER_ID")
        )

        return cls(
            targets=targets,
            job_filter=job_filter,
            storage=storage,
            dispatcher=dispatcher,
            concurrency_limit=concurrency_limit,
            user_id=user_id,
        )

    async def _get_supabase_client(self) -> Optional[Any]:
        if self.supabase_client is not None:
            return self.supabase_client
        if isinstance(self.storage, SupabaseStorage):
            return await self.storage.get_client()
        if hasattr(self.storage, "client") and self.storage.client:
            return self.storage.client
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        if url and key:
            try:
                return await create_async_client(url, key)
            except Exception:
                return None
        return None

    def _restore_initial_configs(self) -> None:
        self.targets = [t.model_copy() for t in self._initial_targets]
        self.job_filter = self._initial_job_filter.model_copy(deep=True)

    def _apply_dynamic_configs(self, dynamic_cfg: SearchConfigData) -> None:
        self._restore_initial_configs()

        if dynamic_cfg.keywords:
            self.job_filter.title_keywords = list(dynamic_cfg.keywords)
        if dynamic_cfg.excluded_keywords:
            self.job_filter.title_exclude = list(dynamic_cfg.excluded_keywords)
        if dynamic_cfg.locations:
            self.job_filter.location_keywords = list(dynamic_cfg.locations)

        if "max_days_old" in dynamic_cfg.ats_filter:
            try:
                self.job_filter.max_days_old = int(dynamic_cfg.ats_filter["max_days_old"])
            except (ValueError, TypeError):
                pass
        if "exclude_inactive" in dynamic_cfg.ats_filter:
            val = dynamic_cfg.ats_filter["exclude_inactive"]
            if isinstance(val, str):
                self.job_filter.exclude_inactive = val.lower() in ("true", "1", "yes")
            else:
                self.job_filter.exclude_inactive = bool(val)
        if "location_exclude" in dynamic_cfg.ats_filter:
            self.job_filter.location_exclude = list(dynamic_cfg.ats_filter["location_exclude"])

        if dynamic_cfg.target_companies:
            self.targets = list(dynamic_cfg.target_companies)
        elif dynamic_cfg.companies:
            self.targets = [TargetCompany(name=c, source="greenhouse") for c in dynamic_cfg.companies]

    async def _sync_search_configs(self, user_id: Optional[str] = None) -> None:
        effective_user_id = user_id if user_id is not None else (self.user_id or os.getenv("SEARCH_CONFIG_USER_ID"))
        if not effective_user_id:
            logger.warning("Using local config.yaml fallback for search configurations")
            self._restore_initial_configs()
            return

        try:
            client = await self._get_supabase_client()
            if client is None:
                logger.warning("Using local config.yaml fallback for search configurations")
                self._restore_initial_configs()
                return

            dynamic_cfg = await load_search_configs(client, user_id=effective_user_id)
            if dynamic_cfg and not dynamic_cfg.is_empty:
                self._apply_dynamic_configs(dynamic_cfg)
                logger.info(f"Loaded dynamic search configurations from Supabase for user {effective_user_id}")
            else:
                logger.warning("Using local config.yaml fallback for search configurations")
                self._restore_initial_configs()
        except Exception as exc:
            logger.warning(
                f"Failed to query dynamic search configurations ({exc}). Using local config.yaml fallback."
            )
            logger.warning("Using local config.yaml fallback for search configurations")
            self._restore_initial_configs()

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

    async def run(self, user_id: Optional[str] = None) -> List[JobOpening]:
        """Runs a complete crawl, filter, persistence and notification cycle."""
        await self._sync_search_configs(user_id=user_id)
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
                saved = False
                if hasattr(self.storage, "save_job"):
                    if inspect.iscoroutinefunction(self.storage.save_job):
                        saved = await self.storage.save_job(job)
                    else:
                        saved = self.storage.save_job(job)
                elif hasattr(self.storage, "mark_as_seen"):
                    if inspect.iscoroutinefunction(self.storage.mark_as_seen):
                        saved = await self.storage.mark_as_seen(job)
                    else:
                        saved = self.storage.mark_as_seen(job)
                else:
                    saved = True

                # Only notify if the job was successfully persisted as new (not rejected as duplicate)
                if saved:
                    await self.dispatcher.notify(job, client=client)
                    notified_jobs.append(job)
                else:
                    logger.info(
                        f"Job '{getattr(job, 'job_id', '')}' (dedup_key: {getattr(job, 'dedup_key', 'N/A')}) "
                        "skipped from notification (duplicate or failed to persist)."
                    )

        return notified_jobs
