"""כללי מיזוג בין config.py של הפריסה לבין הגדרות שנשמרו ב-MongoDB."""


# ערכים אלה ניתנים לאיפוס דרך פעולה מפורשת בממשק. קובץ פריסה שבו הם ריקים
# אינו הוראה למחוק סוד פעיל שכבר נשמר במסד.
PRESERVE_SAVED_WHEN_DEPLOY_EMPTY = {
    "BOT_TOKEN",
    "TELEGRAM_API",
    "TELEGRAM_HASH",
    "OWNER_ID",
    "DATABASE_URL",
    "USER_SESSION_STRING",
    "WEB_ACCESS_PASSWORD",
}


def merge_changed_deploy_config(old_deploy, new_deploy, saved_config):
    """ממזג רק שינויים אמיתיים, בלי שערך ריק ימחק סוד שמור ולא-ריק."""

    merged = dict(saved_config or {})
    for key, value in (new_deploy or {}).items():
        if key in (old_deploy or {}) and old_deploy.get(key) == value:
            continue
        if (
            key in PRESERVE_SAVED_WHEN_DEPLOY_EMPTY
            and value in (None, "", 0)
            and merged.get(key) not in (None, "", 0)
        ):
            continue
        if value is not None:
            merged[key] = value
    return merged
