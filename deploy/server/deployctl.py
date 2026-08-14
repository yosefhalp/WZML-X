"""בקר מקומי לפריסה, עדכון ו-rollback דרך פרופיל SSH פרטי."""

from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path, PurePosixPath


PROFILE_KEYS = (
    "CONTROLLER_PROFILE_VERSION",
    "CONTROLLER_NAME",
    "SSH_HOST",
    "SSH_PORT",
    "SSH_USER",
    "SSH_IDENTITY_FILE",
    "SSH_KNOWN_HOSTS_FILE",
    "SSH_HOST_KEY_SHA256",
    "LOCAL_DEPLOYMENT_ENV_FILE",
    "REMOTE_DEPLOYMENT_ENV",
    "REMOTE_CONTROLLER_DIR",
    "REPOSITORY_URL",
    "REPOSITORY_BRANCH",
)
SAFE_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{1,127}$")


class ControllerError(RuntimeError):
    """שגיאה שעוצרת פעולה מקומית לפני שינוי שרת לא מזוהה."""


def load_profile(path: Path) -> dict[str, str]:
    """קורא פרופיל בלי להפעיל shell ובלי לקבל מפתחות כפולים."""

    if not path.is_file():
        raise ControllerError(f"פרופיל הבקר אינו קיים: {path}")
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ControllerError(f"שורה {line_number} אינה במבנה KEY=VALUE")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or key in values:
            raise ControllerError(f"משתנה לא תקין או כפול בשורה {line_number}")
        values[key] = value
    missing = [key for key in PROFILE_KEYS if not values.get(key)]
    if missing:
        raise ControllerError("בפרופיל הבקר חסרים: " + ", ".join(missing))
    if values["CONTROLLER_PROFILE_VERSION"] != "1":
        raise ControllerError("גרסת פרופיל הבקר אינה נתמכת")
    if not SAFE_NAME.fullmatch(values["CONTROLLER_NAME"]):
        raise ControllerError("CONTROLLER_NAME אינו בטוח")
    try:
        port = int(values["SSH_PORT"])
    except ValueError as error:
        raise ControllerError("SSH_PORT חייב להיות מספר") from error
    if not 1 <= port <= 65535:
        raise ControllerError("SSH_PORT מחוץ לטווח")
    for key in ("REMOTE_DEPLOYMENT_ENV", "REMOTE_CONTROLLER_DIR"):
        remote_path = PurePosixPath(values[key])
        if not remote_path.is_absolute() or ".." in remote_path.parts:
            raise ControllerError(f"{key} חייב להיות נתיב מוחלט ובטוח")
    return values


def run(command: list[str], *, cwd: Path | None = None, capture: bool = False) -> str:
    """מריץ כלי מקומי בלי shell ומחזיר פלט רק כשנדרש לאימות."""

    result = subprocess.run(command, cwd=cwd, text=True, capture_output=capture, check=False)
    if result.returncode:
        message = result.stderr.strip() if capture else f"קוד {result.returncode}"
        raise ControllerError(f"פקודה מקומית נכשלה: {command[0]} ({message})")
    return result.stdout.strip() if capture else ""


def verify_local_files(values: dict[str, str]) -> None:
    """מאמת מפתח, known_hosts ומפת יעד לפני התחברות."""

    for key in ("SSH_IDENTITY_FILE", "SSH_KNOWN_HOSTS_FILE", "LOCAL_DEPLOYMENT_ENV_FILE"):
        path = Path(values[key])
        if not path.is_file():
            raise ControllerError(f"הקובץ של {key} אינו קיים: {path}")
    known_hosts = Path(values["SSH_KNOWN_HOSTS_FILE"])
    fingerprints = run(["ssh-keygen", "-lf", str(known_hosts)], capture=True)
    expected = values["SSH_HOST_KEY_SHA256"]
    if expected not in fingerprints:
        raise ControllerError("טביעת מפתח השרת אינה תואמת ל-known_hosts המוצמד")
    if os.name != "nt":
        for key in ("SSH_IDENTITY_FILE", "LOCAL_DEPLOYMENT_ENV_FILE"):
            if Path(values[key]).stat().st_mode & 0o077:
                raise ControllerError(f"ההרשאות של {key} פתוחות מדי; נדרשת 0600")


def ssh_base(values: dict[str, str]) -> list[str]:
    """בונה חיבור SSH קשיח שאינו חוזר לסיסמה או למפתח אחר."""

    return [
        "ssh",
        "-p",
        values["SSH_PORT"],
        "-i",
        values["SSH_IDENTITY_FILE"],
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        f"UserKnownHostsFile={values['SSH_KNOWN_HOSTS_FILE']}",
        f"{values['SSH_USER']}@{values['SSH_HOST']}",
    ]


