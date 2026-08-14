"""בקשות וסטטוס לניהול מטמון המארח מתוך מסך הבוט."""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


CONTROL_DIR = Path(os.environ.get("WZMLX_CONTROL_DIR", "runtime/control"))
STATUS_FILE = CONTROL_DIR / "cache-status.json"
REQUEST_LOCK = CONTROL_DIR / "cache-request.lock"


@dataclass
class CacheStatus:
    state: str = "idle"
    stage: str = ""
    scanned_at: str = ""
    python_files: int = 0
    python_bytes: int = 0
    docker_build_count: int = 0
    docker_build_bytes: int = 0
    docker_reclaimable_bytes: int = 0
    bot_api_files: int = 0
    bot_api_bytes: int = 0
    bot_api_large_files: int = 0
    bot_api_large_bytes: int = 0
    bot_api_old_files: int = 0
    bot_api_old_bytes: int = 0
    bot_api_protected_files: int = 0
    bot_api_protected_bytes: int = 0
    last_cleaned_at: str = ""
    removed_files: int = 0
    removed_bytes: int = 0
    error: str = ""


def _match_parent_owner(descriptor: int, parent: Path) -> None:
    """שומר על הרשאת 0600 אך מוסר את הקובץ לעובד המארח שקורא אותו."""

    if not hasattr(os, "fchown"):
        return
    try:
        owner = parent.stat()
        os.fchown(descriptor, owner.st_uid, owner.st_gid)
    except OSError:
        pass


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    """כותב קובץ בקרה שלם לפני החלפת הגרסה הקודמת."""

    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    _match_parent_owner(descriptor, path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def read_cache_status() -> CacheStatus:
    """מסנן את נתוני המארח לשדות מספריים וטקסט קצרים בלבד."""

    payload = _read_json(STATUS_FILE)
    defaults = CacheStatus()
    values: dict[str, Any] = {}
    for field_name, default_value in asdict(defaults).items():
        value = payload.get(field_name, default_value)
        try:
            value = max(0, int(value or 0)) if isinstance(default_value, int) else str(value or "")[:300]
        except (TypeError, ValueError):
            value = default_value
        values[field_name] = value
    return CacheStatus(**values)


def request_cache_action(action: str) -> str:
    """מבקש סריקה או ניקוי בטוח; פעולה שנייה נחסמת עד סיום הראשונה."""

    if action not in {"scan", "clean_safe"}:
        raise ValueError("פעולת המטמון אינה מוכרת")
    CONTROL_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        descriptor = os.open(REQUEST_LOCK, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        _match_parent_owner(descriptor, CONTROL_DIR)
    except FileExistsError as error:
        raise RuntimeError("כבר מתבצעת בדיקת מטמון או פעולת ניקוי") from error
    request_id = uuid.uuid4().hex[:12]
    path = CONTROL_DIR / f"cache-request-{request_id}.json"
    try:
        os.write(descriptor, f"{request_id}\n".encode("ascii"))
        os.close(descriptor)
        descriptor = -1
        _atomic_json(
            path,
            {
                "version": 1,
                "request_id": request_id,
                "action": action,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
        )
        status = _read_json(STATUS_FILE)
        status.update(
            {
                "version": 1,
                "state": "queued",
                "stage": "הבקשה ממתינה ל־worker",
                "error": "",
            }
        )
        _atomic_json(STATUS_FILE, status)
        return request_id
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        path.unlink(missing_ok=True)
        REQUEST_LOCK.unlink(missing_ok=True)
        raise
