"""מרכז השליטה והאשפים שמנגישים את יכולות WZML-X ללא הקלדת פקודות."""

from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

from pyrogram.enums import ButtonStyle, ChatType

from .. import DOWNLOAD_DIR, LOGGER, sabnzbd_client, task_dict, task_dict_lock, user_data
from ..core.config_manager import Config
from ..core.tg_client import TgClient
from ..core.torrent_manager import TorrentManager
from ..helper.ext_utils.residual_downloads import (
    clear_residual_downloads,
    residual_download_status,
)
from ..helper.ext_utils.status_utils import get_readable_file_size, get_readable_time
from ..helper.ext_utils.db_handler import database
from ..helper.ext_utils.telegram_delivery import normalize_telegram_channel
from ..helper.telegram_helper.button_build import ButtonMaker
from ..helper.telegram_helper.message_utils import edit_message, send_message
from ..helper.telegram_helper.rich_message import (
    edit_rich_message,
    send_rich_message,
    summary_card,
)
from .guided_ui_model import (
    ADVANCED_VALUE_OPTIONS,
    build_task_command,
    guided_text_mode,
    parse_ui_callback,
    session_defaults,
)


guided_sessions: dict[int, dict] = {}

def _session_defaults(mode: str) -> dict:
    """מחזיר מצב התחלתי מלא כדי שכל אשף יקבל אותן ברירות מחדל."""

    return session_defaults(mode)


def _home_buttons(is_admin: bool):
    buttons = ButtonMaker()
    buttons.data_button("➕ משימה חדשה", "ui new", "header", ButtonStyle.SUCCESS)
    buttons.data_button("⚡ העלאה מהירה ל־GoFile", "ui quick")
    buttons.data_button("📂 קובצי GoFile שלי", "ui gofile")
    buttons.data_button("📥 המשימות שלי", "ui tasks")
    buttons.data_button("🖥 מצב השרת", "ui server")
    buttons.data_button("🧰 כל הכלים", "ui tools")
    buttons.data_button("⚙️ ההגדרות שלי", "ui settings")
    buttons.data_button("❓ עזרה קצרה", "ui help")
    if is_admin:
        buttons.data_button("💾 גיבויים", "ui backup")
        buttons.data_button("🛠 ניהול מתקדם", "ui admin")
    return buttons.build_menu(2, h_cols=1)


async def show_home(message, *, edit=False, user=None):
    """מציג מסך בית קצר שממנו אפשר להגיע לכל יכולת מרכזית."""

    actor = user or message.from_user
    is_admin = actor.id == Config.OWNER_ID
    async with task_dict_lock:
        my_tasks = sum(
            1
            for task in task_dict.values()
            if getattr(getattr(task, "listener", None), "user_id", None) == actor.id
        )
        all_tasks = len(task_dict)
    text = (
        f"<b>👋 שלום {actor.first_name or 'לך'}, מה תרצה לעשות?</b>\n\n"
        "אין צורך לזכור פקודות. בוחרים פעולה, שולחים קישור או קובץ, "
        "ומאשרים את ברירות המחדל.\n\n"
        f"<b>המשימות שלך:</b> {my_tasks}   ·   <b>כל המשימות:</b> {all_tasks}"
    )
    buttons = _home_buttons(is_admin)
    if edit:
        return await edit_message(message, text, buttons)
    return await send_message(message, text, buttons)


def _new_task_buttons():
    buttons = ButtonMaker()
    buttons.data_button("🔗 קישור או Magnet", "ui source auto")
    buttons.data_button("🧲 טורנט", "ui source torrent")
    buttons.data_button("▶️ וידאו / מוזיקה", "ui source youtube")
    if Config.DISABLE_JD or not Config.JD_EMAIL or not Config.JD_PASS:
        buttons.data_button("🧰 JDownloader — נדרשת הגדרה", "ui engine jd")
    else:
        buttons.data_button("🧰 JDownloader", "ui source jdownloader")
    buttons.data_button("📰 NZB / Usenet", "ui source usenet")
    buttons.data_button("☁️ העתקה מ־Drive", "ui source clone")
    buttons.data_button("📤 העלאה ל־GoFile", "ui source gofile")
    buttons.data_button("📎 קובץ מ־Telegram", "ui source file")
    buttons.data_button("🏠 תפריט ראשי", "ui home", "footer")
    return buttons.build_menu(2)


def _destination_buttons(mode: str):
    buttons = ButtonMaker()
    if mode in {"jdownloader", "usenet"}:
        buttons.data_button("⭐ העלאה ל־GoFile", "ui dest gofile", "header")
        buttons.data_button("☁️ העלאה לענן", "ui dest cloud")
        buttons.data_button("✈️ שליחה ל־Telegram", "ui dest telegram")
    elif mode == "youtube":
        buttons.data_button("☁️ העלאה לענן", "ui dest cloud")
        buttons.data_button("✈️ שליחה ל־Telegram", "ui dest telegram")
    elif mode == "clone":
        buttons.data_button("▶️ העתקה ל־Drive", "ui dest clone", "header")
    elif mode == "gofile":
        buttons.data_button("▶️ העלאה ל־GoFile", "ui dest gofile", "header")
    else:
        buttons.data_button("⭐ ברירת מחדל: GoFile", "ui dest gofile", "header")
        buttons.data_button("☁️ העלאה לענן", "ui dest cloud")
        buttons.data_button("✈️ שליחה ל־Telegram", "ui dest telegram")
    buttons.data_button("❌ ביטול", "ui cancel", "footer", ButtonStyle.DANGER)
    return buttons.build_menu(2, h_cols=1)


def _telegram_source_buttons():
    """דורש בחירה מפורשת של החשבון שמבצע את ההעלאה."""

    buttons = ButtonMaker()
    buttons.data_button("🤖 Bot — עד 2GB לחלק", "ui tgsource bot")
    buttons.data_button("⭐ Userbot Premium — עד 3.9GB", "ui tgsource user")
    buttons.data_button("⬅️ שינוי יעד", "ui destinations", "footer")
    buttons.data_button("❌ ביטול", "ui cancel", "footer", ButtonStyle.DANGER)
    return buttons.build_menu(1)


def _telegram_target_buttons(user_id: int):
    """מציג יעד פרטי, חיבור ערוץ ורשימת ערוצים שמורים של המשתמש."""

    buttons = ButtonMaker()
    buttons.data_button("💬 פרטי — הצ׳אט עם הבוט", "ui tgtarget private", "header")
    buttons.data_button("➕ חיבור ערוץ חדש", "ui tgtarget connect")
    channels = user_data.get(user_id, {}).get("TELEGRAM_UPLOAD_CHANNELS", [])
    for index, channel in enumerate(channels[:8]):
        label = str(channel.get("title") or channel.get("target") or "ערוץ")[:42]
        buttons.data_button(f"📣 {label}", f"ui tgchannel {index}")
    buttons.data_button("⬅️ בחירת מקור", "ui dest telegram", "footer")
    buttons.data_button("❌ ביטול", "ui cancel", "footer", ButtonStyle.DANGER)
    return buttons.build_menu(1)


async def _connect_upload_channel(raw_target: str, source: str) -> dict:
    """מוודא שלחשבון שנבחר יש הרשאת פרסום לפני שמירת הערוץ."""

    target = normalize_telegram_channel(raw_target)
    selected_client = TgClient.user if source == "user" else TgClient.bot
    if selected_client is None:
        raise ValueError("מקור ההעלאה שנבחר אינו מחובר כרגע")
    try:
        chat = await selected_client.get_chat(target)
    except Exception as error:
        raise ValueError("הערוץ לא נמצא אצל מקור ההעלאה שנבחר") from error
    if chat.type not in {ChatType.CHANNEL, ChatType.SUPERGROUP}:
        raise ValueError("היעד שנשלח אינו ערוץ או קבוצת־על")
    try:
        member = await chat.get_member(selected_client.me.id)
    except Exception as error:
        raise ValueError("לא ניתן לבדוק את הרשאות ההעלאה בערוץ") from error
    privileges = getattr(member, "privileges", None)
    can_post = bool(
        getattr(privileges, "can_post_messages", False)
        or getattr(privileges, "can_manage_chat", False)
        or str(getattr(member, "status", "")).casefold().endswith("owner")
    )
    if not can_post:
        raise ValueError("למקור ההעלאה שנבחר אין הרשאת פרסום בערוץ")
    canonical = f"@{chat.username}" if getattr(chat, "username", None) else str(chat.id)
    return {"target": canonical, "title": str(chat.title or canonical)[:80]}


