from html import escape
from pyrogram.enums import ButtonStyle
from time import monotonic, time
from uuid import uuid4
from re import match

from aiofiles import open as aiopen
from cloudscraper import create_scraper
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .. import LOGGER, user_data
from ..core.config_manager import Config
from ..core.tg_client import TgClient
from ..helper.ext_utils.bot_utils import new_task, update_user_ldata
from ..helper.ext_utils.links_utils import decode_slink
from ..helper.ext_utils.status_utils import get_readable_time
from ..helper.ext_utils.db_handler import database
from ..helper.languages import Language
from ..helper.telegram_helper.bot_commands import BotCommands
from ..helper.telegram_helper.button_build import ButtonMaker
from ..helper.telegram_helper.filters import CustomFilters
from ..helper.telegram_helper.message_utils import (
    delete_message,
    edit_message,
    edit_reply_markup,
    send_file,
    send_message,
)


@new_task
async def start(_, message):
    userid = message.from_user.id
    lang = Language()
    buttons = ButtonMaker()
    buttons.url_button(
        lang.START_BUTTON1, "https://github.com/yosefhalp/WZML-X"
    )
    buttons.url_button(lang.START_BUTTON2, "https://t.me/linksyosefbot")
    reply_markup = buttons.build_menu(2)

    if len(message.command) > 1 and message.command[1] == "wzmlx":
        await delete_message(message)
    elif len(message.command) > 1 and message.command[1] != "start":
        decrypted_url = decode_slink(message.command[1])
        if Config.MEDIA_STORE and decrypted_url.startswith("file"):
            decrypted_url = decrypted_url.replace("file", "")
            chat_id, msg_id = decrypted_url.split("&&")
            LOGGER.info(f"Copying message from {chat_id} & {msg_id} to {userid}")
            return await TgClient.bot.copy_message(  # TODO: make it function
                chat_id=userid,
                from_chat_id=int(chat_id) if match(r"\d+", chat_id) else chat_id,
                message_id=int(msg_id),
                disable_notification=True,
            )
        elif Config.VERIFY_TIMEOUT:
            input_token, pre_uid = decrypted_url.split("&&")
            if int(pre_uid) != userid:
                return await send_message(
                    message,
                    "<b>קוד הגישה הזה אינו שייך לך.</b>\n\n<i>יש ליצור קוד אישי חדש.</i>",
                )
            data = user_data.get(userid, {})
            if "VERIFY_TOKEN" not in data or data["VERIFY_TOKEN"] != input_token:
                return await send_message(
                    message,
                    "<b>קוד הגישה כבר נוצל.</b>\n\n<i>יש ליצור קוד חדש.</i>",
                )
            elif (
                Config.LOGIN_PASS
                and data["VERIFY_TOKEN"].casefold() == Config.LOGIN_PASS.casefold()
            ):
                return await send_message(
                    message,
                    "<b>כבר התחברת לבוט באמצעות סיסמה.</b>\n\n<i>אין צורך להפעיל קוד זמני.</i>",
                )
            buttons.data_button(
                "הפעלת קוד הגישה", f"start pass {input_token}", "header"
            )
            reply_markup = buttons.build_menu(2)
            msg = f"""⌬ קוד התחברות זמני:
    │
    ┟ <b>מצב</b> ← <code>נוצר בהצלחה</code>
    ┟ <b>קוד גישה</b> ← <code>{input_token}</code>
    ┃
    ┖ <b>בתוקף למשך:</b> {get_readable_time(int(Config.VERIFY_TIMEOUT))}"""
            return await send_message(message, msg, reply_markup)

    if await CustomFilters.authorized(_, message):
        from .guided_ui import show_home

        await show_home(message)
    elif Config.BOT_PM:
        await send_message(
            message,
            "<i>הבוט ישלח אליך לכאן את הקבצים והקישורים. אפשר להתחיל להשתמש בו.</i>",
            reply_markup,
            photo="IMAGES",
        )
    else:
        await send_message(
            message,
            "<i>הבוט יכול להוריד ולהעביר קישורים, קובצי Telegram, טורנטים, NZB ותוכן מ־Rclone אל אחסון בענן, Google Drive או Telegram.\n\n⚠️ אין לך הרשאה להשתמש בבוט הזה. אפשר לפרוס עותק אישי של WZML-X.</i>",
            reply_markup,
            photo="IMAGES",
        )
    await database.set_pm_users(userid)


@new_task
async def start_cb(_, query):
    user_id = query.from_user.id
    input_token = query.data.split()[2]
    data = user_data.get(user_id, {})

    if input_token == "activated":
        return await query.answer("קוד הגישה כבר הופעל.", show_alert=True)
    elif "VERIFY_TOKEN" not in data or data["VERIFY_TOKEN"] != input_token:
        return await query.answer("הקוד כבר נוצל. יש ליצור קוד חדש.", show_alert=True)

    update_user_ldata(user_id, "VERIFY_TOKEN", str(uuid4()))
    update_user_ldata(user_id, "VERIFY_TIME", time())
    if Config.DATABASE_URL:
        await database.update_user_data(user_id)
    await query.answer("קוד הגישה הופעל בהצלחה.", show_alert=True)

    kb = query.message.reply_markup.inline_keyboard[1:]
    kb.insert(
        0,
        [InlineKeyboardButton("✅ הקוד הופעל", callback_data="start pass activated")],
    )
    await edit_reply_markup(query.message, InlineKeyboardMarkup(kb))


