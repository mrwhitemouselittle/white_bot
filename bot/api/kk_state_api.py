import base64
import json
from datetime import UTC, datetime
from typing import Any

from aiohttp import web
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from bot.logger import get_logger
from bot.services.kk_keys import decode_secret, get_key
from bot.services.kk_state import get_online_devices, get_probe_states, record_probe
from bot.settings import settings

logger = get_logger(__name__)


def create_api_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_get("/api/kkstate/status", status)
    app.router.add_post("/api/kkstate/heartbeat", heartbeat)
    return app


async def start_api_server() -> web.AppRunner:
    app = create_api_app()
    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, settings.kkstate_api_host, settings.kkstate_api_port)
    await site.start()
    logger.info(
        "KK state API started at http://%s:%s",
        settings.kkstate_api_host,
        settings.kkstate_api_port,
    )
    return runner


async def stop_api_server(runner: web.AppRunner) -> None:
    await runner.cleanup()
    logger.info("KK state API stopped.")


async def health(request: web.Request) -> web.Response:
    return web.json_response({"ok": True})


async def status(request: web.Request) -> web.Response:
    now = datetime.now(UTC)
    online_devices = {item.device for item in get_online_devices(now)}
    return web.json_response(
        {
            "online": bool(online_devices),
            "devices": [
                {
                    "device": item.device,
                    "online": item.device in online_devices,
                    "sent_at": item.sent_at.isoformat(),
                    "received_at": item.received_at.isoformat(),
                    "remote": item.remote,
                }
                for item in get_probe_states()
            ],
        }
    )


async def heartbeat(request: web.Request) -> web.Response:
    received_timestamp = int(datetime.now(UTC).timestamp())

    payload = await _read_json(request)
    try:
        decrypted_payload = _decrypt_heartbeat(payload)
        state = record_probe(decrypted_payload, request.remote)
    except Exception as exc:
        logger.warning("Rejected KK probe heartbeat remote=%s error=%s", request.remote, exc)
        return web.json_response({"ok": 0, "timestamp": received_timestamp}, status=400)

    logger.info(
        "KK probe heartbeat accepted remote=%s device=%s sent_at=%s",
        request.remote,
        state.device,
        state.sent_at.isoformat(),
    )
    return web.json_response({"ok": 1, "timestamp": received_timestamp})


async def _read_json(request: web.Request) -> dict:
    try:
        data = await request.json()
    except Exception:
        return {}

    return data if isinstance(data, dict) else {}


def _decrypt_heartbeat(payload: dict[str, Any]) -> dict[str, Any]:
    key_id = payload.get("key_id")
    nonce = payload.get("nonce")
    data = payload.get("data")

    if not isinstance(key_id, str) or not key_id.strip():
        raise ValueError("key_id is required")
    if not isinstance(nonce, str) or not nonce.strip():
        raise ValueError("nonce is required")
    if not isinstance(data, str) or not data.strip():
        raise ValueError("data is required")

    probe_key = get_key(key_id)
    if probe_key is None:
        raise ValueError("unknown key_id")

    aesgcm = AESGCM(decode_secret(probe_key.secret))
    plaintext = aesgcm.decrypt(
        base64.urlsafe_b64decode(nonce.encode("ascii")),
        base64.urlsafe_b64decode(data.encode("ascii")),
        key_id.encode("utf-8"),
    )
    decoded = json.loads(plaintext.decode("utf-8"))

    if not isinstance(decoded, dict):
        raise ValueError("decrypted payload must be an object")

    return decoded