def _options_buttons(session: dict):
    buttons = ButtonMaker()
    buttons.data_button("▶️ הפעלה עכשיו", "ui run", "header", ButtonStyle.SUCCESS)
    if session["mode"] in {"auto", "torrent", "file", "jdownloader", "usenet"}:
        buttons.data_button(
            f"{'✅' if session['select'] else '⬜'} בחירת קבצים",
            "ui option select",
        )
        buttons.data_button(
            f"{'✅' if session['extract'] else '⬜'} חילוץ ארכיון",
            "ui option extract",
        )
        buttons.data_button(
            f"{'✅' if session['compress'] else '⬜'} דחיסה ל־ZIP",
            "ui option compress",
        )
        buttons.data_button(
            f"{'✅' if session['join'] else '⬜'} איחוד חלקים",
            "ui option join",
        )
        buttons.data_button(
            f"{'✅' if session['sample'] else '⬜'} סרטון דוגמה",
            "ui option sample",
        )
        buttons.data_button(
            f"{'✅' if session['screenshots'] else '⬜'} צילומי מסך",
            "ui option screenshots",
        )
        if session["mode"] == "torrent":
            buttons.data_button(
                f"{'✅' if session['seed'] else '⬜'} המשך שיתוף",
                "ui option seed",
            )
    buttons.data_button("🧰 אפשרויות מתקדמות", "ui advanced", "l_body")
    buttons.data_button("⬅️ שינוי יעד", "ui destinations", "footer")
    buttons.data_button("❌ ביטול", "ui cancel", "footer", ButtonStyle.DANGER)
    return buttons.build_menu(2, h_cols=1)


def _advanced_options_buttons(session: dict):
    """מציג את כל דגלי המשימה בלי להעמיס אותם על מסך ברירת המחדל."""

    buttons = ButtonMaker()
    toggle_options = [
        ("as_document", "שליחה כקובץ"),
        ("as_media", "שליחה כמדיה"),
        ("force", "אילוץ מלא"),
        ("force_download", "אילוץ הורדה"),
        ("force_upload", "אילוץ העלאה"),
        ("hybrid", "מצב משולב"),
    ]
    for key, label in toggle_options:
        buttons.data_button(
            f"{'✅' if session.get(key) else '⬜'} {label}",
            f"ui advancedtoggle {key}",
        )
    for key, (label, _, _) in ADVANCED_VALUE_OPTIONS.items():
        if key == "yt_options" and session["mode"] != "youtube":
            continue
        if key == "seed_value" and session["mode"] != "torrent":
            continue
        value = str(session.get(key) or "")
        buttons.data_button(
            f"{'✅' if value else '✏️'} {label}",
            f"ui value {key}",
        )
        if value:
            buttons.data_button("🧹 ניקוי", f"ui valueclear {key}")
    buttons.data_button("⬅️ חזרה לסיכום", "ui options", "footer")
    buttons.data_button("❌ ביטול", "ui cancel", "footer", ButtonStyle.DANGER)
    return buttons.build_menu(2)


def _option_summary(session: dict) -> str:
    destinations = {
        "gofile": "GoFile כאורח",
        "cloud": "יעד הענן המוגדר",
        "telegram": "Telegram",
        "clone": "Google Drive",
    }
    enabled = []
    if session.get("select"):
        enabled.append("בחירת קבצים")
    if session.get("extract"):
        enabled.append("חילוץ")
    if session.get("compress"):
        enabled.append("דחיסה")
    if session.get("join"):
        enabled.append("איחוד חלקים")
    if session.get("sample"):
        enabled.append("סרטון דוגמה")
    if session.get("screenshots"):
        enabled.append("צילומי מסך")
    if session.get("seed"):
        enabled.append("המשך שיתוף")
    advanced_count = sum(
        bool(session.get(key))
        for key in (
            "as_document",
            "as_media",
            "force",
            "force_download",
            "force_upload",
            "hybrid",
            "bot_transfer",
            "user_transfer",
            *ADVANCED_VALUE_OPTIONS,
        )
    )
    if advanced_count:
        enabled.append(f"{advanced_count} הגדרות מתקדמות")
    telegram_route = ""
    if session["destination"] == "telegram":
        source = "Userbot Premium" if session.get("upload_source") == "user" else "Bot"
        if session.get("upload_target") == "channel":
            target = f"ערוץ <code>{escape(str(session.get('upload_channel') or ''))}</code>"
        else:
            target = "הצ׳אט הפרטי עם הבוט"
        telegram_route = f"<b>מקור העלאה:</b> {source}\n<b>יעד Telegram:</b> {target}\n"
    return (
        "<b>הכול מוכן להפעלה</b>\n\n"
        f"<b>יעד:</b> {destinations.get(session['destination'], session['destination'])}\n"
        f"{telegram_route}"
        f"<b>אפשרויות:</b> {', '.join(enabled) if enabled else 'ברירות מחדל מומלצות'}\n\n"
        "אפשר להפעיל מיד או לשנות אפשרות בלחיצה."
    )


async def guided_input(client, message):
    """קולט את הקישור או הקובץ רק כאשר המשתמש נמצא בתוך אשף פעיל."""

    user_id = message.from_user.id
    session = guided_sessions.get(user_id)
    if not session:
        return
    if session.get("stage") == "admin_input":
        return await _dispatch_admin_input(client, message, session)
    if session.get("stage") == "telegram_channel_input":
        value = (message.text or message.caption or "").strip()
        try:
            channel = await _connect_upload_channel(
                value, session.get("upload_source", "")
            )
        except ValueError as error:
            return await send_message(message, f"<b>לא ניתן לחבר את הערוץ.</b>\n{escape(str(error))}")
        channels = user_data.setdefault(user_id, {}).setdefault(
            "TELEGRAM_UPLOAD_CHANNELS", []
        )
        channels[:] = [row for row in channels if row.get("target") != channel["target"]]
        channels.insert(0, channel)
        del channels[8:]
        await database.update_user_data(user_id)
        session["upload_target"] = "channel"
        session["upload_channel"] = channel["target"]
        session["stage"] = "options"
        ui_message = await client.get_messages(message.chat.id, session["ui_message_id"])
        return await edit_message(
            ui_message,
            _option_summary(session),
            _options_buttons(session),
        )
    if session.get("stage") == "option_input":
        value = (message.text or message.caption or "").strip()
        if not value:
            return await send_message(message, "<b>יש לשלוח ערך טקסטואלי תקין.</b>")
        key = session["pending_value"]
        if key == "multi" and (not value.isdigit() or int(value) < 1):
            return await send_message(message, "<b>מספר הקישורים חייב להיות מספר חיובי.</b>")
        session[key] = "" if key == "bulk" and value.casefold() == "all" else value
        if key == "bulk" and value.casefold() == "all":
            session[key] = True
        session["stage"] = "options"
        session.pop("pending_value", None)
        ui_message = await client.get_messages(message.chat.id, session["ui_message_id"])
        return await edit_message(
            ui_message,
            "<b>הערך נשמר.</b> אפשר להגדיר אפשרות נוספת או לחזור להפעלה.",
            _advanced_options_buttons(session),
        )
    if session.get("stage") != "input":
        return
    has_media = any(
        getattr(message, field, None)
        for field in ("document", "video", "audio", "photo", "voice", "animation")
    )
    input_text = (message.text or message.caption or "").strip()
    if not input_text and not has_media:
        return await send_message(
            message,
            "<b>לא זיהיתי קישור או קובץ.</b>\nשלחו קישור, Magnet, טורנט או קובץ.",
        )
    text_mode = guided_text_mode(input_text, has_media=has_media)
    if text_mode["too_many"]:
        return await send_message(
            message,
            "<b>אפשר לשלוח עד 50 קישורים במשימה אחת.</b>\n"
            f"בהודעה התקבלו <code>{text_mode['link_count']}</code> קישורים. "
            "פצלו אותם לשתי משימות ושלחו שוב.",
        )
    session.update(
        {
            "stage": "destination",
            "input_message_id": message.id,
            "input_preview": text_mode["preview"],
            "has_media": has_media,
        }
    )
    if text_mode["is_bulk"]:
        session["bulk"] = True
    if session.get("gofile_target_id"):
        session["destination"] = "gofile"
        session["stage"] = "options"
        return await send_message(
            message,
            "<b>הקלט התקבל.</b>\n\nהתוצאה תתווסף לתיקיית GoFile שבחרת.",
            _options_buttons(session),
        )
    await send_message(
        message,
        "<b>הקלט התקבל.</b>\n\nלאן להעביר את התוצאה?",
        _destination_buttons(session["mode"]),
    )


