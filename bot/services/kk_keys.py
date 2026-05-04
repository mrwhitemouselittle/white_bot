import base64
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bot.settings import settings


@dataclass(frozen=True)
class ProbeKey:
    key_id: str
    secret: str
    created_at: str


def create_key() -> ProbeKey:
    key = ProbeKey(
        key_id=secrets.token_urlsafe(8),
        secret=base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii"),
        created_at=datetime.now(UTC).isoformat(),
    )
    keys = _load_keys()
    keys[key.key_id] = {
        "secret": key.secret,
        "created_at": key.created_at,
    }
    _save_keys(keys)
    return key


def list_keys() -> list[ProbeKey]:
    keys = _load_keys()
    return [
        ProbeKey(key_id=key_id, secret=item["secret"], created_at=item["created_at"])
        for key_id, item in sorted(keys.items())
    ]


def get_key(key_id: str) -> ProbeKey | None:
    item = _load_keys().get(key_id)
    if item is None:
        return None

    return ProbeKey(key_id=key_id, secret=item["secret"], created_at=item["created_at"])


def delete_key(key_id: str) -> bool:
    keys = _load_keys()
    if key_id not in keys:
        return False

    del keys[key_id]
    _save_keys(keys)
    return True


def set_key(key_id: str, secret: str) -> ProbeKey:
    decoded = decode_secret(secret)
    if len(decoded) != 32:
        raise ValueError("secret must decode to 32 bytes")

    now = datetime.now(UTC).isoformat()
    keys = _load_keys()
    created_at = keys.get(key_id, {}).get("created_at", now)
    keys[key_id] = {
        "secret": secret,
        "created_at": created_at,
        "updated_at": now,
    }
    _save_keys(keys)
    return ProbeKey(key_id=key_id, secret=secret, created_at=created_at)


def decode_secret(secret: str) -> bytes:
    return base64.urlsafe_b64decode(secret.encode("ascii"))


def _store_path() -> Path:
    return Path(settings.kkstate_key_store_path)


def _load_keys() -> dict[str, dict[str, str]]:
    path = _store_path()
    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8") as file:
        data: Any = json.load(file)

    if not isinstance(data, dict):
        return {}

    return {
        str(key_id): item
        for key_id, item in data.items()
        if isinstance(item, dict)
        and isinstance(item.get("secret"), str)
        and isinstance(item.get("created_at"), str)
    }


def _save_keys(keys: dict[str, dict[str, str]]) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(keys, file, ensure_ascii=False, indent=2)
