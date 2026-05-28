# white0456_bot

一个使用 `uv`、Python 和 `python-telegram-bot` 编写的 Telegram Bot。

当前功能：

- `/start`：启动提示。
- `/help`：查看指令。
- `/menu`：查看菜单。
- `/eatwhat`：从公开仓库 `Anduin2017/HowToCook` 随机推荐一道菜。

## 目录结构

```text
.
├── main.py
├── config.py
├── config.example.py
├── bot/
│   ├── app.py
│   ├── logger.py
│   ├── settings.py
│   ├── handlers/
│   │   ├── basic.py
│   │   └── eatwhat.py
│   └── services/
│       └── howtocook_food.py
├── pyproject.toml
└── uv.lock
```

## 配置

复制示例配置：

```powershell
Copy-Item config.example.py config.py
```

配置字段：

```python
TELEGRAM_BOT_TOKEN = "your_telegram_bot_token_here"

BOT_LOG_RETENTION_DAYS = 30
```

说明：

- `TELEGRAM_BOT_TOKEN`：Telegram Bot Token。
- `BOT_LOG_RETENTION_DAYS`：bot 本地日志保留天数，默认 30 天。

## 启动

安装依赖：

```powershell
uv sync
```

启动：

```powershell
uv run python main.py
```

## 日志

bot 使用项目内封装的日志格式，命令行输出带日期：

```text
[2026-05-04 13:47:09] [INFO] bot.handlers.basic: Command received: /start user_id=...
```

日志也会写入项目根目录的 `logs/` 文件夹：

```text
logs/bot-2026-05-04.log
```

handler 日志会包含用户、私聊/群聊来源；群消息会额外包含群 ID 和群名。

## 指令

```text
/start
/help
/menu
/eatwhat
```

`/eatwhat` 会从 [Anduin2017/HowToCook](https://github.com/Anduin2017/HowToCook) 随机选择一道菜，返回菜名、简介、卡路里信息、做法链接；如果菜谱目录中有图片，会一起发送图片。

## 安全注意

- 不要提交 `config.py`。
- 不要把 Telegram Bot Token 写入 README、日志或公开仓库。
