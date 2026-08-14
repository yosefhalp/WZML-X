import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest import TestCase


def _load_filters_module():
    """טוען את המסננים בבידוד, בלי להפעיל את כל שירותי הבוט בזמן הבדיקה."""

    modules_to_restore = {
        name: sys.modules.get(name)
        for name in (
            "pyrogram",
            "pyrogram.filters",
            "pyrogram.enums",
            "bot",
            "bot.core",
            "bot.core.config_manager",
            "bot.helper",
            "bot.helper.telegram_helper",
            "bot.helper.telegram_helper.tg_utils",
            "bot.helper.telegram_helper.filters",
        )
    }

    pyrogram = ModuleType("pyrogram")
    pyrogram_filters = ModuleType("pyrogram.filters")
    pyrogram_filters.create = lambda callback: callback
    pyrogram_enums = ModuleType("pyrogram.enums")
    pyrogram_enums.ChatType = SimpleNamespace(PRIVATE="private")
    sys.modules["pyrogram"] = pyrogram
    sys.modules["pyrogram.filters"] = pyrogram_filters
    sys.modules["pyrogram.enums"] = pyrogram_enums

    bot = ModuleType("bot")
    bot.auth_chats = {}
    bot.sudo_users = set()
    bot.user_data = {}
    bot_core = ModuleType("bot.core")
    config_manager = ModuleType("bot.core.config_manager")
    config_manager.Config = SimpleNamespace(OWNER_ID=42)
    bot_helper = ModuleType("bot.helper")
    telegram_helper = ModuleType("bot.helper.telegram_helper")
    tg_utils = ModuleType("bot.helper.telegram_helper.tg_utils")
    tg_utils.chat_info = lambda _: None
    sys.modules.update(
        {
            "bot": bot,
            "bot.core": bot_core,
            "bot.core.config_manager": config_manager,
            "bot.helper": bot_helper,
            "bot.helper.telegram_helper": telegram_helper,
            "bot.helper.telegram_helper.tg_utils": tg_utils,
        }
    )

    module_path = (
        Path(__file__).parents[1]
        / "bot"
        / "helper"
        / "telegram_helper"
        / "filters.py"
    )
    spec = importlib.util.spec_from_file_location(
        "bot.helper.telegram_helper.filters", module_path
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module, modules_to_restore


def _restore_modules(previous):
    """מחזיר את טבלת המודולים למצבה הקודם כדי שהבדיקה לא תשפיע על אחרות."""

    for name, module in previous.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


class AuthorizationFilterTests(TestCase):
    def setUp(self):
        self.filters, self.previous_modules = _load_filters_module()

    def tearDown(self):
        _restore_modules(self.previous_modules)

    def _authorized(self, update):
        return asyncio.run(
            self.filters.CustomFilters.authorized_user(None, None, update)
        )

    def _callback(self, user_id=77, chat_id=77, chat_type="private", **message_values):
        message = SimpleNamespace(
            from_user=None,
            sender_chat=None,
            chat=SimpleNamespace(id=chat_id, type=chat_type),
            is_topic_message=message_values.pop("is_topic_message", False),
            message_thread_id=message_values.pop("message_thread_id", None),
            **message_values,
        )
        return SimpleNamespace(
            from_user=SimpleNamespace(id=user_id),
            sender_chat=None,
            message=message,
        )

    def test_owner_message_is_authorized(self):
        message = SimpleNamespace(
            from_user=SimpleNamespace(id=42),
            sender_chat=None,
            chat=SimpleNamespace(id=42, type="private"),
            is_topic_message=False,
        )
        self.assertTrue(self._authorized(message))

    def test_owner_callback_query_is_authorized(self):
        message = SimpleNamespace(
            from_user=None,
            sender_chat=None,
            chat=SimpleNamespace(id=42, type="private"),
            is_topic_message=False,
        )
        callback = SimpleNamespace(
            from_user=SimpleNamespace(id=42),
            sender_chat=None,
            message=message,
        )
        self.assertTrue(self._authorized(callback))

    def test_authorized_group_callback_query_is_authorized(self):
        self.filters.auth_chats[-100123] = []
        self.assertTrue(
            self._authorized(self._callback(chat_id=-100123, chat_type="supergroup"))
        )

    def test_only_configured_topic_is_authorized(self):
        self.filters.auth_chats[-100123] = [19]
        allowed = self._callback(
            chat_id=-100123,
            chat_type="supergroup",
            is_topic_message=True,
            message_thread_id=19,
        )
        denied = self._callback(
            chat_id=-100123,
            chat_type="supergroup",
            is_topic_message=True,
            message_thread_id=20,
        )
        self.assertTrue(self._authorized(allowed))
        self.assertFalse(self._authorized(denied))

    def test_sudo_user_callback_query_is_authorized(self):
        self.filters.sudo_users.add(77)
        self.assertTrue(self._authorized(self._callback()))

    def test_user_database_authorization_is_honored(self):
        self.filters.user_data[77] = {"AUTH": True}
        self.assertTrue(self._authorized(self._callback()))

    def test_chat_database_authorization_is_honored(self):
        self.filters.user_data[-100123] = {"AUTH": True, "thread_ids": []}
        self.assertTrue(
            self._authorized(self._callback(chat_id=-100123, chat_type="supergroup"))
        )

    def test_blacklist_supports_permanent_and_expiring_entries(self):
        callback = self._callback()
        self.filters.user_data[77] = {"BLACKLIST": True}
        permanent = asyncio.run(
            self.filters.CustomFilters.blacklisted_user(None, None, callback)
        )
        self.filters.user_data[77] = {"BLACKLIST": 1}
        expired = asyncio.run(
            self.filters.CustomFilters.blacklisted_user(None, None, callback)
        )
        self.assertTrue(permanent)
        self.assertFalse(expired)
        self.assertFalse(self.filters.user_data[77]["BLACKLIST"])

    def test_unknown_callback_query_is_rejected_without_crashing(self):
        callback = SimpleNamespace(
            from_user=SimpleNamespace(id=77), sender_chat=None, message=None
        )
        self.assertFalse(self._authorized(callback))
