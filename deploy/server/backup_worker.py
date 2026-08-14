#!/usr/bin/env python3
"""Worker מארח שיוצר, מאמת, בודק ושולח את גיבויי WZML-X לטלגרם."""

from __future__ import annotations

import ast
import html
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


PROJECT_DIR = Path(
    os.environ.get(
        "WZMLX_PROJECT_DIR",
        str(Path(__file__).resolve().parents[2]),
    )
).resolve()
CONTROL_DIR = Path(
    os.environ.get(
        "WZMLX_CONTROL_DIR",
        str(PROJECT_DIR / "runtime" / "control"),
    )
).resolve()
BACKUP_ROOT = Path(
    os.environ.get("WZMLX_BACKUP_ROOT", str(Path.home() / "wzmlx-backups"))
).resolve()
CONFIG_PATH = Path(
    os.environ.get("WZMLX_CONFIG_PATH", str(PROJECT_DIR / "config.py"))
).resolve()
SETTINGS_FILE = CONTROL_DIR / "backup-settings.json"
STATUS_FILE = CONTROL_DIR / "backup-status.json"
DAILY_LEDGER_FILE = CONTROL_DIR / "backup-daily-ledger.json"
REQUEST_LOCK = CONTROL_DIR / "backup-request.lock"
CACHE_STATUS_FILE = CONTROL_DIR / "cache-status.json"
CACHE_REQUEST_LOCK = CONTROL_DIR / "cache-request.lock"
BOT_API_BASE = os.environ.get("WZMLX_BOT_API_BASE", "http://127.0.0.1:8081").rstrip("/")
TELEGRAM_MAX_BYTES = 2_000_000_000
POLL_SECONDS = 2
HEARTBEAT_SECONDS = 30


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    """מפרסם JSON אטומית ובהרשאות מצומצמות."""

    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _read_json(path: Path) -> dict[str, Any]:
    """קובץ בקרה פגום מוחזר כריק ואינו מפיל את ה־worker."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _status(**changes: Any) -> dict[str, Any]:
    """שומר סטטוס מצטבר בלי למחוק את תוצאת הגיבוי האחרון בכל heartbeat."""

    status = _read_json(STATUS_FILE)
    status.update(changes)
    status["version"] = 1
    status["worker_seen_at"] = _timestamp()
    _atomic_json(STATUS_FILE, status)
    return status


def _cache_status(**changes: Any) -> dict[str, Any]:
    """מפרסם נתוני מטמון בקובץ נפרד כדי לא לערבב אותם בסטטוס הגיבוי."""

    status = _read_json(CACHE_STATUS_FILE)
    status.update(changes)
    status["version"] = 1
    _atomic_json(CACHE_STATUS_FILE, status)
    return status


def _size_bytes(value: str) -> int:
    """ממיר את פורמט הגודל של Docker לבייטים בלי תלות בשפה של המארח."""

    match = re.match(r"^\s*(-?[0-9.]+)\s*([KMGTPE]?B)\s*", str(value or ""), re.I)
    if not match:
        return 0
    number = max(0.0, float(match.group(1)))
    units = {"B": 1, "KB": 1000, "MB": 1000**2, "GB": 1000**3, "TB": 1000**4, "PB": 1000**5, "EB": 1000**6}
    return int(number * units.get(match.group(2).upper(), 1))


def _python_cache_info(*, clean: bool = False) -> tuple[int, int]:
    """סופר או מנקה רק `__pycache__` שמחוץ לנתיבי נתונים מוגנים."""

    protected = {".git", "accounts", "downloads", "runtime", "tokens", "thumbnails", "rclone"}
    files = 0
    total = 0
    directories = []
    for directory in PROJECT_DIR.rglob("__pycache__"):
        try:
            relative = directory.resolve().relative_to(PROJECT_DIR)
            if any(part in protected for part in relative.parts) or directory.is_symlink():
                continue
            directories.append(directory)
            for path in directory.rglob("*"):
                if path.is_file() and not path.is_symlink():
                    files += 1
                    total += path.stat().st_size
        except OSError:
            continue
    if clean:
        for directory in directories:
            shutil.rmtree(directory, ignore_errors=True)
    return files, total


def _docker_build_cache_info() -> tuple[int, int, int]:
    """קורא את מטמון הבנייה בלבד; images, volumes וקונטיינרים אינם מועמדים לניקוי."""

    result = subprocess.run(
        ["docker", "system", "df", "--format", "{{json .}}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("Docker לא החזיר נתוני נפח")
    for line in result.stdout.decode("utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("Type") == "Build Cache":
            return (
                max(0, int(row.get("TotalCount", 0) or 0)),
                _size_bytes(row.get("Size", "0B")),
                _size_bytes(str(row.get("Reclaimable", "0B")).split()[0]),
            )
    return 0, 0, 0


def _bot_api_cache_info() -> tuple[int, int, int, int, int, int, int, int]:
    """מודד את שירות Bot API המשותף מתוך הקונטיינר בלי למחוק ממנו דבר."""

    root = "/var/lib/telegram-bot-api"
    result = subprocess.run(
        ["docker", "exec", "tg-bot-api", "find", root, "-type", "f", "-print0"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("לא ניתן למדוד את מטמון Telegram Bot API")
    paths = [
        value.decode("utf-8", errors="surrogateescape")
        for value in result.stdout.split(b"\0")
        if value
    ]
    now = time.time()
    files = total = large_files = large_bytes = old_files = old_bytes = 0
    protected_files = protected_bytes = 0
    protected_suffixes = (".binlog", ".db", ".sqlite", ".sqlite3")
    for offset in range(0, len(paths), 200):
        chunk = paths[offset : offset + 200]
        stat_result = subprocess.run(
            ["docker", "exec", "tg-bot-api", "stat", "-c", "%s|%Y", *chunk],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
            check=False,
        )
        if stat_result.returncode != 0:
            raise RuntimeError("לא ניתן לקרוא את גדלי מטמון Telegram Bot API")
        rows = stat_result.stdout.decode("utf-8", errors="replace").splitlines()
        if len(rows) != len(chunk):
            raise RuntimeError("ספירת קובצי מטמון Telegram Bot API אינה עקבית")
        for path, row in zip(chunk, rows, strict=True):
            try:
                size, modified = (int(value) for value in row.split("|", 1))
            except ValueError:
                continue
            if path.lower().endswith(protected_suffixes):
                protected_files += 1
                protected_bytes += size
                continue
            files += 1
            total += size
            if size >= 50 * 1024 * 1024:
                large_files += 1
                large_bytes += size
            if now - modified >= 7 * 86400:
                old_files += 1
                old_bytes += size
    return (
        files,
        total,
        large_files,
        large_bytes,
        old_files,
        old_bytes,
        protected_files,
        protected_bytes,
    )


def _cache_snapshot() -> dict[str, int]:
    python_files, python_bytes = _python_cache_info()
    build_count, build_bytes, reclaimable = _docker_build_cache_info()
    (
        bot_files,
        bot_bytes,
        large_files,
        large_bytes,
        old_files,
        old_bytes,
        protected_files,
        protected_bytes,
    ) = _bot_api_cache_info()
    return {
        "python_files": python_files,
        "python_bytes": python_bytes,
        "docker_build_count": build_count,
        "docker_build_bytes": build_bytes,
        "docker_reclaimable_bytes": reclaimable,
        "bot_api_files": bot_files,
        "bot_api_bytes": bot_bytes,
        "bot_api_large_files": large_files,
        "bot_api_large_bytes": large_bytes,
        "bot_api_old_files": old_files,
        "bot_api_old_bytes": old_bytes,
        "bot_api_protected_files": protected_files,
        "bot_api_protected_bytes": protected_bytes,
    }


def process_cache_request(path: Path) -> None:
    """מבצע סריקה או ניקוי שמרני של Python ו-Build Cache ישן בלבד."""

    try:
        payload = _read_json(path)
        if set(payload) - {"version", "request_id", "action", "created_at"}:
            raise ValueError("בקשת המטמון כוללת שדות שאינם מותרים")
        if not re.fullmatch(r"[0-9a-f]{12}", str(payload.get("request_id", ""))):
            raise ValueError("מזהה בקשת המטמון אינו תקין")
        action = str(payload.get("action", ""))
        if action not in {"scan", "clean_safe"}:
            raise ValueError("פעולת המטמון אינה תקינה")
        _cache_status(state="running", stage="מודד את קטגוריות המטמון", error="")
        before = _cache_snapshot()
        removed_files = removed_bytes = 0
        if action == "clean_safe":
            _cache_status(state="running", stage="מנקה Python ו-Build Cache ישן")
            removed_files, removed_python_bytes = _python_cache_info(clean=True)
            prune_result = subprocess.run(
                ["docker", "builder", "prune", "--force", "--filter", "until=168h"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=1800,
                check=False,
            )
            if prune_result.returncode != 0:
                raise RuntimeError("ניקוי Docker Build Cache נכשל")
            after = _cache_snapshot()
            removed_bytes = removed_python_bytes + max(
                0,
                before["docker_build_bytes"] - after["docker_build_bytes"],
            )
        else:
            after = before
        _cache_status(
            state="success",
            stage="הסריקה הושלמה" if action == "scan" else "הניקוי הבטוח הושלם",
            scanned_at=_timestamp(),
            last_cleaned_at=_timestamp() if action == "clean_safe" else _read_json(CACHE_STATUS_FILE).get("last_cleaned_at", ""),
            removed_files=removed_files,
            removed_bytes=removed_bytes,
            error="",
            **after,
        )
    except Exception as error:
        _cache_status(
            state="failed",
            stage="פעולת המטמון נכשלה",
            error=_safe_error_text(error),
        )
        raise
    finally:
        path.unlink(missing_ok=True)
        CACHE_REQUEST_LOCK.unlink(missing_ok=True)


def _safe_error_text(error: Exception) -> str:
    """מחזיר הודעה שימושית בלי טוקן, כתובת Bot API או פקודה מלאה."""

    text = str(error or "שגיאה לא ידועה")
    text = re.sub(r"\d{5,15}:[A-Za-z0-9_-]{20,}", "[טוקן הוסתר]", text)
    text = re.sub(r"/bot[^/\s]+/", "/bot[הוסתר]/", text)
    text = text.replace(str(PROJECT_DIR), "[תיקיית הפרויקט]")
    text = text.replace(str(BACKUP_ROOT), "[תיקיית הגיבויים]")
    return " ".join(text.split())[:300]


def _config_integer(name: str) -> int:
    """קורא מספר קבוע מ־config.py בלי להריץ את קובץ הסודות."""

    tree = ast.parse(CONFIG_PATH.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(isinstance(target, ast.Name) and target.id == name for target in targets):
            value = ast.literal_eval(node.value)
            return int(value)
    raise RuntimeError(f"{name} חסר בקובץ ההגדרות")


def _bot_token() -> str:
    """קורא את טוקן הבוט כערך קבוע בלבד ואינו מדפיס אותו לעולם."""

    tree = ast.parse(CONFIG_PATH.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(isinstance(target, ast.Name) and target.id == "BOT_TOKEN" for target in targets):
            token = str(ast.literal_eval(node.value))
            if re.fullmatch(r"\d{5,15}:[A-Za-z0-9_-]{20,}", token):
                return token
    raise RuntimeError("BOT_TOKEN חסר או אינו תקין")


def _send_message(
    token: str,
    chat_id: int,
    text: str,
    *,
    parse_mode: str = "",
) -> None:
    """שולח עדכון קצר דרך Local Bot API בלי לרשום סודות בלוג."""

    fields = {
        "chat_id": str(chat_id),
        "text": text,
        "disable_web_page_preview": "true",
    }
    if parse_mode:
        fields["parse_mode"] = parse_mode
    payload = urllib.parse.urlencode(fields).encode("utf-8")
    request = urllib.request.Request(
        f"{BOT_API_BASE}/bot{token}/sendMessage",
        data=payload,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except Exception as error:
        raise RuntimeError("שליחת הודעת הגיבוי לטלגרם נכשלה") from error
    if not result.get("ok"):
        raise RuntimeError("Telegram דחתה את הודעת הגיבוי")


def _send_document(
    token: str,
    chat_id: int,
    archive: Path,
    caption: str,
    *,
    reply_markup: dict[str, Any] | None = None,
) -> None:
    """מעלה את הארכיון דרך Local Bot API ומוודא תשובת ok אמיתית."""

    descriptor, response_name = tempfile.mkstemp(
        prefix="wzmlx-backup-response-",
        suffix=".json",
        dir=CONTROL_DIR,
    )
    os.close(descriptor)
    response_path = Path(response_name)
    command = [
        "curl",
        "--fail-with-body",
        "--silent",
        "--show-error",
        "--max-time",
        "7200",
        "-o",
        str(response_path),
        "-F",
        f"chat_id={chat_id}",
        "-F",
        f"caption={caption}",
        "-F",
        f"document=@{archive};type=application/x-tar",
    ]
    if reply_markup:
        command.extend(
            [
                "-F",
                "reply_markup="
                + json.dumps(reply_markup, ensure_ascii=False, separators=(",", ":")),
            ]
        )
    command.append(f"{BOT_API_BASE}/bot{token}/sendDocument")
    try:
        result = subprocess.run(
            command,
            cwd=PROJECT_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=7300,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError("העלאת קובץ הגיבוי ל־Telegram נכשלה")
        response = json.loads(response_path.read_text(encoding="utf-8"))
        if not response.get("ok"):
            raise RuntimeError("Telegram דחתה את קובץ הגיבוי")
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        raise RuntimeError("לא התקבל אישור למסירת קובץ הגיבוי") from error
    finally:
        response_path.unlink(missing_ok=True)


def _run_checked(command: list[str], *, timeout: int, failure_message: str) -> None:
    """מריץ כלי מקומי ומחזיר הודעת כשל נקייה במקום פקודה שעלולה להכיל סודות."""

    result = subprocess.run(
        command,
        cwd=PROJECT_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip().splitlines()
        suffix = f": {detail[-1]}" if detail else ""
        raise RuntimeError(f"{failure_message}{suffix}")


def _send_rich_message(token: str, chat_id: int, rich_message: dict[str, Any]) -> None:
    """שולח את מדריך הפריסה במבנה Rich Message של Local Bot API."""

    payload = json.dumps(
        {"chat_id": chat_id, "rich_message": rich_message},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{BOT_API_BASE}/bot{token}/sendRichMessage",
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except Exception as error:
        raise RuntimeError("שליחת מדריך הפריסה העשיר נכשלה") from error
    if not result.get("ok"):
        raise RuntimeError("Telegram דחתה את מדריך הפריסה העשיר")


def _deployment_rich_message(archive: Path, job_id: str, mode: str) -> dict[str, Any]:
    """בונה מדריך Rich Message מלא ומקופל שאינו תלוי ב-callback של השרת."""

    archive_name = html.escape(archive.name)
    package_name = html.escape(archive.stem)
    mode_text = "מלאה עם שלוש תמונות Docker" if mode == "full" else "מהירה לשרת שכבר מחזיק את התמונות"
    commands = {
        "old": html.escape(
            "docker update --restart=no wzmlx-hebrew-bot\n"
            "docker stop -t 120 wzmlx-hebrew-bot\n"
            "systemctl --user stop wzmlx-backup-worker.service"
        ),
        "new": html.escape(
            "mkdir -p ~/wzmlx-package\n"
            f"tar -xf {archive.name} -C ~/wzmlx-package\n"
            f"cd ~/wzmlx-package/{archive.stem}\n"
            "./verify.sh .\n"
            "CONFIRM_RESTORE=YES ./restore.sh . ~/wzmlx-restored"
        ),
        "health": html.escape(
            "cd ~/wzmlx-restored\n"
            "docker compose -f docker-compose.server.yml ps\n"
            "curl -fsS http://127.0.0.1:8080/health\n"
            "systemctl --user is-active wzmlx-backup-worker.service"
        ),
        "rollback_new": html.escape(
            "cd ~/wzmlx-restored\n"
            "docker compose -f docker-compose.server.yml down\n"
            "systemctl --user stop wzmlx-backup-worker.service"
        ),
        "rollback_old": html.escape(
            "docker update --restart=unless-stopped wzmlx-hebrew-bot\n"
            "docker start wzmlx-hebrew-bot\n"
            "systemctl --user start wzmlx-backup-worker.service"
        ),
    }
    body = (
        "<h1>✅ ערכת WZML-X מוכנה</h1>"
        f"<p><code>{html.escape(job_id)}</code> · {mode_text}</p>"
        "<p>המדריך נשלח כהודעה עצמאית ונשאר זמין גם אם שרת המקור אינו פועל.</p>"
        "<details open><summary>📦 מה כלול בערכה?</summary><ul>"
        "<li><input type=\"checkbox\" checked>קוד, הגדרות, סודות ו-Sessions</li>"
        "<li><input type=\"checkbox\" checked>dump מלא של MongoDB</li>"
        "<li><input type=\"checkbox\" checked>זהות והגדרות Local Telegram Bot API</li>"
        "<li><input type=\"checkbox\" checked>Worker הגיבוי, מתקין systemd והגדרות התזמון</li>"
        f"<li><input type=\"checkbox\" checked>{'שלוש תמונות Docker מלאות' if mode == 'full' else 'שמות התמונות הנדרשות, ללא קובצי Image'}</li>"
        "</ul></details>"
        "<details><summary>⚠️ לפני המעבר</summary><ul>"
        "<li>שמרו עותק מקומי של הארכיון ושל הודעה זו.</li>"
        "<li>בשרת החדש נדרשים Linux, Docker עם Compose, Python 3, curl, tar ו-gzip.</li>"
        "<li>אין להפעיל שני עותקים של אותו בוט במקביל.</li>"
        "</ul></details>"
        "<details><summary>🚀 מעבר מלא לשרת Linux חדש</summary>"
        "<h3>1. בשרת הישן — עצירת הבוט וה-Worker</h3>"
        f"<pre><code class=\"language-bash\">{commands['old']}</code></pre>"
        "<blockquote>Local Bot API נשאר פעיל עבור בוטים אחרים.</blockquote>"
        "<h3>2. בשרת החדש — חילוץ, אימות ושחזור</h3>"
        f"<pre><code class=\"language-bash\">{commands['new']}</code></pre>"
        "<p>restore.sh טוען Images, משחזר MongoDB, מזהה Local Bot API קיים או מפעיל את המצורף, מעלה את WZML-X ומתקין מחדש את Worker הגיבוי.</p>"
        "</details>"
        "<details><summary>🩺 בדיקות בריאות לאחר השחזור</summary>"
        f"<pre><code class=\"language-bash\">{commands['health']}</code></pre>"
        "</details>"
        "<details><summary>↩️ חזרה לאחור</summary>"
        "<h3>כיבוי השרת החדש</h3>"
        f"<pre><code class=\"language-bash\">{commands['rollback_new']}</code></pre>"
        "<h3>החזרת השרת הישן</h3>"
        f"<pre><code class=\"language-bash\">{commands['rollback_old']}</code></pre>"
        "</details>"
        "<details><summary>✅ שערי האימות שעברו</summary><ul>"
        "<li>checksum ומבנה הארכיון</li>"
        "<li>ארבעת קובצי Worker הגיבוי</li>"
        f"<li>{'שלוש Images תקינות' if mode == 'full' else 'אפס Images כנדרש בערכת state'}</li>"
        "<li>תרגיל שחזור מבודד</li>"
        "<li>אישור מסירה של Telegram</li>"
        "</ul></details>"
        f"<footer>{archive_name} · מטמון Telegram, הורדות וקבצים זמניים אינם נכללים.</footer>"
    )
    return {"html": body, "is_rtl": True, "skip_entity_detection": True}


def _deployment_collapsible_message(archive: Path, job_id: str, mode: str) -> str:
    """בונה מדריך Telegram מקופל שנשאר בצ׳אט גם אם השרת המקורי אינו זמין."""

    mode_text = (
        "חבילה מלאה הכוללת שלוש תמונות Docker"
        if mode == "full"
        else "חבילת מצב מהירה לשרת שכבר מחזיק את התמונות"
    )
    old_server = html.escape(
        "docker update --restart=no wzmlx-hebrew-bot\n"
        "docker stop -t 120 wzmlx-hebrew-bot\n"
        "systemctl --user stop wzmlx-backup-worker.service"
    )
    new_server = html.escape(
        "mkdir -p ~/wzmlx-package\n"
        f"tar -xf {archive.name} -C ~/wzmlx-package\n"
        f"cd ~/wzmlx-package/{archive.stem}\n"
        "./verify.sh .\n"
        "CONFIRM_RESTORE=YES ./restore.sh . ~/wzmlx-restored"
    )
    health = html.escape(
        "cd ~/wzmlx-restored\n"
        "docker compose -f docker-compose.server.yml ps\n"
        "curl -fsS http://127.0.0.1:8080/health\n"
        "systemctl --user is-active wzmlx-backup-worker.service"
    )
    rollback = html.escape(
        "cd ~/wzmlx-restored\n"
        "docker compose -f docker-compose.server.yml down\n"
        "systemctl --user stop wzmlx-backup-worker.service"
    )
    old_server_rollback = html.escape(
        "docker update --restart=unless-stopped wzmlx-hebrew-bot\n"
        "docker start wzmlx-hebrew-bot\n"
        "systemctl --user start wzmlx-backup-worker.service"
    )
    return (
        "<b>📖 מדריך פריסה ושחזור — נשמר עם הגיבוי</b>\n"
        f"<code>{html.escape(job_id)}</code> · {mode_text}\n\n"
        "<blockquote expandable>"
        "מה כלול:\n"
        "• קוד, הגדרות, סודות ו-Sessions\n"
        "• dump מלא של MongoDB\n"
        "• זהות והגדרות Local Telegram Bot API\n"
        "• Worker הגיבוי, מתקין systemd והגדרות התזמון\n"
        f"• {'שלוש תמונות Docker מלאות' if mode == 'full' else 'שמות התמונות בלבד; השרת החדש חייב להחזיק אותן'}\n\n"
        "לפני המעבר:\n"
        "• שמרו עותק מקומי של הארכיון ושל הודעה זו.\n"
        "• בשרת החדש נדרשים Linux, Docker עם Compose, Python 3, curl, tar ו-gzip.\n"
        "• אין להפעיל שני עותקים של אותו בוט במקביל.\n\n"
        "1. בשרת הישן — עצירת הבוט וה-Worker בלבד; Local Bot API נשאר פעיל לבוטים אחרים:\n"
        f"{old_server}\n\n"
        "2. בשרת החדש — חילוץ, אימות ושחזור:\n"
        f"{new_server}\n\n"
        "restore.sh טוען Images, משחזר MongoDB, מזהה Local Bot API קיים או מפעיל את המצורף, מעלה את WZML-X ומתקין מחדש את Worker הגיבוי.\n\n"
        "3. בדיקות בריאות לאחר השחזור:\n"
        f"{health}\n\n"
        "4. חזרה לאחור אם השרת החדש אינו תקין:\n"
        f"{rollback}\n\n"
        "5. החזרת השרת הישן:\n"
        f"{old_server_rollback}\n\n"
        "שערי הבדיקה שעברו לפני המסירה: checksum, מבנה, ארבעת קובצי ה-Worker, שלוש Images במצב מלא, תרגיל שחזור מבודד ואישור Telegram.\n\n"
        "לא כלולים: downloads פעילים, מטמון המדיה של Telegram Bot API וקבצים זמניים."
        "</blockquote>"
    )


def _validate_request(payload: dict[str, Any]) -> dict[str, Any]:
    """מאשר רק את שדות ערכת הניוד הקבועים שהבוט רשאי להעביר ל־worker."""

    allowed = {"version", "job_id", "chat_id", "origin", "mode", "include_images", "created_at"}
    if set(payload) - allowed:
        raise ValueError("בקשת הגיבוי כוללת שדות שאינם מותרים")
    job_id = str(payload.get("job_id", ""))
    if not re.fullmatch(r"[0-9a-f]{12}", job_id):
        raise ValueError("מזהה בקשת הגיבוי אינו תקין")
    chat_id = int(payload.get("chat_id", 0) or 0)
    if chat_id <= 0:
        raise ValueError("מזהה צ'אט המסירה אינו תקין")
    origin = str(payload.get("origin", ""))
    if origin not in {"manual", "daily"}:
        raise ValueError("מקור בקשת הגיבוי אינו תקין")
    mode = str(payload.get("mode", ""))
    include_images = bool(payload.get("include_images"))
    if mode not in {"full", "state"} or include_images != (mode == "full"):
        raise ValueError("מצב ערכת הניוד אינו תקין")
    if origin == "daily" and mode != "full":
        raise ValueError("גיבוי יומי חייב להשתמש בערכה מלאה")
    return {
        "job_id": job_id,
        "chat_id": chat_id,
        "origin": origin,
        "mode": mode,
        "include_images": include_images,
    }


def _latest_archive(mode: str) -> Path:
    """מקבל את הארכיון האחרון רק אם הוא מנוהל ונמצא בתוך תיקיית הגיבויים."""

    latest_file = BACKUP_ROOT / "LATEST"
    archive = Path(latest_file.read_text(encoding="utf-8").strip()).resolve()
    archive.relative_to(BACKUP_ROOT)
    if not archive.is_file() or not archive.name.startswith(f"wzmlx-{mode}-"):
        raise RuntimeError("הארכיון החדש לא נמצא לאחר סיום הבנייה")
    if not archive.with_name(archive.name + ".managed").is_file():
        raise RuntimeError("הארכיון החדש חסר סמן ניהול")
    return archive


def process_request(path: Path) -> None:
    """מעביר בקשה דרך בנייה, אימות, תרגיל שחזור ומסירה מאומתת."""

    request: dict[str, Any] = {}
    token = ""
    try:
        request = _validate_request(_read_json(path))
        token = _bot_token()
        _status(
            worker_state="working",
            state="running",
            stage="יוצר ארכיון מלא",
            job_id=request["job_id"],
            origin=request["origin"],
            mode=request["mode"],
            started_at=_timestamp(),
            finished_at="",
            size_bytes=0,
            archive_name="",
            integrity_verified=False,
            restore_verified=False,
            delivered=False,
            error="",
        )
        _send_message(
            token,
            request["chat_id"],
            "💾 הגיבוי המלא התחיל. הקובץ יישלח לכאן רק אחרי אימות ותרגיל שחזור.",
        )
        environment = os.environ.copy()
        environment["WZMLX_BACKUP_STATUS_EXTERNAL"] = "1"
        environment["WZMLX_BACKUP_MODE"] = request["mode"]
        result = subprocess.run(
            ["/usr/bin/bash", str(PROJECT_DIR / "deploy/server/full-backup.sh")],
            cwd=PROJECT_DIR,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=7200,
            check=False,
        )
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", errors="replace").strip().splitlines()
            suffix = f": {detail[-1]}" if detail else ""
            raise RuntimeError(f"יצירת ארכיון הגיבוי נכשלה{suffix}")
        archive = _latest_archive(request["mode"])
        size_bytes = archive.stat().st_size

        _status(
            state="verifying",
            stage="מאמת checksum ומבנה",
            archive_name=archive.name,
            size_bytes=size_bytes,
        )
        _run_checked(
            ["/usr/bin/bash", str(PROJECT_DIR / "deploy/server/verify-full-backup.sh"), str(archive)],
            timeout=3600,
            failure_message="בדיקת שלמות הגיבוי נכשלה",
        )
        _status(integrity_verified=True, stage="מריץ תרגיל שחזור מבודד")
        _run_checked(
            ["/usr/bin/bash", str(PROJECT_DIR / "deploy/server/restore-drill.sh"), str(archive)],
            timeout=3600,
            failure_message="תרגיל השחזור נכשל",
        )
        _status(restore_verified=True, stage="מכין מסירה לטלגרם")
        if size_bytes > TELEGRAM_MAX_BYTES:
            raise RuntimeError("הגיבוי גדול ממגבלת 2000MB של Local Bot API")

        _status(state="sending", stage="שולח את הארכיון לטלגרם")
        _send_rich_message(
            token,
            request["chat_id"],
            _deployment_rich_message(
                archive, request["job_id"], request["mode"]
            ),
        )
        _send_document(
            token,
            request["chat_id"],
            archive,
            (
                "גיבוי יומי מלא כולל Images"
                if request["origin"] == "daily"
                else "ערכת ניוד מלאה כולל Images"
                if request["mode"] == "full"
                else "ערכת ניוד מהירה ללא Images"
            )
            + f" · {request['job_id']}",
        )
        _status(
            worker_state="ready",
            state="success",
            stage="הגיבוי אומת ונמסר לטלגרם",
            delivered=True,
            finished_at=_timestamp(),
            error="",
        )
    except Exception as error:
        safe_error = _safe_error_text(error)
        _status(
            worker_state="ready",
            state="failed",
            stage="הגיבוי נעצר בבטחה",
            finished_at=_timestamp(),
            error=safe_error,
        )
        if token and request.get("chat_id"):
            try:
                _send_message(token, request["chat_id"], f"❌ הגיבוי נכשל: {safe_error}")
            except Exception:
                pass
        raise
    finally:
        path.unlink(missing_ok=True)
        REQUEST_LOCK.unlink(missing_ok=True)


def _daily_settings() -> dict[str, Any]:
    payload = _read_json(SETTINGS_FILE)
    try:
        return {
            "enabled": bool(payload.get("daily_enabled", True)),
            "hour": min(23, max(0, int(payload.get("daily_hour", 4)))),
            "minute": min(59, max(0, int(payload.get("daily_minute", 15)))),
            "timezone": "Asia/Jerusalem",
            "chat_id": max(0, int(payload.get("daily_chat_id", 0) or 0)),
        }
    except (TypeError, ValueError):
        return {"enabled": True, "hour": 4, "minute": 15, "timezone": "Asia/Jerusalem", "chat_id": 0}


def _create_request(*, chat_id: int, origin: str, daily_date: str = "") -> str:
    """יוצר בקשת מארח אטומית עבור המתזמן, באותה נעילה של הכפתור הידני."""

    descriptor = os.open(
        REQUEST_LOCK,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    job_id = uuid.uuid4().hex[:12]
    path = CONTROL_DIR / f"backup-request-{job_id}.json"
    try:
        os.write(descriptor, f"{job_id}\n".encode("ascii"))
        os.close(descriptor)
        descriptor = -1
        _atomic_json(
            path,
            {
                "version": 1,
                "job_id": job_id,
                "chat_id": int(chat_id),
                "origin": origin,
                "mode": "full",
                "include_images": True,
                "created_at": _timestamp(),
            },
        )
        if origin == "daily":
            # היומן נפרד מקובץ הסטטוס משום שהסטטוס נכתב גם בידי הבוט וה־worker.
            # כך כתיבה מקבילה של מסך ידני אינה יכולה למחוק את סימון הגיבוי היומי.
            _atomic_json(
                DAILY_LEDGER_FILE,
                {
                    "version": 1,
                    "last_attempt_date": daily_date,
                    "job_id": job_id,
                    "created_at": _timestamp(),
                },
            )
        return job_id
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        path.unlink(missing_ok=True)
        REQUEST_LOCK.unlink(missing_ok=True)
        raise


def queue_daily_backup_if_due(now: datetime | None = None) -> bool:
    """מכניס לכל היותר גיבוי יומי אחד לאותו תור שמשמש את הכפתור הידני."""

    settings = _daily_settings()
    if not settings["enabled"] or settings["chat_id"] <= 0:
        return False
    local_now = now or datetime.now(ZoneInfo(settings["timezone"]))
    if local_now.tzinfo is None:
        local_now = local_now.replace(tzinfo=ZoneInfo(settings["timezone"]))
    due_time = local_now.replace(
        hour=settings["hour"],
        minute=settings["minute"],
        second=0,
        microsecond=0,
    )
    today = local_now.date().isoformat()
    status = _read_json(STATUS_FILE)
    ledger = _read_json(DAILY_LEDGER_FILE)
    if (
        local_now < due_time
        or status.get("last_daily_attempt_date") == today
        or ledger.get("last_attempt_date") == today
    ):
        return False
    if REQUEST_LOCK.exists() or any(CONTROL_DIR.glob("backup-request-*.json")):
        return False
    try:
        job_id = _create_request(
            chat_id=settings["chat_id"],
            origin="daily",
            daily_date=today,
        )
    except FileExistsError:
        return False
    _status(
        worker_state="ready",
        state="queued",
        stage="הגיבוי היומי ממתין ל־worker",
        job_id=job_id,
        origin="daily",
        last_daily_attempt_date=today,
        error="",
    )
    return True


def _repair_stale_lock() -> None:
    """מסיר נעילה יתומה רק כשאין בקשה ורק לאחר חמש דקות."""

    if REQUEST_LOCK.exists() and not any(CONTROL_DIR.glob("backup-request-*.json")):
        try:
            if time.time() - REQUEST_LOCK.stat().st_mtime > 300:
                REQUEST_LOCK.unlink(missing_ok=True)
        except OSError:
            pass
    if CACHE_REQUEST_LOCK.exists() and not any(CONTROL_DIR.glob("cache-request-*.json")):
        try:
            if time.time() - CACHE_REQUEST_LOCK.stat().st_mtime > 300:
                CACHE_REQUEST_LOCK.unlink(missing_ok=True)
        except OSError:
            pass


def run_forever() -> None:
    """מפעיל heartbeat, תזמון ותור יחיד בלי להריץ שני גיבויים במקביל."""

    os.umask(0o077)
    CONTROL_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    last_heartbeat = 0.0
    while True:
        _repair_stale_lock()
        if time.monotonic() - last_heartbeat >= HEARTBEAT_SECONDS:
            current = _read_json(STATUS_FILE)
            state = str(current.get("state", "idle"))
            _status(
                worker_state="working"
                if state in {"running", "verifying", "sending"}
                else "ready"
            )
            last_heartbeat = time.monotonic()
        cache_requests = sorted(CONTROL_DIR.glob("cache-request-*.json"))
        if cache_requests:
            try:
                process_cache_request(cache_requests[0])
            except Exception:
                time.sleep(POLL_SECONDS)
            continue
        requests = sorted(CONTROL_DIR.glob("backup-request-*.json"))
        if requests:
            try:
                process_request(requests[0])
            except Exception:
                time.sleep(POLL_SECONDS)
            continue
        try:
            if queue_daily_backup_if_due():
                continue
        except Exception as error:
            _status(
                worker_state="error",
                state="failed",
                stage="בדיקת התזמון נכשלה",
                error=_safe_error_text(error),
            )
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    run_forever()
