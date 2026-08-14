"""מיפוי וניקוי זהיר של קבצים שנשארו ממשימות שהסתיימו או נתקעו."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from shutil import rmtree


@dataclass
class ResidualDownloadStatus:
    """סיכום נפח שאינו חושף שמות קבצים או נתיבים פרטיים."""

    entries: int = 0
    files: int = 0
    bytes: int = 0
    protected_entries: int = 0
    cleanup_allowed: bool = False


def _entry_size(path: Path) -> tuple[int, int]:
    """מודד קבצים רגילים בלבד ואינו עוקב אחרי קישורים סימבוליים."""

    if path.is_symlink():
        return 0, 0
    if path.is_file():
        try:
            return 1, path.stat().st_size
        except OSError:
            return 0, 0
    files = size = 0
    for child in path.rglob("*"):
        try:
            if child.is_file() and not child.is_symlink():
                files += 1
                size += child.stat().st_size
        except OSError:
            continue
    return files, size


def residual_download_status(
    download_root: Path,
    *,
    active_task_ids: set[str] | None = None,
) -> dict[str, int | bool]:
    """ממפה שאריות ומגן על כל תיקייה ששייכת למשימה פעילה."""

    root = download_root.resolve()
    active = {str(value) for value in (active_task_ids or set())}
    status = ResidualDownloadStatus()
    if not root.is_dir():
        return asdict(status)
    for entry in root.iterdir():
        if entry.name in active:
            status.protected_entries += 1
            continue
        files, size = _entry_size(entry)
        status.entries += 1
        status.files += files
        status.bytes += size
    status.cleanup_allowed = not active and status.entries > 0
    return asdict(status)


def clear_residual_downloads(
    download_root: Path,
    *,
    active_task_ids: set[str] | None = None,
) -> dict[str, int | bool]:
    """מוחק שאריות רק כשאין משימה פעילה ומשאיר את תיקיית ההורדות עצמה."""

    active = {str(value) for value in (active_task_ids or set())}
    if active:
        raise RuntimeError("לא ניתן לנקות שאריות כאשר קיימת משימה פעילה")
    root = download_root.resolve()
    before = residual_download_status(root, active_task_ids=active)
    if not root.is_dir():
        return {**before, "removed_entries": 0, "removed_files": 0, "removed_bytes": 0}
    removed_entries = 0
    for entry in list(root.iterdir()):
        try:
            if entry.is_symlink() or entry.is_file():
                entry.unlink(missing_ok=True)
            elif entry.is_dir():
                rmtree(entry)
            else:
                continue
            removed_entries += 1
        except OSError:
            continue
    return {
        **residual_download_status(root, active_task_ids=set()),
        "removed_entries": removed_entries,
        "removed_files": int(before["files"]),
        "removed_bytes": int(before["bytes"]),
    }