async def _dispatch_session(client, query, session: dict):
    """מתרגם את בחירות הכפתורים לפקודה פנימית ומעביר אותה למנוע הקיים."""

    from .clone import clone_node
    from .mirror_leech import (
        jd_leech,
        jd_mirror,
        jd_uphoster,
        leech,
        mirror,
        nzb_leech,
        nzb_mirror,
        nzb_uphoster,
        qb_leech,
        qb_mirror,
        qb_uphoster,
        uphoster,
    )
    from .ytdlp import ytdl, ytdl_leech

    source_message = await client.get_messages(
        query.message.chat.id, session["input_message_id"]
    )
    input_text = (
        ""
        if session.get("has_media")
        else (source_message.text or source_message.caption or "").strip()
    )
    text_mode = guided_text_mode(input_text, has_media=session.get("has_media", False))
    command_text, handler_name = build_task_command(session, text_mode["command_input"])
    handlers = {
        "clone_node": clone_node,
        "jd_leech": jd_leech,
        "jd_mirror": jd_mirror,
        "jd_uphoster": jd_uphoster,
        "leech": leech,
        "mirror": mirror,
        "nzb_leech": nzb_leech,
        "nzb_mirror": nzb_mirror,
        "nzb_uphoster": nzb_uphoster,
        "qb_leech": qb_leech,
        "qb_mirror": qb_mirror,
        "qb_uphoster": qb_uphoster,
        "uphoster": uphoster,
        "ytdl": ytdl,
        "ytdl_leech": ytdl_leech,
    }
    handler = handlers[handler_name]
    command_message = await send_message(source_message, command_text)
    command_message = await client.get_messages(
        chat_id=source_message.chat.id, message_ids=command_message.id
    )
    command_message.from_user = query.from_user
    if session.get("gofile_target_id"):
        # רק המזהה הפנימי עובר למשימה. ה-uploader טוען את הטוקן מ-MongoDB
        # מחדש אחרי בדיקת בעלות, ולכן הסוד אינו מופיע בטקסט הפקודה.
        command_message._gofile_target_id = session["gofile_target_id"]
    if text_mode["reply_required"] or not input_text:
        command_message.reply_to_message = source_message
    await query.answer("המשימה הופעלה.")
    await edit_message(
        query.message,
        "<b>✅ המשימה הופעלה</b>\n\nההתקדמות תופיע במסך המשימות.",
        _after_start_buttons(),
    )
    await handler(client, command_message)


def _after_start_buttons():
    buttons = ButtonMaker()
    buttons.data_button("📥 המשימות שלי", "ui tasks")
    buttons.data_button("📂 קובצי GoFile שלי", "ui gofile")
    buttons.data_button("➕ משימה נוספת", "ui new")
    buttons.data_button("🏠 תפריט ראשי", "ui home", "footer")
    return buttons.build_menu(2)


def _gofile_date(value):
    """מציג תאריך קצר בלי להניח איזה טיפוס החזיר נהג MongoDB."""

    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y %H:%M")
    return str(value or "—")[:16].replace("T", " ")


async def _gofile_overview(user_id, offset=0):
    """בונה רשימת העלאות שאינה כוללת טוקנים או מזהי מחיקה פנימיים."""

    from ..helper.ext_utils.gofile_store import live_gofile_store

    page_size = 5
    offset = max(int(offset or 0), 0)
    records = await live_gofile_store().list_for_user(
        user_id,
        limit=page_size + 1,
        offset=offset,
    )
    has_more = len(records) > page_size
    records = records[:page_size]
    lines = ["\u200f<b>📂 קובצי GoFile שלי</b>"]
    buttons = ButtonMaker()
    if not records:
        lines.append("\nעדיין אין העלאות שמורות בחשבון שלך.")
    for index, record in enumerate(records, start=offset + 1):
        record_id = record["_id"]
        name = escape(str(record.get("name") or "קובץ ללא שם"))
        if len(name) > 42:
            name = f"{name[:20]}…{name[-18:]}"
        status = "נמחק" if record.get("status") == "deleted" else "פעיל"
        lines.append(
            f"\n<b>{index}. {name}</b>\n"
            f"מצב: {status} · גודל: <code>\u2066{get_readable_file_size(record.get('size') or 0)}\u2069</code>\n"
            f"נוצר: <code>\u2066{_gofile_date(record.get('created_at'))}\u2069</code>"
        )
        if status == "פעיל":
            buttons.url_button(f"#{index} פתיחה", record["link"])
            buttons.data_button("➕ הוספה", f"ui gofile add {record_id}")
            buttons.data_button("🗑 מחיקה", f"ui gofile deleteconfirm {record_id}")
    if offset:
        buttons.data_button("⬅️ חדשים יותר", f"ui gofile page {max(0, offset - page_size)}", "l_body")
    if has_more:
        buttons.data_button("ישנים יותר ➡️", f"ui gofile page {offset + page_size}", "l_body")
    buttons.data_button("🔄 רענון", "ui gofile refresh", "footer")
    buttons.data_button("🏠 תפריט ראשי", "ui home", "footer")
    return "\n".join(lines), buttons.build_menu(3, lb_cols=2, f_cols=2)


def _tools_buttons():
    buttons = ButtonMaker()
    buttons.data_button("🔎 חיפוש טורנטים", "ui tool search")
    buttons.data_button("📰 חיפוש Usenet", "ui tool nzbsearch")
    buttons.data_button("🎬 מידע על סרט", "ui tool imdb")
    buttons.data_button("ℹ️ מידע על קובץ", "ui tool mediainfo")
    buttons.data_button("🖼 גלריית תמונות", "ui tool images")
    buttons.data_button("🔍 חיפוש ב־Drive", "ui tool gdsearch")
    buttons.data_button("📊 ספירה ב־Drive", "ui tool gdcount")
    buttons.data_button("🧹 ניקוי Drive", "ui tool gdclean")
    buttons.data_button("🗑 מחיקה מ־Drive", "ui tool gddelete")
    buttons.data_button("📡 מקורות RSS", "ui tool rss")
    buttons.data_button("🎯 בחירת קבצים במשימה", "ui tool select")
    buttons.data_button("🚦 אילוץ התחלת משימה", "ui tool force")
    buttons.data_button("📂 שינוי קטגוריה", "ui tool category")
    buttons.data_button("❌ ביטול משימות", "ui tool cancelall")
    buttons.data_button("📖 כל הפקודות", "ui tool commands")
    buttons.data_button("🏠 תפריט ראשי", "ui home", "footer")
    return buttons.build_menu(2)


def _admin_buttons():
    buttons = ButtonMaker()
    buttons.data_button("⚙️ הגדרות הבוט", "ui admin botsettings")
    buttons.data_button("👥 משתמשים והרשאות", "ui admin access")
    buttons.data_button("📣 הפצת הודעה", "ui admin input broadcast")
    buttons.data_button("🧩 ניהול תוספים", "ui admin plugins")
    buttons.data_button("🔑 יצירת Session", "ui admin sessions")
    buttons.data_button("♻️ רענון Sessions", "ui admin restartsessions")
    buttons.data_button("🖼 הוספת תמונה", "ui admin input addimage")
    buttons.data_button("⌨️ מסוף הבעלים", "ui admin terminal")
    buttons.data_button("📄 לוגים", "ui admin logs")
    buttons.data_button("🧹 ניקוי מטמון", "ui cache")
    buttons.data_button("💾 גיבויים", "ui backup")
    buttons.data_button("🔄 הפעלה מחדש", "ui admin restart")
    buttons.data_button("🏠 תפריט ראשי", "ui home", "footer")
    return buttons.build_menu(2)


