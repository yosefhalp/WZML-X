from asyncio import gather, sleep, wait_for, TimeoutError
from pyrogram.enums import ButtonStyle
from platform import platform, version
from re import search as research
from time import time
from pathlib import Path
from json import loads, JSONDecodeError
from socket import create_connection

from aiofiles.os import path as aiopath
from speedtest import ConfigRetrievalError, Speedtest
from psutil import (
    Process,
    boot_time,
    cpu_count,
    cpu_freq,
    cpu_percent,
    disk_io_counters,
    disk_usage,
    getloadavg,
    net_io_counters,
    swap_memory,
    virtual_memory,
    process_iter,
    NoSuchProcess,
    AccessDenied,
)

from .. import LOGGER, bot_cache, bot_start_time, bot_loop, task_dict, task_dict_lock
from ..core.config_manager import Config, BinConfig
from ..helper.ext_utils.bot_lock import get_system_resources_cached
from ..helper.ext_utils.bot_utils import (
    cmd_exec,
    compare_versions,
    git_info,
    new_task,
    sync_to_async,
)
from ..helper.ext_utils.status_utils import (
    get_progress_bar_string,
    get_readable_file_size,
    get_readable_time,
)
from ..helper.telegram_helper.filters import CustomFilters
from ..helper.telegram_helper.button_build import ButtonMaker
from ..helper.telegram_helper.message_utils import (
    delete_message,
    edit_message,
    send_message,
)
from ..helper.telegram_helper.rich_message import (
    edit_rich_message,
    send_rich_message,
    summary_card,
)
from ..version import get_version

commands = {
    "aria2": ([BinConfig.ARIA2_NAME, "--version"], r"aria2 version ([\d.]+)"),
    "qBittorrent": ([BinConfig.QBIT_NAME, "--version"], r"qBittorrent v([\d.]+)"),
    "SABnzbd+": (
        [BinConfig.SABNZBD_NAME, "--version"],
        rf"{BinConfig.SABNZBD_NAME}-([\d.]+)",
    ),
    "python": (["python3", "--version"], r"Python ([\d.]+)"),
    "rclone": ([BinConfig.RCLONE_NAME, "--version"], r"rclone v([\d.]+)"),
    "yt-dlp": (["yt-dlp", "--version"], r"([\d.]+)"),
    "ffmpeg": (
        [BinConfig.FFMPEG_NAME, "-version"],
        r"ffmpeg version ([\d.]+(-\w+)?).*",
    ),
    "7z": (["7z", "i"], r"7-Zip ([\d.]+)"),
    "aiohttp": (["uv", "pip", "show", "aiohttp"], r"Version: ([\d.]+)"),
    "wzgram": (["uv", "pip", "show", "wzgram"], r"Version: ([\d.]+)"),
    "gapi": (["uv", "pip", "show", "google-api-python-client"], r"Version: ([\d.]+)"),
    "mega": (
        [
            "python3",
            "-c",
            "from mega import MegaApi; print(MegaApi('test').getVersion())",
        ],
        r"v?([\d.]+)",
    ),
}


