import asyncio
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
        await update.message.reply_text("这个指令只能由主人在私聊里使用。")
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
        await update.message.reply_text(
            "用法：\n/kkkey new 生成新密钥\n/kkkey list 查看密钥列表\n/kkkey set <key_id> <secret> 修改或导入密钥\n/kkkey delete <key_id> 删除密钥"
        )

    logger.info("Command completed: /kkkey action=%s %s", action, log_context)


async def _new_key(update: Update) -> None:
    if update.message is None:
        return

    key = create_key()
    message = await update.message.reply_text(
        "新的探针密钥已生成，请尽快写入探针配置。\n"
        f"key_id: {key.key_id}\n"
        f"secret: {key.secret}\n"
        f"这条消息会在 {DELETE_SECRET_AFTER_SECONDS} 秒后删除。"
    )
    asyncio.create_task(_delete_message_later(message, DELETE_SECRET_AFTER_SECONDS))


async def _list_keys(update: Update) -> None:
    if update.message is None:
        return

    keys = list_keys()
    if not keys:
        await update.message.reply_text("当前没有探针密钥。")
        return

    lines = ["当前探针密钥："]
    lines.extend(f"{item.key_id} 创建于 {item.created_at}" for item in keys)
    await update.message.reply_text("\n".join(lines))


async def _delete_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    if len(context.args) < 2:
        await update.message.reply_text("用法：/kkkey delete <key_id>")
        return

    key_id = context.args[1]
    if delete_key(key_id):
        await update.message.reply_text(f"已删除密钥：{key_id}")
    else:
        await update.message.reply_text(f"没有找到密钥：{key_id}")


async def _set_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    if len(context.args) < 3:
        await update.message.reply_text("用法：/kkkey set <key_id> <secret>")
        return

    key_id = context.args[1].strip()
    secret = context.args[2].strip()

    try:
        set_key(key_id, secret)
    except Exception as exc:
        await update.message.reply_text(f"密钥修改失败：{exc}")
        return

    asyncio.create_task(_delete_message_later(update.message, DELETE_SECRET_AFTER_SECONDS))
    message = await update.message.reply_text(
        f"已修改密钥：{key_id}\n这条确认消息会在 {DELETE_SECRET_AFTER_SECONDS} 秒后删除。"
    )
    asyncio.create_task(_delete_message_later(message, DELETE_SECRET_AFTER_SECONDS))


async def _delete_message_later(message: Message, delay_seconds: int) -> None:
    await asyncio.sleep(delay_seconds)
    try:
        await message.delete()
    except Exception:
        logger.exception("Failed to delete secret message.")


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