def scp_base(values: dict[str, str]) -> list[str]:
    """בונה העתקה מאובטחת עם אותם כללי זהות של SSH."""

    return [
        "scp",
        "-P",
        values["SSH_PORT"],
        "-i",
        values["SSH_IDENTITY_FILE"],
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        f"UserKnownHostsFile={values['SSH_KNOWN_HOSTS_FILE']}",
    ]


def remote(values: dict[str, str], arguments: list[str], *, capture: bool = False) -> str:
    """מריץ argv מרוחק כשהערכים מצוטטים בנפרד."""

    command = " ".join(shlex.quote(argument) for argument in arguments)
    return run(ssh_base(values) + [command], capture=capture)


def upload(values: dict[str, str], source: Path, destination: str) -> None:
    """מעלה קובץ יחיד ליעד שכבר אומת בפרופיל."""

    target = f"{values['SSH_USER']}@{values['SSH_HOST']}:{destination}"
    run(scp_base(values) + [str(source), target])


def repository_files(repository: Path) -> list[Path]:
    """מחזיר קבצים עקובים וחדשים שאינם מוחרגים; סודות ב-gitignore לא נכללים."""

    output = run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=repository,
        capture=True,
    )
    return [repository / item for item in output.split("\0") if item]


def package_repository(repository: Path, output: Path) -> str:
    """אורז את עותק העבודה הנוכחי ומחזיר מזהה release ניתן למעקב."""

    revision = run(["git", "rev-parse", "--short=12", "HEAD"], cwd=repository, capture=True)
    dirty = run(["git", "status", "--porcelain"], cwd=repository, capture=True)
    suffix = f"-worktree-{int(time.time())}" if dirty else ""
    release_id = f"{revision}{suffix}"
    with tarfile.open(output, "w:gz") as bundle:
        for path in repository_files(repository):
            if path.is_file():
                bundle.add(path, arcname=path.relative_to(repository).as_posix(), recursive=False)
    return release_id


def install_controller(values: dict[str, str], repository: Path) -> None:
    """מעלה את מנגנון השרת ואת מפת היעד הפרטית בהרשאות מצומצמות."""

    remote_dir = values["REMOTE_CONTROLLER_DIR"]
    deployment_env_parent = str(PurePosixPath(values["REMOTE_DEPLOYMENT_ENV"]).parent)
    remote(values, ["mkdir", "-p", remote_dir, deployment_env_parent])
    for name in ("deployment_profile.py", "portable_deploy.py"):
        upload(values, repository / "deploy" / "server" / name, f"{remote_dir}/{name}")
    temporary_env = f"{remote_dir}/deployment.env.incoming"
    upload(values, Path(values["LOCAL_DEPLOYMENT_ENV_FILE"]), temporary_env)
    remote(values, ["install", "-m", "600", temporary_env, values["REMOTE_DEPLOYMENT_ENV"]])
    remote(values, ["rm", "-f", temporary_env])


def invoke_server(values: dict[str, str], arguments: list[str], *, capture: bool = False) -> str:
    """מפעיל את מנהל הפריסה המרוחק מול מפת השרת הקבועה."""

    script = f"{values['REMOTE_CONTROLLER_DIR']}/portable_deploy.py"
    return remote(values, ["python3", script, "--env", values["REMOTE_DEPLOYMENT_ENV"], *arguments], capture=capture)


def main() -> int:
    parser = argparse.ArgumentParser(description="בקר פריסה מקומי של WZML-X")
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("command", choices=("preflight", "bootstrap", "deploy", "status", "rollback", "cleanup"))
    arguments = parser.parse_args()
    try:
        values = load_profile(arguments.profile)
        verify_local_files(values)
        remote(values, ["true"])
        if arguments.command == "preflight":
            print("פרופיל הבקר, מפתח השרת וחיבור SSH תקינים.")
            return 0
        install_controller(values, arguments.repository)
        if arguments.command == "bootstrap":
            invoke_server(values, ["bootstrap"])
        elif arguments.command == "deploy":
            with tempfile.TemporaryDirectory() as directory:
                archive = Path(directory) / "release.tar.gz"
                release_id = package_repository(arguments.repository, archive)
                remote_archive = f"{values['REMOTE_CONTROLLER_DIR']}/{release_id}.tar.gz"
                upload(values, archive, remote_archive)
                try:
                    invoke_server(values, ["deploy", "--archive", remote_archive, "--release-id", release_id])
                finally:
                    remote(values, ["rm", "-f", remote_archive])
        elif arguments.command == "rollback":
            invoke_server(values, ["rollback"])
        elif arguments.command == "cleanup":
            invoke_server(values, ["cleanup", "--confirm", values["CONTROLLER_NAME"]])
        else:
            print(invoke_server(values, ["status"], capture=True))
    except ControllerError as error:
        print(f"פעולת הבקר נעצרה בבטחה: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
