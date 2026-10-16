import asyncio
import inspect
import logging
import os
from pathlib import Path
from typing import Any, List, Optional, Sequence

import firebase_admin
import httpx
from firebase_admin import credentials, messaging
from supabase import create_async_client

from src.models import JobOpening
from src.notifiers.base import BaseNotifier

logger = logging.getLogger(__name__)


def is_unregistered_or_invalid_token_error(exc: Optional[Exception]) -> bool:
    """Detects if an FCM delivery exception indicates an invalid, expired, or unregistered device token."""
    if exc is None:
        return False
    if isinstance(exc, messaging.UnregisteredError):
        return True
    if isinstance(exc, (messaging.SenderIdMismatchError,)):
        return True

    code = getattr(exc, "code", "") or getattr(exc, "http_status", "") or ""
    code_str = str(code).lower()
    if code_str in (
        "registration-token-not-registered",
        "invalid-registration-token",
        "mismatched-credential",
    ):
        return True

    err_str = str(exc).lower()
    return any(
        term in err_str
        for term in (
            "unregistered",
            "not-registered",
            "registration-token-not-registered",
            "invalid-registration-token",
            "not found",
            "invalid registration token",
        )
    )


class FcmNotifier(BaseNotifier):
    """Notifier that dispatches native push notifications via Firebase Cloud Messaging (FCM)."""

    def __init__(
        self,
        supabase_client: Optional[Any] = None,
        user_id: Optional[str] = None,
        credentials_path: Optional[str] = None,
        firebase_app: Optional[Any] = None,
    ) -> None:
        self.supabase_client = supabase_client
        self.user_id = user_id or os.getenv("SEARCH_CONFIG_USER_ID")
        self.credentials_path = credentials_path or os.getenv("FIREBASE_CREDENTIALS_PATH")
        self.firebase_app = firebase_app or self._init_firebase_app(self.credentials_path)

    @classmethod
    def _init_firebase_app(cls, credentials_path: Optional[str]) -> Optional[Any]:
        """Initializes or retrieves the default Firebase Admin App instance."""
        try:
            return firebase_admin.get_app()
        except ValueError:
            pass

        if credentials_path:
            path = Path(credentials_path)
            if path.is_file():
                try:
                    cred = credentials.Certificate(str(path))
                    return firebase_admin.initialize_app(cred)
                except Exception as exc:
                    logger.error(f"Failed to initialize Firebase App with '{credentials_path}': {exc}")
                    return None
            else:
                logger.warning(f"FIREBASE_CREDENTIALS_PATH file does not exist: {credentials_path}")
        else:
            logger.warning("FIREBASE_CREDENTIALS_PATH is not configured.")
        return None

    @property
    def is_configured(self) -> bool:
        return self.firebase_app is not None

    async def _get_supabase_client(self) -> Optional[Any]:
        if self.supabase_client is not None:
            return self.supabase_client
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        if url and key:
            try:
                self.supabase_client = await create_async_client(url, key)
                return self.supabase_client
            except Exception as exc:
                logger.warning(f"Failed to create Supabase client for FcmNotifier: {exc}")
                return None
        return None

    async def get_active_tokens(
        self,
        user_id: str,
        client: Optional[Any] = None,
    ) -> List[str]:
        """Queries active device registration tokens for the given user from public.user_device_tokens."""
        sb_client = client or await self._get_supabase_client()
        if not sb_client:
            logger.warning("Supabase client unavailable for querying device tokens.")
            return []

        try:
            table_fn = getattr(sb_client, "table", None) or getattr(sb_client, "from_", None)
            if not table_fn:
                return []

            table = table_fn("user_device_tokens")
            if inspect.isawaitable(table):
                table = await table

            query = table.select("fcm_token").eq("user_id", user_id)
            res = query.execute()
            if inspect.isawaitable(res):
                res = await res

            data = getattr(res, "data", None)
            if data is None and isinstance(res, (list, tuple)):
                data = res

            if not data or not isinstance(data, list):
                return []

            tokens = [row["fcm_token"] for row in data if isinstance(row, dict) and row.get("fcm_token")]
            return list(dict.fromkeys(tokens))
        except Exception as exc:
            logger.error(f"Error retrieving FCM tokens for user {user_id}: {exc}")
            return []

    async def remove_invalid_tokens(
        self,
        invalid_tokens: Sequence[str],
        user_id: Optional[str] = None,
        client: Optional[Any] = None,
    ) -> None:
        """Removes expired or invalid FCM device tokens from public.user_device_tokens."""
        if not invalid_tokens:
            return

        sb_client = client or await self._get_supabase_client()
        if not sb_client:
            logger.warning("Supabase client unavailable for deleting invalid FCM tokens.")
            return

        try:
            table_fn = getattr(sb_client, "table", None) or getattr(sb_client, "from_", None)
            if not table_fn:
                return

            table = table_fn("user_device_tokens")
            if inspect.isawaitable(table):
                table = await table

            for token in invalid_tokens:
                query = table.delete().eq("fcm_token", token)
                if user_id:
                    query = query.eq("user_id", user_id)
                res = query.execute()
                if inspect.isawaitable(res):
                    await res

            logger.info(f"Removed {len(invalid_tokens)} invalid/expired FCM token(s) from Supabase.")
        except Exception as exc:
            logger.error(f"Error removing invalid FCM tokens: {exc}")

    def build_multicast_message(
        self,
        job: JobOpening,
        tokens: List[str],
    ) -> messaging.MulticastMessage:
        """Constructs an FCM MulticastMessage for a discovered job vacancy."""
        import warnings

        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=DeprecationWarning, message=".*MulticastMessage.tokens.*")
            return messaging.MulticastMessage(
                tokens=tokens,
                notification=messaging.Notification(
                    title=f"🎯 Nova vaga: {job.title}",
                    body=f"{job.company} • {job.location} ({job.ats})",
                ),
                data={
                    "job_id": str(job.id),
                    "url": str(job.url),
                },
            )

    async def notify(
        self,
        job: JobOpening,
        client: Optional[httpx.AsyncClient] = None,
        user_id: Optional[str] = None,
        **kwargs: Any,
    ) -> bool:
        """Sends push notification to user's registered devices via FCM multicast.

        Returns True if at least one token successfully received the push message.
        """
        if not self.is_configured:
            logger.warning("FcmNotifier is not configured (missing or invalid Firebase app).")
            return False

        target_user_id = user_id or self.user_id or os.getenv("SEARCH_CONFIG_USER_ID")
        if not target_user_id:
            logger.warning("FCM notification skipped: user_id is not specified.")
            return False

        sb_client = await self._get_supabase_client()
        tokens = await self.get_active_tokens(target_user_id, client=sb_client)
        if not tokens:
            logger.info(f"No active device tokens found for user {target_user_id}. Skipping FCM notification.")
            return False

        message = self.build_multicast_message(job, tokens)

        try:
            batch_response = await asyncio.to_thread(
                messaging.send_each_for_multicast,
                message,
                app=self.firebase_app,
            )
        except Exception as exc:
            logger.error(f"Failed to dispatch FCM multicast message: {exc}", exc_info=True)
            return False

        invalid_tokens: List[str] = []
        success_count = 0

        for idx, resp in enumerate(batch_response.responses):
            if resp.success:
                success_count += 1
            else:
                if is_unregistered_or_invalid_token_error(resp.exception):
                    invalid_tokens.append(tokens[idx])
                logger.warning(f"FCM dispatch error for token {tokens[idx][:8]}...: {resp.exception}")

        if invalid_tokens:
            await self.remove_invalid_tokens(invalid_tokens, user_id=target_user_id, client=sb_client)

        logger.info(
            f"FCM multicast dispatch finished for job {job.id}: {success_count} success, "
            f"{len(batch_response.responses) - success_count} failure(s)."
        )
        return success_count > 0
