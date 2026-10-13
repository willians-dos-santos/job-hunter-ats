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


def test_filters_config_schema():
    from src.config import FiltersConfig

    default_cfg = FiltersConfig()
    assert default_cfg.max_days_old == 30
    assert default_cfg.exclude_inactive is True

    custom_cfg = FiltersConfig(max_days_old=60, exclude_inactive=False)
    assert custom_cfg.max_days_old == 60
    assert custom_cfg.exclude_inactive is False


def test_load_config_search_config_user_id_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("SEARCH_CONFIG_USER_ID", "user-uuid-env-123")
    config_file = tmp_path / "config.yaml"
    with open(config_file, "w", encoding="utf-8") as f:
        yaml.dump({}, f)

    cfg = load_config(str(config_file))
    assert cfg["search_config_user_id"] == "user-uuid-env-123"
    assert cfg["SEARCH_CONFIG_USER_ID"] == "user-uuid-env-123"


def test_load_config_search_config_user_id_from_yaml(tmp_path, monkeypatch):
    monkeypatch.setenv("SEARCH_CONFIG_USER_ID", "user-uuid-env")
    config_data = {"search_config_user_id": "user-uuid-yaml"}
    config_file = tmp_path / "config.yaml"
    with open(config_file, "w", encoding="utf-8") as f:
        yaml.dump(config_data, f)

    cfg = load_config(str(config_file))
    assert cfg["search_config_user_id"] == "user-uuid-yaml"


def test_app_config_search_config_user_id_schema():
    from src.config import AppConfig

    default_cfg = AppConfig()
    assert default_cfg.search_config_user_id is None
    assert default_cfg.SEARCH_CONFIG_USER_ID is None

    custom_cfg = AppConfig(search_config_user_id="uuid-custom")
    assert custom_cfg.search_config_user_id == "uuid-custom"
