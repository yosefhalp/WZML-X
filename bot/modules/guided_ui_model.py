"""לוגיקה טהורה של אשף המשימות, ללא חיבור ל-Telegram או לשירותי הרקע."""

from __future__ import annotations

ADVANCED_VALUE_OPTIONS = {
    "name": ("שם חדש", "-n", "שלחו שם חדש לקובץ או לתיקייה."),
    "folder": ("תיקייה מאחדת", "-m", "שלחו שם תיקייה שאליה יאוחדו תוצאות המשימה."),
    "split": ("גודל פיצול", "-sp", "שלחו גודל בבייטים, לדוגמה 2000000000."),
    "multi": ("מספר קישורים", "-i", "שלחו את מספר הקישורים הרצופים לעיבוד."),
    "bulk": ("טווח קישורים", "-b", "שלחו טווח כגון 2:8, או את המילה all לכל הקישורים."),
    "seed_value": ("יחס וזמן שיתוף", "-d", "שלחו יחס:דקות, לדוגמה 1.0:30."),
    "upload": ("יעד העלאה", "-up", "שלחו מזהה Drive או נתיב Rclone מלא."),
    "category": ("קטגוריית Drive", "-gc", "שלחו את שם קטגוריית Drive המוגדרת."),
    "rclone_flags": ("אפשרויות Rclone", "-rcf", "שלחו אפשרויות Rclone בתבנית הנתמכת."),
    "thumbnail": ("תמונה ממוזערת", "-t", "שלחו קישור ישיר לתמונה ממוזערת."),
    "convert_audio": ("המרת שמע", "-ca", "שלחו פורמט שמע, לדוגמה mp3."),
    "convert_video": ("המרת וידאו", "-cv", "שלחו פורמט וידאו, לדוגמה mkv."),
    "name_swap": ("החלפה בשם", "-ns", "שלחו תבנית החלפה כגון old:new."),
    "thumb_layout": ("פריסת תמונות", "-tl", "שלחו פריסה כגון 3x3 או 1280x720."),
    "headers": ("כותרות HTTP", "-h", "שלחו כותרות HTTP בתבנית הנתמכת."),
    "metadata": ("מטא־דאטה", "-meta", "שלחו key=value, ואפשר להפריד כמה ערכים באמצעות |."),
    "ffmpeg": ("פקודות FFmpeg", "-ff", "שלחו רשימה או מילון Python תקינים של פקודות FFmpeg."),
    "yt_options": ("אפשרויות yt-dlp", "-opt", "שלחו מילון Python תקין של אפשרויות yt-dlp."),
    "extract_password": ("סיסמת חילוץ", "-e", "שלחו את סיסמת הארכיון לחילוץ."),
    "compress_password": ("סיסמת ZIP", "-z", "שלחו סיסמה לארכיון שייווצר."),
    "sample_value": ("משך סרטון דוגמה", "-sv", "שלחו משך:קטע, לדוגמה 60:4."),
    "screenshots_value": ("מספר צילומי מסך", "-ss", "שלחו את מספר צילומי המסך הרצוי."),
}

BOOLEAN_FLAGS = {
    "as_document": "-doc",
    "as_media": "-med",
    "force": "-f",
    "force_download": "-fd",
    "force_upload": "-fu",
    "hybrid": "-hl",
    "bot_transfer": "-bt",
    "user_transfer": "-ut",
}

SPECIAL_VALUE_KEYS = {
    "extract_password",
    "compress_password",
    "sample_value",
    "screenshots_value",
    "seed_value",
}

SUPPORTED_MODES = {
    "auto",
    "torrent",
    "youtube",
    "jdownloader",
    "usenet",
    "clone",
    "gofile",
    "file",
}
SUPPORTED_DESTINATIONS = {"gofile", "telegram", "cloud", "clone"}
MAX_GUIDED_LINKS = 50
BASIC_TOGGLES = {"select", "extract", "compress", "join", "sample", "screenshots", "seed"}
TOOL_ACTIONS = {
    "search",
    "nzbsearch",
    "imdb",
    "mediainfo",
    "images",
    "gdsearch",
    "gdcount",
    "gdclean",
    "gddelete",
    "rss",
    "select",
    "force",
    "category",
    "cancelall",
    "commands",
}
ADMIN_INPUT_ACTIONS = {
    "authorize",
    "unauthorize",
    "addsudo",
    "rmsudo",
    "blacklist",
    "rmblacklist",
    "broadcast",
    "addimage",
    "shell",
    "aexec",
    "exec",
}


