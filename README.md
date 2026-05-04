# white0456_bot

一个使用 `uv`、Python 和 `python-telegram-bot` 编写的 Telegram Bot。

当前功能：

- `/start`：启动提示。
- `/help`：查看指令。
- `/menu`：查看菜单。
- `/eatwhat`：调用 Gemini 随机推荐一道全球美食和热量。
- `/kkstate`：查看主人当前是否在线。
- `/kkapi`：主人私聊中查看探针心跳接口参数。
- `/kkkey`：主人私聊中管理 KK 探针密钥。

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
│   ├── api/
│   │   └── kk_state_api.py
│   ├── handlers/
│   │   ├── basic.py
│   │   ├── eatwhat.py
│   │   ├── kkkey.py
│   │   └── kkstate.py
│   └── services/
│       ├── gemini_food.py
│       ├── kk_keys.py
│       └── kk_state.py
└── probe/
    └── kkprobe/
        ├── go.mod
        ├── main.go
        └── config.example.json
```

## Python Bot 配置

复制示例配置：

```powershell
Copy-Item config.example.py config.py
```

配置字段：

```python
TELEGRAM_BOT_TOKEN = "your_telegram_bot_token_here"
GEMINI_API_KEY = "your_gemini_api_key_here"
GEMINI_MODEL = "gemini-2.5-flash"

KKSTATE_API_HOST = "0.0.0.0"
KKSTATE_API_PORT = 8080
KKSTATE_ONLINE_SECONDS = 180
KKSTATE_KEY_STORE_PATH = "data/kkstate_keys.json"

