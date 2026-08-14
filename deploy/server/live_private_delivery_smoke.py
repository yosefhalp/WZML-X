"""בדיקת מסירה חיה וקצרה מה-Session אל השיחה הפרטית עם הבוט.

הבדיקה אינה מדפיסה טוקנים או Session. היא מעלה את קובץ הבדיקה עצמו,
מוודאת שהבוט רואה אותו באותו דו-שיח ומוחקת אותו משני הצדדים בסיום.
"""

from asyncio import Event, TimeoutError, run, wait_for
from pathlib import Path

from pyrogram import Client, filters
from pyrogram.handlers import MessageHandler

import config as deploy_config
from bot.core.config_manager import Config


def _setting(name):
    """קורא הגדרה פעילה, ובבדיקה עצמאית נופל לקובץ הפריסה הממופה."""

    return getattr(Config, name, None) or getattr(deploy_config, name, None)


async def main():
    session_string = _setting("USER_SESSION_STRING")
    bot_token = _setting("BOT_TOKEN")
    telegram_api = _setting("TELEGRAM_API")
    telegram_hash = _setting("TELEGRAM_HASH")
    if not session_string:
        raise RuntimeError("USER_SESSION_STRING אינו מוגדר")

    bot_id = int(bot_token.split(":", 1)[0])
    common = {
        "api_id": telegram_api,
        "api_hash": telegram_hash,
        "in_memory": True,
    }
    user = Client(
        "WZ-LiveDeliverySmoke-User",
        session_string=session_string,
        no_updates=True,
        **common,
    )
    bot = Client(
        "WZ-LiveDeliverySmoke-Bot",
        bot_token=bot_token,
        no_updates=False,
        **common,
    )
    sent = None
    cleaned_up = False
    received_event = Event()
    received_by_bot = False
    sender_matches_session = False

    async def _capture_delivery(_, message):
        nonlocal received_by_bot, sender_matches_session
        if (message.caption or "") != "בדיקת מסירה פרטית של WZML-X":
            return
        received_by_bot = bool(message.document)
        sender_matches_session = bool(
            message.from_user and message.from_user.id == user.me.id
        )
        received_event.set()

    bot.add_handler(
        MessageHandler(_capture_delivery, filters.private & filters.document),
        group=-10,
    )
    try:
        await user.start()
        await bot.start()
        bot_peer = f"@{bot.me.username}"
        sent = await user.send_document(
            chat_id=bot_peer,
            document=str(Path(__file__).resolve()),
            caption="בדיקת מסירה פרטית של WZML-X",
            disable_notification=True,
        )
        try:
            await wait_for(received_event.wait(), timeout=15)
        except TimeoutError:
            pass
        print(f"sent_to_bot={sent.chat.id == bot_id}")
        print(f"not_saved_messages={sent.chat.id != user.me.id}")
        print(f"bot_received={received_by_bot}")
        print(f"sender_matches_session={sender_matches_session}")
    finally:
        if sent is not None:
            try:
                await user.delete_messages(bot_peer, sent.id, revoke=True)
                cleaned_up = True
            except Exception:
                cleaned_up = False
        print(f"cleaned_up={cleaned_up}")
        if bot.is_connected:
            await bot.stop()
        if user.is_connected:
            await user.stop()


if __name__ == "__main__":
    run(main())