async def get_server_overview(event):
    """מחזיר תמונת מצב קצרה של השרת שמתאימה למסך נייד ול־Rich Message."""

    user_id = event.from_user.id
    cpu_usage = cpu_percent(interval=0.2)
    memory = virtual_memory()
    total, used, free, disk_percent = disk_usage("/")
    network = net_io_counters()
    async with task_dict_lock:
        active_tasks = len(task_dict)

    services = [] if Config.DISABLE_TORRENTS else ["qBittorrent", "Aria2"]
    if not Config.DISABLE_JD:
        services.append("JDownloader")
    if not Config.DISABLE_NZB:
        services.append("SABnzbd")
    if not Config.DISABLE_MEGA:
        services.append("Mega")

    def port_ready(port):
        try:
            with create_connection(("127.0.0.1", port), timeout=0.4):
                return True
        except OSError:
            return False

    backup_status = {}
    try:
        backup_status = loads(
            Path("runtime/control/backup-status.json").read_text(encoding="utf-8")
        )
    except (OSError, JSONDecodeError, TypeError):
        pass
    backup_labels = {"running": "מתבצע", "success": "תקין", "failed": "נכשל"}

    rows = [
        ("זמן פעילות הבוט", get_readable_time(time() - bot_start_time)),
        ("מעבד", f"{cpu_usage}% · {cpu_count(logical=True) or 0} ליבות"),
        (
            "זיכרון",
            f"{get_readable_file_size(memory.used)} מתוך {get_readable_file_size(memory.total)} · {memory.percent}%",
        ),
        (
            "אחסון",
            f"{get_readable_file_size(used)} מתוך {get_readable_file_size(total)} · {disk_percent}%",
        ),
        ("משימות פעילות", str(active_tasks)),
        (
            "תעבורת רשת",
            f"נכנס {get_readable_file_size(network.bytes_recv)} · יוצא {get_readable_file_size(network.bytes_sent)}",
        ),
        ("מנועים פעילים", ", ".join(services) or "אין מנועים פעילים"),
        ("MongoDB", "מחובר" if port_ready(27017) else "לא זמין"),
        ("Telegram Bot API", "מחובר" if port_ready(8081) else "לא זמין"),
        (
            "גיבוי מלא",
            backup_labels.get(backup_status.get("state"), "אין מידע")
            + (
                f" · {backup_status.get('finished_at')}"
                if backup_status.get("finished_at")
                else ""
            ),
        ),
    ]
    rich_html = summary_card(
        "מצב השרת",
        rows,
        intro="תמונה עדכנית של המשאבים, המשימות והשירותים.",
        footer="אפשר לרענן את הנתונים או להריץ בדיקת מהירות מלאה.",
    )
    fallback = f"""<b>🖥 מצב השרת</b>

<b>זמן פעילות:</b> {rows[0][1]}
<b>מעבד:</b> {rows[1][1]}
<b>זיכרון:</b> {rows[2][1]}
<b>אחסון:</b> {rows[3][1]}
<b>משימות פעילות:</b> {rows[4][1]}
<b>תעבורת רשת:</b> {rows[5][1]}
<b>מנועים פעילים:</b> {rows[6][1]}"""

    buttons = ButtonMaker()
    buttons.data_button("🔄 רענון", f"stats {user_id} server")
    buttons.data_button("🚀 בדיקת מהירות", f"stats {user_id} speed")
    buttons.data_button("📊 נתונים מפורטים", f"stats {user_id} home")
    if user_id == Config.OWNER_ID:
        buttons.data_button("💾 גיבויים", "ui backup")
    buttons.data_button("🏠 תפריט ראשי", "ui home")
    buttons.data_button(
        "סגירה", f"stats {user_id} close", "footer", style=ButtonStyle.DANGER
    )
    return rich_html, fallback, buttons.build_menu(2)


async def run_server_speedtest():
    """מריץ את speedtest מחוץ ללולאת האירועים כדי שהבוט יישאר זמין."""

    speed_results = await sync_to_async(Speedtest)
    await sync_to_async(speed_results.get_best_server)
    await sync_to_async(speed_results.download)
    await sync_to_async(speed_results.upload)
    return speed_results.results.dict()


def get_speedtest_view(result, user_id):
    """בונה תוצאה נגישה של בדיקת המהירות ללא חשיפת נתוני הגדרה."""

    server = result.get("server") or {}
    rows = [
        ("מהירות הורדה", f'{get_readable_file_size(result.get("download", 0) / 8)}/שנייה'),
        ("מהירות העלאה", f'{get_readable_file_size(result.get("upload", 0) / 8)}/שנייה'),
        ("זמן תגובה", f'{result.get("ping", 0):.2f} מילישניות'),
        ("שרת בדיקה", str(server.get("name") or "לא ידוע")),
        ("מיקום", ", ".join(filter(None, [server.get("country"), server.get("cc")])) or "לא ידוע"),
        ("ספק", str(server.get("sponsor") or "לא ידוע")),
    ]
    rich_html = summary_card(
        "בדיקת מהירות השרת",
        rows,
        intro="הבדיקה הסתיימה בהצלחה.",
        footer="התוצאות משקפות את החיבור בין השרת לשרת הבדיקה שנבחר.",
    )
    fallback = "<b>🚀 בדיקת מהירות השרת</b>\n\n" + "\n".join(
        f"<b>{label}:</b> {value}" for label, value in rows
    )
    buttons = ButtonMaker()
    buttons.data_button("🔁 בדיקה חוזרת", f"stats {user_id} speed")
    buttons.data_button("חזרה למצב השרת", f"stats {user_id} server")
    buttons.data_button(
        "סגירה", f"stats {user_id} close", "footer", style=ButtonStyle.DANGER
    )
    return rich_html, fallback, buttons.build_menu(2)


