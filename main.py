from bot.app import create_application


def main() -> None:
    app = create_application()
    app.run_polling()


if __name__ == "__main__":
    main()
