from telegram import Update
from telegram.ext import ContextTypes

from bot.logger import get_logger, telegram_update_context
from bot.services.howtocook_food import fetch_recipe_image, generate_food_recommendation

logger = get_logger(__name__)


async def eatwhat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    log_context = telegram_update_context(update)
    logger.info("Command received: /eatwhat %s", log_context)

    thinking_message = await update.message.reply_text("正在从 HowToCook 随机挑一道菜...", do_quote=True)

    try:
        recommendation = await generate_food_recommendation()
    except Exception:
        logger.exception("Command failed: /eatwhat %s", log_context)
        await thinking_message.edit_text("暂时没有从 HowToCook 拉到菜谱，请稍后再试。")
        return

    message = recommendation.to_html_message()
    if recommendation.image_url:
        try:
            image = await fetch_recipe_image(recommendation.image_url)
            await update.message.reply_photo(
                photo=image,
                caption=message,
                parse_mode="HTML",
                do_quote=True,
            )
            await thinking_message.delete()
        except Exception as exc:
            logger.warning("Failed to send recipe image, falling back to text: %s", exc)
            await thinking_message.edit_text(message, parse_mode="HTML")
    else:
        await thinking_message.edit_text(message, parse_mode="HTML")

    logger.info("Command completed: /eatwhat %s", log_context)
