"""יצירה, אימות וחילוץ של חבילת ניוד מוצפנת בין שרתי WZML-X."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path, PurePosixPath

from deployment_profile import adapt, load_env, require_valid, write_env


class MigrationError(RuntimeError):
    """שגיאה שמונעת שימוש בחבילת ניוד לא שלמה או לא מאומתת."""


def sha256(path: Path) -> str:
    """מחשב טביעת תוכן מלאה בלי לטעון קובץ גדול לזיכרון."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(command: list[str]) -> None:
    """מריץ age ללא shell כדי שמזהים ונתיבים לא יהפכו לפקודות."""

    result = subprocess.run(command, text=True, check=False, capture_output=True)
    if result.returncode:
        raise MigrationError(f"פקודת ההצפנה נכשלה: {result.stderr.strip()}")


def safe_extract(archive: Path, target: Path) -> None:
    """מחלץ מעטפת רק לאחר חסימת נתיבים וקישורים מסוכנים."""

    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle.getmembers():
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or member.issym() or member.islnk() or member.isdev():
                raise MigrationError(f"פריט לא בטוח במעטפה: {member.name}")
        bundle.extractall(target, filter="data")


def create_envelope(backup: Path, deployment_env: Path, envelope: Path) -> dict:
    """יוצר מעטפת פנימית עם manifest וטביעות, לפני הצפנה."""

    if not backup.is_file() or not deployment_env.is_file():
        raise MigrationError("קובץ הגיבוי או מפת המקור חסרים")
    values = load_env(deployment_env)
    require_valid(values)
    with tempfile.TemporaryDirectory() as directory:
        payload = Path(directory) / "payload"
        payload.mkdir(mode=0o700)
        backup_target = payload / "backup.archive"
        env_target = payload / "source-deployment.env"
        shutil.copyfile(backup, backup_target)
        shutil.copyfile(deployment_env, env_target)
        os.chmod(env_target, 0o600)
        manifest = {
            "schema": 1,
            "created_at": int(time.time()),
            "source_deployment": values["DEPLOYMENT_NAME"],
            "files": {
                "backup.archive": {"role": "full_backup", "sha256": sha256(backup_target)},
                "source-deployment.env": {"role": "source_map", "sha256": sha256(env_target)},
            },
        }
        manifest_path = payload / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        with tarfile.open(envelope, "w:gz") as bundle:
            for path in sorted(payload.iterdir()):
                bundle.add(path, arcname=path.name, recursive=False)
    return manifest


def validate_envelope(envelope: Path, target: Path) -> dict:
    """מאמת schema וטביעות לפני מסירת חומר השחזור."""

    safe_extract(envelope, target)
    manifest_path = target / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MigrationError("manifest חסר או פגום") from error
    if manifest.get("schema") != 1 or not isinstance(manifest.get("files"), dict):
        raise MigrationError("גרסת manifest אינה נתמכת")
    expected_names = {"backup.archive", "source-deployment.env"}
    if set(manifest["files"]) != expected_names:
        raise MigrationError("רשימת הקבצים בחבילה אינה מדויקת")
    actual_names = {path.name for path in target.iterdir() if path.name != "manifest.json"}
    if actual_names != expected_names:
        raise MigrationError("המעטפה מכילה קבצים לא מוכרים")
    for name, metadata in manifest["files"].items():
        if sha256(target / name) != metadata.get("sha256"):
            raise MigrationError(f"טביעת הקובץ אינה תואמת: {name}")
    source_values = load_env(target / "source-deployment.env")
    require_valid(source_values)
    return manifest


def encrypt(backup: Path, deployment_env: Path, recipient: str, output: Path) -> dict:
    """יוצר חבילה מוצפנת ל-recipient; המעטפה הגלויה נמחקת מיד."""

    if shutil.which("age") is None:
        raise MigrationError("הכלי age אינו מותקן")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        envelope = Path(directory) / "migration-envelope.tar.gz"
        manifest = create_envelope(backup, deployment_env, envelope)
        run(["age", "-r", recipient, "-o", str(output), str(envelope)])
    os.chmod(output, 0o600)
    return manifest


