import importlib.util
from pathlib import Path
from unittest import TestCase


MODULE_PATH = Path(__file__).parents[1] / "bot" / "helper" / "ext_utils" / "status_view.py"
SPEC = importlib.util.spec_from_file_location("status_view", MODULE_PATH)
STATUS_VIEW = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STATUS_VIEW)


class StatusRtlTests(TestCase):
    def test_technical_value_is_explicitly_ltr(self):
        rendered = STATUS_VIEW.ltr_code("702.4 Mbps / ETA 1h20m")
        self.assertIn(STATUS_VIEW.LRI, rendered)
        self.assertIn(STATUS_VIEW.PDI, rendered)
        self.assertTrue(rendered.startswith("<code>"))

    def test_hebrew_label_is_explicitly_rtl(self):
        rendered = STATUS_VIEW.value_line("מהירות", "25.5 MB/s")
        self.assertIn(STATUS_VIEW.RLI, rendered)
        self.assertIn(STATUS_VIEW.LRI, rendered)
        self.assertLess(rendered.index(STATUS_VIEW.RLI), rendered.index(STATUS_VIEW.LRI))

    def test_dynamic_values_are_html_escaped(self):
        rendered = STATUS_VIEW.ltr_text("<bad>&value")
        self.assertNotIn("<bad>", rendered)
        self.assertIn("&lt;bad&gt;&amp;value", rendered)

    def test_all_internal_statuses_have_hebrew_labels(self):
        required = {
            "Upload",
            "Download",
            "Clone",
            "QueueDl",
            "QueueUp",
            "Pause",
            "Archive",
            "Extract",
            "Split",
            "CheckUp",
            "Seed",
            "SamVid",
            "Convert",
            "FFmpeg",
            "YouTube",
            "Metadata",
        }
        self.assertTrue(required.issubset(STATUS_VIEW.STATUS_LABELS))
        for value in required:
            self.assertNotEqual(value, STATUS_VIEW.status_label(value))