def guided_text_mode(input_text: str, *, has_media: bool = False) -> dict:
    """ממפה קלט יחיד או רשימת קישורים לחוזה ה־Bulk הוותיק של המנוע."""

    lines = [line.strip() for line in str(input_text or "").splitlines() if line.strip()]
    is_bulk = len(lines) > 1
    return {
        "link_count": len(lines),
        "is_bulk": is_bulk,
        "too_many": len(lines) > MAX_GUIDED_LINKS,
        "command_input": "" if is_bulk or has_media else (lines[0] if lines else ""),
        "reply_required": bool(is_bulk or has_media),
        "preview": f"{len(lines)} קישורים" if is_bulk else ((lines[0][:160]) if lines else "קובץ מ־Telegram"),
    }
ADMIN_ACTIONS = {
    "botsettings",
    "access",
    "plugins",
    "sessions",
    "restartsessions",
    "terminal",
    "logs",
    "users",
    "clear",
    "restart",
}


def _telegram_command_destination(source: str, target: str, channel="") -> str:
    """בונה את יעד הפקודה בלי לטעון את תהליך הבוט במודול הבדיקות הטהור."""

    if source not in {"bot", "user"}:
        raise ValueError("יש לבחור מקור העלאה: Bot או Userbot")
    prefix = "u" if source == "user" else "b"
    if target == "private":
        return f"{prefix}:pm"
    channel = str(channel or "").strip()
    valid_username = (
        channel.startswith("@")
        and 5 <= len(channel[1:]) <= 32
        and channel[1:].replace("_", "").isalnum()
    )
    valid_numeric = (
        channel.startswith("-100")
        and channel[1:].isdigit()
        and 10 <= len(channel) <= 20
    )
    if target != "channel" or not (valid_username or valid_numeric):
        raise ValueError("יש להזין @username של ערוץ או מזהה מספרי שמתחיל ב־100-")
    return f"{prefix}:{channel}"
ENGINE_INFO_ACTIONS = {"jd"}


def parse_ui_callback(data: str) -> tuple[str, list[str]]:
    """מאמת נתוני כפתור לפני שהמנתב ניגש לפרמטרים שלהם."""

    parts = str(data or "").split()
    if len(parts) < 2 or parts[0] != "ui":
        raise ValueError("מזהה הכפתור אינו שייך למרכז השליטה")
    action, arguments = parts[1], parts[2:]
    no_argument_actions = {
        "home",
        "new",
        "quick",
        "tasks",
        "server",
        "tools",
        "settings",
        "help",
        "run",
        "destinations",
        "options",
        "advanced",
        "cancel",
    }
    if action in no_argument_actions and not arguments:
        return action, arguments
    if action == "source" and len(arguments) == 1 and arguments[0] in SUPPORTED_MODES:
        return action, arguments
    if action == "dest" and len(arguments) == 1 and arguments[0] in SUPPORTED_DESTINATIONS:
        return action, arguments
    if action == "tgsource" and len(arguments) == 1 and arguments[0] in {"bot", "user"}:
        return action, arguments
    if action == "tgtarget" and len(arguments) == 1 and arguments[0] in {"private", "connect"}:
        return action, arguments
    if action == "tgchannel" and len(arguments) == 1 and arguments[0].isdigit():
        return action, arguments
    if action == "option" and len(arguments) == 1 and arguments[0] in BASIC_TOGGLES:
        return action, arguments
    if action == "advancedtoggle" and len(arguments) == 1 and arguments[0] in BOOLEAN_FLAGS:
        return action, arguments
    if action in {"value", "valueclear"} and len(arguments) == 1 and arguments[0] in ADVANCED_VALUE_OPTIONS:
        return action, arguments
    if action == "tool" and len(arguments) == 1 and arguments[0] in TOOL_ACTIONS:
        return action, arguments
    if action == "engine" and len(arguments) == 1 and arguments[0] in ENGINE_INFO_ACTIONS:
        return action, arguments
    if action == "backup" and (
        not arguments
        or len(arguments) == 1
        and arguments[0]
        in {
            "handoff",
            "full",
            "state",
            "daily",
            "dailyrun",
            "refresh",
            "restore",
            "dailyon",
            "dailyoff",
            "timem60",
            "timep60",
            "timem15",
            "timep15",
        }
        or len(arguments) == 2
        and arguments[0] == "guide"
        and len(arguments[1]) == 12
        and all(char in "0123456789abcdef" for char in arguments[1])
    ):
        return action, arguments
    if action == "gofile" and (
        not arguments
        or len(arguments) == 1
        and arguments[0] == "refresh"
        or len(arguments) == 2
        and arguments[0] in {"page", "deleteconfirm", "delete", "add"}
        and (
            arguments[1].isdigit()
            if arguments[0] == "page"
            else len(arguments[1]) == 32
            and all(char in "0123456789abcdef" for char in arguments[1])
        )
    ):
        return action, arguments
    if action == "cache" and (
        not arguments
        or len(arguments) == 1
        and arguments[0]
        in {"run", "refresh", "leftovers_confirm", "leftovers_run"}
    ):
        return action, arguments
    if action == "admin":
        if not arguments or len(arguments) == 1 and arguments[0] in ADMIN_ACTIONS:
            return action, arguments
        if (
            len(arguments) == 2
            and arguments[0] == "input"
            and arguments[1] in ADMIN_INPUT_ACTIONS
        ):
            return action, arguments
    raise ValueError(f"מזהה הכפתור אינו מוכר או שחסרים בו פרמטרים: {data}")


