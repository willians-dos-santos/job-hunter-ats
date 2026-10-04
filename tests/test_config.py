import os
import pytest
import yaml
from src.config import load_config


def test_load_config_telegram_fallback_to_env(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env_token_123")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "env_chat_456")

    config_data = {
        "concurrency_limit": 3,
        "telegram": {
            "enabled": True,
            "bot_token": None,
            "chat_id": None,
        },
    }
    config_file = tmp_path / "config.yaml"
    with open(config_file, "w", encoding="utf-8") as f:
        yaml.dump(config_data, f)

    cfg = load_config(str(config_file))
    assert cfg["telegram"]["bot_token"] == "env_token_123"
    assert cfg["telegram"]["chat_id"] == "env_chat_456"


def test_load_config_telegram_prefers_yaml_when_set(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env_token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "env_chat")

    config_data = {
        "telegram": {
            "enabled": True,
            "bot_token": "yaml_token",
            "chat_id": "yaml_chat",
        },
    }
    config_file = tmp_path / "config.yaml"
    with open(config_file, "w", encoding="utf-8") as f:
        yaml.dump(config_data, f)

    cfg = load_config(str(config_file))
    assert cfg["telegram"]["bot_token"] == "yaml_token"
    assert cfg["telegram"]["chat_id"] == "yaml_chat"


def test_load_config_file_not_found():
    with pytest.raises(FileNotFoundError):
        load_config("nonexistent_config_file.yaml")