async def get_stats(event, key="home"):
    user_id = event.from_user.id
    btns = ButtonMaker()
    if key == "home":
        btns = ButtonMaker()
        btns.data_button("משאבי הבוט", f"stats {user_id} stbot")
        btns.data_button("מערכת ורשת", f"stats {user_id} stsys")
        btns.data_button("גרסת המאגר", f"stats {user_id} strepo")
        btns.data_button("גרסאות רכיבים", f"stats {user_id} stpkgs")
        btns.data_button("מגבלות משימות", f"stats {user_id} tlimits")
        btns.data_button("תהליכי מערכת", f"stats {user_id} systasks")
        btns.data_button("מצב השרת", f"stats {user_id} server", "header")
        msg = "⌬ <b><i>נתונים מפורטים על הבוט והשרת</i></b>"
    elif key == "stbot":
        total, used, free, disk = disk_usage("/")
        swap = swap_memory()
        memory = virtual_memory()
        disk_io = disk_io_counters()
        res = get_system_resources_cached()
        bot_ram_mb = res["ram_mb"]
        bot_ram_total = bot_ram_mb * 1024 * 1024
        user = Process().username()
        bot_ram_used = sum(
            p.memory_info().rss for p in process_iter() if p.username() == user
        )
        bot_ram_free = max(0, bot_ram_total - bot_ram_used)
        bot_ram_pct = (
            round((bot_ram_used / bot_ram_total * 100), 2) if bot_ram_total > 0 else 0
        )
        instance_cpu = res["cpu_count"]
        sys_cpu = cpu_count(logical=True)
        p_cores = cpu_count(logical=False)
        v_cores = (sys_cpu or 0) - (p_cores or 0)
        msg = f"""⌬ <b><i>נתוני הבוט</i></b>
┖ <b>זמן פעילות הבוט:</b> {get_readable_time(time() - bot_start_time)}

┎ <b><i>זיכרון שהוקצה לבוט</i></b>
┃ {get_progress_bar_string(bot_ram_pct)} {bot_ram_pct}%
┖ <b>בשימוש:</b> {get_readable_file_size(bot_ram_used)} | <b>פנוי:</b> {get_readable_file_size(bot_ram_free)} | <b>סה״כ:</b> {get_readable_file_size(bot_ram_total)}

┎ <b><i>זיכרון המערכת</i></b>
┃ {get_progress_bar_string(memory.percent)} {memory.percent}%
┖ <b>בשימוש:</b> {get_readable_file_size(memory.used)} | <b>פנוי:</b> {get_readable_file_size(memory.available)} | <b>סה״כ:</b> {get_readable_file_size(memory.total)}

┎ <b><i>זיכרון החלפה</i></b>
┃ {get_progress_bar_string(swap.percent)} {swap.percent}%
┖ <b>בשימוש:</b> {get_readable_file_size(swap.used)} | <b>פנוי:</b> {get_readable_file_size(swap.free)} | <b>סה״כ:</b> {get_readable_file_size(swap.total)}

┎ <b><i>מעבד שהוקצה לבוט</i></b>
┃ <b>ליבות במופע:</b> {instance_cpu}
┠ <b>סה״כ ליבות:</b> {sys_cpu} | <b>פיזיות:</b> {p_cores} | <b>לוגיות נוספות:</b> {v_cores}
┖ <b>ליבות זמינות:</b> {len(Process().cpu_affinity())}

┎ <b><i>אחסון המערכת</i></b>
┃ {get_progress_bar_string(disk)} {disk}%
┃ <b>קריאה מהדיסק:</b> {f"{get_readable_file_size(disk_io.read_bytes)} ({get_readable_time(disk_io.read_time / 1000)})" if disk_io else "אין הרשאה"}
┃ <b>כתיבה לדיסק:</b> {f"{get_readable_file_size(disk_io.write_bytes)} ({get_readable_time(disk_io.write_time / 1000)})" if disk_io else "אין הרשאה"}
┖ <b>בשימוש:</b> {get_readable_file_size(used)} | <b>פנוי:</b> {get_readable_file_size(free)} | <b>סה״כ:</b> {get_readable_file_size(total)}
"""
    elif key == "stsys":
        cpu_usage = cpu_percent(interval=0.5)
        sys_cpu = cpu_count(logical=True)
        p_cores = cpu_count(logical=False)
        v_cores = (sys_cpu or 0) - (p_cores or 0)
        msg = f"""⌬ <b><i>מערכת ההפעלה</i></b>
╟ <b>זמן פעילות:</b> {get_readable_time(time() - boot_time())}
┠ <b>גרסה:</b> {version()}
┖ <b>ארכיטקטורה:</b> {platform()}

⌬ <b><i>רשת המערכת</i></b>
╟ <b>מידע שנשלח:</b> {get_readable_file_size(net_io_counters().bytes_sent)}
┠ <b>מידע שהתקבל:</b> {get_readable_file_size(net_io_counters().bytes_recv)}
┠ <b>חבילות שנשלחו:</b> {str(net_io_counters().packets_sent)[:-3]}k
┠ <b>חבילות שהתקבלו:</b> {str(net_io_counters().packets_recv)[:-3]}k
┖ <b>סה״כ תעבורה:</b> {get_readable_file_size(net_io_counters().bytes_recv + net_io_counters().bytes_sent)}

┎ <b><i>מעבד המערכת</i></b>
┃ {get_progress_bar_string(cpu_usage)} {cpu_usage}%
┠ <b>תדר המעבד:</b> {f"{cpu_freq().current / 1000:.2f} GHz" if cpu_freq() else "אין הרשאה"}
┠ <b>עומס ממוצע:</b> {"%, ".join(str(round((x / (cpu_count() or 1) * 100), 2)) for x in getloadavg())}%, (דקה, 5 דקות, 15 דקות)
┠ <b>ליבות פיזיות:</b> {p_cores} | <b>ליבות לוגיות נוספות:</b> {v_cores}
┠ <b>סה״כ ליבות:</b> {sys_cpu}
┖ <b>ליבות זמינות:</b> {len(Process().cpu_affinity())}
"""
    elif key == "strepo":
        last_commit = git_info.commit_date() or "אין נתונים"
        changelog = git_info.commit_msg() or "N/A"
        if git_info.commit_hash() != "unknown":
            changelog += f" | <code>{git_info.commit_hash()}</code>"
        official_v = (
            await cmd_exec(
                f"curl -o latestversion.py https://raw.githubusercontent.com/SilentDemonSD/WZML-X/{Config.UPSTREAM_BRANCH}/bot/version.py -s && python3 latestversion.py && rm latestversion.py",
                True,
            )
        )[0]
        msg = f"""⌬ <b><i>נתוני המאגר</i></b>
│
┟ <b>עדכון אחרון של הבוט:</b> {last_commit}
┠ <b>גרסה נוכחית:</b> {get_version()}
┠ <b>גרסה אחרונה:</b> {official_v}
┖ <b>שינוי אחרון:</b> {changelog}

⌬ <b>הערה:</b> <code>{compare_versions(get_version(), official_v)}</code>
    """
    elif key == "stpkgs":
        ver = bot_cache.get("eng_versions", {})
        msg = f"""⌬ <b><i>גרסאות רכיבים</i></b>
│
┟ <b>python:</b> v{ver.get("python", "N/A")}
┠ <b>aria2:</b> v{ver.get("aria2", "N/A")}
┠ <b>qBittorrent:</b> v{ver.get("qBittorrent", "N/A")}
┠ <b>SABnzbd+:</b> v{ver.get("SABnzbd+", "N/A")}
┠ <b>rclone:</b> v{ver.get("rclone", "N/A")}
┠ <b>yt-dlp:</b> v{ver.get("yt-dlp", "N/A")}
┠ <b>ffmpeg:</b> v{ver.get("ffmpeg", "N/A")}
┠ <b>7z:</b> v{ver.get("7z", "N/A")}
┠ <b>Aiohttp:</b> v{ver.get("aiohttp", "N/A")}
┠ <b>WzGram:</b> v{ver.get("wzgram", "N/A")}
┠ <b>Google API:</b> v{ver.get("gapi", "N/A")}
┖ <b>MegaSDK:</b> v{ver.get("mega", "N/A")}
"""
    elif key == "tlimits":
        msg = f"""⌬ <b><i>מגבלות משימות</i></b>
│
┟ <b>קישור ישיר:</b> {Config.DIRECT_LIMIT or "∞"} GB
┠ <b>טורנט:</b> {Config.TORRENT_LIMIT or "∞"} GB
┠ <b>הורדה מ־Google Drive:</b> {Config.GD_DL_LIMIT or "∞"} GB
┠ <b>הורדה ב־Rclone:</b> {Config.RC_DL_LIMIT or "∞"} GB
┠ <b>שכפול:</b> {Config.CLONE_LIMIT or "∞"} GB
┠ <b>JDownloader:</b> {Config.JD_LIMIT or "∞"} GB
┠ <b>NZB:</b> {Config.NZB_LIMIT or "∞"} GB
┠ <b>YT-DLP:</b> {Config.YTDLP_LIMIT or "∞"} GB
┠ <b>פלייליסט:</b> {Config.PLAYLIST_LIMIT or "∞"}
┠ <b>Mega:</b> {Config.MEGA_LIMIT or "∞"} GB
┠ <b>שליחה ל־Telegram:</b> {Config.LEECH_LIMIT or "∞"} GB
┠ <b>דחיסה:</b> {Config.ARCHIVE_LIMIT or "∞"} GB
┠ <b>חילוץ:</b> {Config.EXTRACT_LIMIT or "∞"} GB
┞ <b>שטח פנוי מזערי:</b> {Config.STORAGE_LIMIT or "∞"} GB
│
┟ <b>תוקף אימות:</b> {get_readable_time(Config.VERIFY_TIMEOUT) if Config.VERIFY_TIMEOUT else "מושבת"}
┠ <b>המתנה בין משימות משתמש:</b> {Config.USER_TIME_INTERVAL or "0"} שניות
┠ <b>משימות מרביות למשתמש:</b> {Config.USER_MAX_TASKS or "∞"}
┖ <b>משימות מרביות בבוט:</b> {Config.BOT_MAX_TASKS or "∞"}
    """

    elif key == "systasks":
        try:
            processes = []
            for proc in process_iter(
                ["pid", "name", "cpu_percent", "memory_percent", "username"]
            ):
                try:
                    info = proc.info
                    if (
                        info.get("cpu_percent", 0) > 1.0
                        or info.get("memory_percent", 0) > 1.0
                    ):
                        processes.append(info)
                except (NoSuchProcess, AccessDenied):
                    continue
            processes.sort(
                key=lambda x: x.get("cpu_percent", 0) + x.get("memory_percent", 0),
                reverse=True,
            )
            processes = processes[:15]
        except Exception:
            processes = []

        msg = "⌬ <b><i>תהליכי מערכת בעלי צריכה גבוהה</i></b>\n│\n"

        if processes:
            for i, proc in enumerate(processes, 1):
                name = proc.get("name", "לא ידוע")[:20]
                cpu = proc.get("cpu_percent", 0)
                mem = proc.get("memory_percent", 0)
                user = proc.get("username", "לא ידוע")[:10]
                msg += f"┠ <b>{i:2d}.</b> <code>{name}</code>\n┃    🔹 <b>מעבד:</b> {cpu:.1f}% | <b>זיכרון:</b> {mem:.1f}%\n┃    👤 <b>משתמש:</b> {user} | <b>מזהה תהליך:</b> {proc['pid']}\n"
                btns.data_button(f"{i}", f"stats {user_id} killproc {proc['pid']}")
            msg += "┃\n┖ <i>לחיצה על המספר תאפשר לעצור את התהליך</i>"
        else:
            msg += "┃\n┖ <i>לא נמצאו תהליכים בעלי צריכה גבוהה</i>"

        btns.data_button("🔄 Refresh", f"stats {user_id} systasks", "header")

    btns.data_button("חזרה", f"stats {user_id} home", "footer")
    btns.data_button(
        "סגירה", f"stats {user_id} close", "footer", style=ButtonStyle.DANGER
    )
    return msg, btns.build_menu(8 if key == "systasks" else 2)


