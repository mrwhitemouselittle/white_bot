import logging
import sys
from typing import Any

from telegram import Update

LOG_FORMAT = "[%(asctime)s] [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: int = logging.INFO) -> None:
    root_logger = logging.getLogger()

    if root_logger.handlers:
        root_logger.setLevel(level)
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))

    root_logger.setLevel(level)
    root_logger.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)


def update_context(**kwargs: Any) -> str:
    parts = [f"{key}={value}" for key, value in kwargs.items() if value is not None]
    return " ".join(parts)


def telegram_update_context(update: Update) -> str:
    user = update.effective_user
    chat = update.effective_chat

    return update_context(
        user_id=user.id if user else None,
        username=user.username if user else None,
        user_name=user.full_name if user else None,
        chat_id=chat.id if chat else None,
        chat_type=chat.type if chat else None,
        group_id=chat.id if chat and chat.type in {"group", "supergroup"} else None,
        group_title=chat.title if chat and chat.type in {"group", "supergroup"} else None,
    )
