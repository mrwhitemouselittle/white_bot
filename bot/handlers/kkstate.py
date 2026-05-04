from telegram import Update
from telegram.ext import ContextTypes

from bot.logger import get_logger, telegram_update_context
from bot.services.kk_state import format_state_message

logger = get_logger(__name__)


async def kkstate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    log_context = telegram_update_context(update)
    logger.info("Command received: /kkstate %s", log_context)

    await update.message.reply_text(format_state_message(), do_quote=True)
    logger.info("Command completed: /kkstate %s", log_context)
