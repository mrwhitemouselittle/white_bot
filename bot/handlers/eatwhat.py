from telegram import Update
from telegram.ext import ContextTypes

from bot.logger import get_logger, telegram_update_context
from bot.services.gemini_food import generate_food_recommendation

logger = get_logger(__name__)


async def eatwhat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    log_context = telegram_update_context(update)
    logger.info("Command received: /eatwhat %s", log_context)

    thinking_message = await update.message.reply_text("正在帮你随机挑一道全球美食...")

    try:
        recommendation = await generate_food_recommendation()
    except Exception:
        logger.exception("Command failed: /eatwhat %s", log_context)
        await thinking_message.edit_text("Gemini 暂时没有返回结果，请稍后再试。")
        return

    await thinking_message.edit_text(recommendation)
    logger.info("Command completed: /eatwhat %s", log_context)
