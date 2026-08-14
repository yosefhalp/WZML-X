import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase


MODULE_PATH = Path(__file__).parents[1] / "bot" / "helper" / "ext_utils" / "cache_manager.py"
SPEC = importlib.util.spec_from_file_location("cache_manager", MODULE_PATH)
CACHE_MANAGER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CACHE_MANAGER)


class CacheManagerTests(TestCase):
    def test_only_python_cache_is_removed(self):
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            cache = root / "bot" / "__pycache__"
            cache.mkdir(parents=True)
            (cache / "module.pyc").write_bytes(b"cache-data")
            source = root / "bot" / "module.py"
            source.write_text("print('safe')", encoding="utf-8")
            result = CACHE_MANAGER.clear_filesystem_cache(root)
            self.assertFalse(cache.exists())
            self.assertTrue(source.exists())
            self.assertEqual(1, result["directories"])
            self.assertEqual(len(b"cache-data"), result["bytes"])

    def test_protected_user_data_is_never_removed(self):
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            protected_files = {
                "downloads/__pycache__/movie.part": b"movie",
                "accounts/__pycache__/session": b"session",
                "tokens/__pycache__/token.pickle": b"token",
                "thumbnails/__pycache__/thumb.jpg": b"image",
                "runtime/__pycache__/backup-status.json": b"state",
            }
            for relative_path, contents in protected_files.items():
                path = root / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(contents)
            CACHE_MANAGER.clear_filesystem_cache(root)
            for relative_path, contents in protected_files.items():
                self.assertEqual(contents, (root / relative_path).read_bytes())
