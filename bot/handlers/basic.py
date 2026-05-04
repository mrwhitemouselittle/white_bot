from telegram import Update
from telegram.ext import ContextTypes

from bot.logger import get_logger, telegram_update_context

logger = get_logger(__name__)


def _log_command(command: str, update: Update) -> None:
    logger.info("Command received: %s %s", command, telegram_update_context(update))


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    _log_command("/start", update)
    await update.message.reply_text("你好，我是 White。发送 /help 查看可用指令。", do_quote=True)
    logger.info("Command completed: /start %s", telegram_update_context(update))


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    _log_command("/help", update)
    await update.message.reply_text(
        "可用指令：\n/start 启动 Bot\n/menu 打开菜单\n/eatwhat 随机推荐美食\n/kkstate 查看 KK 是否在线\n/kkapi 查看心跳接口参数\n/kkkey 管理探针密钥",
        do_quote=True,
    )
    logger.info("Command completed: /help %s", telegram_update_context(update))


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    _log_command("/menu", update)
    await update.message.reply_text(
        "菜单：\n/eatwhat 随机推荐一道全球美食和热量\n/kkstate 查看 KK 是否在线\n/kkapi 查看心跳接口参数\n/kkkey 管理探针密钥",
        do_quote=True,
    )
    logger.info("Command completed: /menu %s", telegram_update_context(update))
