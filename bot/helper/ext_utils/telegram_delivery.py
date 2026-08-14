"""כללי ניתוב למסירת קבצים גדולים בשיחה הפרטית עם הבוט."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UploadReplyContext:
    """יעד ההשבה המקורי שאסור להחליף בזמן העלאות מקבילות."""

    target: object
    message_id: int


@dataclass(frozen=True, slots=True)
class UploadDeliveryReceipt:
    """קבלה פנימית שמוכיחה מי שלח ולאיזה יעד התבצעה השליחה."""

    message: object
    client_kind: str
    requested_chat_id: object


def build_upload_reply_context(message) -> UploadReplyContext:
    """מקפיא את הודעת המקור לפני שחלקים מקבילים מתחילים להישלח."""

    if message is None or getattr(message, "chat", None) is None:
        raise ValueError("הודעת המקור להעלאה אינה תקינה")
    message_id = getattr(message, "id", None)
    if not isinstance(message_id, int) or message_id <= 0:
        raise ValueError("מזהה הודעת המקור להעלאה אינו תקין")
    return UploadReplyContext(target=message, message_id=message_id)


def delivered_upload_count(upload_sequence) -> int:
    """סופר רק חלקים שקיבלו הודעת Telegram מאומתת."""

    return sum(entry is not None for entry in upload_sequence)


def upload_delivery_complete(upload_sequence, total_files: int) -> bool:
    """מונע הכרזת הצלחה כאשר חסרה הודעה עבור קובץ או חלק כלשהו."""

    return total_files > 0 and delivered_upload_count(upload_sequence) == total_files


def eligible_hyper_client_keys(clients: dict, *, user_session: bool) -> list:
    """מפריד בין לקוחות Bot ללקוחות Userbot לפי מפתח מאגר Hyper."""

    return [
        key
        for key in clients
        if isinstance(key, int) and (key < 0 if user_session else key >= 0)
    ]


def normalize_telegram_channel(value) -> str:
    """מאמת מזהה ערוץ בלי לקבל קישור, פקודה או יעד פרטי סמוי."""

    value = str(value or "").strip()
    if value.startswith("@"):
        username = value[1:]
        if 5 <= len(username) <= 32 and username.replace("_", "").isalnum():
            return f"@{username}"
    if value.startswith("-100") and value[1:].isdigit() and 10 <= len(value) <= 20:
        return value
    raise ValueError("יש להזין @username של ערוץ או מזהה מספרי שמתחיל ב־100-")


def telegram_command_destination(source: str, target: str, channel="") -> str:
    """בונה יעד `-up` מפורש שמקבע גם את סוג הלקוח שנבחר."""

    if source not in {"bot", "user"}:
        raise ValueError("יש לבחור מקור העלאה: Bot או Userbot")
    if target == "private":
        return f"{'u' if source == 'user' else 'b'}:pm"
    if target != "channel":
        raise ValueError("יש לבחור יעד פרטי או ערוץ")
    normalized = normalize_telegram_channel(channel)
    return f"{'u' if source == 'user' else 'b'}:{normalized}"


def delivery_receipt_matches_route(
    receipt: UploadDeliveryReceipt,
    *,
    expected_client_kind: str,
    private_chat: bool,
    owner_id,
) -> bool:
    """דוחה מסירה שבוצעה בלקוח אחר או ב־Saved Messages של ה־Userbot."""

    if receipt.client_kind != expected_client_kind:
        return False
    message = receipt.message
    chat = getattr(message, "chat", None)
    if chat is None:
        return False
    if private_chat and expected_client_kind == "user":
        if str(getattr(chat, "id", "")) == str(owner_id):
            return False
        requested = receipt.requested_chat_id
        if str(requested).startswith("@"):
            return str(getattr(chat, "username", "") or "").casefold() == str(
                requested
            )[1:].casefold()
        return str(getattr(chat, "id", "")) == str(requested)
    if private_chat and expected_client_kind == "bot":
        return str(getattr(chat, "id", "")) == str(owner_id)
    requested = receipt.requested_chat_id
    if isinstance(requested, int) or str(requested).lstrip("-").isdigit():
        return str(getattr(chat, "id", "")) == str(requested)
    if str(requested).startswith("@"):
        return str(getattr(chat, "username", "") or "").casefold() == str(
            requested
        )[1:].casefold()
    return False


def is_saved_messages_destination(destination, owner_id) -> bool:
    """מזהה יעד שבחשבון המשתמש פירושו "הודעות שמורות" של הבעלים."""

    if destination in (None, "") or owner_id in (None, ""):
        return False
    value = str(destination).split("|", 1)[0].strip()
    if value.lower() == "pm":
        return True
    return value.lstrip("+") == str(owner_id).lstrip("+")


def resolve_private_transmission_mode(mode: str, *, user_available: bool) -> str:
    """משאיר Userbot פעיל בצ׳אט פרטי ורק נופל לבוט כשאין לקוח משתמש."""

    if mode in {"user", "both"} and not user_available:
        return "bot"
    return mode


def is_direct_private_session_delivery(
    *,
    user_session: bool,
    private_chat: bool,
    explicit_destination,
    dump_destination,
    bot_peer,
    owner_id=None,
) -> bool:
    """בודק אם חשבון המשתמש צריך להעלות ישירות אל חשבון הבוט.

    בצד של הבוט, מזהה הצ'אט הפרטי הוא מזהה המשתמש. אם מעבירים את אותו
    מזהה ללקוח המשתמש הוא מתקבל כ"הודעות שמורות". לכן במסלול הפרטי,
    כשאין יעד מפורש, לקוח המשתמש חייב לשלוח אל מזהה חשבון הבוט עצמו.
    """

    destination = explicit_destination or dump_destination
    destination_is_saved = is_saved_messages_destination(destination, owner_id)
    return bool(
        user_session
        and private_chat
        and (not destination or destination_is_saved)
        and bot_peer
    )


def resolve_upload_chat_id(
    *,
    user_session: bool,
    private_chat: bool,
    explicit_destination,
    dump_destination,
    bot_peer,
    fallback_chat_id,
):
    """מחזיר את מזהה היעד הנכון מנקודת המבט של הלקוח שמעלה."""

    if is_direct_private_session_delivery(
        user_session=user_session,
        private_chat=private_chat,
        explicit_destination=explicit_destination,
        dump_destination=dump_destination,
        bot_peer=bot_peer,
        owner_id=fallback_chat_id,
    ):
        return bot_peer
    return explicit_destination or dump_destination or fallback_chat_id


def normalize_delivery_chat_id(
    *,
    sent_chat_id,
    owner_id,
    user_session: bool,
    private_chat: bool,
    explicit_destination,
    dump_destination,
    bot_peer,
):
    """מתרגם את מזהה הדו-שיח מתצוגת המשתמש לתצוגת הבוט.

    הודעה שנשלחה מהחשבון אל הבוט נמצאת אצל לקוח המשתמש בדו-שיח שמזההו
    הוא מזהה הבוט. אותה הודעה נראית ללקוח הבוט בדו-שיח שמזההו הוא מזהה
    בעל החשבון. הנרמול מאפשר פעולות המשך בלי להתבלבל בין שתי התצוגות.
    """

    if is_direct_private_session_delivery(
        user_session=user_session,
        private_chat=private_chat,
        explicit_destination=explicit_destination,
        dump_destination=dump_destination,
        bot_peer=bot_peer,
        owner_id=owner_id,
    ):
        return owner_id
    return sent_chat_id
