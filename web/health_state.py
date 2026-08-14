"""ערכי מצב קטנים ובטוחים שמשמשים את נקודת הבריאות של השרת."""

from pathlib import Path
from re import fullmatch


DEFAULT_RELEASE_ID_PATH = Path("/usr/src/app/.release-id")


def read_release_id(path: Path = DEFAULT_RELEASE_ID_PATH) -> str:
    """קורא מזהה release מאומת בלי להפיל את בדיקת הבריאות אם הקובץ חסר."""

    try:
        release_id = path.read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"
    if not fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", release_id):
        return "unknown"
    return release_id
