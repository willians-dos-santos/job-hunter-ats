import base64
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from firebase_admin import messaging

from src.models import JobOpening
from src.notifiers.console import ConsoleNotifier
from src.notifiers.dispatcher import NotificationDispatcher
from src.notifiers.fcm import FcmNotifier, is_unregistered_or_invalid_token_error
from src.notifiers.telegram import TelegramNotifier
from src.orchestrator import CrawlerOrchestrator


def make_sample_job(
    title: str = "Senior Python Engineer",
    company: str = "Acme Corp",
    location: str = "Remoto",
    ats: str = "greenhouse",
    job_id: str = "greenhouse:acme:12345",
    url: str = "https://boards.greenhouse.io/acme/jobs/12345",
) -> JobOpening:
    return JobOpening(
        job_id=job_id,
        source=ats,
        company=company,
        title=title,
        location=location,
        url=url,
        published_at=datetime.now(timezone.utc),
    )


def build_mock_supabase_client(tokens_data=None, query_exception=None, delete_exception=None):
    """Constructs a mock Supabase client for user_device_tokens queries and deletes."""
    mock_client = AsyncMock()
    mock_table = MagicMock()
    mock_select_query = MagicMock()
    mock_delete_query = MagicMock()

    mock_select_query.eq.return_value = mock_select_query
    if query_exception:
        mock_select_query.execute = AsyncMock(side_effect=query_exception)
    else:
        mock_res = MagicMock()
        mock_res.data = tokens_data if tokens_data is not None else []
        mock_select_query.execute = AsyncMock(return_value=mock_res)

    mock_table.select.return_value = mock_select_query

    mock_delete_query.eq.return_value = mock_delete_query
    if delete_exception:
        mock_delete_query.execute = AsyncMock(side_effect=delete_exception)
    else:
        mock_delete_query.execute = AsyncMock(return_value=MagicMock(data=[]))

    mock_table.delete.return_value = mock_delete_query
    mock_client.table.return_value = mock_table
    return mock_client, mock_table, mock_select_query, mock_delete_query


# ---------------------------------------------------------------------------
# 1. Initialization and Configuration Tests
# ---------------------------------------------------------------------------


def test_fcm_init_with_base64_credentials_from_env(monkeypatch):
    raw_payload = {"type": "service_account", "project_id": "b64-project", "client_email": "bot@b64.iam"}
    b64_str = base64.b64encode(json.dumps(raw_payload).encode("utf-8")).decode("utf-8")
    monkeypatch.setenv("FIREBASE_SERVICE_ACCOUNT_BASE64", b64_str)
    monkeypatch.delenv("FIREBASE_CREDENTIALS_PATH", raising=False)

    mock_app = MagicMock()
    with (
        patch("firebase_admin.get_app", side_effect=ValueError("No app")),
        patch("firebase_admin.credentials.Certificate") as mock_cert,
        patch("firebase_admin.initialize_app", return_value=mock_app) as mock_init,
    ):
        notifier = FcmNotifier()
        assert notifier.is_configured is True
        assert notifier.firebase_app == mock_app
        mock_cert.assert_called_once_with(raw_payload)
        mock_init.assert_called_once()


def test_fcm_init_with_base64_credentials_as_arg(monkeypatch):
    monkeypatch.delenv("FIREBASE_SERVICE_ACCOUNT_BASE64", raising=False)
    monkeypatch.delenv("FIREBASE_CREDENTIALS_PATH", raising=False)

    raw_payload = {"type": "service_account", "project_id": "arg-project", "client_email": "arg@iam"}
    b64_str = base64.b64encode(json.dumps(raw_payload).encode("utf-8")).decode("utf-8")

    mock_app = MagicMock()
    with (
        patch("firebase_admin.get_app", side_effect=ValueError("No app")),
        patch("firebase_admin.credentials.Certificate") as mock_cert,
        patch("firebase_admin.initialize_app", return_value=mock_app) as mock_init,
    ):
        notifier = FcmNotifier(service_account_base64=b64_str)
        assert notifier.is_configured is True
        assert notifier.firebase_app == mock_app
        mock_cert.assert_called_once_with(raw_payload)
        mock_init.assert_called_once()