def decrypt(bundle: Path, identity: Path, output: Path) -> None:
    """מפענח חבילה לקובץ זמני בלבד באמצעות זהות מקומית פרטית."""

    if shutil.which("age") is None:
        raise MigrationError("הכלי age אינו מותקן")
    if not bundle.is_file() or not identity.is_file():
        raise MigrationError("חבילת הניוד או זהות הפענוח חסרות")
    run(["age", "-d", "-i", str(identity), "-o", str(output), str(bundle)])


def inspect_bundle(bundle: Path, identity: Path) -> dict:
    """מפענח זמנית ומחזיר manifest מאומת בלי להשאיר סודות בדיסק הקבוע."""

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        envelope = root / "envelope.tar.gz"
        extracted = root / "extracted"
        extracted.mkdir()
        decrypt(bundle, identity, envelope)
        return validate_envelope(envelope, extracted)


def extract_bundle(
    bundle: Path,
    identity: Path,
    target: Path,
    *,
    target_root: str,
    name: str,
    port_base: int,
    bot_api_url: str | None,
    confirm: str,
) -> dict:
    """מוציא גיבוי ומייצר מפת יעד חדשה במקום לשכפל נתיבי שרת ישנים."""

    if confirm != name:
        raise MigrationError("האישור אינו תואם לשם פריסת היעד")
    if target.exists() and any(target.iterdir()):
        raise MigrationError("תיקיית החילוץ אינה ריקה")
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        envelope = root / "envelope.tar.gz"
        extracted = root / "extracted"
        extracted.mkdir()
        decrypt(bundle, identity, envelope)
        manifest = validate_envelope(envelope, extracted)
        source_values = load_env(extracted / "source-deployment.env")
        target_values = adapt(
            source_values,
            target_root=target_root,
            name=name,
            port_base=port_base,
            bot_api_url=bot_api_url,
        )
        shutil.copyfile(extracted / "backup.archive", target / "backup.archive")
        write_env(target / "deployment.env", target_values)
        (target / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.chmod(target / "manifest.json", 0o600)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="חבילת ניוד מוצפנת של WZML-X")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create_parser = subparsers.add_parser("create")
    create_parser.add_argument("--backup", required=True, type=Path)
    create_parser.add_argument("--deployment-env", required=True, type=Path)
    create_parser.add_argument("--recipient", required=True)
    create_parser.add_argument("--output", required=True, type=Path)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--bundle", required=True, type=Path)
    verify_parser.add_argument("--identity", required=True, type=Path)
    extract_parser = subparsers.add_parser("extract")
    extract_parser.add_argument("--bundle", required=True, type=Path)
    extract_parser.add_argument("--identity", required=True, type=Path)
    extract_parser.add_argument("--target", required=True, type=Path)
    extract_parser.add_argument("--target-root", required=True)
    extract_parser.add_argument("--name", required=True)
    extract_parser.add_argument("--port-base", required=True, type=int)
    extract_parser.add_argument("--bot-api-url")
    extract_parser.add_argument("--confirm", required=True)
    arguments = parser.parse_args()
    try:
        if arguments.command == "create":
            manifest = encrypt(arguments.backup, arguments.deployment_env, arguments.recipient, arguments.output)
        elif arguments.command == "verify":
            manifest = inspect_bundle(arguments.bundle, arguments.identity)
        else:
            manifest = extract_bundle(
                arguments.bundle,
                arguments.identity,
                arguments.target,
                target_root=arguments.target_root,
                name=arguments.name,
                port_base=arguments.port_base,
                bot_api_url=arguments.bot_api_url,
                confirm=arguments.confirm,
            )
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
    except MigrationError as error:
        print(f"חבילת הניוד נדחתה בבטחה: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
