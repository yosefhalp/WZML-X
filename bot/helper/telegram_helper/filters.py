from time import time

from pyrogram.filters import create
from pyrogram.enums import ChatType

from ... import auth_chats, sudo_users, user_data
from ...core.config_manager import Config
from .tg_utils import chat_info


def _message_from_update(update):
    """מחזיר את ההודעה שמכילה את פרטי הצ'אט גם בלחיצה על כפתור."""

    return getattr(update, "message", None) or update


def _sender_from_update(update):
    """מאתר את השולח בעדכון רגיל, בלחיצת כפתור או בהודעת ערוץ."""

    message = _message_from_update(update)
    return (
        getattr(update, "from_user", None)
        or getattr(update, "sender_chat", None)
        or getattr(message, "from_user", None)
        or getattr(message, "sender_chat", None)
    )


class CustomFilters:
    async def owner_filter(self, _, update):
        user = _sender_from_update(update)
        return bool(user and user.id == Config.OWNER_ID)

    owner = create(owner_filter)

    async def authorized_user(self, _, update):
        user = _sender_from_update(update)
        if user is None:
            return False
        message = _message_from_update(update)
        chat = getattr(message, "chat", None)
        uid = user.id
        chat_id = getattr(chat, "id", None)
        thread_id = (
            getattr(message, "message_thread_id", None)
            if getattr(message, "is_topic_message", False)
            else None
        )
        return bool(
            uid == Config.OWNER_ID
            or (
                uid in user_data
                and (
                    user_data[uid].get("AUTH", False)
                    or user_data[uid].get("SUDO", False)
                )
            )
            or (
                chat_id is not None
                and chat_id in user_data
                and user_data[chat_id].get("AUTH", False)
                and (
                    thread_id is None
                    or thread_id in user_data[chat_id].get("thread_ids", [])
                )
            )
            or uid in sudo_users
            or uid in auth_chats
            or (
                chat_id is not None
                and chat_id in auth_chats
                and (
                    auth_chats[chat_id]
                    and thread_id
                    and thread_id in auth_chats[chat_id]
                    or not auth_chats[chat_id]
                )
            )
        )

    authorized = create(authorized_user)

    async def authorized_usetting(self, _, update):
        user = _sender_from_update(update)
        if user is None:
            return False
        uid = user.id
        message = _message_from_update(update)
        chat = getattr(message, "chat", None)
        is_exists = False
        if await CustomFilters.authorized("", update):
            is_exists = True
        elif chat and chat.type == ChatType.PRIVATE:
            for channel_id in user_data:
                if not (
                    user_data[channel_id].get("is_auth")
                    and str(channel_id).startswith("-100")
                ):
                    continue
                try:
                    if await (await chat_info(str(channel_id))).get_member(uid):
                        is_exists = True
                        break
                except Exception:
                    continue
        return is_exists

    authorized_uset = create(authorized_usetting)

    async def sudo_user(self, _, update):
        user = _sender_from_update(update)
        if user is None:
            return False
        uid = user.id
        return bool(
            uid == Config.OWNER_ID
            or uid in user_data
            and user_data[uid].get("SUDO")
            or uid in sudo_users
        )

    sudo = create(sudo_user)

    async def blacklisted_user(self, _, update):
        user = _sender_from_update(update)
        if user is None:
            return False
        uid = user.id
        if uid not in user_data:
            return False
        bl = user_data[uid].get("BLACKLIST", False)
        if not bl:
            return False
        if bl is True:
            return True
        if isinstance(bl, (int, float)):
            if bl > time():
                return True
            user_data[uid]["BLACKLIST"] = False
            return False
        return False

    blacklisted = create(blacklisted_user)