@new_task
async def bot_stats(_, message):
    rich_html, fallback, btns = await get_server_overview(message)
    await send_rich_message(message, rich_html, fallback, btns)


@new_task
async def stats_pages(_, query):
    data = query.data.split()
    message = query.message
    user_id = query.from_user.id
    if user_id != int(data[1]):
        await query.answer("המסך הזה שייך למשתמש אחר.", show_alert=True)
    elif data[2] == "close":
        await query.answer()
        await delete_message(message, message.reply_to_message)
    elif data[2] == "server":
        await query.answer("הנתונים רועננו.")
        rich_html, fallback, btns = await get_server_overview(query)
        await edit_rich_message(message, rich_html, fallback, btns)
    elif data[2] == "speed":
        await query.answer("בדיקת המהירות התחילה.")
        waiting = (
            "<b>🚀 בדיקת מהירות השרת</b>\n\n"
            "הבדיקה עשויה להימשך עד שתי דקות. הבוט יישאר זמין בזמן ההרצה."
        )
        await edit_message(message, waiting)
        try:
            result = await wait_for(run_server_speedtest(), timeout=120)
            rich_html, fallback, btns = get_speedtest_view(result, user_id)
            await edit_rich_message(message, rich_html, fallback, btns)
        except (ConfigRetrievalError, TimeoutError):
            buttons = ButtonMaker()
            buttons.data_button("ניסיון נוסף", f"stats {user_id} speed")
            buttons.data_button("חזרה", f"stats {user_id} server")
            await edit_message(
                message,
                "<b>בדיקת המהירות לא הושלמה.</b>\n\nשרת הבדיקה אינו זמין כרגע או שהבדיקה ארכה זמן רב מדי.",
                buttons.build_menu(2),
            )
        except Exception as error:
            LOGGER.error("בדיקת מהירות השרת נכשלה: %s", error, exc_info=True)
            buttons = ButtonMaker()
            buttons.data_button("ניסיון נוסף", f"stats {user_id} speed")
            buttons.data_button("חזרה", f"stats {user_id} server")
            await edit_message(
                message,
                "<b>בדיקת המהירות נכשלה.</b>\n\nאפשר לנסות שוב בעוד רגע.",
                buttons.build_menu(2),
            )
    elif data[2] == "killproc":
        if not await CustomFilters.owner(_, query):
            await query.answer("Sorry! You cannot Kill System Tasks!", show_alert=True)
            return
        pid = int(data[3])
        try:
            process = Process(pid)
            proc_name = process.name()
            process.terminate()
            await sleep(2)
            if process.is_running():
                process.kill()
                status = "🔥 Force killed"
            else:
                status = "✅ Terminated"
            await query.answer(f"{status}: {proc_name} (PID: {pid})", show_alert=True)
        except NoSuchProcess:
            await query.answer(
                "❌ Process not found or already terminated!", show_alert=True
            )
        except AccessDenied:
            await query.answer(
                "❌ Access denied! Cannot kill this process.", show_alert=True
            )
        except Exception as e:
            await query.answer(f"❌ שגיאה: {str(e)}", show_alert=True)

        msg, btns = await get_stats(query, "systasks")
        await edit_message(message, msg, btns)
    else:
        if data[2] == "systasks" and not await CustomFilters.sudo(_, query):
            await query.answer("Sorry! You cannot open System Tasks!", show_alert=True)
            return
        await query.answer()
        msg, btns = await get_stats(query, data[2])
        await edit_message(message, msg, btns)


