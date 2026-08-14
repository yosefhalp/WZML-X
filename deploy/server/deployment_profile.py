"""טעינה, התאמה ואימות קשיח של מפת פריסה פרטית לשרת."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse


NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,62}$")
CONTAINER_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{1,127}$")
REQUIRED_KEYS = (
    "DEPLOYMENT_VERSION",
    "DEPLOYMENT_NAME",
    "DEPLOYMENT_ROOT",
    "DEPLOYMENT_SHARED_DIR",
    "DEPLOYMENT_RELEASES_DIR",
    "DEPLOYMENT_BACKUP_DIR",
    "DEPLOYMENT_CURRENT_LINK",
    "DEPLOYMENT_STATE_FILE",
    "DEPLOYMENT_LOCK_FILE",
    "DEPLOYMENT_COMPOSE_PROJECT",
    "DEPLOYMENT_COMPOSE_FILE",
    "DEPLOYMENT_SERVICE",
    "DEPLOYMENT_HEALTH_URL",
    "DEPLOYMENT_KEEP_RELEASES",
    "WZMLX_CONTAINER_NAME",
    "WZMLX_IMAGE",
    "WZMLX_HOST_PORT",
    "WZMLX_MONGO_CONTAINER_NAME",
    "WZMLX_MONGO_PORT",
    "WZMLX_MONGO_VOLUME_NAME",
    "WZMLX_BOT_API_CONTAINER_NAME",
    "WZMLX_BOT_API_MODE",
    "WZMLX_BOT_API_BASE_URL",
    "WZMLX_BOT_API_PORT",
    "WZMLX_BOT_API_VOLUME_NAME",
    "WZMLX_NETWORK_NAME",
    "WZMLX_CONFIG_PATH",
    "WZMLX_ENV_PATH",
    "WZMLX_MONGO_ENV_PATH",
    "WZMLX_BOT_API_ENV_PATH",
    "WZMLX_ACCOUNTS_DIR",
    "WZMLX_DOWNLOADS_DIR",
    "WZMLX_CONTROL_DIR",
)
PATH_KEYS = (
    "DEPLOYMENT_ROOT",
    "DEPLOYMENT_SHARED_DIR",
    "DEPLOYMENT_RELEASES_DIR",
    "DEPLOYMENT_BACKUP_DIR",
    "DEPLOYMENT_CURRENT_LINK",
    "DEPLOYMENT_STATE_FILE",
    "DEPLOYMENT_LOCK_FILE",
    "WZMLX_CONFIG_PATH",
    "WZMLX_ENV_PATH",
    "WZMLX_MONGO_ENV_PATH",
    "WZMLX_BOT_API_ENV_PATH",
    "WZMLX_ACCOUNTS_DIR",
    "WZMLX_DOWNLOADS_DIR",
    "WZMLX_CONTROL_DIR",
)
PORT_KEYS = ("WZMLX_HOST_PORT", "WZMLX_MONGO_PORT", "WZMLX_BOT_API_PORT")
CONTAINER_KEYS = (
    "WZMLX_CONTAINER_NAME",
    "WZMLX_MONGO_CONTAINER_NAME",
    "WZMLX_MONGO_VOLUME_NAME",
    "WZMLX_BOT_API_CONTAINER_NAME",
    "WZMLX_BOT_API_VOLUME_NAME",
    "WZMLX_NETWORK_NAME",
)
SECRET_PATH_KEYS = (
    "WZMLX_CONFIG_PATH",
    "WZMLX_ENV_PATH",
    "WZMLX_MONGO_ENV_PATH",
    "WZMLX_BOT_API_ENV_PATH",
)


class DeploymentProfileError(ValueError):
    """שגיאה שמונעת פריסה לפני שנוצר שינוי כלשהו בשרת."""


def load_env(path: Path) -> dict[str, str]:
    """קורא קובץ env פשוט, אוסר כפילויות ואינו מריץ הרחבות shell."""

    if not path.is_file():
        raise DeploymentProfileError(f"קובץ הפריסה אינו קיים: {path}")
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise DeploymentProfileError(
                f"שורה {line_number} אינה במבנה KEY=VALUE"
            )
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise DeploymentProfileError(f"שם משתנה אינו תקין בשורה {line_number}")
        if key in values:
            raise DeploymentProfileError(f"המשתנה {key} מופיע יותר מפעם אחת")
        if any(character in value for character in ("\x00", "\n", "\r")):
            raise DeploymentProfileError(f"הערך של {key} מכיל תו אסור")
        values[key] = value
    return values


def _is_inside(path: PurePosixPath, parent: PurePosixPath) -> bool:
    """בודק גבול נתיב בלי להסתמך על קיום התיקייה במחשב הנוכחי."""

    return path == parent or parent in path.parents


def validate(values: dict[str, str]) -> list[str]:
    """מחזיר את כל השגיאות כדי שהפריסה תוכל להיעצר פעם אחת ובבירור."""

    errors: list[str] = []
    for key in REQUIRED_KEYS:
        if not values.get(key, "").strip():
            errors.append(f"{key} חסר")

    if values.get("DEPLOYMENT_VERSION") not in {None, "", "1"}:
        errors.append("DEPLOYMENT_VERSION אינו נתמך")

    name = values.get("DEPLOYMENT_NAME", "")
    if name and not NAME_PATTERN.fullmatch(name):
        errors.append("DEPLOYMENT_NAME חייב להיות שם קצר ובטוח")

    root_text = values.get("DEPLOYMENT_ROOT", "")
    root = PurePosixPath(root_text) if root_text else PurePosixPath("/")
    if root_text:
        if not root.is_absolute() or root == PurePosixPath("/"):
            errors.append("DEPLOYMENT_ROOT חייב להיות נתיב מוחלט שאינו /")
        if ".." in root.parts or "$" in root_text or "~" in root_text:
            errors.append("DEPLOYMENT_ROOT מכיל רכיב לא פתור או לא בטוח")

    for key in PATH_KEYS:
        text = values.get(key, "")
        if not text:
            continue
        path = PurePosixPath(text)
        if not path.is_absolute() or ".." in path.parts or "$" in text or "~" in text:
            errors.append(f"{key} חייב להיות נתיב מוחלט ופתור")
            continue
        if key != "DEPLOYMENT_LOCK_FILE" and root_text and not _is_inside(path, root):
            errors.append(f"{key} חייב להישאר בתוך DEPLOYMENT_ROOT")

    shared_text = values.get("DEPLOYMENT_SHARED_DIR", "")
    if shared_text:
        shared = PurePosixPath(shared_text)
        for key in SECRET_PATH_KEYS:
            text = values.get(key, "")
            if text and not _is_inside(PurePosixPath(text), shared):
                errors.append(f"{key} חייב להישאר בתוך DEPLOYMENT_SHARED_DIR")

    seen_ports: dict[int, str] = {}
    for key in PORT_KEYS:
        raw_port = values.get(key, "")
        if not raw_port:
            continue
        try:
            port = int(raw_port)
        except ValueError:
            errors.append(f"{key} חייב להיות מספר")
            continue
        external_bot_api = key == "WZMLX_BOT_API_PORT" and values.get("WZMLX_BOT_API_MODE") == "external"
        minimum = 1 if external_bot_api else 1024
        if not minimum <= port <= 65535:
            errors.append(f"{key} חייב להיות בין {minimum} ל-65535")
        # פורט של שירות חיצוני יכול להיות זהה במקרה שהוא נמצא במארח אחר.
        if not external_bot_api:
            if port in seen_ports:
                errors.append(f"{key} מתנגש עם {seen_ports[port]}")
            seen_ports[port] = key

    for key in CONTAINER_KEYS:
        value = values.get(key, "")
        if value and not CONTAINER_PATTERN.fullmatch(value):
            errors.append(f"{key} מכיל שם Docker לא תקין")

    keep_releases = values.get("DEPLOYMENT_KEEP_RELEASES", "")
    if keep_releases:
        try:
            if int(keep_releases) < 2:
                errors.append("DEPLOYMENT_KEEP_RELEASES חייב להיות לפחות 2")
        except ValueError:
            errors.append("DEPLOYMENT_KEEP_RELEASES חייב להיות מספר")

    compose_file = values.get("DEPLOYMENT_COMPOSE_FILE", "")
    if compose_file and (
        PurePosixPath(compose_file).is_absolute()
        or ".." in PurePosixPath(compose_file).parts
    ):
        errors.append("DEPLOYMENT_COMPOSE_FILE חייב להיות נתיב יחסי בתוך release")

    health_url = values.get("DEPLOYMENT_HEALTH_URL", "")
    if health_url:
        parsed = urlparse(health_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            errors.append("DEPLOYMENT_HEALTH_URL אינה כתובת HTTP תקינה")

    bot_api_mode = values.get("WZMLX_BOT_API_MODE", "")
    if bot_api_mode not in {"external", "managed"}:
        errors.append("WZMLX_BOT_API_MODE חייב להיות external או managed")
    bot_api_url = values.get("WZMLX_BOT_API_BASE_URL", "")
    if bot_api_url:
        parsed = urlparse(bot_api_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            errors.append("WZMLX_BOT_API_BASE_URL אינה כתובת HTTP תקינה")

    return errors


def require_valid(values: dict[str, str]) -> None:
    """עוצר מיד אם מפת הפריסה אינה בטוחה או שלמה."""

    errors = validate(values)
    if errors:
        raise DeploymentProfileError("\n".join(f"- {error}" for error in errors))


def adapt(
    source: dict[str, str],
    *,
    target_root: str,
    name: str,
    port_base: int,
    bot_api_url: str | None = None,
) -> dict[str, str]:
    """יוצר מפת יעד חדשה מתפקידי הקבצים, בלי להעתיק נתיבים מהשרת הישן."""

    root = PurePosixPath(target_root)
    shared = root / "shared"
    prefix = name.replace("_", "-")
    parsed_bot_api = urlparse(bot_api_url) if bot_api_url else None
    try:
        bot_api_port = (
            parsed_bot_api.port
            if parsed_bot_api and parsed_bot_api.port
            else (443 if parsed_bot_api and parsed_bot_api.scheme == "https" else port_base + 1)
        )
    except ValueError as error:
        raise DeploymentProfileError("הפורט בכתובת Local Bot API אינו תקין") from error
    adapted = dict(source)
    adapted.update(
        {
            "DEPLOYMENT_VERSION": "1",
            "DEPLOYMENT_NAME": name,
            "DEPLOYMENT_ROOT": str(root),
            "DEPLOYMENT_SHARED_DIR": str(shared),
            "DEPLOYMENT_RELEASES_DIR": str(root / "releases"),
            "DEPLOYMENT_BACKUP_DIR": str(root / "backups"),
            "DEPLOYMENT_CURRENT_LINK": str(root / "current"),
            "DEPLOYMENT_STATE_FILE": str(shared / "deployment-state.json"),
            "DEPLOYMENT_LOCK_FILE": f"/run/lock/{prefix}-deploy.lock",
            "DEPLOYMENT_COMPOSE_PROJECT": name.replace("-", "_"),
            "DEPLOYMENT_HEALTH_URL": f"http://127.0.0.1:{port_base}/health",
            "WZMLX_CONTAINER_NAME": f"{prefix}-app",
            "WZMLX_HOST_PORT": str(port_base),
            "WZMLX_MONGO_CONTAINER_NAME": f"{prefix}-mongodb",
            "WZMLX_MONGO_PORT": str(port_base + 2),
            "WZMLX_MONGO_VOLUME_NAME": f"{prefix}-mongo-data",
            "WZMLX_BOT_API_CONTAINER_NAME": f"{prefix}-bot-api",
            "WZMLX_BOT_API_MODE": "external",
            "WZMLX_BOT_API_BASE_URL": bot_api_url or f"http://127.0.0.1:{port_base + 1}",
            "WZMLX_BOT_API_PORT": str(bot_api_port),
            "WZMLX_BOT_API_VOLUME_NAME": f"{prefix}-bot-api-data",
            "WZMLX_NETWORK_NAME": f"{prefix}-net",
            "WZMLX_CONFIG_PATH": str(shared / "secrets" / "config.py"),
            "WZMLX_ENV_PATH": str(shared / "secrets" / ".env.server"),
            "WZMLX_MONGO_ENV_PATH": str(shared / "secrets" / ".env.mongo"),
            "WZMLX_BOT_API_ENV_PATH": str(
                shared / "secrets" / "telegram-bot-api.env"
            ),
            "WZMLX_ACCOUNTS_DIR": str(shared / "accounts"),
            "WZMLX_DOWNLOADS_DIR": str(shared / "downloads"),
            "WZMLX_CONTROL_DIR": str(shared / "runtime" / "control"),
        }
    )
    require_valid(adapted)
    return adapted


def write_env(path: Path, values: dict[str, str]) -> None:
    """כותב קובץ פרטי אטומית ובהרשאת 0600."""

    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{key}={values[key]}" for key in sorted(values)]
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=str(path.parent), text=True
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def safe_summary(values: dict[str, str]) -> dict[str, str]:
    """מחזיר רק מפת מבנה בטוחה לתצוגה ואינו מדפיס ערכי סוד."""

    hidden_terms = ("TOKEN", "PASSWORD", "SECRET", "HASH", "KEY")
    return {
        key: "[מוסתר]" if any(term in key for term in hidden_terms) else value
        for key, value in sorted(values.items())
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="ניהול מפת פריסה פרטית של WZML-X")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("path", type=Path)

    show_parser = subparsers.add_parser("show")
    show_parser.add_argument("path", type=Path)

    adapt_parser = subparsers.add_parser("adapt")
    adapt_parser.add_argument("source", type=Path)
    adapt_parser.add_argument("output", type=Path)
    adapt_parser.add_argument("--target-root", required=True)
    adapt_parser.add_argument("--name", required=True)
    adapt_parser.add_argument("--port-base", required=True, type=int)
    adapt_parser.add_argument("--bot-api-url")

    arguments = parser.parse_args()
    try:
        values = load_env(arguments.path if arguments.command != "adapt" else arguments.source)
        if arguments.command == "adapt":
            values = adapt(
                values,
                target_root=arguments.target_root,
                name=arguments.name,
                port_base=arguments.port_base,
                bot_api_url=arguments.bot_api_url,
            )
            write_env(arguments.output, values)
            print(f"מפת היעד נוצרה: {arguments.output}")
        else:
            require_valid(values)
            if arguments.command == "show":
                print(json.dumps(safe_summary(values), ensure_ascii=False, indent=2))
            else:
                print("מפת הפריסה תקינה.")
    except DeploymentProfileError as error:
        print(f"מפת הפריסה נדחתה:\n{error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