def test_fcm_init_base64_takes_precedence_over_file(tmp_path, monkeypatch):
    raw_payload = {"type": "service_account", "project_id": "priority-b64"}
    b64_str = base64.b64encode(json.dumps(raw_payload).encode("utf-8")).decode("utf-8")
    monkeypatch.setenv("FIREBASE_SERVICE_ACCOUNT_BASE64", b64_str)

    cred_file = tmp_path / "ignored_file.json"
    cred_file.write_text('{"type": "service_account", "project_id": "ignored-file"}')

    mock_app = MagicMock()
    with (
        patch("firebase_admin.get_app", side_effect=ValueError("No app")),
        patch("firebase_admin.credentials.Certificate") as mock_cert,
        patch("firebase_admin.initialize_app", return_value=mock_app) as mock_init,
    ):
        notifier = FcmNotifier(credentials_path=str(cred_file))
        assert notifier.is_configured is True
        assert notifier.firebase_app == mock_app
        # Must use base64 dictionary payload, NOT the file path
        mock_cert.assert_called_once_with(raw_payload)
        mock_init.assert_called_once()


def test_fcm_init_with_valid_credentials_file_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv("FIREBASE_SERVICE_ACCOUNT_BASE64", raising=False)
    cred_file = tmp_path / "service_account.json"
    cred_file.write_text('{"type": "service_account", "project_id": "test-project"}')

    mock_app = MagicMock()
    with (
        patch("firebase_admin.get_app", side_effect=ValueError("No app")),
        patch("firebase_admin.credentials.Certificate") as mock_cert,
        patch("firebase_admin.initialize_app", return_value=mock_app) as mock_init,
    ):
        notifier = FcmNotifier(credentials_path=str(cred_file))
        assert notifier.is_configured is True
        assert notifier.firebase_app == mock_app
        mock_cert.assert_called_once_with(str(cred_file))
        mock_init.assert_called_once()


def test_fcm_init_with_env_credentials_file_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv("FIREBASE_SERVICE_ACCOUNT_BASE64", raising=False)
    cred_file = tmp_path / "env_service_account.json"
    cred_file.write_text('{"type": "service_account", "project_id": "env-file-project"}')
    monkeypatch.setenv("FIREBASE_CREDENTIALS_PATH", str(cred_file))

    mock_app = MagicMock()
    with (
        patch("firebase_admin.get_app", side_effect=ValueError("No app")),
        patch("firebase_admin.credentials.Certificate") as mock_cert,
        patch("firebase_admin.initialize_app", return_value=mock_app) as mock_init,
    ):
        notifier = FcmNotifier()
        assert notifier.is_configured is True
        assert notifier.firebase_app == mock_app
        mock_cert.assert_called_once_with(str(cred_file))
        mock_init.assert_called_once()


def test_fcm_init_with_default_file_fallback(monkeypatch):
    monkeypatch.delenv("FIREBASE_SERVICE_ACCOUNT_BASE64", raising=False)
    monkeypatch.delenv("FIREBASE_CREDENTIALS_PATH", raising=False)

    mock_app = MagicMock()
    with (
        patch("firebase_admin.get_app", side_effect=ValueError("No app")),
        patch("pathlib.Path.is_file", return_value=True),
        patch("firebase_admin.credentials.Certificate") as mock_cert,
        patch("firebase_admin.initialize_app", return_value=mock_app) as mock_init,
    ):
        notifier = FcmNotifier()
        assert notifier.is_configured is True
        assert notifier.firebase_app == mock_app
        mock_cert.assert_called_once_with(str(Path("./firebase-service-account.json")))
        mock_init.assert_called_once()


def test_fcm_init_no_credentials_configured_raises_error(monkeypatch):
    monkeypatch.delenv("FIREBASE_SERVICE_ACCOUNT_BASE64", raising=False)
    monkeypatch.delenv("FIREBASE_CREDENTIALS_PATH", raising=False)

    with (
        patch("firebase_admin.get_app", side_effect=ValueError("No app")),
        patch("pathlib.Path.is_file", return_value=False),
    ):
        with pytest.raises(ValueError, match="No Firebase credentials configured"):
            FcmNotifier()


def test_fcm_init_with_missing_credentials_file(monkeypatch):
    monkeypatch.delenv("FIREBASE_SERVICE_ACCOUNT_BASE64", raising=False)
    with patch("firebase_admin.get_app", side_effect=ValueError("No app")):
        with pytest.raises(FileNotFoundError, match="Firebase credentials file not found"):
            FcmNotifier(credentials_path="/non/existent/path.json")


