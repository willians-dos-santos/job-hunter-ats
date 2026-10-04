import pytest
import respx
import httpx
from src.models import JobOpening
from src.notifiers import TelegramNotifier, ConsoleNotifier, NotificationDispatcher


def make_sample_job() -> JobOpening:
    return JobOpening(
        job_id="greenhouse:acme:123456",
        source="greenhouse",
        company="Acme Corp",
        title="Senior Python Backend Engineer",
        location="Remote, Worldwide",
        url="https://boards.greenhouse.io/acme/jobs/123456",
    )


def test_console_notifier_outputs_cleanly(capsys):
    notifier = ConsoleNotifier()
    job = make_sample_job()

    notifier.notify(job)

    captured = capsys.readouterr()
    assert "Acme Corp" in captured.out
    assert "Senior Python Backend Engineer" in captured.out
    assert "Remote, Worldwide" in captured.out
    assert "https://boards.greenhouse.io/acme/jobs/123456" in captured.out


@pytest.mark.asyncio
async def test_telegram_notifier_sends_markdown_message(respx_mock):
    bot_token = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
    chat_id = "987654321"

    notifier = TelegramNotifier(bot_token=bot_token, chat_id=chat_id)
    job = make_sample_job()

    route = respx_mock.post(f"https://api.telegram.org/bot{bot_token}/sendMessage").respond(
        status_code=200,
        json={"ok": True, "result": {}},
    )

    async with httpx.AsyncClient() as client:
        success = await notifier.notify(job, client=client)

    assert success is True
    assert route.called
    request_data = route.calls.last.request
    assert request_data.headers["content-type"] == "application/json"
    body = request_data.read().decode("utf-8")
    assert chat_id in body
    assert "Senior Python Backend Engineer" in body
    assert "https://boards.greenhouse.io/acme/jobs/123456" in body


@pytest.mark.asyncio
async def test_telegram_notifier_error_does_not_crash(respx_mock):
    bot_token = "invalid_token"
    chat_id = "123"

    notifier = TelegramNotifier(bot_token=bot_token, chat_id=chat_id)
    job = make_sample_job()

    respx_mock.post(f"https://api.telegram.org/bot{bot_token}/sendMessage").respond(
        status_code=400,
        json={"ok": False, "description": "Bad Request: chat not found"},
    )

    async with httpx.AsyncClient() as client:
        success = await notifier.notify(job, client=client)

    assert success is False


@pytest.mark.asyncio
async def test_dispatcher_fallback_to_console_when_no_telegram(capsys):
    # Scenario 2: When no telegram credentials are provided, prints to console without error
    dispatcher = NotificationDispatcher(telegram_notifier=None, console_notifier=ConsoleNotifier())
    job = make_sample_job()

    await dispatcher.notify(job)

    captured = capsys.readouterr()
    assert "Senior Python Backend Engineer" in captured.out
    assert "Acme Corp" in captured.out
