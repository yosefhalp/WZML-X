import tempfile
import unittest
from pathlib import Path

from web.health_state import read_release_id


ROOT = Path(__file__).parents[1]
WEB_SERVER = ROOT / "web" / "wserver.py"


class ProductionHealthReleaseIdTests(unittest.TestCase):
    def test_reads_the_release_id_created_by_the_deployer(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / ".release-id"
            marker.write_text("87fe16c2d311\n", encoding="utf-8")
            self.assertEqual("87fe16c2d311", read_release_id(marker))

    def test_missing_or_invalid_marker_is_reported_as_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / ".release-id"
            self.assertEqual("unknown", read_release_id(marker))
            marker.write_text("../../not-a-release\n", encoding="utf-8")
            self.assertEqual("unknown", read_release_id(marker))

    def test_production_health_payload_exposes_the_release_id(self):
        source = WEB_SERVER.read_text(encoding="utf-8")
        self.assertIn('"release_id": read_release_id()', source)
        self.assertIn("from web.health_state import read_release_id", source)


if __name__ == "__main__":
    unittest.main()
