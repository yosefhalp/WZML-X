"""תור קבצים מקומי שמוסר בקשות מהדשבורד לתהליך Telegram הראשי."""

from __future__ import annotations

import json
import os
import time
import uuid
from hashlib import sha256
from asyncio import sleep
from datetime import datetime, timezone
from pathlib import Path


CONTROL_DIR = Path(os.environ.get("WZMLX_CONTROL_DIR", "runtime/control"))
STATUS_FILE = CONTROL_DIR / "dashboard-task-status.json"
DEDUPE_FILE = CONTROL_DIR / "dashboard-task-dedupe.json"
REQUEST_LOCK = CONTROL_DIR / "dashboard-task-request.lock"


def _match_parent_owner(descriptor: int, parent: Path) -> None:
    """מוסר את קובץ התור לבעל כרך המארח בלי להרחיב הרשאות."""

    if not hasattr(os, "fchown"):
        return
    try:
        owner = parent.stat()
        os.fchown(descriptor, owner.st_uid, owner.st_gid)
    except OSError:
        pass


def _atomic_json(path: Path, payload: dict) -> None:
    """כותב JSON שלם ורק אז מחליף את הגרסה הנראית לתהליך השני."""

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
        os.chmod(path, 0o600)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def enqueue_task_request(
    *,
    command: str,
    source_text: str = "",
    requires_premium: bool = False,
) -> str:
    """מכניס לתור רק פקודה שנבנתה בשרת ורשימת מקור מוגבלת בגודל."""

    command = str(command or "").strip()
    source_text = str(source_text or "").strip()
    if not command.startswith("/") or len(command) > 8192:
        raise ValueError("פקודת המשימה אינה תקינה")
    if len(source_text.encode("utf-8")) > 128 * 1024:
        raise ValueError("רשימת הקישורים גדולה מדי")
    fingerprint = sha256(
        f"{command}\0{source_text}\0{int(bool(requires_premium))}".encode("utf-8")
    ).hexdigest()
    CONTROL_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        descriptor = os.open(REQUEST_LOCK, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        _match_parent_owner(descriptor, CONTROL_DIR)
        os.close(descriptor)
    except FileExistsError as error:
        raise RuntimeError("בקשת משימה אחרת נקלטת כעת; נסו שוב בעוד רגע") from error
    try:
        try:
            previous = json.loads(DEDUPE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            previous = {}
        if (
            previous.get("fingerprint") == fingerprint
            and time.time() - float(previous.get("created_epoch") or 0) <= 15
        ):
            return str(previous.get("request_id") or "")[:12]
        request_id = uuid.uuid4().hex[:12]
        created_at = datetime.now(timezone.utc).isoformat()
        _atomic_json(
            CONTROL_DIR / f"task-request-{request_id}.json",
            {
                "version": 1,
                "request_id": request_id,
                "command": command,
                "source_text": source_text,
                "requires_premium": bool(requires_premium),
                "created_at": created_at,
            },
        )
        _atomic_json(
            DEDUPE_FILE,
            {
                "request_id": request_id,
                "fingerprint": fingerprint,
                "created_epoch": time.time(),
            },
        )
        return request_id
    finally:
        REQUEST_LOCK.unlink(missing_ok=True)


def read_task_request_status() -> dict:
    """מחזיר לדשבורד סטטוס קצר בלי הפקודה או קישורי המקור."""

    try:
        payload = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        "request_id": str(payload.get("request_id") or "")[:12],
        "state": str(payload.get("state") or "")[:20],
        "message": str(payload.get("message") or "")[:200],
        "updated_at": str(payload.get("updated_at") or "")[:40],
    }


async def _process_task_request(path: Path) -> None:
    """מוסר בקשה אחת דרך ה־Userbot שכבר מחובר בתהליך הראשי."""

    from ... import LOGGER
    from ...core.tg_client import TgClient

    request_id = path.stem.removeprefix("task-request-")[:12]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("request_id") != request_id:
            raise ValueError("מזהה בקשת המשימה אינו תואם לקובץ")
        created = datetime.fromisoformat(str(payload.get("created_at") or ""))
        if created.tzinfo is None or time.time() - created.timestamp() > 600:
            raise ValueError("בקשת המשימה פגה לפני שנמסרה לבוט")
        if TgClient.user is None or not TgClient.BNAME:
            raise RuntimeError("חשבון המשתמש של Telegram אינו מחובר")
        if payload.get("requires_premium") and not TgClient.IS_PREMIUM_USER:
            raise RuntimeError("חשבון המשתמש המחובר אינו Premium")
        source_text = str(payload.get("source_text") or "").strip()
        command = str(payload.get("command") or "").strip()
        source = None
        if source_text:
            source = await TgClient.user.send_message(
                TgClient.BNAME,
                source_text,
                disable_web_page_preview=True,
            )
        await TgClient.user.send_message(
            TgClient.BNAME,
            command,
            reply_to_message_id=source.id if source else None,
        )
        _atomic_json(
            STATUS_FILE,
            {
                "request_id": request_id,
                "state": "success",
                "message": "הבקשה נמסרה לבוט Telegram",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        LOGGER.info("בקשת Dashboard נמסרה לבוט: %s", request_id)
    except Exception as error:
        _atomic_json(
            STATUS_FILE,
            {
                "request_id": request_id,
                "state": "failed",
                "message": " ".join(str(error or "המסירה נכשלה").split())[:200],
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        LOGGER.error("בקשת Dashboard נכשלה: %s: %s", request_id, type(error).__name__)
    finally:
        path.unlink(missing_ok=True)


async def task_request_worker() -> None:
    """מאזין לתור המשותף כל עוד תהליך הבוט פעיל."""

    while True:
        try:
            for path in sorted(CONTROL_DIR.glob("task-request-*.json")):
                request_id = path.stem.removeprefix("task-request-")
                if len(request_id) != 12 or any(c not in "0123456789abcdef" for c in request_id):
                    continue
                await _process_task_request(path)
        except Exception:
            # כשל בסריקת התיקייה אינו רשאי להפיל את לקוח Telegram.
            pass
        await sleep(1)