def test_fcm_init_invalid_base64_payload_raises_error(monkeypatch):
    monkeypatch.setenv("FIREBASE_SERVICE_ACCOUNT_BASE64", "invalid-base64-payload!!!")
    with patch("firebase_admin.get_app", side_effect=ValueError("No app")):
        with pytest.raises(ValueError, match="Invalid FIREBASE_SERVICE_ACCOUNT_BASE64 payload"):
            FcmNotifier()


def test_fcm_init_with_existing_default_app():
    mock_app = MagicMock()
    with patch("firebase_admin.get_app", return_value=mock_app):
        notifier = FcmNotifier(credentials_path="any_path.json")
        assert notifier.is_configured is True
        assert notifier.firebase_app == mock_app


def test_fcm_init_with_injected_firebase_app():
    mock_app = MagicMock()
    notifier = FcmNotifier(firebase_app=mock_app)
    assert notifier.is_configured is True
    assert notifier.firebase_app == mock_app



# ---------------------------------------------------------------------------
# 2. Token Retrieval and Error Handling Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_active_tokens_success():
    records = [
        {"fcm_token": "token_device_1", "user_id": "u-123"},
        {"fcm_token": "token_device_2", "user_id": "u-123"},
        {"fcm_token": "token_device_1", "user_id": "u-123"},  # Duplicate
        {"fcm_token": None, "user_id": "u-123"},  # Null token
        {},  # Missing key
    ]
    mock_client, mock_table, mock_select, _ = build_mock_supabase_client(tokens_data=records)

    notifier = FcmNotifier(supabase_client=mock_client, firebase_app=MagicMock())
    tokens = await notifier.get_active_tokens("u-123")

    assert tokens == ["token_device_1", "token_device_2"]
    mock_table.select.assert_called_with("fcm_token")
    mock_select.eq.assert_called_with("user_id", "u-123")


@pytest.mark.asyncio
async def test_get_active_tokens_handles_query_exception():
    mock_client, _, _, _ = build_mock_supabase_client(query_exception=RuntimeError("DB Connection Lost"))
    notifier = FcmNotifier(supabase_client=mock_client, firebase_app=MagicMock())

    tokens = await notifier.get_active_tokens("u-123")
    assert tokens == []


@pytest.mark.asyncio
async def test_get_active_tokens_handles_none_client():
    notifier = FcmNotifier(supabase_client=None, firebase_app=MagicMock())
    with patch.object(notifier, "_get_supabase_client", AsyncMock(return_value=None)):
        tokens = await notifier.get_active_tokens("u-123")
        assert tokens == []


# ---------------------------------------------------------------------------
# 3. Message Payload Construction Tests
# ---------------------------------------------------------------------------


def test_fcm_build_multicast_message():
    job = make_sample_job(
        title="Staff Backend Engineer",
        company="PicPay",
        location="Remoto - Brasil",
        ats="gupy",
        job_id="gupy_98765",
        url="https://picpay.gupy.io/job/98765",
    )
    notifier = FcmNotifier(firebase_app=MagicMock())
    tokens = ["token_1", "token_2"]

    msg = notifier.build_multicast_message(job, tokens)

    assert msg.tokens == tokens
    assert msg.notification.title == "🎯 Nova vaga: Staff Backend Engineer"
    assert msg.notification.body == "PicPay • Remoto - Brasil (gupy)"
    assert msg.data == {
        "job_id": "gupy_98765",
        "url": "https://picpay.gupy.io/job/98765",
    }


# ---------------------------------------------------------------------------
# 4. Token Cleanup Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remove_invalid_tokens_calls_delete():
    mock_client, mock_table, _, mock_delete = build_mock_supabase_client()
    notifier = FcmNotifier(supabase_client=mock_client, firebase_app=MagicMock())

    await notifier.remove_invalid_tokens(["stale_token_1", "stale_token_2"], user_id="u-123")

    assert mock_table.delete.call_count == 2
    assert mock_delete.eq.call_count >= 2


@pytest.mark.asyncio
async def test_remove_invalid_tokens_handles_exception_cleanly():
    mock_client, _, _, _ = build_mock_supabase_client(delete_exception=RuntimeError("Supabase Error"))
    notifier = FcmNotifier(supabase_client=mock_client, firebase_app=MagicMock())

    # Should not raise exception
    await notifier.remove_invalid_tokens(["bad_token"], user_id="u-123")