def _access_buttons():
    buttons = ButtonMaker()
    buttons.data_button("✅ מתן הרשאה", "ui admin input authorize")
    buttons.data_button("🚫 הסרת הרשאה", "ui admin input unauthorize")
    buttons.data_button("⭐ הוספת מנהל", "ui admin input addsudo")
    buttons.data_button("➖ הסרת מנהל", "ui admin input rmsudo")
    buttons.data_button("⛔ חסימת משתמש", "ui admin input blacklist")
    buttons.data_button("🔓 ביטול חסימה", "ui admin input rmblacklist")
    buttons.data_button("📋 רשימת משתמשים", "ui admin users")
    buttons.data_button("⬅️ חזרה לניהול", "ui admin", "footer")
    return buttons.build_menu(2)


def _terminal_buttons():
    buttons = ButtonMaker()
    buttons.data_button("🖥 פקודת Shell", "ui admin input shell")
    buttons.data_button("🐍 קוד Python אסינכרוני", "ui admin input aexec")
    buttons.data_button("🐍 קוד Python רגיל", "ui admin input exec")
    buttons.data_button("🧹 ניקוי משתנים זמניים", "ui admin clear")
    buttons.data_button("⬅️ חזרה לניהול", "ui admin", "footer")
    return buttons.build_menu(2)


ADMIN_INPUTS = {
    "authorize": ("/authorize", "שלחו מזהה משתמש או צ׳אט."),
    "unauthorize": ("/unauthorize", "שלחו מזהה משתמש או צ׳אט."),
    "addsudo": ("/addsudo", "שלחו את מזהה המשתמש שיהפוך למנהל."),
    "rmsudo": ("/rmsudo", "שלחו את מזהה המנהל להסרה."),
    "blacklist": ("/blacklist", "שלחו מזהה משתמש. אפשר לצרף זמן, למשל: 123456 -t 2h"),
    "rmblacklist": ("/rmblacklist", "שלחו את מזהה המשתמש לשחרור."),
    "broadcast": ("/broadcast", "שלחו או העבירו את ההודעה שברצונכם להפיץ."),
    "addimage": ("/addimage", "שלחו תמונה או השיבו לתמונה שברצונכם להוסיף."),
    "shell": ("/shell", "שלחו את פקודת המערכת להרצה."),
    "aexec": ("/aexec", "שלחו קוד Python אסינכרוני להרצה."),
    "exec": ("/exec", "שלחו קוד Python רגיל להרצה."),
}


async def _dispatch_admin_input(client, message, session: dict):
    """מעביר קלט ממסך ניהול לפונקציה הוותיקה המתאימה, עם הרשאת הבעלים בלבד."""

    from .broadcast import broadcast
    from .chat_permission import (
        add_blacklist,
        add_sudo,
        authorize,
        remove_blacklist,
        remove_sudo,
        unauthorize,
    )
    from .exec import aioexecute, execute
    from .images import picture_add
    from .shell import run_shell

    if message.from_user.id != Config.OWNER_ID:
        guided_sessions.pop(message.from_user.id, None)
        return
    key = session["admin_action"]
    command, _ = ADMIN_INPUTS[key]
    reply_only = key in {"broadcast", "addimage"}
    input_text = (message.text or message.caption or "").strip()
    command_text = command if reply_only else " ".join(filter(None, [command, input_text]))
    command_message = await send_message(message, command_text)
    command_message = await client.get_messages(message.chat.id, command_message.id)
    command_message.from_user = message.from_user
    if reply_only:
        command_message.reply_to_message = message
    handlers = {
        "authorize": authorize,
        "unauthorize": unauthorize,
        "addsudo": add_sudo,
        "rmsudo": remove_sudo,
        "blacklist": add_blacklist,
        "rmblacklist": remove_blacklist,
        "broadcast": broadcast,
        "addimage": picture_add,
        "shell": run_shell,
        "aexec": aioexecute,
        "exec": execute,
    }
    guided_sessions.pop(message.from_user.id, None)
    await handlers[key](client, command_message)


def _backup_date(value: str) -> str:
    """מציג זמן גיבוי לפי שעון ישראל ושומר את המספרים בכיוון LTR."""

    if not value:
        return "אין נתון"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        local = parsed.astimezone(ZoneInfo("Asia/Jerusalem"))
        return f"<code>\u2066{local:%d/%m/%Y %H:%M}\u2069</code>"
    except (TypeError, ValueError):
        return f"<code>\u2066{escape(str(value)[:32])}\u2069</code>"


def backup_home() -> tuple[str, object]:
    """מפריד בין ערכת ניוד ידנית לגיבוי יומי, כפי שנעשה בבוט GoFile."""

    buttons = ButtonMaker()
    buttons.data_button("📦 ערכת ניוד בלחיצה אחת", "ui backup handoff", "header")
    buttons.data_button("🛡 גיבוי יומי", "ui backup daily")
    buttons.data_button("🏠 תפריט ראשי", "ui home", "footer")
    return summary_card(
        "גיבויים והתאוששות",
        [
            ("ערכת ניוד", "בחירה בין חבילה מלאה עם Images לחבילה מהירה ללא Images"),
            ("גיבוי יומי", "חבילה מלאה אוטומטית בשעה קבועה עם מסירה לטלגרם"),
            ("שערי הצלחה", "אריזה, checksum, תרגיל שחזור ואישור מסירה"),
        ],
        footer="שתי הזרימות משתמשות באותו Worker ובאותם כלי שחזור; אין מנגנון כפול.",
    ), buttons.build_menu(1)


def backup_overview(user_id: int, *, daily: bool) -> tuple[str, object]:
    """מציג את ערכת הניוד או את הגיבוי היומי בלי לערבב ביניהם."""

    from ..helper.ext_utils.backup_control import (
        ensure_backup_settings,
        read_backup_status,
    )

    status = read_backup_status()
    settings = ensure_backup_settings(user_id)
    state_labels = {
        "idle": "ממתין",
        "queued": "ממתין ל־worker",
        "running": "יוצר ארכיון",
        "verifying": "מאמת ומשחזר לבדיקה",
        "sending": "שולח לטלגרם",
        "success": "הושלם ונמסר",
        "failed": "נכשל",
    }
    worker_labels = {
        "ready": "פעיל ומוכן",
        "working": "פעיל ועובד",
        "error": "פעיל עם תקלה",
        "unknown": "טרם זוהה",
    }
    schedule = (
        f"פעיל — כל יום בשעה <code>\u2066{settings.daily_hour:02d}:{settings.daily_minute:02d}\u2069</code>"
        if settings.daily_enabled
        else "מושהה"
    )
    rows = [
        ("Host Worker", worker_labels.get(status.worker_state, "טרם זוהה")),
        ("מצב", state_labels.get(status.state, "טרם התקבל מידע")),
        ("שלב נוכחי", status.stage or "ממתין לבקשה"),
        ("סיום אחרון", _backup_date(status.finished_at)),
        (
            "גודל",
            f"<code>\u2066{get_readable_file_size(status.size_bytes)}\u2069</code>"
            if status.size_bytes
            else "אין נתון",
        ),
        ("בדיקת שלמות", "עברה" if status.integrity_verified else "טרם עברה"),
        ("תרגיל שחזור", "עבר" if status.restore_verified else "טרם עבר"),
        ("מסירה לטלגרם", "אושרה" if status.delivered else "טרם אושרה"),
        (
            "סוג הערכה האחרונה",
            "מלאה עם שלוש Images" if status.mode == "full" else "מהירה ללא Images" if status.mode == "state" else "אין נתון",
        ),
        ("כולל", "קוד, סודות, Sessions, MongoDB וזהות Local Bot API"),
        ("שימור", "שני גיבויים מנוהלים; גיבויים ישנים לא נמחקים"),
    ]
    if daily:
        rows.append(("תזמון יומי", schedule))
    if status.archive_name:
        rows.append(
            ("שם ארכיון", f"<code>\u2066{escape(status.archive_name)}\u2069</code>")
        )
    if status.error:
        rows.append(("תקלה אחרונה", escape(status.error)))
    buttons = ButtonMaker()
    busy = status.state in {"queued", "running", "verifying", "sending"}
    if daily:
        if not busy:
            buttons.data_button("📦 צור גיבוי מלא עכשיו", "ui backup dailyrun", "header")
        buttons.data_button("− שעה", "ui backup timem60")
        buttons.data_button("+ שעה", "ui backup timep60")
        buttons.data_button("− 15 דקות", "ui backup timem15")
        buttons.data_button("+ 15 דקות", "ui backup timep15")
        buttons.data_button(
            "⏸ השהיית גיבוי יומי" if settings.daily_enabled else "▶️ הפעלת גיבוי יומי",
            "ui backup dailyoff" if settings.daily_enabled else "ui backup dailyon",
        )
        buttons.data_button("🔄 רענון מצב", "ui backup daily")
    else:
        if not busy:
            buttons.data_button("🚀 מלאה כולל Images", "ui backup full", "header")
            buttons.data_button("⚡ מהירה ללא Images", "ui backup state", "header")
        buttons.data_button("🔄 רענון מצב", "ui backup handoff")
    buttons.data_button("🧪 מידע על שחזור", "ui backup restore")
    buttons.data_button("⬅️ חזרה לגיבויים", "ui backup", "footer")
    return summary_card(
        "גיבוי יומי" if daily else "ערכת ניוד בלחיצה אחת",
        rows,
        footer=(
            "הגיבוי היומי תמיד מלא. מדריך הפריסה נפתח מהכפתור המצורף לקובץ."
            if daily
            else "הערכה המלאה ניידת לשרת ריק; המהירה מיועדת לשרת שכבר מחזיק את התמונות."
        ),
    ), buttons.build_menu(2, h_cols=1)


