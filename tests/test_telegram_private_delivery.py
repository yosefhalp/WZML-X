import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "bot"
    / "helper"
    / "ext_utils"
    / "telegram_delivery.py"
)
SPEC = importlib.util.spec_from_file_location("telegram_delivery", MODULE_PATH)
telegram_delivery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(telegram_delivery)


class TelegramPrivateDeliveryTests(unittest.TestCase):
    def test_reply_context_stays_on_original_message_during_parallel_updates(self):
        original = SimpleNamespace(id=400, chat=SimpleNamespace(id=111))
        context = telegram_delivery.build_upload_reply_context(original)
        mutable_last_message = SimpleNamespace(id=900, chat=SimpleNamespace(id=9876543210))

        self.assertIs(original, context.target)
        self.assertEqual(400, context.message_id)
        self.assertIsNot(mutable_last_message, context.target)

    def test_completion_requires_a_telegram_message_for_every_part(self):
        sequence = [None, None]
        sequence[1] = {"msg_id": 502}
        self.assertFalse(telegram_delivery.upload_delivery_complete(sequence, 2))
        sequence[0] = {"msg_id": 501}
        self.assertTrue(telegram_delivery.upload_delivery_complete(sequence, 2))
        self.assertEqual(2, telegram_delivery.delivered_upload_count(sequence))

    def test_hyper_pool_never_uses_userbot_for_bot_route(self):
        clients = {-1: object()}
        self.assertEqual(
            [],
            telegram_delivery.eligible_hyper_client_keys(
                clients, user_session=False
            ),
        )
        self.assertEqual(
            [-1],
            telegram_delivery.eligible_hyper_client_keys(
                clients, user_session=True
            ),
        )

    def test_receipt_rejects_saved_messages_and_wrong_client(self):
        saved = telegram_delivery.UploadDeliveryReceipt(
            message=SimpleNamespace(chat=SimpleNamespace(id=111)),
            client_kind="user",
            requested_chat_id=111,
        )
        self.assertFalse(
            telegram_delivery.delivery_receipt_matches_route(
                saved,
                expected_client_kind="user",
                private_chat=True,
                owner_id=111,
            )
        )
        bot_chat = telegram_delivery.UploadDeliveryReceipt(
            message=SimpleNamespace(
                chat=SimpleNamespace(id=9876543210, username="example_delivery_bot")
            ),
            client_kind="user",
            requested_chat_id="@example_delivery_bot",
        )
        self.assertTrue(
            telegram_delivery.delivery_receipt_matches_route(
                bot_chat,
                expected_client_kind="user",
                private_chat=True,
                owner_id=111,
            )
        )
        wrong_client = telegram_delivery.UploadDeliveryReceipt(
            message=SimpleNamespace(chat=SimpleNamespace(id=111)),
            client_kind="user",
            requested_chat_id=111,
        )
        self.assertFalse(
            telegram_delivery.delivery_receipt_matches_route(
                wrong_client,
                expected_client_kind="bot",
                private_chat=True,
                owner_id=111,
            )
        )

    def test_explicit_private_and_channel_destinations_keep_the_source(self):
        self.assertEqual(
            "b:pm",
            telegram_delivery.telegram_command_destination(
                "bot", "private"
            ),
        )
        self.assertEqual(
            "u:@example_channel",
            telegram_delivery.telegram_command_destination(
                "user", "channel", "@example_channel"
            ),
        )

    def test_private_premium_upload_targets_bot_instead_of_saved_messages(self):
        target = telegram_delivery.resolve_upload_chat_id(
            user_session=True,
            private_chat=True,
            explicit_destination=None,
            dump_destination=None,
            bot_peer="@example_delivery_bot",
            fallback_chat_id=111,
        )
        self.assertEqual("@example_delivery_bot", target)
        self.assertNotEqual(111, target)

    def test_bot_view_uses_owner_chat_for_direct_delivery(self):
        normalized = telegram_delivery.normalize_delivery_chat_id(
            sent_chat_id=9876543210,
            owner_id=111,
            user_session=True,
            private_chat=True,
            explicit_destination=None,
            dump_destination=None,
            bot_peer="@example_delivery_bot",
        )
        self.assertEqual(111, normalized)

    def test_legacy_owner_dump_is_redirected_from_saved_messages_to_bot(self):
        target = telegram_delivery.resolve_upload_chat_id(
            user_session=True,
            private_chat=True,
            explicit_destination=None,
            dump_destination=111,
            bot_peer="@example_delivery_bot",
            fallback_chat_id=111,
        )
        self.assertEqual("@example_delivery_bot", target)

    def test_private_hybrid_mode_stays_enabled_when_user_session_exists(self):
        self.assertEqual(
            "both",
            telegram_delivery.resolve_private_transmission_mode(
                "both", user_available=True
            ),
        )
        self.assertEqual(
            "bot",
            telegram_delivery.resolve_private_transmission_mode(
                "both", user_available=False
            ),
        )

    def test_explicit_destination_is_never_overridden(self):
        target = telegram_delivery.resolve_upload_chat_id(
            user_session=True,
            private_chat=True,
            explicit_destination=-1001234567890,
            dump_destination=None,
            bot_peer="@example_delivery_bot",
            fallback_chat_id=111,
        )
        self.assertEqual(-1001234567890, target)

    def test_bot_mode_keeps_private_recipient(self):
        target = telegram_delivery.resolve_upload_chat_id(
            user_session=False,
            private_chat=True,
            explicit_destination=None,
            dump_destination=None,
            bot_peer="@example_delivery_bot",
            fallback_chat_id=111,
        )
        self.assertEqual(111, target)

    def test_full_private_premium_route_keeps_4180mb_and_targets_bot(self):
        mode = telegram_delivery.resolve_private_transmission_mode(
            "both", user_available=True
        )
        configured_split = 4_180_000_000
        premium_max = 4_194_304_000
        effective_split = min(configured_split, premium_max)
        target = telegram_delivery.resolve_upload_chat_id(
            user_session=mode in {"user", "both"},
            private_chat=True,
            explicit_destination=None,
            dump_destination=111,
            bot_peer="@example_delivery_bot",
            fallback_chat_id=111,
        )

        self.assertEqual(4_180_000_000, effective_split)
        self.assertEqual("@example_delivery_bot", target)

    def test_upload_call_sites_keep_command_and_dump_destinations_separate(self):
        hyper = (
            Path(__file__).parents[1]
            / "bot"
            / "helper"
            / "ext_utils"
            / "hyperul_utils.py"
        ).read_text(encoding="utf-8")
        uploader = (
            Path(__file__).parents[1]
            / "bot"
            / "helper"
            / "mirror_leech_utils"
            / "upload_utils"
            / "telegram_uploader.py"
        ).read_text(encoding="utf-8")

        self.assertIn("explicit_destination=self._listener.cmd_up_dest", hyper)
        self.assertIn("explicit_destination=self._listener.cmd_up_dest", uploader)
        self.assertIn("is_saved_messages_destination(dest", uploader)
        self.assertIn("self._reply_context = build_upload_reply_context", uploader)
        self.assertIn("reply_target=self._reply_context.target", uploader)
        self.assertNotIn("reply_target=self._sent_msg", uploader)
        self.assertIn("upload_delivery_complete", uploader)
        self.assertIn("delivery_receipt_matches_route", uploader)
        self.assertIn("eligible_hyper_client_keys", hyper)

    def test_hyper_upload_log_uses_a_per_call_file_name(self):
        hyper = (
            Path(__file__).parents[1]
            / "bot"
            / "helper"
            / "ext_utils"
            / "hyperul_utils.py"
        ).read_text(encoding="utf-8")

        self.assertIn("upload_name = ospath.basename(file_path)", hyper)
        self.assertNotIn("self._up_file", hyper)


if __name__ == "__main__":
    unittest.main()
