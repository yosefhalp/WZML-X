"""מנהל releases אטומי ל-WZML-X, עם בדיקות בריאות ו-rollback אוטומטי."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

try:
    import fcntl
except ImportError:  # pragma: no cover - מנגנון הפריסה עצמו מיועד לשרת Linux.
    fcntl = None

from deployment_profile import DeploymentProfileError, load_env, require_valid


RELEASE_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")


class DeploymentError(RuntimeError):
    """שגיאה בטוחה שמפסיקה את הפריסה לפני השארת מצב חלקי."""


def atomic_json(path: Path, payload: dict) -> None:
    """כותב מצב באופן אטומי ובהרשאת 0600."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def read_state(values: dict[str, str]) -> dict:
    """קורא מצב קיים; קובץ פגום אינו מוחלף בשקט במצב ריק."""

    path = Path(values["DEPLOYMENT_STATE_FILE"])
    if not path.exists():
        return {"version": 1, "current": None, "previous": None}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DeploymentError(f"קובץ מצב הפריסה פגום: {path}") from error
    if state.get("version") != 1:
        raise DeploymentError("גרסת קובץ מצב הפריסה אינה נתמכת")
    return state


@contextlib.contextmanager
def deployment_lock(values: dict[str, str]):
    """מונע משתי פעולות לשנות את אותה פריסה במקביל."""

    if fcntl is None:
        raise DeploymentError("נעילת הפריסה זמינה רק בשרת Linux")
    lock_path = Path(values["DEPLOYMENT_LOCK_FILE"])
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise DeploymentError("פעולת פריסה אחרת כבר מתבצעת") from error
        yield


def run(command: list[str], *, cwd: Path | None = None) -> None:
    """מריץ פקודה בלי shell כדי שערכים מהפרופיל לא יהפכו לקוד."""

    result = subprocess.run(command, cwd=cwd, text=True, check=False)
    if result.returncode:
        raise DeploymentError(f"הפקודה נכשלה עם קוד {result.returncode}: {' '.join(command[:4])}")


def compose_command(values: dict[str, str], release: Path) -> list[str]:
    """בונה פקודת Compose עם project ו-env ייחודיים לפריסה."""

    profile_path = release / ".deployment.env"
    compose_path = release / values["DEPLOYMENT_COMPOSE_FILE"]
    if not profile_path.is_file() or not compose_path.is_file():
        raise DeploymentError("ב-release חסרים קובץ הפריסה או קובץ Compose")
    return [
        "docker",
        "compose",
        "--project-name",
        values["DEPLOYMENT_COMPOSE_PROJECT"],
        "--env-file",
        str(profile_path),
        "-f",
        str(compose_path),
    ]


def safe_extract(archive: Path, target: Path) -> None:
    """מחלץ ארכיון קוד בלי לאפשר יציאה מהיעד או קישורים עוקפים."""

    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle.getmembers():
            member_path = PurePosixPath(member.name)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise DeploymentError(f"נתיב לא בטוח בארכיון: {member.name}")
            if member.issym() or member.islnk() or member.isdev():
                raise DeploymentError(f"סוג קובץ אסור בארכיון: {member.name}")
        bundle.extractall(target, filter="data")


def write_release_profile(source: Path, release: Path) -> None:
    """מקבע עותק פרטי של מפת הפריסה לצד ה-release לצורך rollback עתידי."""

    target = release / ".deployment.env"
    shutil.copyfile(source, target)
    os.chmod(target, 0o600)


def check_url(
    url: str,
    *,
    attempts: int = 1,
    delay: float = 1.0,
    expected_release: str | None = None,
) -> None:
    """בודק נגישות HTTP; תשובת 4xx מוכיחה שהשירות נגיש, 5xx אינה בריאה."""

    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            with urlopen(url, timeout=3) as response:
                body = response.read()
                if response.status < 500:
                    if expected_release:
                        try:
                            payload = json.loads(body.decode("utf-8"))
                        except (UnicodeDecodeError, json.JSONDecodeError) as error:
                            raise DeploymentError("בדיקת הבריאות לא החזירה JSON עם מזהה release") from error
                        if payload.get("release_id") != expected_release:
                            last_error = DeploymentError("השירות עונה אך עדיין מריץ release אחר")
                        else:
                            return
                    else:
                        return
        except HTTPError as error:
            if error.code < 500 and not expected_release:
                return
            last_error = error
        except (URLError, TimeoutError, OSError) as error:
            last_error = error
        time.sleep(delay)
    raise DeploymentError(f"בדיקת HTTP נכשלה עבור {url}: {last_error}")


