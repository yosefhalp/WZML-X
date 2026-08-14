"""בדיקת GoFile חיה דרך פקודת הבוט, כולל שמירה ומחיקת תוכן הבדיקה."""

from asyncio import run, sleep
from datetime import datetime, timezone
from pathlib import Path
from time import time

from aiohttp import ClientSession
from pymongo import AsyncMongoClient
from pyrogram import Client

import config as deploy_config
from bot.core.config_manager import Config
from bot.helper.ext_utils.gofile_delete import GONE_OUTCOMES, delete_content


def _setting(name):
    """קורא הגדרה פעילה בלי להדפיס את ערכה."""

    return getattr(Config, name, None) or getattr(deploy_config, name, None)


async def main():
    session_string = _setting("USER_SESSION_STRING")
    bot_token = _setting("BOT_TOKEN")
    database_url = _setting("DATABASE_URL")
    if not session_string or not bot_token or not database_url:
        raise RuntimeError("חסרה הגדרה סודית הנדרשת לבדיקה")

    api_id = _setting("TELEGRAM_API")
    api_hash = _setting("TELEGRAM_HASH")
    stamp = int(time())
    started_at = datetime.now(timezone.utc)
    file_name = f"wzmlx-gofile-smoke-{stamp}.txt"
    file_path = Path("/tmp") / file_name
    file_path.write_text("WZML-X GoFile live smoke test\n", encoding="utf-8")

    user = Client(
        "WZ-GoFileSmoke-User",
        api_id=api_id,
        api_hash=api_hash,
        session_string=session_string,
        in_memory=True,
        no_updates=True,
    )
    mongo = AsyncMongoClient(database_url)
    collection = mongo.wzmlx.gofile_uploads
    record = None
    media_message = None
    command_message = None
    bot_peer = None
    bot_message_ids = []
    completion_text = ""
    completion_buttons = []
    telegram_cleaned = False
    gofile_cleaned = False
    try:
        await user.start()
        # מזהה מספרי אינו תמיד מוכר ל-Session חדש; שם המשתמש נפתר דרך getMe
        # בלי להדפיס או לשמור את טוקן הבוט בתוצאת הבדיקה.
        async with ClientSession() as http:
            async with http.get(f"https://api.telegram.org/bot{bot_token}/getMe") as response:
                payload = await response.json()
        bot_peer = f"@{payload['result']['username']}"
        media_message = await user.send_document(
            bot_peer,
            str(file_path),
            caption="בדיקת GoFile חיה של WZML-X",
            disable_notification=True,
        )
        command_message = await media_message.reply("/gofile")

        for _ in range(60):
            record = await collection.find_one(
                {
                    "name": file_name,
                    "created_at": {"$gte": started_at},
                }
            )
            if record:
                break
            await sleep(2)

        print(f"record_created={bool(record)}")
        print(f"owner_token_saved={bool(record and record.get('guest_token'))}")
        print(f"content_ids_saved={bool(record and record.get('content_ids'))}")
        print(f"public_link_saved={bool(record and record.get('link'))}")

        for _ in range(20):
            async for history_message in user.get_chat_history(bot_peer, limit=30):
                text = history_message.text or history_message.caption or ""
                if history_message.from_user and history_message.from_user.is_bot:
                    if file_name in text:
                        bot_message_ids.append(history_message.id)
                    if "המשימה הושלמה בהצלחה" in text and file_name in text:
                        completion_text = text
                        markup = history_message.reply_markup
                        completion_buttons = [
                            button.text
                            for row in (markup.inline_keyboard if markup else [])
                            for button in row
                        ]
            if completion_text:
                break
            await sleep(1)
        required_labels = ("המשימה הושלמה בהצלחה", "גודל", "זמן כולל", "מצב קלט", "מצב פלט")
        forbidden_labels = ("Task Size", "Time Taken", "In Mode", "Out Mode", "Task By")
        print(f"completion_screen_found={bool(completion_text)}")
        print(f"completion_hebrew_labels={all(value in completion_text for value in required_labels)}")
        print(f"completion_no_legacy_english={not any(value in completion_text for value in forbidden_labels)}")
        has_rtl_wrapper = chr(0x2067) in completion_text and chr(0x2069) in completion_text
        print(f"completion_rtl_wrapper={has_rtl_wrapper}")
        print(f"completion_button_hebrew={any('קישור' in value or 'פתיחה' in value for value in completion_buttons)}")

        if record:
            targets = (
                [record["folder_id"]]
                if record.get("delete_scope") == "folder" and record.get("folder_id")
                else list(record.get("content_ids") or [])
            )
            outcomes = []
            for target in targets:
                outcome, _ = await delete_content(record.get("guest_token"), target)
                outcomes.append(outcome)
            if outcomes and all(value in GONE_OUTCOMES for value in outcomes):
                await collection.update_one(
                    {"_id": record["_id"]},
                    {
                        "$set": {
                            "status": "deleted",
                            "deleted_at": datetime.now(timezone.utc),
                        },
                        "$unset": {"guest_token": ""},
                    },
                )
                gofile_cleaned = True
    finally:
        if user.is_connected:
            ids = [
                message.id
                for message in (media_message, command_message)
                if message is not None
            ]
            ids.extend(bot_message_ids)
            ids = sorted(set(ids))
            if ids:
                try:
                    await user.delete_messages(bot_peer, ids, revoke=True)
                    telegram_cleaned = True
                except Exception:
                    telegram_cleaned = False
            await user.stop()
        await mongo.close()
        file_path.unlink(missing_ok=True)
        print(f"gofile_cleaned={gofile_cleaned}")
        print(f"telegram_cleaned={telegram_cleaned}")


if __name__ == "__main__":
    run(main())
