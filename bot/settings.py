from dataclasses import dataclass

import config


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str


settings = Settings(
    telegram_bot_token=config.TELEGRAM_BOT_TOKEN,
)