# ---------------------------------------------------------------------------
# 5. Multicast Dispatching (`notify`) Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fcm_notify_success_all_delivered():
    mock_client, _, _, _ = build_mock_supabase_client(tokens_data=[{"fcm_token": "token_a"}, {"fcm_token": "token_b"}])
    notifier = FcmNotifier(supabase_client=mock_client, user_id="u-123", firebase_app=MagicMock())

    batch_resp = messaging.BatchResponse(
        [
            messaging.SendResponse({"name": "projects/p/messages/1"}, None),
            messaging.SendResponse({"name": "projects/p/messages/2"}, None),
        ]
    )

    with patch("firebase_admin.messaging.send_each_for_multicast", return_value=batch_resp) as mock_send:
        job = make_sample_job()
        success = await notifier.notify(job)

        assert success is True
        mock_send.assert_called_once()


@pytest.mark.asyncio
async def test_fcm_notify_partial_failure_removes_unregistered_token():
    mock_client, _, _, mock_delete = build_mock_supabase_client(
        tokens_data=[{"fcm_token": "valid_token"}, {"fcm_token": "unregistered_token"}]
    )
    notifier = FcmNotifier(supabase_client=mock_client, user_id="u-123", firebase_app=MagicMock())

    batch_resp = messaging.BatchResponse(
        [
            messaging.SendResponse({"name": "projects/p/messages/1"}, None),
            messaging.SendResponse(None, messaging.UnregisteredError("Registration token is not registered")),
        ]
    )

    with (
        patch("firebase_admin.messaging.send_each_for_multicast", return_value=batch_resp),
        patch.object(notifier, "remove_invalid_tokens", AsyncMock()) as mock_remove,
    ):
        job = make_sample_job()
        success = await notifier.notify(job)

        assert success is True  # One token succeeded
        mock_remove.assert_called_once_with(["unregistered_token"], user_id="u-123", client=mock_client)


@pytest.mark.asyncio
async def test_fcm_notify_all_tokens_unregistered_returns_false():
    mock_client, _, _, _ = build_mock_supabase_client(tokens_data=[{"fcm_token": "expired_token"}])
    notifier = FcmNotifier(supabase_client=mock_client, user_id="u-123", firebase_app=MagicMock())

    batch_resp = messaging.BatchResponse(
        [
            messaging.SendResponse(None, messaging.UnregisteredError("Token expired")),
        ]
    )

    with (
        patch("firebase_admin.messaging.send_each_for_multicast", return_value=batch_resp),
        patch.object(notifier, "remove_invalid_tokens", AsyncMock()) as mock_remove,
    ):
        job = make_sample_job()
        success = await notifier.notify(job)

        assert success is False
        mock_remove.assert_called_once_with(["expired_token"], user_id="u-123", client=mock_client)


@pytest.mark.asyncio
async def test_fcm_notify_skipped_when_no_active_tokens():
    mock_client, _, _, _ = build_mock_supabase_client(tokens_data=[])
    notifier = FcmNotifier(supabase_client=mock_client, user_id="u-123", firebase_app=MagicMock())

    with patch("firebase_admin.messaging.send_each_for_multicast") as mock_send:
        job = make_sample_job()
        success = await notifier.notify(job)

        assert success is False
        mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_fcm_notify_skipped_when_user_id_is_missing(monkeypatch):
    monkeypatch.delenv("SEARCH_CONFIG_USER_ID", raising=False)
    notifier = FcmNotifier(supabase_client=MagicMock(), user_id=None, firebase_app=MagicMock())

    job = make_sample_job()
    success = await notifier.notify(job)
    assert success is False


@pytest.mark.asyncio
async def test_fcm_notify_skipped_when_not_configured():
    notifier = FcmNotifier(firebase_app=None)
    job = make_sample_job()
    success = await notifier.notify(job)
    assert success is False


@pytest.mark.asyncio
async def test_fcm_notify_catches_send_exception():
    mock_client, _, _, _ = build_mock_supabase_client(tokens_data=[{"fcm_token": "token_1"}])
    notifier = FcmNotifier(supabase_client=mock_client, user_id="u-123", firebase_app=MagicMock())

    with patch("firebase_admin.messaging.send_each_for_multicast", side_effect=Exception("FCM Service Unavailable")):
        job = make_sample_job()
        success = await notifier.notify(job)
        assert success is False


