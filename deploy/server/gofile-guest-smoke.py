"""בודק העלאת GoFile כאורח דרך מחלקת ה-uploader של הבוט ומנקה את קובץ הבדיקה."""

import asyncio
import json
import os
import tempfile

from aiohttp import ClientSession

from bot.core.config_manager import Config
from bot.helper.mirror_leech_utils.uphoster_utils.uploaders_utils.gofile_uploader import (
    GoFileUpload,
)

Config.load()


class SmokeListener:
    """מספק ל-uploader רק את שדות המאזין שנדרשים לבדיקת קובץ יחיד."""

    user_id = Config.OWNER_ID
    is_cancelled = False
    name = "wzmlx-gofile-smoke.txt"


async def main() -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as handle:
        handle.write("WZML-X GoFile guest upload smoke test\n")
        test_path = handle.name

    try:
        uploader = GoFileUpload(SmokeListener(), test_path)
        # הבדיקה חייבת לרוץ ללא טוקן חשבון, כדי לא לגעת בחשבון או בבריכה פרטית.
        uploader.token = None
        result = await uploader.upload_file(test_path)
        required = ("guestToken", "parentFolder", "downloadPage")
        if any(not str(result.get(key) or "").strip() for key in required):
            raise RuntimeError("GoFile לא החזיר זהות אורח וקישור מלאים")

        cleanup_ok = False
        headers = {"Authorization": f"Bearer {result['guestToken']}"}
        async with ClientSession() as session, session.delete(
            "https://api.gofile.io/contents",
            headers=headers,
            json={"contentsId": result["parentFolder"]},
        ) as response:
            # נקודות הקצה השונות של GoFile מחזירות 200, 202 או 204 ללא מבנה גוף אחיד.
            cleanup_ok = 200 <= response.status < 300

        print(json.dumps({"upload_ok": True, "guest_mode": True, "cleanup_ok": cleanup_ok}))
        if not cleanup_ok:
            raise RuntimeError("ההעלאה הצליחה אך ניקוי תיקיית הבדיקה נכשל")
    finally:
        os.unlink(test_path)


if __name__ == "__main__":
    asyncio.run(main())
