from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from bot.settings import settings


@dataclass
class DeviceHeartbeat:
    device: str
    sent_at: datetime
    received_at: datetime
    remote: str | None = None


_devices: dict[str, DeviceHeartbeat] = {}


def record_probe(payload: dict[str, Any], remote: str | None) -> DeviceHeartbeat:
    device = _clean(payload.get("device"))
    timestamp = _parse_timestamp(payload.get("timestamp"))

    if device is None:
        raise ValueError("device is required")
    if timestamp is None:
        raise ValueError("timestamp is required")

    heartbeat = DeviceHeartbeat(
        device=device,
        sent_at=timestamp,
        received_at=datetime.now(UTC),
        remote=remote,
    )
    _devices[device] = heartbeat
    return heartbeat


def get_probe_states() -> list[DeviceHeartbeat]:
    return sorted(_devices.values(), key=lambda item: item.device)


def get_online_devices(now: datetime | None = None) -> list[DeviceHeartbeat]:
    now = now or datetime.now(UTC)
    online = [
        heartbeat
        for heartbeat in _devices.values()
        if _is_device_online(heartbeat, now)
    ]
    return sorted(online, key=lambda item: item.device)


def format_state_message() -> str:
    online_devices = get_online_devices()

    if not online_devices:
        return "主人不在线哦~"

    names = "、".join(item.device for item in online_devices)
    return f"主人在的，在{names}前！"


def _is_device_online(heartbeat: DeviceHeartbeat, now: datetime) -> bool:
    age = (now - heartbeat.sent_at).total_seconds()
    return 0 <= age <= settings.kkstate_online_seconds


def _clean(value: Any) -> str | None:
    if value is None:
        return None

    text = str(value).strip()
    return text or None


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, UTC)

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None

        if text.isdigit():
            return datetime.fromtimestamp(int(text), UTC)

        normalized = text.removesuffix("Z") + "+00:00" if text.endswith("Z") else text
        parsed = datetime.fromisoformat(normalized)
        return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    return None
