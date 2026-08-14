import importlib.util
import ast
from pathlib import Path
from unittest import TestCase


MODEL_PATH = Path(__file__).parents[1] / "bot" / "modules" / "guided_ui_model.py"
SPEC = importlib.util.spec_from_file_location("guided_ui_model", MODEL_PATH)
MODEL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODEL)
ADVANCED_VALUE_OPTIONS = MODEL.ADVANCED_VALUE_OPTIONS
BOOLEAN_FLAGS = MODEL.BOOLEAN_FLAGS
SUPPORTED_MODES = MODEL.SUPPORTED_MODES
build_task_command = MODEL.build_task_command
guided_text_mode = MODEL.guided_text_mode
session_defaults = MODEL.session_defaults
task_route = MODEL.task_route
parse_ui_callback = MODEL.parse_ui_callback


class GuidedUiParameterTests(TestCase):
    def test_every_static_button_callback_is_valid(self):
        source_path = Path(__file__).parents[1] / "bot" / "modules" / "guided_ui.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        callback_values = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or len(node.args) < 2:
                continue
            if not isinstance(node.func, ast.Attribute) or node.func.attr != "data_button":
                continue
            if isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str):
                callback_values.append(node.args[1].value)
        self.assertGreater(len(callback_values), 40)
        for callback_data in callback_values:
            with self.subTest(callback_data=callback_data):
                parse_ui_callback(callback_data)

    def test_every_dynamic_button_parameter_is_valid(self):
        callbacks = [
            *(f"ui advancedtoggle {key}" for key in BOOLEAN_FLAGS),
            *(f"ui value {key}" for key in ADVANCED_VALUE_OPTIONS),
            *(f"ui valueclear {key}" for key in ADVANCED_VALUE_OPTIONS),
        ]
        for callback_data in callbacks:
            with self.subTest(callback_data=callback_data):
                parse_ui_callback(callback_data)

    def test_broken_or_unknown_button_parameters_are_rejected(self):
        for callback_data in (
            "",
            "ui",
            "ui source",
            "ui source unknown",
            "ui option unknown",
            "ui admin input",
            "ui admin input unknown",
            "ui backup delete",
            "ui quick unexpected",
        ):
            with self.subTest(callback_data=callback_data):
                with self.assertRaises(ValueError):
                    parse_ui_callback(callback_data)

    def test_every_source_mode_has_complete_defaults(self):
        for mode in SUPPORTED_MODES:
            with self.subTest(mode=mode):
                session = session_defaults(mode)
                self.assertEqual(mode, session["mode"])
                for key in BOOLEAN_FLAGS:
                    self.assertIn(key, session)
                for key in ADVANCED_VALUE_OPTIONS:
                    self.assertIn(key, session)

    def test_every_visible_route_maps_to_expected_engine(self):
        expected = {
            ("auto", "gofile"): ("/gofile", "uphoster"),
            ("torrent", "gofile"): ("/gofile", "qb_uphoster"),
            ("youtube", "cloud"): ("/ytdl", "ytdl"),
            ("youtube", "telegram"): ("/ytdlleech", "ytdl_leech"),
            ("jdownloader", "gofile"): ("/gofile", "jd_uphoster"),
            ("jdownloader", "cloud"): ("/jdmirror", "jd_mirror"),
            ("jdownloader", "telegram"): ("/jdleech", "jd_leech"),
            ("usenet", "gofile"): ("/gofile", "nzb_uphoster"),
            ("usenet", "cloud"): ("/nzbmirror", "nzb_mirror"),
            ("usenet", "telegram"): ("/nzbleech", "nzb_leech"),
            ("torrent", "cloud"): ("/qbmirror", "qb_mirror"),
            ("torrent", "telegram"): ("/qbleech", "qb_leech"),
            ("file", "cloud"): ("/mirror", "mirror"),
            ("file", "telegram"): ("/leech", "leech"),
            ("clone", "clone"): ("/clone", "clone_node"),
            ("gofile", "gofile"): ("/gofile", "uphoster"),
        }
        for route, result in expected.items():
            with self.subTest(route=route):
                self.assertEqual(result, task_route(*route))

    def test_gofile_engine_handlers_preserve_the_selected_downloader(self):
        source_path = Path(__file__).parents[1] / "bot" / "modules" / "mirror_leech.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        functions = {
            node.name: node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        expected_flags = {
            "qb_uphoster": {"is_qbit", "is_uphoster"},
            "jd_uphoster": {"is_jd", "is_uphoster"},
        }
        for handler, required_flags in expected_flags.items():
            with self.subTest(handler=handler):
                self.assertIn(handler, functions)
                enabled_flags = {
                    keyword.arg
                    for node in ast.walk(functions[handler])
                    if isinstance(node, ast.Call)
                    for keyword in node.keywords
                    if keyword.arg and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is True
                }
                self.assertTrue(required_flags.issubset(enabled_flags))

        nzb_handler = functions["nzb_uphoster"]
        delegated_calls = [
            node
            for node in ast.walk(nzb_handler)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_start_nzb_task"
        ]
        self.assertEqual(1, len(delegated_calls))
        self.assertTrue(
            any(
                keyword.arg == "is_uphoster"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
                for keyword in delegated_calls[0].keywords
            )
        )

    def test_jdownloader_configuration_button_has_a_valid_callback(self):
        self.assertEqual(("engine", ["jd"]), parse_ui_callback("ui engine jd"))

    def test_every_supported_source_has_a_fast_destination(self):
        for mode in SUPPORTED_MODES:
            with self.subTest(mode=mode):
                destination = "clone" if mode == "clone" else "gofile"
                command, handler = task_route(mode, destination)
                self.assertTrue(command.startswith("/"))
                self.assertTrue(handler)

    def test_every_regular_source_can_reach_telegram_and_cloud(self):
        for mode in SUPPORTED_MODES - {"clone", "gofile"}:
            for destination in ("telegram", "cloud"):
                with self.subTest(mode=mode, destination=destination):
                    command, handler = task_route(mode, destination)
                    self.assertTrue(command.startswith("/"))
                    self.assertTrue(handler)

    def test_every_boolean_parameter_reaches_the_command(self):
        for key, flag in BOOLEAN_FLAGS.items():
            with self.subTest(parameter=key):
                session = session_defaults("auto")
                session.update(destination="gofile", **{key: True})
                command, handler = build_task_command(session, "https://example.test/file")
                self.assertEqual("uphoster", handler)
                self.assertIn(flag, command.split())

    def test_every_advanced_value_reaches_the_command(self):
        for key, (_, flag, _) in ADVANCED_VALUE_OPTIONS.items():
            with self.subTest(parameter=key):
                mode = "torrent" if key == "seed_value" else "youtube"
                session = session_defaults(mode)
                session.update(destination="gofile", **{key: "test-value"})
                command, _ = build_task_command(session, "https://example.test/file")
                parts = command.split()
                self.assertIn(flag, parts)
                self.assertIn("test-value", parts)

    def test_boolean_fallback_parameters_reach_the_command(self):
        session = session_defaults("torrent")
        session.update(
            destination="gofile",
            extract=True,
            compress=True,
            join=True,
            sample=True,
            screenshots=True,
            seed=True,
        )
        command, _ = build_task_command(session, "magnet:?xt=test")
        for flag in ("-e", "-z", "-j", "-sv", "-ss", "-d"):
            self.assertIn(flag, command.split())

    def test_unknown_mode_and_destination_are_rejected(self):
        with self.assertRaises(ValueError):
            session_defaults("unknown")
        with self.assertRaises(ValueError):
            task_route("auto", "unknown")
        with self.assertRaises(ValueError):
            task_route("auto", "clone")

    def test_multiple_lines_are_mapped_to_the_existing_bulk_contract(self):
        mapped = guided_text_mode(
            "https://example.test/one\nhttps://example.test/two"
        )
        self.assertTrue(mapped["is_bulk"])
        self.assertTrue(mapped["reply_required"])
        self.assertEqual("", mapped["command_input"])
        self.assertEqual(2, mapped["link_count"])
        self.assertFalse(mapped["too_many"])

        session = session_defaults("auto")
        session.update(destination="telegram", bulk=True)
        command, _ = build_task_command(session, mapped["command_input"])
        self.assertIn("-b", command.split())

    def test_telegram_route_requires_explicit_source_and_target(self):
        session = session_defaults("auto")
        session.update(
            destination="telegram",
            upload_source="user",
            upload_target="private",
        )
        command, _ = build_task_command(session, "https://example.test/file")
        self.assertIn("-ut", command.split())
        self.assertIn("u:pm", command.split())
        self.assertNotIn("-bt", command.split())

        session.update(
            upload_source="bot",
            upload_target="channel",
            upload_channel="-1001234567890",
        )
        command, _ = build_task_command(session, "https://example.test/file")
        self.assertIn("-bt", command.split())
        self.assertIn("b:-1001234567890", command.split())
        self.assertNotIn("-ut", command.split())

    def test_telegram_source_target_callbacks_are_valid(self):
        for callback in (
            "ui tgsource bot",
            "ui tgsource user",
            "ui tgtarget private",
            "ui tgtarget connect",
            "ui tgchannel 0",
        ):
            with self.subTest(callback=callback):
                parse_ui_callback(callback)

    def test_guided_bulk_limit_is_reported_before_dispatch(self):
        mapped = guided_text_mode(
            "\n".join(f"https://example.test/{index}" for index in range(51))
        )
        self.assertEqual(51, mapped["link_count"])
        self.assertTrue(mapped["is_bulk"])
        self.assertTrue(mapped["too_many"])
