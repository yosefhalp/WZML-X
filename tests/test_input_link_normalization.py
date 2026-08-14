import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "links_utils_normalization_test",
    ROOT / "bot" / "helper" / "ext_utils" / "links_utils.py",
)
LINKS = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = LINKS
SPEC.loader.exec_module(LINKS)

BULK_SPEC = importlib.util.spec_from_file_location(
    "bulk_links_normalization_test",
    ROOT / "bot" / "helper" / "ext_utils" / "bulk_links.py",
)


class InputLinkNormalizationTests(unittest.TestCase):
    def test_rtl_isolation_marks_are_removed_from_copied_url(self):
        original = "http://example.test/file\u2069\u2069"
        self.assertEqual("http://example.test/file", LINKS.normalize_external_link(original))

    def test_all_directional_controls_are_removed_without_changing_query(self):
        wrapped = "\u2067https://example.test/d/a?x=1%202&y=שלום\u2069"
        self.assertEqual(
            "https://example.test/d/a?x=1%202&y=שלום",
            LINKS.normalize_external_link(wrapped),
        )

    def test_magnet_and_nzb_links_keep_their_meaning(self):
        magnet = "magnet:?xt=urn:btih:ABC\u200f"
        nzb = "https://example.test/file.nzb\u202c"
        self.assertEqual("magnet:?xt=urn:btih:ABC", LINKS.normalize_external_link(magnet))
        self.assertEqual("https://example.test/file.nzb", LINKS.normalize_external_link(nzb))

    def test_bulk_source_uses_the_same_normalization(self):
        source = (ROOT / "bot" / "helper" / "ext_utils" / "bulk_links.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("normalize_external_link(item)", source)
        self.assertIn("normalize_external_link(line)", source)


if __name__ == "__main__":
    unittest.main()
