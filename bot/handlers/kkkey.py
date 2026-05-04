import asyncio
import json
from telegram import Message, Update
from telegram.ext import ContextTypes

from bot.logger import get_logger, telegram_update_context
from bot.services.kk_keys import create_key, delete_key, list_keys, set_key
from bot.settings import settings

logger = get_logger(__name__)

DELETE_SECRET_AFTER_SECONDS = 60


async def kkkey(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    log_context = telegram_update_context(update)
    logger.info("Command received: /kkkey %s", log_context)

    if not _is_owner_private_chat(update):
        await _reply_ephemeral(update.message, "这个指令只能由主人在私聊里使用。")
        logger.warning("Command rejected: /kkkey %s", log_context)
        return

    action = context.args[0].lower() if context.args else "help"

    if action in {"new", "create"}:
        await _new_key(update)
    elif action in {"list", "view"}:
        await _list_keys(update)
    elif action in {"delete", "del", "remove"}:
        await _delete_key(update, context)
    elif action in {"set", "update", "modify"}:
        await _set_key(update, context)
    else:
        await _reply_ephemeral(
            update.message,
            "用法：\n/kkkey new 生成新密钥\n/kkkey list 查看密钥列表\n/kkkey set <key_id> <secret> 修改或导入密钥\n/kkkey delete <key_id> 删除密钥"
        )

    logger.info("Command completed: /kkkey action=%s %s", action, log_context)


async def _new_key(update: Update) -> None:
    if update.message is None:
        return

    key = create_key()
    await _reply_ephemeral(
        update.message,
        "新的探针密钥已生成，请尽快写入探针配置。\n"
        f"{_json_code_block({'key_id': key.key_id, 'secret': key.secret})}\n"
        f"这条消息会在 {DELETE_SECRET_AFTER_SECONDS} 秒后删除。",
        parse_mode="Markdown",
    )


async def _list_keys(update: Update) -> None:
    if update.message is None:
        return

    keys = list_keys()
    if not keys:
        await _reply_ephemeral(update.message, "当前没有探针密钥。")
        return

    key_payload = [
        {"key_id": item.key_id, "secret": item.secret, "created_at": item.created_at}
        for item in keys
    ]
    await _reply_ephemeral(
        update.message,
        "当前探针密钥：\n"
        f"{_json_code_block(key_payload)}\n"
        f"这条消息会在 {DELETE_SECRET_AFTER_SECONDS} 秒后删除。",
        parse_mode="Markdown",
    )


async def _delete_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    if len(context.args) < 2:
        await _reply_ephemeral(update.message, "用法：/kkkey delete <key_id>")
        return

    key_id = context.args[1]
    if delete_key(key_id):
        await _reply_ephemeral(update.message, f"已删除密钥：{key_id}")
    else:
        await _reply_ephemeral(update.message, f"没有找到密钥：{key_id}")


async def _set_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    if len(context.args) < 3:
        await _reply_ephemeral(update.message, "用法：/kkkey set <key_id> <secret>")
        return

    key_id = context.args[1].strip()
    secret = context.args[2].strip()

    try:
        set_key(key_id, secret)
    except Exception as exc:
        await _reply_ephemeral(update.message, f"密钥修改失败：{exc}")
        return

    await _reply_ephemeral(
        update.message,
        "已修改密钥：\n"
        f"{_json_code_block({'key_id': key_id, 'secret': secret})}\n"
        f"这条确认消息会在 {DELETE_SECRET_AFTER_SECONDS} 秒后删除。",
        parse_mode="Markdown",
    )


async def _reply_ephemeral(message: Message, text: str, parse_mode: str | None = None) -> None:
    sent_message = await message.reply_text(text, parse_mode=parse_mode, do_quote=True)
    asyncio.create_task(_delete_messages_later(sent_message, message, DELETE_SECRET_AFTER_SECONDS))


async def _delete_messages_later(bot_message: Message, sender_message: Message, delay_seconds: int) -> None:
    await asyncio.sleep(delay_seconds)
    await _delete_message(bot_message, "bot secret reply")
    await _delete_message(sender_message, "sender secret command")


async def _delete_message(message: Message, label: str) -> None:
    try:
        await message.delete()
    except Exception as exc:
        logger.warning("Failed to delete %s: %s", label, exc)


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


def _json_code_block(value: object) -> str:
    content = json.dumps(value, ensure_ascii=False, indent=2)
    return f"```json\n{content}\n```"