def session_defaults(mode: str) -> dict:
    """מחזיר מצב התחלתי מלא ודוחה מראש סוג מקור שאינו נתמך."""

    if mode not in SUPPORTED_MODES:
        raise ValueError(f"סוג המקור אינו נתמך: {mode}")
    return {
        "stage": "input",
        "mode": mode,
        "select": mode == "torrent",
        "extract": False,
        "compress": False,
        "join": False,
        "sample": False,
        "screenshots": False,
        "seed": False,
        "upload_source": "",
        "upload_target": "",
        "upload_channel": "",
        **{key: False for key in BOOLEAN_FLAGS},
        **{key: "" for key in ADVANCED_VALUE_OPTIONS},
    }


def task_route(mode: str, destination: str) -> tuple[str, str]:
    """ממפה מקור ויעד לפקודה ולשם המנוע הקיים שמבצע אותה."""

    if mode not in SUPPORTED_MODES:
        raise ValueError(f"סוג המקור אינו נתמך: {mode}")
    if destination not in SUPPORTED_DESTINATIONS:
        raise ValueError(f"יעד ההעלאה אינו נתמך: {destination}")
    if destination == "gofile":
        return {
            "torrent": ("/gofile", "qb_uphoster"),
            "jdownloader": ("/gofile", "jd_uphoster"),
            "usenet": ("/gofile", "nzb_uphoster"),
        }.get(mode, ("/gofile", "uphoster"))
    if destination == "clone":
        if mode != "clone":
            raise ValueError("יעד העתקת Drive זמין רק במצב clone")
        return "/clone", "clone_node"
    if destination == "telegram":
        return {
            "youtube": ("/ytdlleech", "ytdl_leech"),
            "torrent": ("/qbleech", "qb_leech"),
            "jdownloader": ("/jdleech", "jd_leech"),
            "usenet": ("/nzbleech", "nzb_leech"),
        }.get(mode, ("/leech", "leech"))
    return {
        "youtube": ("/ytdl", "ytdl"),
        "torrent": ("/qbmirror", "qb_mirror"),
        "jdownloader": ("/jdmirror", "jd_mirror"),
        "usenet": ("/nzbmirror", "nzb_mirror"),
    }.get(mode, ("/mirror", "mirror"))


def build_task_command(session: dict, input_text: str) -> tuple[str, str]:
    """בונה פקודה סופית ובודקת שכל פרמטר מוכר לפני מסירתה למנוע."""

    command, handler_name = task_route(session["mode"], session["destination"])
    options = []
    if session["destination"] == "telegram" and session.get("upload_source"):
        source = session["upload_source"]
        target = session.get("upload_target") or "private"
        explicit_destination = _telegram_command_destination(
            source, target, session.get("upload_channel", "")
        )
        options.append("-ut" if source == "user" else "-bt")
        if explicit_destination:
            options.extend(["-up", explicit_destination])
    if session.get("select"):
        options.append("-s")
    if session.get("extract_password"):
        options.extend(["-e", str(session["extract_password"])])
    elif session.get("extract"):
        options.append("-e")
    if session.get("compress_password"):
        options.extend(["-z", str(session["compress_password"])])
    elif session.get("compress"):
        options.append("-z")
    if session.get("join"):
        options.append("-j")
    if session.get("sample_value"):
        options.extend(["-sv", str(session["sample_value"])])
    elif session.get("sample"):
        options.append("-sv")
    if session.get("screenshots_value"):
        options.extend(["-ss", str(session["screenshots_value"])])
    elif session.get("screenshots"):
        options.append("-ss")
    if session.get("seed_value"):
        options.extend(["-d", str(session["seed_value"])])
    elif session.get("seed"):
        options.append("-d")
    for key, flag in BOOLEAN_FLAGS.items():
        if session["destination"] == "telegram" and session.get("upload_source") and key in {
            "bot_transfer",
            "user_transfer",
        }:
            continue
        if session.get(key):
            options.append(flag)
    for key, (_, flag, _) in ADVANCED_VALUE_OPTIONS.items():
        if key in SPECIAL_VALUE_KEYS:
            continue
        value = session.get(key)
        if value is True:
            options.append(flag)
        elif value:
            options.extend([flag, str(value)])
    command_text = " ".join(filter(None, [command, input_text.strip(), *options]))
    return command_text, handler_name
