from html import escape
from logging import getLogger
from re import compile as re_compile

from aiohttp import ClientSession, ClientTimeout

from .message_utils import edit_message, send_message
from ...core.tg_client import TgClient

LOGGER = getLogger(__name__)

RLM = "\u200f"
RLI = "\u2067"
PDI = "\u2069"
COMMAND_RE = re_compile(r"^/[A-Za-z][A-Za-z0-9_]{0,31}$")
TABLE_RTL_ATTR = 'dir="rtl" style="direction:rtl;text-align:right"'
CELL_RTL_ATTR = 'align="right" dir="rtl" style="direction:rtl;text-align:right"'


def html_escape(value) -> str:
    """מגן על ערך דינמי לפני שילובו בתוך Rich Message."""

    return escape(str(value or ""), quote=True)


def rtl(value) -> str:
    """מבודד טקסט מעורב בעברית, אנגלית ומספרים כדי למנוע היפוך חזותי."""

    return RLM + RLI + html_escape(value) + PDI + RLM


def rtl_html(value: str) -> str:
    """מבודד קטע HTML שכבר נבנה באופן בטוח במודול הזה."""

    return RLM + RLI + str(value or "") + PDI + RLM


def rich_cell(value) -> str:
    text = str(value or "").strip()
    if COMMAND_RE.fullmatch(text):
        return html_escape(text)
    return rtl(text)


def kv_table(
    rows: list[tuple[str, str]],
    *,
    header: tuple[str, str] = ("פרט", "ערך"),
) -> str:
    """בונה טבלת מפתח־ערך ימנית, קצרה ונוחה לקריאה בנייד."""

    body = "".join(
        f'<tr><td {CELL_RTL_ATTR}><b>{rich_cell(label)}</b></td>'
        f'<td {CELL_RTL_ATTR}>{rich_cell(value)}</td></tr>'
        for label, value in rows
    )
    return (
        f'<table {TABLE_RTL_ATTR} bordered striped>'
        f'<tr><th {CELL_RTL_ATTR}>{rich_cell(header[0])}</th>'
        f'<th {CELL_RTL_ATTR}>{rich_cell(header[1])}</th></tr>'
        f"{body}</table>"
    )


def summary_card(
    title: str,
    rows: list[tuple[str, str]],
    *,
    intro: str | None = None,
    footer: str | None = None,
) -> str:
    """יוצר כרטיס מידע עשיר בעל מבנה עקבי בכל מסכי הניהול."""

    parts = [f"<h2>{rtl(title)}</h2>"]
    if intro:
        parts.extend(
            f"<p>{rtl(line)}</p>" for line in str(intro).splitlines() if line.strip()
        )
    parts.append(kv_table(rows, header=("נושא", "פרטים")))
    if footer:
        parts.append(f"<p>{rtl(footer)}</p>")
    return "".join(parts)


def _inline_markup_to_dict(markup):
    """ממיר מקלדת WzGram למבנה שמקבל Telegram Bot API המקומי."""

    if markup is None:
        return None
    if isinstance(markup, dict):
        return markup
    keyboard = []
    for row in getattr(markup, "inline_keyboard", []) or []:
        output_row = []
        for button in row:
            item = {"text": button.text}
            for field in ("url", "callback_data", "switch_inline_query"):
                value = getattr(button, field, None)
                if value is not None:
                    item[field] = value
            style = getattr(button, "style", None)
            if style is not None:
                item["style"] = getattr(style, "value", style)
            output_row.append(item)
        keyboard.append(output_row)
    return {"inline_keyboard": keyboard} if keyboard else None


async def _local_bot_api(method, payload):
    """שולח Rich Message דרך ה־Bot API המקומי כאשר הוא הוגדר בשרת."""

    from ...core.config_manager import Config

    base = str(getattr(Config, "LOCAL_BOT_API_BASE", "") or "").rstrip("/")
    if not base:
        return False
    url = f"{base}/bot{Config.BOT_TOKEN}/{method}"
    try:
        async with (
            ClientSession(timeout=ClientTimeout(total=10)) as session,
            session.post(url, json=payload) as response,
        ):
            data = await response.json(content_type=None)
            if response.status == 200 and data.get("ok") is True:
                return True
            LOGGER.warning(
                "Telegram Bot API המקומי דחה Rich Message: %s",
                str(data.get("description") or response.status)[:200],
            )
    except Exception as error:
        LOGGER.warning("החיבור ל־Telegram Bot API המקומי נכשל: %s", error)
    return False


async def send_rich_message(message, rich_html, fallback_text, buttons=None):
    """שולח Rich Message ונופל בבטחה להודעת HTML רגילה במקרה של חוסר תמיכה."""

    payload = {
        "chat_id": message.chat.id,
        "reply_parameters": {
            "message_id": message.id,
            "allow_sending_without_reply": True,
        },
        "rich_message": {
            "html": rich_html,
            "is_rtl": True,
            "skip_entity_detection": False,
        },
    }
    if markup := _inline_markup_to_dict(buttons):
        payload["reply_markup"] = markup
    if await _local_bot_api("sendRichMessage", payload):
        return True
    try:
        return await TgClient.bot.send_message(
            chat_id=message.chat.id,
            rich_text=rich_html,
            reply_to_message_id=message.id,
            reply_markup=buttons,
            disable_notification=True,
        )
    except Exception:
        LOGGER.warning("שליחת Rich Message נכשלה; עובר לתצוגת HTML רגילה", exc_info=True)
        return await send_message(message, fallback_text, buttons)


async def edit_rich_message(message, rich_html, fallback_text, buttons=None):
    """עורך Rich Message קיים ושומר על מסלול fallback נגיש."""

    payload = {
        "chat_id": message.chat.id,
        "message_id": message.id,
        "rich_message": {
            "html": rich_html,
            "is_rtl": True,
            "skip_entity_detection": False,
        },
    }
    if markup := _inline_markup_to_dict(buttons):
        payload["reply_markup"] = markup
    if await _local_bot_api("editMessageText", payload):
        return True
    try:
        return await TgClient.bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=message.id,
            text="",
            rich_text=rich_html,
            reply_markup=buttons,
        )
    except Exception:
        LOGGER.warning("עריכת Rich Message נכשלה; עובר לתצוגת HTML רגילה", exc_info=True)
        return await edit_message(message, fallback_text, buttons)