def backup_deployment_guide(job_id: str) -> str:
    """מציג מדריך פריסה ללא סודות עבור הקובץ שכבר נמסר לטלגרם."""

    return (
        "<h1>✅ מדריך פריסת WZML-X</h1>"
        f"<p>מזהה עבודה: <code>\u2066{escape(job_id)}\u2069</code></p>"
        "<details open><summary>🚀 שרת Linux חדש</summary>"
        "<pre><code class=\"language-bash\">mkdir -p ~/wzmlx-package\n"
        "tar -xf wzmlx-*.tar -C ~/wzmlx-package\n"
        "cd ~/wzmlx-package/wzmlx-*\n"
        "CONFIRM_RESTORE=YES ./restore.sh . ~/wzmlx-restored\n"
        "cd ~/wzmlx-restored\n"
        "docker compose -f docker-compose.server.yml ps</code></pre>"
        "</details><details><summary>🧪 מה נבדק לפני המסירה?</summary><ul>"
        "<li>checksum ומבנה החבילה</li><li>שחזור MongoDB למסד מבודד</li>"
        "<li>זיהוי Local Bot API</li><li>אישור מסירת הקובץ מטלגרם</li>"
        "</ul></details>"
    )


async def _residual_download_snapshot() -> dict[str, int | bool]:
    """בודק את הבוט ואת שלושת מנועי ההורדה לפני שמאפשר מחיקת שאריות."""

    async with task_dict_lock:
        active_ids = {str(mid) for mid in task_dict}
    if TorrentManager.qbittorrent is not None:
        try:
            if await TorrentManager.qbittorrent.torrents.info():
                active_ids.add("qbittorrent-active")
        except Exception as error:
            LOGGER.warning("לא ניתן לבדוק פעילות qBittorrent לפני ניקוי: %s", error)
            active_ids.add("qbittorrent-check-failed")
    if TorrentManager.aria2 is not None:
        try:
            if (await TorrentManager.aria2.tellActive()) or (
                await TorrentManager.aria2.tellWaiting(0, 100)
            ):
                active_ids.add("aria2-active")
        except Exception as error:
            LOGGER.warning("לא ניתן לבדוק פעילות Aria2 לפני ניקוי: %s", error)
            active_ids.add("aria2-check-failed")
    if getattr(sabnzbd_client, "LOGGED_IN", False):
        try:
            queue = (await sabnzbd_client.get_downloads()).get("queue", {})
            if queue.get("slots"):
                active_ids.add("sabnzbd-active")
        except Exception as error:
            LOGGER.warning("לא ניתן לבדוק פעילות SABnzbd לפני ניקוי: %s", error)
            active_ids.add("sabnzbd-check-failed")
    return residual_download_status(Path(DOWNLOAD_DIR), active_task_ids=active_ids)


def cache_overview(residuals: dict[str, int | bool] | None = None) -> tuple[str, object]:
    """מציג מה תופס נפח ומה מוגן לפני שהמשתמש מאשר ניקוי."""

    from ..helper.ext_utils.cache_control import read_cache_status

    status = read_cache_status()
    residuals = residuals or residual_download_status(Path(DOWNLOAD_DIR))
    state_labels = {
        "idle": "טרם נסרק",
        "queued": "ממתין ל־worker",
        "running": "סורק כעת",
        "success": "הנתונים מעודכנים",
        "failed": "הסריקה נכשלה",
    }
    rows = [
        ("מצב", state_labels.get(status.state, "לא ידוע")),
        ("שלב", status.stage or "ממתין לסריקה"),
        ("סריקה אחרונה", _backup_date(status.scanned_at)),
        (
            "מטמון Python",
            f"<code>\u2066{status.python_files}\u2069</code> קבצים · "
            f"<code>\u2066{get_readable_file_size(status.python_bytes)}\u2069</code>",
        ),
        (
            "Docker Build Cache",
            f"<code>\u2066{status.docker_build_count}\u2069</code> פריטים · "
            f"<code>\u2066{get_readable_file_size(status.docker_build_bytes)}\u2069</code>",
        ),
        (
            "ניתן לפינוי ב־Docker",
            f"<code>\u2066{get_readable_file_size(status.docker_reclaimable_bytes)}\u2069</code>",
        ),
        (
            "מדיה ב־Local Bot API",
            f"<code>\u2066{status.bot_api_files}\u2069</code> קבצים · "
            f"<code>\u2066{get_readable_file_size(status.bot_api_bytes)}\u2069</code>",
        ),
        (
            "קובצי Bot API גדולים",
            f"<code>\u2066{status.bot_api_large_files}\u2069</code> · "
            f"<code>\u2066{get_readable_file_size(status.bot_api_large_bytes)}\u2069</code>",
        ),
        (
            "קובצי Bot API ישנים משבוע",
            f"<code>\u2066{status.bot_api_old_files}\u2069</code> · "
            f"<code>\u2066{get_readable_file_size(status.bot_api_old_bytes)}\u2069</code>",
        ),
        (
            "קובצי מצב מוגנים של Bot API",
            f"<code>\u2066{status.bot_api_protected_files}\u2069</code> · "
            f"<code>\u2066{get_readable_file_size(status.bot_api_protected_bytes)}\u2069</code>",
        ),
        (
            "שאריות ממשימות תקועות",
            f"<code>\u2066{residuals['entries']}\u2069</code> פריטים · "
            f"<code>\u2066{residuals['files']}\u2069</code> קבצים · "
            f"<code>\u2066{get_readable_file_size(residuals['bytes'])}\u2069</code>",
        ),
        (
            "הגנת משימות פעילות",
            "אין משימה פעילה; ניתן לנקות שאריות."
            if residuals["cleanup_allowed"]
            else "הניקוי חסום כשמנוע הורדה או משימת בוט פעילים.",
        ),
        ("מוגן תמיד", "הורדות פעילות, accounts, Sessions, סודות, MongoDB ו־volumes"),
        ("Bot API משותף", "מוצג למדידה בלבד ואינו נמחק מכפתור הניקוי הבטוח"),
    ]
    if status.last_cleaned_at:
        rows.extend(
            [
                ("ניקוי אחרון", _backup_date(status.last_cleaned_at)),
                (
                    "תוצאת הניקוי",
                    f"<code>\u2066{status.removed_files}\u2069</code> קובצי Python · "
                    f"<code>\u2066{get_readable_file_size(status.removed_bytes)}\u2069</code> שוחררו",
                ),
            ]
        )
    if status.error:
        rows.append(("תקלה אחרונה", escape(status.error)))
    buttons = ButtonMaker()
    if status.state not in {"queued", "running"}:
        buttons.data_button("🔍 סריקה מחדש", "ui cache refresh")
        buttons.data_button(
            "🧹 ניקוי בטוח",
            "ui cache run",
            "header",
            ButtonStyle.DANGER,
        )
        if residuals["cleanup_allowed"]:
            buttons.data_button(
                "🗑 ניקוי שאריות תקועות",
                "ui cache leftovers_confirm",
                "header",
                ButtonStyle.DANGER,
            )
    buttons.data_button("⬅️ חזרה לניהול", "ui admin", "footer")
    return summary_card(
        "מפת המטמון של השרת",
        rows,
        footer=(
            "ניקוי בטוח מסיר מטמון Python ו-Build Cache ישן. ניקוי השאריות "
            "הנפרד מסיר רק את תוכן תיקיית ההורדות, ורק כשכל המנועים פנויים."
        ),
    ), buttons.build_menu(2, h_cols=1)