# ---------------------------------------------------------------------------
# 6. Unregistered Error Detector Helper Tests
# ---------------------------------------------------------------------------


def test_is_unregistered_or_invalid_token_error():
    assert is_unregistered_or_invalid_token_error(None) is False
    assert is_unregistered_or_invalid_token_error(messaging.UnregisteredError("token not registered")) is True
    assert is_unregistered_or_invalid_token_error(messaging.SenderIdMismatchError("mismatched id")) is True
    assert is_unregistered_or_invalid_token_error(ValueError("Registration-token-not-registered")) is True
    assert is_unregistered_or_invalid_token_error(RuntimeError("Invalid registration token")) is True
    assert is_unregistered_or_invalid_token_error(Exception("Network timeout")) is False


# ---------------------------------------------------------------------------
# 7. Integration with NotificationDispatcher Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatcher_with_fcm_and_telegram():
    mock_tg = AsyncMock(spec=TelegramNotifier)
    mock_tg.is_configured = True
    mock_tg.notify = AsyncMock(return_value=True)

    mock_fcm = AsyncMock(spec=FcmNotifier)
    mock_fcm.is_configured = True
    mock_fcm.notify = AsyncMock(return_value=True)

    mock_console = MagicMock(spec=ConsoleNotifier)

    dispatcher = NotificationDispatcher(
        telegram_notifier=mock_tg,
        console_notifier=mock_console,
        fcm_notifier=mock_fcm,
    )

    job = make_sample_job()
    success = await dispatcher.notify(job, user_id="u-abc")

    assert success is True
    mock_tg.notify.assert_called_once()
    mock_fcm.notify.assert_called_once_with(job, client=None, user_id="u-abc")
    mock_console.notify.assert_not_called()


@pytest.mark.asyncio
async def test_dispatcher_fcm_success_prevents_console_fallback():
    mock_fcm = AsyncMock(spec=FcmNotifier)
    mock_fcm.is_configured = True
    mock_fcm.notify = AsyncMock(return_value=True)

    mock_console = MagicMock(spec=ConsoleNotifier)

    dispatcher = NotificationDispatcher(
        telegram_notifier=None,
        console_notifier=mock_console,
        fcm_notifier=mock_fcm,
    )

    job = make_sample_job()
    success = await dispatcher.notify(job, user_id="u-abc")

    assert success is True
    mock_fcm.notify.assert_called_once()
    mock_console.notify.assert_not_called()


@pytest.mark.asyncio
async def test_dispatcher_falls_back_to_console_when_fcm_and_tg_fail():
    mock_tg = AsyncMock(spec=TelegramNotifier)
    mock_tg.is_configured = True
    mock_tg.notify = AsyncMock(return_value=False)

    mock_fcm = AsyncMock(spec=FcmNotifier)
    mock_fcm.is_configured = True
    mock_fcm.notify = AsyncMock(return_value=False)

    mock_console = MagicMock(spec=ConsoleNotifier)
    mock_console.notify.return_value = True

    dispatcher = NotificationDispatcher(
        telegram_notifier=mock_tg,
        console_notifier=mock_console,
        fcm_notifier=mock_fcm,
    )

    job = make_sample_job()
    success = await dispatcher.notify(job, user_id="u-abc")

    assert success is True
    mock_console.notify.assert_called_once()


# ---------------------------------------------------------------------------
# 8. Orchestrator Integration Tests
# ---------------------------------------------------------------------------


def test_orchestrator_initializes_fcm_notifier(tmp_path):
    cred_file = tmp_path / "firebase.json"
    cred_file.write_text("{}")

    config = {
        "concurrency_limit": 1,
        "storage_type": "sqlite",
        "database_path": str(tmp_path / "test.db"),
        "search_config_user_id": "user-test-uuid",
        "targets": [],
        "fcm": {
            "enabled": True,
            "credentials_path": str(cred_file),
        },
    }
    file_path = tmp_path / "fcm_config.yaml"
    import yaml

    with open(file_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f)

    mock_app = MagicMock()
    with patch("src.notifiers.fcm.FcmNotifier._init_firebase_app", return_value=mock_app):
        orchestrator = CrawlerOrchestrator.from_config_file(str(file_path))

        assert orchestrator.dispatcher.fcm_notifier is not None
        assert orchestrator.dispatcher.fcm_notifier.user_id == "user-test-uuid"
        assert orchestrator.dispatcher.fcm_notifier.is_configured is True