def preflight(values: dict[str, str]) -> None:
    """בודק תלויות וסודות לפני build או שינוי symlink."""

    if shutil.which("docker") is None:
        raise DeploymentError("Docker אינו מותקן")
    run(["docker", "compose", "version"])
    if values["WZMLX_BOT_API_MODE"] == "external":
        check_url(values["WZMLX_BOT_API_BASE_URL"])
    if values.get("DEPLOYMENT_TEST_MODE") == "1":
        return
    required = (
        "WZMLX_CONFIG_PATH",
        "WZMLX_ENV_PATH",
        "WZMLX_MONGO_ENV_PATH",
        "WZMLX_ACCOUNTS_DIR",
    )
    missing = [key for key in required if not Path(values[key]).exists()]
    if missing:
        raise DeploymentError("כספת השרת אינה שלמה: " + ", ".join(missing))


def prepare_directories(values: dict[str, str]) -> None:
    """יוצר רק את מבנה הפריסה שהוגדר במפה המאומתת."""

    for key in ("DEPLOYMENT_ROOT", "DEPLOYMENT_SHARED_DIR", "DEPLOYMENT_RELEASES_DIR", "DEPLOYMENT_BACKUP_DIR"):
        path = Path(values[key])
        path.mkdir(parents=True, exist_ok=True)
        os.chmod(path, 0o700)
    marker = Path(values["DEPLOYMENT_ROOT"]) / ".deployment-owner"
    if marker.exists() and marker.read_text(encoding="utf-8").strip() != values["DEPLOYMENT_NAME"]:
        raise DeploymentError("תיקיית השורש שייכת לפריסה אחרת")
    if not marker.exists():
        marker.write_text(values["DEPLOYMENT_NAME"] + "\n", encoding="utf-8")
        os.chmod(marker, 0o600)


def switch_current(link: Path, release: Path) -> None:
    """מחליף symlink אטומית בלי למחוק את ה-release הקודם."""

    temporary = link.with_name(f".{link.name}.next")
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(release, target_is_directory=True)
    os.replace(temporary, link)


def health(values: dict[str, str], attempts: int = 30, expected_release: str | None = None) -> None:
    """ממתין לבריאות השירות לאחר החלפת release."""

    required_release = expected_release if values.get("DEPLOYMENT_HEALTH_VERIFY_RELEASE") == "1" else None
    check_url(
        values["DEPLOYMENT_HEALTH_URL"],
        attempts=attempts,
        delay=1.0,
        expected_release=required_release,
    )


def activate(values: dict[str, str], release: Path) -> None:
    """מפעיל release שכבר נבנה ומאמת אותו."""

    switch_current(Path(values["DEPLOYMENT_CURRENT_LINK"]), release)
    command = compose_command(values, release)
    run(command + ["up", "-d", "--force-recreate"], cwd=release)
    health(values, expected_release=release.name)


def prune_releases(values: dict[str, str], protected: set[str]) -> None:
    """שומר releases אחרונים ולעולם אינו מוחק current או previous."""

    keep = int(values["DEPLOYMENT_KEEP_RELEASES"])
    releases = [path for path in Path(values["DEPLOYMENT_RELEASES_DIR"]).iterdir() if path.is_dir() and RELEASE_PATTERN.fullmatch(path.name)]
    releases.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    for path in releases[keep:]:
        if path.name not in protected:
            shutil.rmtree(path)


def deploy(values: dict[str, str], profile_path: Path, archive: Path, release_id: str) -> None:
    """בונה release חדש ומחזיר את הקודם אוטומטית אם ההפעלה נכשלת."""

    if not RELEASE_PATTERN.fullmatch(release_id):
        raise DeploymentError("מזהה release אינו בטוח")
    preflight(values)
    prepare_directories(values)
    releases_root = Path(values["DEPLOYMENT_RELEASES_DIR"])
    release = releases_root / release_id
    if release.exists():
        raise DeploymentError(f"ה-release כבר קיים: {release_id}")
    state = read_state(values)
    previous_id = state.get("current")
    previous_release = releases_root / previous_id if previous_id else None
    try:
        release.mkdir(mode=0o700)
        safe_extract(archive, release)
        (release / ".release-id").write_text(release_id + "\n", encoding="utf-8")
        write_release_profile(profile_path, release)
        command = compose_command(values, release)
        run(command + ["config", "--quiet"], cwd=release)
        run(command + ["build"], cwd=release)
        activate(values, release)
    except Exception:
        if previous_release and previous_release.is_dir():
            previous_values = load_env(previous_release / ".deployment.env")
            activate(previous_values, previous_release)
        else:
            with contextlib.suppress(Exception):
                run(compose_command(values, release) + ["down"], cwd=release)
        raise
    new_state = {
        "version": 1,
        "current": release_id,
        "previous": previous_id,
        "updated_at": int(time.time()),
    }
    atomic_json(Path(values["DEPLOYMENT_STATE_FILE"]), new_state)
    prune_releases(values, {item for item in (release_id, previous_id) if item})


