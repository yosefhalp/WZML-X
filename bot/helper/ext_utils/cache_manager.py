"""ניקוי מטמון בטוח שאינו נוגע בנתוני משתמש או במשימות פעילות."""

from __future__ import annotations

from importlib import invalidate_caches
from pathlib import Path
from shutil import rmtree


PROTECTED_DIRECTORIES = {
    ".git",
    "accounts",
    "downloads",
    "rclone",
    "runtime",
    "thumbnails",
    "tokens",
}


def clear_filesystem_cache(project_root: Path) -> dict:
    """מוחק רק תיקיות __pycache__ שאינן נמצאות תחת נתיב מוגן."""

    root = project_root.resolve()
    removed_directories = 0
    removed_bytes = 0
    for current_root, directories, _ in __import__("os").walk(root, topdown=True):
        current = Path(current_root)
        directories[:] = [
            name
            for name in directories
            if name not in PROTECTED_DIRECTORIES
            and not (current / name).is_symlink()
        ]
        if current.name != "__pycache__":
            continue
        try:
            relative = current.resolve().relative_to(root)
        except ValueError:
            continue
        if any(part in PROTECTED_DIRECTORIES for part in relative.parts):
            continue
        try:
            removed_bytes += sum(
                path.stat().st_size
                for path in current.rglob("*")
                if path.is_file() and not path.is_symlink()
            )
            rmtree(current)
            removed_directories += 1
        except OSError:
            continue
        directories[:] = []
    return {
        "directories": removed_directories,
        "bytes": removed_bytes,
    }


def clear_runtime_cache(project_root: Path | None = None) -> dict:
    """מנקה מטמון קוד ותצוגה בלבד ומחזיר דוח שאפשר להציג למשתמש."""

    result = clear_filesystem_cache(project_root or Path.cwd())
    memory_entries = 0
    try:
        from ... import bot_cache

        # גרסאות המנועים נשמרות כדי שמסך הסטטוס לא יציג N/A עד האתחול הבא.
        for key in ("commit",):
            if key in bot_cache:
                bot_cache.pop(key, None)
                memory_entries += 1
    except ImportError:
        pass
    try:
        from .bot_lock import clear_system_resources_cache

        clear_system_resources_cache()
        memory_entries += 1
    except ImportError:
        pass
    invalidate_caches()
    result["memory_entries"] = memory_entries
    return result
