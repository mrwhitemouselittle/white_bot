from dataclasses import dataclass

import config


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    gemini_api_key: str
    gemini_model: str
    kkstate_api_host: str
    kkstate_api_port: int
    kkstate_online_seconds: int
    kkstate_key_store_path: str
    owner_id: int | None


def _parse_owner_id(value: object) -> int | None:
    text = str(value).strip()
    return int(text) if text.isdigit() else None


settings = Settings(
    telegram_bot_token=config.TELEGRAM_BOT_TOKEN,
    gemini_api_key=config.GEMINI_API_KEY,
    gemini_model=config.GEMINI_MODEL,
    kkstate_api_host=getattr(config, "KKSTATE_API_HOST", "0.0.0.0"),
    kkstate_api_port=int(getattr(config, "KKSTATE_API_PORT", 8080)),
    kkstate_online_seconds=int(getattr(config, "KKSTATE_ONLINE_SECONDS", 180)),
    kkstate_key_store_path=getattr(config, "KKSTATE_KEY_STORE_PATH", "data/kkstate_keys.json"),
    owner_id=_parse_owner_id(getattr(config, "OWNER_ID", "")),
)