async def _invoke_tool(client, query, tool: str):
    """פותח מסכים ותיקים מתוך הקטלוג החדש בלי לשכפל את הלוגיקה שלהם."""

    from .cancel_task import cancel_all_buttons
    from .category_select import change_category
    from .file_selector import select
    from .force_start import remove_from_queue
    from .gd_clean import drive_clean
    from .gd_count import count_node
    from .gd_delete import delete_file
    from .gd_search import gdrive_search
    from .images import pictures
    from .imdb import imdb_search
    from .mediainfo import mediainfo
    from .nzb_search import hydra_search
    from .rss import get_rss_menu
    from .search import torrent_search

    tools = {
        "search": (torrent_search, "/search"),
        "nzbsearch": (hydra_search, "/nzbsearch"),
        "imdb": (imdb_search, "/imdb"),
        "mediainfo": (mediainfo, "/mediainfo"),
        "images": (pictures, "/images"),
        "gdsearch": (gdrive_search, "/list"),
        "gdcount": (count_node, "/count"),
        "gdclean": (drive_clean, "/gdclean"),
        "gddelete": (delete_file, "/del"),
        "rss": (get_rss_menu, "/rss"),
        "select": (select, "/select"),
        "force": (remove_from_queue, "/forcestart"),
        "category": (change_category, "/category"),
        "cancelall": (cancel_all_buttons, "/cancelall"),
    }
    if tool == "commands":
        return await edit_message(
            query.message,
            "<b>פקודות ישירות למשתמשים מתקדמים</b>\n\n"
            "<code>/mirror</code> ענן · <code>/leech</code> Telegram · "
            "<code>/gofile</code> GoFile · <code>/ytdl</code> וידאו · "
            "<code>/status</code> משימות · <code>/server</code> שרת\n\n"
            "אין צורך להשתמש בהן בשימוש רגיל; כל הפעולות זמינות בכפתורים.",
            _tools_buttons(),
        )
    handler, command = tools[tool]
    query.message.from_user = query.from_user
    query.message.text = command
    await query.answer()
    await handler(client, query.message)


