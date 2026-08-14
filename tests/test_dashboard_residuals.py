import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = (
    Path(__file__).parents[1]
    / "bot"
    / "helper"
    / "ext_utils"
    / "residual_downloads.py"
)
SPEC = importlib.util.spec_from_file_location("residual_downloads_test", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
clear_residual_downloads = MODULE.clear_residual_downloads
residual_download_status = MODULE.residual_download_status


class DashboardResidualTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "downloads"
        self.root.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def test_scan_separates_active_task_directory_from_residuals(self):
        active = self.root / "101"
        residual = self.root / "_incomplete"
        active.mkdir()
        residual.mkdir()
        (active / "active.bin").write_bytes(b"active")
        (residual / "stuck.bin").write_bytes(b"stuck")

        status = residual_download_status(self.root, active_task_ids={"101"})

        self.assertEqual(1, status["protected_entries"])
        self.assertEqual(1, status["entries"])
        self.assertEqual(5, status["bytes"])
        self.assertFalse(status["cleanup_allowed"])

    def test_cleanup_is_blocked_while_any_task_is_active(self):
        (self.root / "stale.bin").write_bytes(b"stale")
        with self.assertRaisesRegex(RuntimeError, "משימה פעילה"):
            clear_residual_downloads(self.root, active_task_ids={"999"})
        self.assertTrue((self.root / "stale.bin").exists())

    def test_cleanup_removes_residuals_but_keeps_download_root(self):
        residual = self.root / "_incomplete"
        residual.mkdir()
        (residual / "stuck.bin").write_bytes(b"123456")

        result = clear_residual_downloads(self.root, active_task_ids=set())

        self.assertTrue(self.root.is_dir())
        self.assertFalse(residual.exists())
        self.assertEqual(1, result["removed_entries"])
        self.assertEqual(1, result["removed_files"])
        self.assertEqual(6, result["removed_bytes"])


if __name__ == "__main__":
    unittest.main()
