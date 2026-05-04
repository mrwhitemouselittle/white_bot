import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import config
from telegram import Update

LOG_FORMAT = "[%(asctime)s] [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_FILE_PREFIX = "bot-"
_configured = False


def setup_logging(level: int = logging.INFO) -> None:
    global _configured

    root_logger = logging.getLogger()

    if _configured:
        root_logger.setLevel(level)
        return

    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
    retention_days = _log_retention_days()
    _cleanup_old_logs(retention_days)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(
        LOG_DIR / f"{LOG_FILE_PREFIX}{datetime.now().strftime('%Y-%m-%d')}.log",
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    root_logger.setLevel(level)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    _configured = True


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


def _log_retention_days() -> int:
    value = getattr(config, "BOT_LOG_RETENTION_DAYS", 30)
    try:
        days = int(value)
    except (TypeError, ValueError):
        return 30

    return days if days > 0 else 30


def _cleanup_old_logs(retention_days: int) -> None:
    if not LOG_DIR.exists():
        return

    cutoff = datetime.now() - timedelta(days=retention_days)
    for path in LOG_DIR.glob(f"{LOG_FILE_PREFIX}*.log"):
        try:
            if datetime.fromtimestamp(path.stat().st_mtime) < cutoff:
                path.unlink()
        except OSError:
            continue