@new_task
async def login(_, message):
    if Config.LOGIN_PASS is None:
        return await send_message(message, "<i>התחברות באמצעות סיסמה אינה מופעלת.</i>")
    elif len(message.command) > 1:
        user_id = message.from_user.id
        input_pass = message.command[1]

        if user_data.get(user_id, {}).get("VERIFY_TOKEN", "") == Config.LOGIN_PASS:
            return await send_message(
                message, "<b>כבר התחברת לבוט.</b>\n\n<i>אין צורך להתחבר שוב.</i>"
            )

        if input_pass.casefold() != Config.LOGIN_PASS.casefold():
            return await send_message(
                message, "<b>הסיסמה שגויה.</b>\n\n<i>יש לבדוק אותה ולנסות שוב.</i>"
            )

        update_user_ldata(user_id, "VERIFY_TOKEN", Config.LOGIN_PASS)
        if Config.DATABASE_URL:
            await database.update_user_data(user_id)
        return await send_message(
            message, "<b>ההתחברות הקבועה הצליחה.</b>\n\n<i>כעת אפשר להשתמש בבוט.</i>"
        )
    else:
        await send_message(
            message, "<b>כך מתחברים לבוט:</b>\n\n<code>/login [סיסמה]</code>"
        )


@new_task
async def ping(_, message):
    start_time = monotonic()
    reply = await send_message(message, "<i>בודק את זמן התגובה...</i>")
    end_time = monotonic()
    await edit_message(
        reply, f"<i>הבוט זמין.</i>\n <code>{int((end_time - start_time) * 1000)} מילישניות</code>"
    )


@new_task
async def log(_, message):
    uid = message.from_user.id
    buttons = ButtonMaker()
    buttons.data_button("הצגת הלוג", f"log {uid} disp")
    buttons.data_button("לוג בדפדפן", f"log {uid} web")
    buttons.data_button("סגירה", f"log {uid} close", style=ButtonStyle.DANGER)
    await send_file(message, "log.txt", buttons=buttons.build_menu(2))


@new_task
async def log_cb(_, query):
    data = query.data.split()
    message = query.message
    user_id = query.from_user.id
    if user_id != int(data[1]):
        await query.answer("הפעולה הזאת אינה שייכת לך.", show_alert=True)
    elif data[2] == "close":
        await query.answer()
        await delete_message(message, message.reply_to_message)
    elif data[2] == "disp":
        await query.answer("טוען את הלוג...")
        async with aiopen("log.txt", "r") as f:
            content = await f.read()

        def parse(line):
            parts = line.split("] [", 1)
            return f"[{parts[1]}" if len(parts) > 1 else line

        try:
            res, total = [], 0
            for line in reversed(content.splitlines()):
                line = parse(line)
                res.append(line)
                total += len(line) + 1
                if total > 3500:
                    break

            log_content = escape("\n".join(reversed(res)))
            text = f"<b>{len(res)} השורות האחרונות מתוך log.txt:</b> \n\n----------<b>תחילת הלוג</b>----------\n\n<blockquote expandable>{log_content}</blockquote>\n----------<b>סוף הלוג</b>----------"

            btn = ButtonMaker()
            btn.data_button("סגירה", f"log {user_id} close", style=ButtonStyle.DANGER)
            await send_message(message, text, btn.build_menu(1))
            await edit_reply_markup(message, None)
        except Exception as err:
            LOGGER.error(f"TG Log Display : {str(err)}")
    elif data[2] == "web":
        boundary = "R1eFDeaC554BUkLF"
        headers = {
            "Content-Type": f"multipart/form-data; boundary=----WebKitFormBoundary{boundary}",
            "Origin": "https://spaceb.in",
            "Referer": "https://spaceb.in/",
            "sec-ch-ua": '"Not-A.Brand";v="99", "Chromium";v="124"',
            "sec-ch-ua-mobile": "?1",
            "sec-ch-ua-platform": '"Android"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
        }

        async with aiopen("log.txt", "r") as f:
            content = await f.read()

        data = (
            f"------WebKitFormBoundary{boundary}\r\n"
            f'Content-Disposition: form-data; name="content"\r\n\r\n'
            f"{content}\r\n"
            f"------WebKitFormBoundary{boundary}--\r\n"
        )

        cget = create_scraper().request
        resp = cget("POST", "https://spaceb.in/", headers=headers, data=data)
        if resp.status_code == 200:
            await query.answer("יוצר קישור...")
            btn = ButtonMaker()
            btn.url_button("📨 פתיחת הלוג בדפדפן", resp.url, style=ButtonStyle.PRIMARY)
            await edit_reply_markup(message, btn.build_menu(1))
        else:
            await query.answer("יצירת הקישור נכשלה. יש לבדוק את הלוגים.", show_alert=True)
