import asyncio
import json

from telegram import Message, Update
from telegram.ext import ContextTypes

from bot.logger import get_logger, telegram_update_context
from bot.settings import settings

logger = get_logger(__name__)

DELETE_CONFIG_AFTER_SECONDS = 60


async def kkapi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    log_context = telegram_update_context(update)
    logger.info("Command received: /kkapi %s", log_context)

    if not _is_owner_private_chat(update):
        await _reply_ephemeral(update.message, "这个指令只能由主人在私聊里使用。")
        logger.warning("Command rejected: /kkapi %s", log_context)
        return

    config = {
        "api_url": _heartbeat_api_url(),
        "adaptive_backoff": True,
        "standby_after_failures": 5,
        "standby_min_seconds": 10,
        "standby_max_seconds": 300,
        "standby_backoff_factor": 1.8,
        "min_interval_seconds": 5,
        "max_interval_seconds": 60,
        "steady_interval_seconds": 30,
        "request_timeout_seconds": 10,
        "log_retention_days": 30,
    }
    await _reply_ephemeral(
        update.message,
        "当前心跳接口参数：\n"
        f"```json\n{json.dumps(config, ensure_ascii=False, indent=2)}\n```\n"
        f"这条消息会在 {DELETE_CONFIG_AFTER_SECONDS} 秒后删除。",
        parse_mode="Markdown",
    )
    logger.info("Command completed: /kkapi %s", log_context)


def _heartbeat_api_url() -> str:
    host = settings.kkstate_api_host
    if host in {"0.0.0.0", "::"}:
        host = "127.0.0.1"

    return f"http://{host}:{settings.kkstate_api_port}/api/kkstate/heartbeat"


async def _reply_ephemeral(message: Message, text: str, parse_mode: str | None = None) -> None:
    sent_message = await message.reply_text(text, parse_mode=parse_mode, do_quote=True)
    asyncio.create_task(_delete_messages_later(sent_message, message, DELETE_CONFIG_AFTER_SECONDS))


async def _delete_messages_later(bot_message: Message, sender_message: Message, delay_seconds: int) -> None:
    await asyncio.sleep(delay_seconds)
    await _delete_message(bot_message, "bot API config reply")
    await _delete_message(sender_message, "sender API config command")


async def _delete_message(message: Message, label: str) -> None:
    try:
        await message.delete()
    except Exception:
        logger.exception("Failed to delete %s.", label)


def _is_owner_private_chat(update: Update) -> bool:
    user = update.effective_user
    chat = update.effective_chat
    return (
        user is not None
        and chat is not None
        and chat.type == "private"
        and settings.owner_id is not None
        and user.id == settings.owner_id
    )
