"""בדיקות בטיחות לקובצי הסודות לפני בנייה או הפעלה של הפריסה."""

from __future__ import annotations

import ast
from pathlib import Path


def read_config_value(path: Path, key: str) -> str:
    """קורא ערך קבוע מקובץ Python בלי להריץ את הקובץ הסודי."""

    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(
            isinstance(target, ast.Name) and target.id == key for target in targets
        ):
            continue
        try:
            return str(ast.literal_eval(node.value)).strip()
        except (ValueError, TypeError):
            return ""
    return ""


def read_env_values(path: Path) -> dict[str, str]:
    """קורא קובץ env פשוט ושומר רק את הערך האחרון של כל מפתח."""

    values = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def validate(config_path: Path, env_path: Path) -> list[str]:
    """מחזיר רשימת שגיאות מלאה כדי לתקן את כולן לפני ניסיון פריסה נוסף."""

    errors = []
    env = read_env_values(env_path)
    required_config = ("BOT_TOKEN", "OWNER_ID", "TELEGRAM_API", "TELEGRAM_HASH")
    for key in required_config:
        if not read_config_value(config_path, key):
            errors.append(f"{key} חסר ב-config.py")
    if not env.get("DATABASE_URL") and not read_config_value(config_path, "DATABASE_URL"):
        errors.append("DATABASE_URL חסר ב-config.py וב-.env.server")
    configured_password = read_config_value(config_path, "WEB_ACCESS_PASSWORD")
    overridden_password = env.get("WEB_ACCESS_PASSWORD", "")
    if not configured_password and not overridden_password:
        errors.append("WEB_ACCESS_PASSWORD חסר ב-config.py וב-.env.server")
    if (
        configured_password
        and overridden_password
        and configured_password != overridden_password
    ):
        errors.append(
            "WEB_ACCESS_PASSWORD שונה בין config.py לבין .env.server"
        )
    return errors


def main() -> int:
    errors = validate(Path("config.py"), Path(".env.server"))
    if errors:
        print("הפריסה נעצרה בגלל שגיאות בהגדרות:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("בדיקת הסודות והגדרות הפריסה עברה בהצלחה.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