async def guided_callback(client, query):
    """מנתב את כל כפתורי מרכז השליטה לפי מזהה פעולה קצר ויציב."""

    try:
        action, arguments = parse_ui_callback(query.data)
    except ValueError:
        return await query.answer(
            "הכפתור אינו תקין או שייך לגרסה ישנה. פתחו מחדש את /menu.",
            show_alert=True,
        )
    parts = ["ui", action, *arguments]
    user_id = query.from_user.id
    if action == "home":
        guided_sessions.pop(user_id, None)
        await query.answer()
        return await show_home(query.message, edit=True, user=query.from_user)
    if action == "new":
        guided_sessions.pop(user_id, None)
        await query.answer()
        return await edit_message(
            query.message,
            "<b>איזו משימה תרצה ליצור?</b>\n\nבחרו סוג ושלחו את הקישור או הקובץ במסך הבא.",
            _new_task_buttons(),
        )
    if action == "quick":
        guided_sessions[user_id] = _session_defaults("gofile")
        await query.answer()
        return await edit_message(
            query.message,
            "<b>שלחו עכשיו קישור, Magnet, טורנט או קובץ.</b>\n\nהתוצאה תעלה ל־GoFile כאורח, ללא חשבון וללא pool.",
            _cancel_buttons(),
        )
    if action == "source":
        mode = parts[2]
        guided_sessions[user_id] = _session_defaults(mode)
        prompts = {
            "auto": "שלחו קישור או Magnet.",
            "torrent": "שלחו Magnet או קובץ ‎.torrent.",
            "youtube": "שלחו קישור לווידאו, אודיו או פלייליסט.",
            "jdownloader": "שלחו קישור או קובץ DLC שמתאים ל־JDownloader.",
            "usenet": "שלחו קישור NZB או קובץ ‎.nzb.",
            "clone": "שלחו קישור או מזהה של Google Drive.",
            "gofile": "שלחו קישור, Magnet, טורנט או קובץ.",
            "file": "שלחו קובץ מתוך Telegram.",
        }
        await query.answer()
        return await edit_message(
            query.message,
            f"<b>{prompts[mode]}</b>\n\nאחרי הקלט נבחר יעד ואפשרויות.",
            _cancel_buttons(),
        )
    if action == "engine" and parts[2] == "jd":
        await query.answer(
            "JDownloader דורש כתובת דוא״ל וסיסמה של MyJDownloader. כרגע הוא מושבת ואין פרטי חיבור שמורים.",
            show_alert=True,
        )
        return
    session = guided_sessions.get(user_id)
    if action == "cancel":
        guided_sessions.pop(user_id, None)
        await query.answer("הפעולה בוטלה.")
        return await show_home(query.message, edit=True, user=query.from_user)
    if action == "destinations" and session:
        await query.answer()
        return await edit_message(
            query.message, "<b>לאן להעביר את התוצאה?</b>", _destination_buttons(session["mode"])
        )
    if action == "dest" and session:
        session["destination"] = parts[2]
        if session["destination"] == "telegram":
            session["stage"] = "telegram_source"
            session["upload_source"] = ""
            session["upload_target"] = ""
            session["upload_channel"] = ""
            await query.answer()
            return await edit_message(
                query.message,
                "<b>מי יבצע את ההעלאה ל־Telegram?</b>\n\nהבחירה נשמרת לכל חלקי המשימה ולא תוחלף אוטומטית.",
                _telegram_source_buttons(),
            )
        session["stage"] = "options"
        await query.answer()
        return await edit_message(
            query.message, _option_summary(session), _options_buttons(session)
        )
    if action == "tgsource" and session:
        source = parts[2]
        if source == "user" and TgClient.user is None:
            return await query.answer("ה־Userbot אינו מחובר כרגע.", show_alert=True)
        session["upload_source"] = source
        session["stage"] = "telegram_target"
        await query.answer()
        return await edit_message(
            query.message,
            "<b>לאן לשלוח את הקבצים?</b>\n\nפרטי פירושו השיחה הנוכחית עם הבוט. ערוץ נשמר לאחר בדיקת הרשאות.",
            _telegram_target_buttons(user_id),
        )
    if action == "tgtarget" and session:
        if parts[2] == "private":
            session["upload_target"] = "private"
            session["upload_channel"] = ""
            session["stage"] = "options"
            await query.answer()
            return await edit_message(
                query.message, _option_summary(session), _options_buttons(session)
            )
        session["stage"] = "telegram_channel_input"
        session["ui_message_id"] = query.message.id
        await query.answer()
        return await edit_message(
            query.message,
            "<b>שלחו עכשיו את מזהה הערוץ.</b>\n\nאפשר לשלוח <code>@username</code> או מזהה שמתחיל ב־<code>-100</code>. מקור ההעלאה שנבחר חייב להיות מנהל בעל הרשאת פרסום.",
            _cancel_buttons(),
        )
    if action == "tgchannel" and session:
        channels = user_data.get(user_id, {}).get("TELEGRAM_UPLOAD_CHANNELS", [])
        index = int(parts[2])
        if index >= len(channels):
            return await query.answer("הערוץ השמור כבר אינו זמין.", show_alert=True)
        try:
            channel = await _connect_upload_channel(
                channels[index]["target"], session.get("upload_source", "")
            )
        except ValueError as error:
            return await query.answer(str(error), show_alert=True)
        session["upload_target"] = "channel"
        session["upload_channel"] = channel["target"]
        session["stage"] = "options"
        await query.answer()
        return await edit_message(
            query.message, _option_summary(session), _options_buttons(session)
        )
    if action == "options" and session:
        session["stage"] = "options"
        session.pop("pending_value", None)
        await query.answer()
        return await edit_message(
            query.message, _option_summary(session), _options_buttons(session)
        )
    if action == "advanced" and session:
        session["stage"] = "options"
        session.pop("pending_value", None)
        await query.answer()
        return await edit_message(
            query.message,
            "<b>🧰 אפשרויות מתקדמות</b>\n\n"
            "אפשר להגדיר רק את מה שנדרש. כל שדה שלא נבחר נשאר בברירת המחדל.",
            _advanced_options_buttons(session),
        )
    if action == "advancedtoggle" and session:
        key = parts[2]
        session[key] = not session.get(key, False)
        if session[key] and key == "as_document":
            session["as_media"] = False
        elif session[key] and key == "as_media":
            session["as_document"] = False
        elif session[key] and key == "bot_transfer":
            session["user_transfer"] = False
        elif session[key] and key == "user_transfer":
            session["bot_transfer"] = False
        await query.answer("האפשרות עודכנה.")
        return await edit_message(
            query.message,
            "<b>🧰 אפשרויות מתקדמות</b>\n\nהאפשרויות המסומנות יתווספו למשימה.",
            _advanced_options_buttons(session),
        )
    if action == "value" and session:
        key = parts[2]
        if key not in ADVANCED_VALUE_OPTIONS:
            return await query.answer("השדה אינו מוכר.", show_alert=True)
        session["stage"] = "option_input"
        session["pending_value"] = key
        session["ui_message_id"] = query.message.id
        label, _, prompt = ADVANCED_VALUE_OPTIONS[key]
        await query.answer()
        buttons = ButtonMaker()
        buttons.data_button("⬅️ חזרה ללא שינוי", "ui advanced")
        buttons.data_button("❌ ביטול המשימה", "ui cancel", style=ButtonStyle.DANGER)
        return await edit_message(
            query.message,
            f"<b>✏️ {label}</b>\n\n{prompt}\n\nהערך נשמר רק למשימה הנוכחית.",
            buttons.build_menu(1),
        )
    if action == "valueclear" and session:
        key = parts[2]
        if key in ADVANCED_VALUE_OPTIONS:
            session[key] = ""
        await query.answer("הערך נוקה.")
        return await edit_message(
            query.message,
            "<b>🧰 אפשרויות מתקדמות</b>\n\nהערך חזר לברירת המחדל.",
            _advanced_options_buttons(session),
        )
    if action == "option" and session:
        key = parts[2]
        session[key] = not session[key]
        await query.answer("האפשרות עודכנה.")
        return await edit_message(
            query.message, _option_summary(session), _options_buttons(session)
        )
    if action == "run" and session:
        guided_sessions.pop(user_id, None)
        return await _dispatch_session(client, query, session)
    if action == "tasks":
        from .status import task_status

        query.message.from_user = query.from_user
        query.message.text = "/status me"
        await query.answer()
        return await task_status(client, query.message)
    if action == "server":
        from .stats import get_server_overview

        await query.answer()
        rich, fallback, buttons = await get_server_overview(query)
        return await edit_rich_message(query.message, rich, fallback, buttons)
    if action == "tools":
        await query.answer()
        return await edit_message(
            query.message,
            "<b>🧰 כלים נוספים</b>\n\nהיכולות המתקדמות מסודרות לפי פעולה.",
            _tools_buttons(),
        )
    if action == "tool":
        return await _invoke_tool(client, query, parts[2])
    if action == "settings":
        from .users_settings import send_user_settings

        query.message.from_user = query.from_user
        await query.answer()
        return await send_user_settings(client, query.message)
    if action == "help":
        await query.answer()
        return await edit_message(
            query.message,
            "<b>כך עובדים עם הבוט</b>\n\n"
            "1. לוחצים <b>משימה חדשה</b>.\n"
            "2. שולחים קישור, Magnet, טורנט או קובץ.\n"
            "3. בוחרים יעד. GoFile הוא ברירת המחדל המהירה.\n"
            "4. מפעילים מיד או מסמנים אפשרות מתקדמת.\n"
            "5. עוקבים דרך <b>המשימות שלי</b>.\n\n"
            "בכל מסך יש כפתור חזרה; אין צורך לזכור פקודות.",
            _home_buttons(user_id == Config.OWNER_ID),
        )
    if action == "gofile":
        from ..helper.ext_utils.gofile_delete import delete_owned_upload
        from ..helper.ext_utils.gofile_store import live_gofile_store

        subaction = arguments[0] if arguments else "show"
        if subaction in {"show", "refresh", "page"}:
            offset = int(arguments[1]) if subaction == "page" else 0
            await query.answer("הנתונים רועננו." if subaction == "refresh" else "")
            text, buttons = await _gofile_overview(user_id, offset)
            return await edit_message(query.message, text, buttons)

        record_id = arguments[1]
        record = await live_gofile_store().get_owned(user_id, record_id)
        if not record or record.get("status") != "active":
            return await query.answer(
                "לא מצאתי העלאה פעילה כזו בחשבון שלך.", show_alert=True
            )
        if subaction == "add":
            session = _session_defaults("gofile")
            session["gofile_target_id"] = record_id
            guided_sessions[user_id] = session
            await query.answer()
            return await edit_message(
                query.message,
                "<b>➕ הוספה לתיקיית GoFile קיימת</b>\n\n"
                "שלחו קישור, Magnet, טורנט או קובץ. התוצאה תתווסף לאותה תיקייה "
                "בלי לחשוף או לבקש את טוקן הבעלות.",
                _cancel_buttons(),
            )
        if subaction == "deleteconfirm":
            buttons = ButtonMaker()
            buttons.data_button(
                "✅ כן, למחוק מ־GoFile",
                f"ui gofile delete {record_id}",
                "header",
                ButtonStyle.DANGER,
            )
            buttons.data_button("↩️ ביטול", "ui gofile", "footer")
            await query.answer()
            return await edit_message(
                query.message,
                "\u200f<b>🗑 למחוק את ההעלאה?</b>\n\n"
                f"<b>{escape(str(record.get('name') or 'קובץ ללא שם'))}</b>\n"
                "הפעולה תמחק את התוכן מ־GoFile והיא אינה הפיכה.",
                buttons.build_menu(1),
            )
        if subaction == "delete":
            # callback_data נשלט בידי הלקוח; המחיקה טוענת שוב את הרשומה עם
            # user_id בצד השרת ואינה מסתמכת על המסך הקודם.
            await query.answer()
            outcome, detail = await delete_owned_upload(
                live_gofile_store(), user_id, record_id
            )
            text, buttons = await _gofile_overview(user_id, 0)
            return await edit_message(
                query.message,
                f"\u200f<b>{'✅' if outcome in {'deleted', 'already_gone'} else '⚠️'} {escape(detail)}</b>\n\n{text}",
                buttons,
            )
    if action == "backup":
        if user_id != Config.OWNER_ID:
            return await query.answer("המסך זמין לבעל הבוט בלבד.", show_alert=True)
        from ..helper.ext_utils.backup_control import (
            adjust_daily_backup_time,
            request_backup,
            set_daily_backup,
        )

        subaction = parts[2] if len(parts) > 2 else "show"
        if subaction in {"full", "state", "dailyrun"}:
            try:
                request_backup(
                    chat_id=user_id,
                    include_images=subaction != "state",
                    origin="daily" if subaction == "dailyrun" else "manual",
                )
            except RuntimeError as error:
                await query.answer(str(error), show_alert=True)
            else:
                await query.answer(
                    (
                        "הערכה המלאה נמסרה ל־Worker. הקובץ והמדריך יגיעו לכאן לאחר הבדיקות."
                        if subaction in {"full", "dailyrun"}
                        else "הערכה המהירה נמסרה ל־Worker. היא אינה כוללת Images."
                    ),
                    show_alert=True,
                )
        elif subaction in {"dailyon", "dailyoff"}:
            enabled = subaction == "dailyon"
            set_daily_backup(enabled=enabled, chat_id=user_id)
            await query.answer(
                "הגיבוי היומי הופעל לשעה 04:15."
                if enabled
                else "הגיבוי היומי הושהה.",
                show_alert=True,
            )
        elif subaction in {"timem60", "timep60", "timem15", "timep15"}:
            offsets = {
                "timem60": -60,
                "timep60": 60,
                "timem15": -15,
                "timep15": 15,
            }
            settings = adjust_daily_backup_time(
                minutes=offsets[subaction], chat_id=user_id
            )
            await query.answer(
                f"שעת הגיבוי נשמרה: {settings.daily_hour:02d}:{settings.daily_minute:02d}",
                show_alert=False,
            )
        elif subaction == "restore":
            await query.answer(
                "כל גיבוי נפתח ונבדק, MongoDB משוחזר למסד זמני ונמחק בסיום, וחיבור Local Bot API מאומת. שחזור מלא לשרת חדש עדיין דורש אישור מפורש.",
                show_alert=True,
            )
        elif subaction == "guide" and len(parts) > 3:
            await query.answer()
            buttons = ButtonMaker()
            buttons.data_button("🛡 חזרה לגיבוי יומי", "ui backup daily", "footer")
            return await send_rich_message(
                query.message,
                backup_deployment_guide(parts[3]),
                "<b>📖 מדריך פריסת WZML-X</b>",
                buttons.build_menu(1),
            )
        else:
            await query.answer("הנתונים רועננו." if subaction == "refresh" else "")
        if subaction == "show":
            rich, buttons = backup_home()
            title = "<b>💾 גיבויים והתאוששות</b>"
        else:
            daily = subaction in {
                "daily",
                "dailyrun",
                "dailyon",
                "dailyoff",
                "timem60",
                "timep60",
                "timem15",
                "timep15",
            }
            rich, buttons = backup_overview(user_id, daily=daily)
            title = "<b>🛡 גיבוי יומי</b>" if daily else "<b>📦 ערכת ניוד</b>"
        return await edit_rich_message(
            query.message,
            rich,
            title,
            buttons,
        )
    if action == "cache":
        if user_id != Config.OWNER_ID:
            return await query.answer("המסך זמין לבעל הבוט בלבד.", show_alert=True)
        from ..helper.ext_utils.cache_control import request_cache_action

        subaction = arguments[0] if arguments else "show"
        if subaction == "leftovers_confirm":
            residuals = await _residual_download_snapshot()
            if not residuals["cleanup_allowed"]:
                return await query.answer(
                    "אין שאריות לניקוי או שקיימת משימה פעילה.", show_alert=True
                )
            buttons = ButtonMaker()
            buttons.data_button(
                "✅ כן, למחוק את השאריות",
                "ui cache leftovers_run",
                "header",
                ButtonStyle.DANGER,
            )
            buttons.data_button("↩️ ביטול", "ui cache", "footer")
            await query.answer()
            return await edit_message(
                query.message,
                "<b>🗑 ניקוי שאריות ממשימות תקועות</b>\n\n"
                f"יימחקו <code>\u2066{residuals['files']}\u2069</code> קבצים בנפח "
                f"<code>\u2066{get_readable_file_size(residuals['bytes'])}\u2069</code>.\n"
                "Sessions, MongoDB, גיבויים, סודות ו־volumes אינם חלק מהפעולה.",
                buttons.build_menu(1),
            )
        if subaction == "leftovers_run":
            residuals = await _residual_download_snapshot()
            try:
                result = clear_residual_downloads(
                    Path(DOWNLOAD_DIR),
                    active_task_ids=(
                        {"active"} if not residuals["cleanup_allowed"] else set()
                    ),
                )
            except RuntimeError as error:
                await query.answer(str(error), show_alert=True)
            else:
                await query.answer(
                    f"נמחקו {result['removed_files']} קבצים; "
                    f"שוחררו {get_readable_file_size(result['removed_bytes'])}.",
                    show_alert=True,
                )
        elif subaction in {"refresh", "run"}:
            try:
                request_cache_action("clean_safe" if subaction == "run" else "scan")
            except RuntimeError as error:
                await query.answer(str(error), show_alert=True)
            else:
                await query.answer(
                    "הניקוי הבטוח התחיל. רעננו בעוד רגע."
                    if subaction == "run"
                    else "סריקת המטמון התחילה. רעננו בעוד רגע.",
                    show_alert=True,
                )
        else:
            await query.answer()
        residuals = await _residual_download_snapshot()
        rich, buttons = cache_overview(residuals)
        return await edit_rich_message(
            query.message,
            rich,
            "<b>🧹 מפת המטמון של השרת</b>",
            buttons,
        )
    if action == "admin":
        if user_id != Config.OWNER_ID:
            return await query.answer("המסך זמין לבעל הבוט בלבד.", show_alert=True)
        if len(parts) == 2:
            await query.answer()
            return await edit_message(
                query.message, "<b>🛠 ניהול מתקדם</b>", _admin_buttons()
            )
        tool = parts[2]
        query.message.from_user = query.from_user
        await query.answer()
        if tool == "access":
            return await edit_message(
                query.message,
                "<b>👥 משתמשים והרשאות</b>\n\nבחרו פעולה ושלחו את המזהה במסך הבא.",
                _access_buttons(),
            )
        if tool == "terminal":
            return await edit_message(
                query.message,
                "<b>⌨️ מסוף הבעלים</b>\n\nהפעולות כאן מריצות קוד בשרת וזמינות לבעל הבוט בלבד.",
                _terminal_buttons(),
            )
        if tool == "input":
            admin_action = parts[3]
            if admin_action not in ADMIN_INPUTS:
                return await query.answer("פעולת הניהול אינה מוכרת.", show_alert=True)
            guided_sessions[user_id] = {
                "stage": "admin_input",
                "admin_action": admin_action,
            }
            _, prompt = ADMIN_INPUTS[admin_action]
            return await edit_message(
                query.message,
                f"<b>{prompt}</b>\n\nאפשר לבטל ולחזור ללא שינוי.",
                _cancel_buttons(),
            )
        if tool == "botsettings":
            from .bot_settings import send_bot_settings

            return await send_bot_settings(client, query.message)
        if tool == "users":
            from .users_settings import get_users_settings

            query.message.text = "/users"
            return await get_users_settings(client, query.message)
        if tool == "plugins":
            from .plugin_manager import plugins_command

            query.message.text = "/plugins"
            return await plugins_command(client, query.message)
        if tool == "sessions":
            from .gen_pyro_sess import gen_pyro_string

            query.message.text = "/exportsession"
            return await gen_pyro_string(client, query.message)
        if tool == "restartsessions":
            from .restart import restart_sessions

            query.message.text = "/restartses"
            return await restart_sessions(client, query.message)
        if tool == "clear":
            from .exec import clear

            query.message.text = "/clearlocals"
            return await clear(client, query.message)
        if tool == "logs":
            from .services import log

            return await log(client, query.message)
        if tool == "restart":
            from .restart import restart_bot

            query.message.text = "/restart"
            return await restart_bot(client, query.message)


def _cancel_buttons():
    buttons = ButtonMaker()
    buttons.data_button("❌ ביטול וחזרה", "ui cancel", "footer", ButtonStyle.DANGER)
    return buttons.build_menu(1)


async def menu_command(_, message):
    """פקודה קצרה שפותחת מחדש את מרכז השליטה מכל מקום."""

    guided_sessions.pop(message.from_user.id, None)
    await show_home(message)


async def server_command(_, message):
    """שם ברור ונפרד למצב השרת, כדי לא לבלבל אותו עם מצב המשימות."""

    from .stats import bot_stats

    await bot_stats(_, message)