async def get_version_async(command, regex, timeout=5):
    try:
        out, err, code = await wait_for(cmd_exec(command), timeout=timeout)
        if code != 0:
            return f"Error: {err}"
        match = research(regex, out)
        return match.group(1) if match else "-"
    except TimeoutError:
        return "Timeout"
    except Exception as e:
        return f"Exception: {str(e)}"


async def retry_mega_version():
    await sleep(60)
    command, regex = commands["mega"]
    version = await get_version_async(command, regex, timeout=10)
    if version != "Timeout" and not version.startswith("Exception"):
        bot_cache["eng_versions"]["mega"] = version
        LOGGER.info(f"MegaSDK Version Fetched: {version}")
    else:
        LOGGER.warning(f"Failed to fetch MegaSDK Version: {version}")


@new_task
async def get_packages_version():
    tasks = [get_version_async(command, regex) for command, regex in commands.values()]
    versions = await gather(*tasks)
    bot_cache["eng_versions"] = {}
    for tool, ver in zip(commands.keys(), versions):
        bot_cache["eng_versions"][tool] = ver
    if await aiopath.exists(".git"):
        last_commit = await cmd_exec(
            "git log -1 --date=short --pretty=format:'%cd <b>From</b> %cr'", True
        )
        last_commit = last_commit[0]
    else:
        last_commit = "No UPSTREAM_REPO"
    bot_cache["commit"] = last_commit

    if bot_cache["eng_versions"]["mega"] in ["Timeout", "N/A"] or bot_cache[
        "eng_versions"
    ]["mega"].startswith("Exception"):
        bot_loop.create_task(retry_mega_version())

    LOGGER.info("Fetched Package Versions!")
