"""ניקוי בטוח של קבצי משימה ושחרור זיכרון לאחר סיום העבודה."""

from asyncio import to_thread
from ctypes import CDLL
from functools import wraps
from gc import collect
from os import path as ospath
from pathlib import Path
from shutil import rmtree
from sys import platform


def ensure_terminal_cleanup(preserve_while_seeding=False):
    """מבטיח שמשאבי המשימה ישוחררו גם אם פעולת הסיום העלתה חריגה."""

    def decorator(callback):
        @wraps(callback)
        async def wrapped(listener, *args, **kwargs):
            try:
                return await callback(listener, *args, **kwargs)
            finally:
                if not (preserve_while_seeding and listener.seed):
                    await listener.finalize_terminal_task()

        return wrapped

    return decorator


def is_safe_task_path(target, download_root):
    """בודק שהיעד הוא צאצא של תיקיית ההורדות ואינו התיקייה הראשית עצמה."""
    if not target or not download_root:
        return False

    root = Path(download_root).resolve(strict=False)
    candidate = Path(target).resolve(strict=False)
    return candidate != root and root in candidate.parents


def _remove_path(target):
    """מוחק קובץ או תיקייה בלי לעקוב אחרי קישור סמלי אל מחוץ ליעד."""
    path = Path(target)
    if not ospath.lexists(path):
        return False
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    else:
        rmtree(path, ignore_errors=False)
    return True


async def clean_task_paths(paths, download_root, logger=None):
    """מוחק רק נתיבי משימה בטוחים ומחזיר את הנתיבים שנמחקו בפועל."""
    removed = []
    seen = set()
    for target in paths:
        if not target:
            continue
        normalized = str(Path(target))
        if normalized in seen:
            continue
        seen.add(normalized)

        if not is_safe_task_path(target, download_root):
            if logger:
                logger.error(f"ניקוי משימה נחסם עבור נתיב לא בטוח: {target}")
            continue

        try:
            if await to_thread(_remove_path, target):
                removed.append(normalized)
                if logger:
                    logger.info(f"קבצי המשימה נמחקו: {target}")
        except Exception as error:
            if logger:
                logger.error(f"מחיקת קבצי המשימה נכשלה עבור {target}: {error}")
    return removed


def _release_process_memory():
    """משחרר אובייקטים לא פעילים ומחזיר ל־Linux דפי זיכרון פנויים כשאפשר."""
    collected = collect()
    trimmed = False
    if platform.startswith("linux"):
        try:
            trimmed = bool(CDLL("libc.so.6").malloc_trim(0))
        except (AttributeError, OSError):
            trimmed = False
    return collected, trimmed


async def release_process_memory(logger=None):
    """מריץ שחרור זיכרון מחוץ ללולאת האירועים כדי לא לעכב את הבוט."""
    try:
        collected, trimmed = await to_thread(_release_process_memory)
        if logger:
            logger.info(
                "ניקוי זיכרון לאחר משימה הושלם: "
                f"אובייקטים={collected}, החזרה למערכת={'כן' if trimmed else 'לא'}"
            )
        return collected, trimmed
    except Exception as error:
        if logger:
            logger.error(f"ניקוי הזיכרון לאחר משימה נכשל: {error}")
        return 0, False