OWNER_ID = "your_telegram_user_id_here"
```

说明：

- `OWNER_ID` 是 Telegram 用户 ID，只有这个用户能在一对一私聊里使用 `/kkkey`。
- `KKSTATE_ONLINE_SECONDS` 默认是 `180`，也就是每个设备最近一次心跳超过 3 分钟就认为离线。
- `KKSTATE_KEY_STORE_PATH` 是探针密钥的本地持久化文件，默认在 `data/` 下，已被 `.gitignore` 忽略。

## 启动 Bot

安装依赖：

```powershell
uv sync
```

启动：

```powershell
uv run python main.py
```

启动后会同时启动 aiohttp API：

```text
http://0.0.0.0:8080
```

如果 bot 和探针不在同一台机器，请确保这个端口能被探针访问。

## KK 在线状态逻辑

探针会定时上传加密心跳包。服务端按 `device` 独立保存最新心跳。

当有人发送 `/kkstate`：

- 如果至少有一个设备的最新心跳未超过 3 分钟，返回：

```text
主人在的，在台式、笔记本前！
```

- 如果没有任何在线设备，返回：

```text
主人不在线哦~
```

多个设备互不覆盖。例如 `台式` 的心跳仍然有效，此时 `笔记本` 又上传心跳，bot 会拼接所有在线设备名称。

## 探针密钥管理

密钥由 bot 生成，并持久化保存在本地。管理指令只能由 `OWNER_ID` 对应的用户在 bot 私聊里使用。

生成新密钥：

```text
/kkkey new
```

bot 会返回：

```text
key_id: ...
secret: ...
```

这条包含 secret 的消息会在 60 秒后自动删除。

查看密钥列表：

```text
/kkkey list
```

返回内容会使用 Markdown JSON 代码块展示，并在 60 秒后自动删除。

修改或导入密钥：

```text
/kkkey set <key_id> <secret>
```

`secret` 必须是 base64-url 编码，解码后长度为 32 字节。

删除密钥：

```text
/kkkey delete <key_id>
```

删除后使用该 `key_id` 的探针心跳会被拒绝。

查看探针心跳接口参数：

```text
/kkapi
```

bot 会返回可直接复制到探针配置里的 JSON 片段，例如：

```json
{
  "api_url": "http://127.0.0.1:8080/api/kkstate/heartbeat",
  "adaptive_backoff": true,
  "standby_after_failures": 5,
  "standby_min_seconds": 10,
  "standby_max_seconds": 300,
  "standby_backoff_factor": 1.8,
  "min_interval_seconds": 5,
  "max_interval_seconds": 60,
  "steady_interval_seconds": 30,
  "request_timeout_seconds": 10,
  "log_retention_days": 30
}
```

所有密钥和探针配置相关指令的 bot 返回消息都会在 60 秒后自动删除；如果命令本身包含密钥内容，也会尝试定时删除用户发出的命令消息。

## 心跳 API

地址：

```text
POST /api/kkstate/heartbeat
```

请求体是 JSON：

```json
{
  "key_id": "bot_generated_key_id",
  "nonce": "base64_url_nonce",
  "data": "base64_url_aes_gcm_ciphertext"
}
```

加密规则：

- 算法：AES-256-GCM。
- 密钥：`/kkkey new` 返回的 `secret`，base64-url 解码后是 32 字节。
- nonce：随机 12 字节。
- AAD：`key_id` 的 UTF-8 字节。
- 明文 JSON 至少包含：

```json
{
  "device": "台式",
  "timestamp": 1770000000
}
```

字段说明：

- `device`：自定义设备名，由探针端决定，例如 `台式`、`笔记本`、`闪亮亮的Macbook Pro`。
- `timestamp`：探针发送心跳时的 Unix 秒级时间戳。

响应：

```json
{
  "ok": 1,
  "timestamp": 1770000001
}
```

响应字段：

- `ok`：`1` 表示包格式正确、解密成功、服务端记录成功；`0` 表示失败。
- `timestamp`：服务端接收到该请求时的 Unix 秒级时间戳。

状态调试接口：

```text
GET /api/kkstate/status
```

返回当前服务端内存里记录的设备状态。

## Go 探针

探针在 `probe/kkprobe`，使用 Go 标准库实现，轻量运行。

复制配置：

```powershell
cd probe\kkprobe
Copy-Item config.example.json config.json
```

Linux/macOS：

```bash
cd probe/kkprobe
cp config.example.json config.json
```

配置示例：

```json
{
  "api_url": "http://127.0.0.1:8080/api/kkstate/heartbeat",
  "key_id": "your_key_id_from_bot",
  "secret": "your_base64_secret_from_bot",
  "device": "台式",
  "adaptive_backoff": true,
  "standby_after_failures": 5,
  "standby_min_seconds": 10,
  "standby_max_seconds": 300,
  "standby_backoff_factor": 1.8,
  "min_interval_seconds": 5,
  "max_interval_seconds": 60,
  "steady_interval_seconds": 30,
  "request_timeout_seconds": 10
}
```

字段说明：

- `api_url`：bot 服务器的心跳接口地址。
- `key_id` / `secret`：从 `/kkkey new` 获取。
- `device`：这个探针上报的设备名称。
- `adaptive_backoff`：是否启用自适应指数退避。
- `standby_after_failures`：连续失败多少次后进入待机模式。
- `standby_min_seconds`：刚进入待机模式时的最短探测间隔。
- `standby_max_seconds`：待机模式退避到上限后的固定探测间隔。
- `standby_backoff_factor`：待机模式下每次失败后的指数退避倍率。
- `min_interval_seconds`：自适应模式初始和最小发包间隔。
- `max_interval_seconds`：自适应模式最大发包间隔。
- `steady_interval_seconds`：关闭自适应模式时的固定发包间隔。
- `request_timeout_seconds`：单次请求超时。
- `log_retention_days`：本地日志保留天数，默认 30 天。

运行探针：

```powershell
go run .
```

或指定配置文件：

```powershell
go run . C:\path\to\config.json
```

Linux/macOS 指定配置文件：

```bash
go run . /path/to/config.json
```

### 探针开机自启动

探针支持按当前系统注册用户级开机自启动。

Windows：

```powershell
.\kkprobe.exe install
.\kkprobe.exe install C:\path\to\config.json
.\kkprobe.exe uninstall
```

Linux/macOS：

```bash
./kkprobe install
./kkprobe install /path/to/config.json
./kkprobe uninstall
```

各平台使用的自启动方式：

- Windows：写入当前用户的 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`，并在 `install` 成功后立即启动一次探针进程；注册表项会在下次登录时继续自动启动。
- Linux：写入 `~/.config/systemd/user/kkprobe.service`，并执行 `systemctl --user enable --now kkprobe.service`。
- macOS：写入 `~/Library/LaunchAgents/com.white0456.kkprobe.plist`，并使用 `launchctl bootstrap` 加载。

