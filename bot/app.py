from telegram import BotCommand
from telegram.ext import Application, CommandHandler

from bot.api.kk_state_api import start_api_server, stop_api_server
from bot.handlers.basic import help_command, menu, start
from bot.handlers.eatwhat import eatwhat
from bot.handlers.kkapi import kkapi
from bot.handlers.kkkey import kkkey
from bot.handlers.kkstate import kkstate
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
            BotCommand("kkstate", "查看主人是否在线"),
            BotCommand("kkapi", "查看 KK 心跳接口参数"),
            BotCommand("kkkey", "管理 KK 探针密钥"),
        ]
    )
    logger.info("Telegram bot commands registered.")
    application.bot_data["kkstate_api_runner"] = await start_api_server()


async def post_shutdown(application: Application) -> None:
    runner = application.bot_data.get("kkstate_api_runner")
    if runner is not None:
        await stop_api_server(runner)


def create_application() -> Application:
    setup_logging()
    logger.info("Creating Telegram application.")

    app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("eatwhat", eatwhat))
    app.add_handler(CommandHandler("kkstate", kkstate))
    app.add_handler(CommandHandler("kkapi", kkapi))
    app.add_handler(CommandHandler("kkkey", kkkey))

    logger.info("Telegram handlers registered.")
    return app
