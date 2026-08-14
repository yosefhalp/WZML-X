import importlib.util
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "deploy" / "server"
sys.path.insert(0, str(SERVER_DIR))
SPEC = importlib.util.spec_from_file_location("migration_bundle", SERVER_DIR / "migration_bundle.py")
migration_bundle = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(migration_bundle)


class MigrationBundleTests(unittest.TestCase):
    def test_envelope_contains_only_manifest_source_map_and_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backup = root / "backup.tar.gz"
            backup.write_bytes(b"opaque-backup")
            envelope = root / "envelope.tar.gz"
            manifest = migration_bundle.create_envelope(
                backup,
                SERVER_DIR / "deployment.env.example",
                envelope,
            )
            with tarfile.open(envelope, "r:gz") as bundle:
                self.assertEqual(
                    {"manifest.json", "source-deployment.env", "backup.archive"},
                    set(bundle.getnames()),
                )
            self.assertEqual("wzmlx-primary", manifest["source_deployment"])

    def test_modified_payload_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backup = root / "backup.tar.gz"
            backup.write_bytes(b"original")
            envelope = root / "envelope.tar.gz"
            migration_bundle.create_envelope(backup, SERVER_DIR / "deployment.env.example", envelope)
            extracted = root / "extracted"
            extracted.mkdir()
            migration_bundle.safe_extract(envelope, extracted)
            (extracted / "backup.archive").write_bytes(b"modified")
            # אורזים מחדש כדי לוודא שהבדיקה נשענת על הטביעות ולא על הארכיון המקורי.
            modified = root / "modified.tar.gz"
            with tarfile.open(modified, "w:gz") as bundle:
                for path in extracted.iterdir():
                    bundle.add(path, arcname=path.name, recursive=False)
            validation = root / "validation"
            validation.mkdir()
            with self.assertRaises(migration_bundle.MigrationError):
                migration_bundle.validate_envelope(modified, validation)

    def test_wrong_confirmation_stops_before_decryption(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(migration_bundle.MigrationError):
                migration_bundle.extract_bundle(
                    root / "missing.age",
                    root / "missing.key",
                    root / "output",
                    target_root="/srv/new",
                    name="new-server",
                    port_base=18080,
                    bot_api_url="http://127.0.0.1:28081",
                    confirm="wrong-server",
                )
            self.assertFalse((root / "output").exists())


if __name__ == "__main__":
    unittest.main()
