from dataclasses import dataclass

from config import GEMINI_API_KEY, GEMINI_MODEL, TELEGRAM_BOT_TOKEN


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    gemini_api_key: str
    gemini_model: str


settings = Settings(
    telegram_bot_token=TELEGRAM_BOT_TOKEN,
    gemini_api_key=GEMINI_API_KEY,
    gemini_model=GEMINI_MODEL,
)
