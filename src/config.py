import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()


class TelegramConfig(BaseModel):
    enabled: bool = False
    bot_token: Optional[str] = None
    chat_id: Optional[str] = None


class FiltersConfig(BaseModel):
    title_keywords: List[str] = Field(default_factory=list)
    title_exclude: List[str] = Field(default_factory=list)
    location_keywords: List[str] = Field(default_factory=list)
    location_exclude: List[str] = Field(default_factory=list)
    max_days_old: Optional[int] = Field(default=30)
    exclude_inactive: bool = Field(default=True)


class AppConfig(BaseModel):
    concurrency_limit: int = 5
    database_path: str = "data/jobs.db"
    targets: List[Dict[str, Any]] = Field(default_factory=list)
    filters: FiltersConfig = Field(default_factory=FiltersConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)


def load_config(config_path: str = "config.yaml") -> Dict[str, Any]:
    """Loads configuration from a YAML file, ensuring Telegram credentials fallback to env vars."""
    path = Path(config_path)
    if not path.is_file():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    tg_cfg = data.get("telegram")
    if tg_cfg is None or not isinstance(tg_cfg, dict):
        tg_cfg = {}
        data["telegram"] = tg_cfg

    # Resolve Telegram credentials from env vars if null/empty in YAML
    bot_token = tg_cfg.get("bot_token") or os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = tg_cfg.get("chat_id") or os.getenv("TELEGRAM_CHAT_ID")

    tg_cfg["bot_token"] = bot_token
    tg_cfg["chat_id"] = chat_id

    return data
