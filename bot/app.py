from telegram import BotCommand
from telegram.ext import Application, CommandHandler

from bot.handlers.basic import help_command, menu, start
from bot.handlers.eatwhat import eatwhat
from bot.logger import get_logger, setup_logging
from bot.settings import settings

logger = get_logger(__name__)


async def post_init(application: Application) -> None:
    await application.bot.set_my_commands(
        [
            BotCommand("start", "启动 Bot"),
            BotCommand("help", "查看帮助"),
            BotCommand("menu", "打开菜单"),
            BotCommand("eatwhat", "随机推荐全球美食和热量"),
        ]
    )
    logger.info("Telegram bot commands registered.")


def create_application() -> Application:
    setup_logging()
    logger.info("Creating Telegram application.")

    app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("eatwhat", eatwhat))

    logger.info("Telegram handlers registered.")
    return app