Linux 如果希望用户未登录时也运行 user service，需要启用 linger：

```bash
loginctl enable-linger "$USER"
```

### 探针编译

建议把构建产物放在 `probe/kkprobe/bin/`，该目录已被 `.gitignore` 忽略。

一键构建所有平台：

```powershell
uv run python build_probe.py --clean
```

Linux/macOS：

```bash
uv run python build_probe.py --clean
```

该脚本会构建：

- `kkprobe-windows-amd64.exe`
- `kkprobe-windows-arm64.exe`
- `kkprobe-linux-amd64`
- `kkprobe-linux-arm64`
- `kkprobe-darwin-amd64`
- `kkprobe-darwin-arm64`

在当前平台编译：

```powershell
New-Item -ItemType Directory -Force bin
go build -o bin\kkprobe.exe .
```

Linux/macOS：

```bash
mkdir -p bin
go build -o bin/kkprobe .
```

在 Windows 上交叉编译 Linux/macOS：

```powershell
$env:GOOS="linux"; $env:GOARCH="amd64"; go build -o bin\kkprobe-linux-amd64 .
$env:GOOS="linux"; $env:GOARCH="arm64"; go build -o bin\kkprobe-linux-arm64 .
$env:GOOS="darwin"; $env:GOARCH="amd64"; go build -o bin\kkprobe-darwin-amd64 .
$env:GOOS="darwin"; $env:GOARCH="arm64"; go build -o bin\kkprobe-darwin-arm64 .
$env:GOOS="windows"; $env:GOARCH="amd64"; go build -o bin\kkprobe-windows-amd64.exe .
Remove-Item Env:\GOOS
Remove-Item Env:\GOARCH
```

在 Linux/macOS 上交叉编译：

```bash
mkdir -p bin
GOOS=linux GOARCH=amd64 go build -o bin/kkprobe-linux-amd64 .
GOOS=linux GOARCH=arm64 go build -o bin/kkprobe-linux-arm64 .
GOOS=darwin GOARCH=amd64 go build -o bin/kkprobe-darwin-amd64 .
GOOS=darwin GOARCH=arm64 go build -o bin/kkprobe-darwin-arm64 .
GOOS=windows GOARCH=amd64 go build -o bin/kkprobe-windows-amd64.exe .
```

自适应退避逻辑：

- 启动早期以 `min_interval_seconds` 较快发包。
- 最近 10 次请求完全成功且延迟稳定时，逐步增加间隔。
- 丢包率低且延迟还算稳定时，缓慢增加间隔。
- 丢包或延迟波动明显时，缩短间隔。
- 间隔始终限制在 `min_interval_seconds` 和 `max_interval_seconds` 之间。

待机模式：

- 如果连续失败次数达到 `standby_after_failures`，探针认为当前可能是网络波动、断网或 bot 服务器不可达。
- 进入待机后，先用 `standby_min_seconds` 较快探测，避免短时网络波动恢复后等待太久。
- 如果仍然不可达，待机探测间隔按 `standby_backoff_factor` 指数增长。
- 待机间隔增长到 `standby_max_seconds` 后保持固定，避免长期断网时频繁请求。
- 待机模式下只要任意一次心跳成功，就立即退出待机，清空连续失败计数，恢复正常心跳模式。
- 待机模式不会修改服务端状态；服务端仍然按最近一次有效心跳的 `timestamp` 判断设备是否在线。

探针本地日志：

- 探针会在可执行文件所在目录下创建 `logs/`。
- 日志文件按日期命名，例如 `logs/kkprobe-2026-05-04.log`。
- `log_retention_days` 控制日志保留天数，默认 30 天。

## 日志

bot 使用项目内封装的日志格式，命令行输出带日期：

```text
[2026-05-04 13:47:09] [INFO] bot.handlers.kkstate: Command received: /kkstate user_id=...
```

handler 日志会包含用户、私聊/群聊来源；群消息会额外包含群 ID 和群名。

## 安全注意

- 不要提交 `config.py`、`data/`、探针真实配置文件。
- `/kkkey new` 返回的 `secret` 只显示一次，消息会定时删除，但仍应避免截图或转发。
- 如果怀疑密钥泄露，使用 `/kkkey delete <key_id>` 删除旧密钥，然后生成新密钥并更新探针配置。
