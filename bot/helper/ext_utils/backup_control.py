"""ערוץ בטוח בין מסך הגיבוי בבוט לבין ה־worker שפועל על המארח."""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


CONTROL_DIR = Path(os.environ.get("WZMLX_CONTROL_DIR", "runtime/control"))
SETTINGS_FILE = CONTROL_DIR / "backup-settings.json"
STATUS_FILE = CONTROL_DIR / "backup-status.json"
REQUEST_LOCK = CONTROL_DIR / "backup-request.lock"


@dataclass
class BackupSettings:
    """הגדרות התזמון שנשמרות גם לאחר הפעלה מחדש של הבוט."""

    daily_enabled: bool = True
    daily_hour: int = 4
    daily_minute: int = 15
    daily_timezone: str = "Asia/Jerusalem"
    daily_chat_id: int = 0


@dataclass
class BackupStatus:
    """תמונת מצב מצומצמת שאינה חושפת נתיבים, פקודות או סודות."""

    worker_seen_at: str = ""
    worker_state: str = "unknown"
    state: str = "idle"
    stage: str = ""
    job_id: str = ""
    origin: str = ""
    mode: str = ""
    started_at: str = ""
    finished_at: str = ""
    size_bytes: int = 0
    archive_name: str = ""
    integrity_verified: bool = False
    restore_verified: bool = False
    delivered: bool = False
    error: str = ""
    last_daily_attempt_date: str = ""


def _match_parent_owner(descriptor: int, parent: Path) -> None:
    """מתאים קובץ שנוצר בקונטיינר לבעלות תיקיית הבקרה של עובד המארח."""

    if not hasattr(os, "fchown"):
        return
    try:
        owner = parent.stat()
        os.fchown(descriptor, owner.st_uid, owner.st_gid)
    except OSError:
        pass


def _atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    """כותב JSON אטומית כדי שהצד השני לעולם לא יקרא קובץ חלקי."""

    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
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


def read_backup_settings(*, default_chat_id: int = 0) -> BackupSettings:
    """קורא הגדרות ומחזיר ערכים בטוחים גם אם הקובץ חסר או פגום."""

    payload = _read_json(SETTINGS_FILE)
    try:
        return BackupSettings(
            daily_enabled=bool(payload.get("daily_enabled", True)),
            daily_hour=min(23, max(0, int(payload.get("daily_hour", 4)))),
            daily_minute=min(59, max(0, int(payload.get("daily_minute", 15)))),
            daily_timezone="Asia/Jerusalem",
            daily_chat_id=max(
                0,
                int(payload.get("daily_chat_id", default_chat_id) or 0),
            ),
        )
    except (TypeError, ValueError):
        return BackupSettings(daily_chat_id=max(0, int(default_chat_id or 0)))


def ensure_backup_settings(chat_id: int) -> BackupSettings:
    """יוצר את הגדרות ברירת המחדל פעם אחת עם צ'אט המסירה של בעל הבוט."""

    settings = read_backup_settings(default_chat_id=chat_id)
    if not SETTINGS_FILE.exists() or settings.daily_chat_id <= 0:
        settings.daily_chat_id = int(chat_id)
        save_backup_settings(settings)
    return settings


def save_backup_settings(settings: BackupSettings) -> None:
    """שומר רק שדות תזמון מאושרים; סודות אינם חלק מקובץ ההגדרות."""

    if not 0 <= int(settings.daily_hour) <= 23:
        raise ValueError("שעת הגיבוי אינה תקינה")
    if not 0 <= int(settings.daily_minute) <= 59:
        raise ValueError("דקת הגיבוי אינה תקינה")
    if int(settings.daily_chat_id) <= 0:
        raise ValueError("מזהה צ'אט המסירה אינו תקין")
    normalized = BackupSettings(
        daily_enabled=bool(settings.daily_enabled),
        daily_hour=int(settings.daily_hour),
        daily_minute=int(settings.daily_minute),
        daily_timezone="Asia/Jerusalem",
        daily_chat_id=int(settings.daily_chat_id),
    )
    _atomic_json_write(SETTINGS_FILE, {"version": 1, **asdict(normalized)})


def set_daily_backup(*, enabled: bool, chat_id: int) -> BackupSettings:
    """מפעיל או משהה את הגיבוי היומי בלי לשנות את שעת ברירת המחדל."""

    settings = ensure_backup_settings(chat_id)
    settings.daily_enabled = bool(enabled)
    settings.daily_chat_id = int(chat_id)
    save_backup_settings(settings)
    return settings


def read_backup_status() -> BackupStatus:
    """מסנן את קובץ ה־worker לרשימת שדות קבועה לפני הצגתו בבוט."""

    payload = _read_json(STATUS_FILE)
    defaults = BackupStatus()
    values: dict[str, Any] = {}
    for field_name, default_value in asdict(defaults).items():
        value = payload.get(field_name, default_value)
        try:
            if isinstance(default_value, bool):
                value = bool(value)
            elif isinstance(default_value, int):
                value = max(0, int(value or 0))
            else:
                value = str(value or "")[:300]
        except (TypeError, ValueError):
            value = default_value
        values[field_name] = value
    return BackupStatus(**values)


def request_backup(
    *,
    chat_id: int,
    include_images: bool,
    origin: str = "manual",
) -> str:
    """יוצר ערכת ניוד מלאה או מהירה וחוסם לחיצה כפולה עד סיום ה־worker."""

    if int(chat_id) <= 0:
        raise ValueError("מזהה צ'אט המסירה אינו תקין")
    if origin not in {"manual", "daily"}:
        raise ValueError("מקור בקשת הגיבוי אינו מוכר")
    if origin == "daily" and not include_images:
        raise ValueError("גיבוי יומי חייב להיות חבילה מלאה הכוללת Images")
    mode = "full" if include_images else "state"
    CONTROL_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        descriptor = os.open(
            REQUEST_LOCK,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        _match_parent_owner(descriptor, CONTROL_DIR)
    except FileExistsError as error:
        raise RuntimeError("כבר קיים גיבוי שממתין או מתבצע") from error

    job_id = uuid.uuid4().hex[:12]
    request_path = CONTROL_DIR / f"backup-request-{job_id}.json"
    try:
        os.write(descriptor, f"{job_id}\n".encode("ascii"))
        os.close(descriptor)
        descriptor = -1
        _atomic_json_write(
            request_path,
            {
                "version": 1,
                "job_id": job_id,
                "chat_id": int(chat_id),
                "origin": origin,
                "mode": mode,
                "include_images": bool(include_images),
                "created_at": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ",
                    time.gmtime(),
                ),
            },
        )
        status = _read_json(STATUS_FILE)
        status.update(
            {
                "version": 1,
                "state": "queued",
                "stage": "בקשת הגיבוי ממתינה ל־worker",
                "job_id": job_id,
                "origin": origin,
                "mode": mode,
                "started_at": "",
                "finished_at": "",
                "size_bytes": 0,
                "archive_name": "",
                "integrity_verified": False,
                "restore_verified": False,
                "delivered": False,
                "error": "",
            }
        )
        _atomic_json_write(STATUS_FILE, status)
        return job_id
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        request_path.unlink(missing_ok=True)
        REQUEST_LOCK.unlink(missing_ok=True)
        raise


def request_full_backup(*, chat_id: int, origin: str = "manual") -> str:
    """שומר תאימות למסלולים ותיקים ומפנה תמיד לערכה המלאה."""

    return request_backup(
        chat_id=chat_id,
        include_images=True,
        origin=origin,
    )
