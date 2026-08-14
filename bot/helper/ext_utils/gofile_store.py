"""אחסון מאובטח של בעלות GoFile במסד MongoDB של הבוט.

הטוקן לעולם אינו מוחזר ממסלולי הרשימה הרגילים. רק פעולה פנימית שדורשת בעלות,
כגון מחיקה או הוספה לאותה תיקייה, יכולה לבקש רשומה הכוללת את הטוקן.
"""

from datetime import datetime, timezone
from uuid import uuid4


PUBLIC_FIELDS = {
    "_id": 1,
    "user_id": 1,
    "name": 1,
    "size": 1,
    "link": 1,
    "mode": 1,
    "status": 1,
    "folder_id": 1,
    "created_at": 1,
}


class GoFileStore:
    """שכבת גישה קטנה שניתנת לבדיקה בלי להפעיל את כל הבוט."""

    def __init__(self, database):
        self.database = database
        self._indexes_ready = False

    def _collection(self):
        if self.database is None or self.database.db is None:
            raise RuntimeError("מסד MongoDB אינו מחובר; פרטי הבעלות של GoFile לא נשמרו")
        return self.database.db.gofile_uploads

    async def _ensure_indexes(self):
        if self._indexes_ready:
            return
        collection = self._collection()
        await collection.create_index([("user_id", 1), ("created_at", -1)])
        await collection.create_index("job_id")
        self._indexes_ready = True

    async def save_upload(
        self,
        *,
        user_id,
        name,
        size,
        link,
        mode,
        job_id,
        content_ids,
        folder_id,
        guest_token,
        delete_scope,
        reused_from="",
    ):
        """שומר את כל המזהים בזמן ההעלאה, לפני שאפשר לאבד אותם."""

        if not link or not guest_token:
            raise RuntimeError("GoFile לא החזיר קישור וטוקן בעלות מלאים")
        await self._ensure_indexes()
        record = {
            "_id": uuid4().hex,
            "user_id": int(user_id),
            "name": str(name or "קובץ ללא שם"),
            "size": int(size or 0),
            "link": str(link),
            "mode": str(mode or "file"),
            "status": "active",
            "job_id": str(job_id or ""),
            "content_ids": [str(value) for value in content_ids if value],
            "folder_id": str(folder_id or ""),
            "guest_token": str(guest_token),
            "delete_scope": str(delete_scope or "contents"),
            "reused_from": str(reused_from or ""),
            "created_at": datetime.now(timezone.utc),
        }
        await self._collection().insert_one(record)
        return self._public(record)

    async def list_for_user(self, user_id, *, limit=8, offset=0):
        """מחזיר רשימה נקייה מטוקנים ורק עבור בעל הרשומות."""

        await self._ensure_indexes()
        cursor = (
            self._collection()
            .find({"user_id": int(user_id)}, PUBLIC_FIELDS)
            .sort("created_at", -1)
            .skip(max(int(offset or 0), 0))
            .limit(max(min(int(limit or 1), 25), 1))
        )
        return [self._public(row) async for row in cursor]

    async def get_owned(self, user_id, record_id, *, include_secret=False):
        """טוען רשומה לפי מזהה וגם לפי בעלים; callback לבדו אינו הרשאה."""

        await self._ensure_indexes()
        projection = None if include_secret else PUBLIC_FIELDS
        row = await self._collection().find_one(
            {"_id": str(record_id), "user_id": int(user_id)}, projection
        )
        return dict(row) if row else None

    async def mark_deleted(self, user_id, record_id):
        """מסמן מחיקה ומוחק את הטוקן לאחר שאינו שולט עוד בתוכן."""

        result = await self._collection().update_one(
            {"_id": str(record_id), "user_id": int(user_id), "status": "active"},
            {
                "$set": {
                    "status": "deleted",
                    "deleted_at": datetime.now(timezone.utc),
                },
                "$unset": {"guest_token": ""},
            },
        )
        return bool(result.modified_count)

    @staticmethod
    def _public(record):
        """מסיר שדות סודיים גם אם הנהג החזיר מסמך מלא במקרה."""

        clean = dict(record)
        clean.pop("guest_token", None)
        clean.pop("content_ids", None)
        clean.pop("delete_scope", None)
        return clean


def live_gofile_store():
    """יוצר גישה למסד החי רק בזמן שימוש, כדי למנוע import מעגלי."""

    from .db_handler import database

    return GoFileStore(database)