def rollback(values: dict[str, str]) -> None:
    """מחליף בין current ל-previous ושומר אפשרות לחזור שוב."""

    state = read_state(values)
    target_id = state.get("previous")
    current_id = state.get("current")
    if not target_id or not current_id:
        raise DeploymentError("אין release קודם זמין ל-rollback")
    target = Path(values["DEPLOYMENT_RELEASES_DIR"]) / target_id
    if not target.is_dir():
        raise DeploymentError("תיקיית ה-release הקודם חסרה")
    target_values = load_env(target / ".deployment.env")
    require_valid(target_values)
    preflight(target_values)
    activate(target_values, target)
    atomic_json(
        Path(values["DEPLOYMENT_STATE_FILE"]),
        {"version": 1, "current": target_id, "previous": current_id, "updated_at": int(time.time())},
    )


def status(values: dict[str, str]) -> dict:
    """מחזיר מצב מבני בטוח בלי להדפיס סודות."""

    state = read_state(values)
    return {
        "deployment": values["DEPLOYMENT_NAME"],
        "root": values["DEPLOYMENT_ROOT"],
        "bot_api_mode": values["WZMLX_BOT_API_MODE"],
        "current": state.get("current"),
        "previous": state.get("previous"),
        "current_link_exists": Path(values["DEPLOYMENT_CURRENT_LINK"]).is_symlink(),
    }


def cleanup(values: dict[str, str], confirm: str) -> None:
    """מסיר רק את הפריסה המזוהה, בלי לגעת ב-Local Bot API חיצוני או ב-volumes."""

    if confirm != values["DEPLOYMENT_NAME"]:
        raise DeploymentError("אישור הניקוי אינו תואם לשם הפריסה")
    root = Path(values["DEPLOYMENT_ROOT"])
    marker = root / ".deployment-owner"
    if not marker.is_file() or marker.read_text(encoding="utf-8").strip() != values["DEPLOYMENT_NAME"]:
        raise DeploymentError("סמן הבעלות של תיקיית הפריסה חסר או אינו תואם")
    state = read_state(values)
    current_id = state.get("current")
    if current_id:
        release = Path(values["DEPLOYMENT_RELEASES_DIR"]) / current_id
        if release.is_dir():
            current_values = load_env(release / ".deployment.env")
            run(compose_command(current_values, release) + ["down", "--remove-orphans"], cwd=release)
    shutil.rmtree(root)


def main() -> int:
    parser = argparse.ArgumentParser(description="מנהל פריסות ניידות של WZML-X")
    parser.add_argument("--env", required=True, type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("bootstrap")
    deploy_parser = subparsers.add_parser("deploy")
    deploy_parser.add_argument("--archive", required=True, type=Path)
    deploy_parser.add_argument("--release-id", required=True)
    subparsers.add_parser("rollback")
    subparsers.add_parser("status")
    cleanup_parser = subparsers.add_parser("cleanup")
    cleanup_parser.add_argument("--confirm", required=True)
    arguments = parser.parse_args()

    try:
        values = load_env(arguments.env)
        require_valid(values)
        with deployment_lock(values):
            if arguments.command == "bootstrap":
                prepare_directories(values)
                preflight(values)
            elif arguments.command == "deploy":
                deploy(values, arguments.env, arguments.archive, arguments.release_id)
            elif arguments.command == "rollback":
                rollback(values)
            elif arguments.command == "cleanup":
                cleanup(values, arguments.confirm)
            else:
                print(json.dumps(status(values), ensure_ascii=False, indent=2))
    except (DeploymentError, DeploymentProfileError) as error:
        print(f"הפעולה נכשלה בבטחה: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
