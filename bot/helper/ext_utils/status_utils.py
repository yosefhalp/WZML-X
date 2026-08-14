from asyncio import gather, iscoroutinefunction
from html import escape
from pyrogram.enums import ButtonStyle
from re import findall
from time import time

from psutil import cpu_percent, disk_usage, virtual_memory

from ... import (
    DOWNLOAD_DIR,
    bot_cache,
    bot_start_time,
    status_dict,
    task_dict,
    task_dict_lock,
)
from ...core.config_manager import Config
from ..telegram_helper.button_build import ButtonMaker
from .status_view import ltr_code, ltr_text, rtl_html, rtl_text, status_label, value_line

SIZE_UNITS = ["B", "KB", "MB", "GB", "TB", "PB"]


class MirrorStatus:
    STATUS_UPLOAD = "Upload"
    STATUS_DOWNLOAD = "Download"
    STATUS_CLONE = "Clone"
    STATUS_QUEUEDL = "QueueDl"
    STATUS_QUEUEUP = "QueueUp"
    STATUS_PAUSED = "Pause"
    STATUS_ARCHIVE = "Archive"
    STATUS_EXTRACT = "Extract"
    STATUS_SPLIT = "Split"
    STATUS_CHECK = "CheckUp"
    STATUS_SEED = "Seed"
    STATUS_SAMVID = "SamVid"
    STATUS_CONVERT = "Convert"
    STATUS_FFMPEG = "FFmpeg"
    STATUS_YT = "YouTube"
    STATUS_METADATA = "Metadata"


class EngineStatus:
    def __init__(self):
        ver = bot_cache.get("eng_versions", {})
        self.STATUS_ARIA2 = f"Aria2 v{ver.get('aria2', 'N/A')}"
        self.STATUS_AIOHTTP = f"AioHttp v{ver.get('aiohttp', 'N/A')}"
        self.STATUS_GDAPI = f"Google-API v{ver.get('gapi', 'N/A')}"
        self.STATUS_QBIT = f"qBit v{ver.get('qBittorrent', 'N/A')}"
        self.STATUS_TGRAM = f"WzPyro v{ver.get('wzgram', 'N/A')}"
        self.STATUS_MEGA = f"MegaSDK v{ver.get('mega', 'N/A')}"
        self.STATUS_YTDLP = f"yt-dlp v{ver.get('yt-dlp', 'N/A')}"
        self.STATUS_FFMPEG = f"ffmpeg v{ver.get('ffmpeg', 'N/A')}"
        self.STATUS_7Z = f"7z v{ver.get('7z', 'N/A')}"
        self.STATUS_RCLONE = f"RClone v{ver.get('rclone', 'N/A')}"
        self.STATUS_SABNZBD = f"SABnzbd+ v{ver.get('SABnzbd+', 'N/A')}"
        self.STATUS_QUEUE = "QSystem v2"
        self.STATUS_JD = "JDownloader v2"
        self.STATUS_YT = "Youtube-Api"
        self.STATUS_METADATA = "Metadata"
        self.STATUS_UPHOSTER = "Uphoster"


STATUSES = {
    "הכול": "All",
    "הורדה": MirrorStatus.STATUS_DOWNLOAD,
    "העלאה": MirrorStatus.STATUS_UPLOAD,
    "תור הורדה": MirrorStatus.STATUS_QUEUEDL,
    "תור העלאה": MirrorStatus.STATUS_QUEUEUP,
    "אריזה": MirrorStatus.STATUS_ARCHIVE,
    "חילוץ": MirrorStatus.STATUS_EXTRACT,
    "שיתוף": MirrorStatus.STATUS_SEED,
    "העתקה": MirrorStatus.STATUS_CLONE,
    "המרה": MirrorStatus.STATUS_CONVERT,
    "פיצול": MirrorStatus.STATUS_SPLIT,
    "דוגמה": MirrorStatus.STATUS_SAMVID,
    "FFmpeg": MirrorStatus.STATUS_FFMPEG,
    "מושהה": MirrorStatus.STATUS_PAUSED,
    "בדיקה": MirrorStatus.STATUS_CHECK,
}


async def get_task_by_gid(gid: str):
    async with task_dict_lock:
        for tk in task_dict.values():
            if hasattr(tk, "seeding"):
                await tk.update()
            if tk.gid() == gid or tk.gid().startswith(gid):
                return tk
        return None


async def get_specific_tasks(status, user_id):
    if status == "All":
        if user_id:
            return [tk for tk in task_dict.values() if tk.listener.user_id == user_id]
        else:
            return list(task_dict.values())
    tasks_to_check = (
        [tk for tk in task_dict.values() if tk.listener.user_id == user_id]
        if user_id
        else list(task_dict.values())
    )
    coro_tasks = []
    coro_tasks.extend(tk for tk in tasks_to_check if iscoroutinefunction(tk.status))
    coro_statuses = await gather(*[tk.status() for tk in coro_tasks])
    result = []
    coro_index = 0
    for tk in tasks_to_check:
        if tk in coro_tasks:
            st = coro_statuses[coro_index]
            coro_index += 1
        else:
            st = tk.status()
        if (st == status) or (
            status == MirrorStatus.STATUS_DOWNLOAD and st not in STATUSES.values()
        ):
            result.append(tk)
    return result


async def get_all_tasks(req_status: str, user_id):
    async with task_dict_lock:
        return await get_specific_tasks(req_status, user_id)


def get_raw_file_size(size):
    num, unit = size.split()
    return int(float(num) * (1024 ** SIZE_UNITS.index(unit)))


def get_readable_file_size(size_in_bytes):
    if not size_in_bytes:
        return "0B"
    if size_in_bytes < 0:
        return "Unknown"

    index = 0
    while size_in_bytes >= 1024 and index < len(SIZE_UNITS) - 1:
        size_in_bytes /= 1024
        index += 1

    return f"{size_in_bytes:.2f}{SIZE_UNITS[index]}"


def get_readable_time(seconds: int):
    periods = [("d", 86400), ("h", 3600), ("m", 60), ("s", 1)]
    result = ""
    for period_name, period_seconds in periods:
        if seconds >= period_seconds:
            period_value, seconds = divmod(seconds, period_seconds)
            result += f"{int(period_value)}{period_name}"
    return result


def get_raw_time(time_str: str) -> int:
    time_units = {"d": 86400, "h": 3600, "m": 60, "s": 1}
    return sum(
        int(value) * time_units[unit]
        for value, unit in findall(r"(\d+)([dhms])", time_str)
    )


def time_to_seconds(time_duration):
    try:
        parts = time_duration.split(":")
        if len(parts) == 3:
            hours, minutes, seconds = map(float, parts)
        elif len(parts) == 2:
            hours = 0
            minutes, seconds = map(float, parts)
        elif len(parts) == 1:
            hours = 0
            minutes = 0
            seconds = float(parts[0])
        else:
            return 0
        return hours * 3600 + minutes * 60 + seconds
    except Exception:
        return 0


def speed_string_to_bytes(size_text: str):
    size = 0
    size_text = size_text.lower()
    if "k" in size_text:
        size += float(size_text.split("k")[0]) * 1024
    elif "m" in size_text:
        size += float(size_text.split("m")[0]) * 1048576
    elif "g" in size_text:
        size += float(size_text.split("g")[0]) * 1073741824
    elif "t" in size_text:
        size += float(size_text.split("t")[0]) * 1099511627776
    elif "b" in size_text:
        size += float(size_text.split("b")[0])
    return size


def get_progress_bar_string(pct):
    pct = float(str(pct).strip("%"))
    p = min(max(pct, 0), 100)
    cFull = int(p // 8)
    cPart = int(p % 8 - 1)
    p_str = "■" * cFull
    if cPart >= 0:
        p_str += ["▤", "▥", "▦", "▧", "▨", "▩", "■"][cPart]
    p_str += "□" * (12 - cFull)
    return f"[{p_str}]"


def _task_status_card(index, task, tstatus, elapsed):
    """בונה כרטיס משימה עברי שבו כל ערך טכני מבודד כ-LTR."""

    from ..telegram_helper.bot_commands import BotCommands

    listener = task.listener
    lines = [
        f"📦 <b>{rtl_text(f'משימה {index}')}</b>",
        value_line("שם", task.name(), code=False),
    ]
    if listener.subname:
        lines.append(value_line("שם משנה", listener.subname, code=False))

    user = listener.message.from_user
    actor = user.mention(style="html")
    lines.append(
        f"<b>{rtl_text('הופעלה על ידי')}:</b> {rtl_html(actor)} · "
        f"<b>{rtl_text('מזהה')}:</b> {ltr_code(user.id)}"
    )
    if listener.is_super_chat:
        lines.append(
            f"<b>{rtl_text('מקור')}:</b> "
            f"<a href='{escape(listener.message.link, quote=True)}'>{rtl_text('פתיחת ההודעה')}</a>"
        )

    if (
        tstatus not in [MirrorStatus.STATUS_SEED, MirrorStatus.STATUS_QUEUEUP]
        and listener.progress
    ):
        progress = task.progress()
        lines.append(
            f"<b>{rtl_text('התקדמות')}:</b> "
            f"{ltr_text(f'{get_progress_bar_string(progress)} {progress}')}"
        )
        processed_values = [task.processed_bytes()]
        if listener.subname:
            processed_values.append(get_readable_file_size(listener.subsize))
        lines.append(
            f"<b>{rtl_text('עובד')}:</b> "
            f"{ltr_code(' / '.join(processed_values))} "
            f"<b>{rtl_text('מתוך')}:</b> {ltr_code(task.size())}"
        )
        if listener.subname:
            total_files = len(listener.files_to_proceed) or "?"
            lines.append(
                f"<b>{rtl_text('קבצים')}:</b> "
                f"{ltr_code(f'{listener.proceed_count} / {total_files}')}"
            )
        lines.append(f"<b>{rtl_text('מצב')}:</b> {rtl_text(status_label(tstatus))}")
        lines.append(value_line("מהירות", task.speed()))
        eta = task.eta()
        total_time = get_readable_time(elapsed + get_raw_time(eta))
        lines.append(
            f"<b>{rtl_text('זמן נותר')}:</b> {ltr_code(eta)} · "
            f"<b>{rtl_text('זמן כולל משוער')}:</b> {ltr_code(total_time)} · "
            f"<b>{rtl_text('זמן שעבר')}:</b> {ltr_code(get_readable_time(elapsed))}"
        )
        if tstatus == MirrorStatus.STATUS_DOWNLOAD and (
            listener.is_torrent or listener.is_qbit
        ):
            try:
                lines.append(
                    f"<b>{rtl_text('משתפים')}:</b> {ltr_code(task.seeders_num())} · "
                    f"<b>{rtl_text('מורידים')}:</b> {ltr_code(task.leechers_num())}"
                )
            except Exception:
                pass
    elif tstatus == MirrorStatus.STATUS_SEED:
        lines.extend(
            [
                f"<b>{rtl_text('גודל')}:</b> {ltr_code(task.size())} · "
                f"<b>{rtl_text('הועלה')}:</b> {ltr_code(task.uploaded_bytes())}",
                f"<b>{rtl_text('מצב')}:</b> {rtl_text(status_label(tstatus))}",
                value_line("מהירות שיתוף", task.seed_speed()),
                value_line("יחס שיתוף", task.ratio()),
                f"<b>{rtl_text('זמן שיתוף')}:</b> {ltr_code(task.seeding_time())} · "
                f"<b>{rtl_text('זמן שעבר')}:</b> {ltr_code(get_readable_time(elapsed))}",
            ]
        )
    else:
        lines.extend(
            [
                f"<b>{rtl_text('מצב')}:</b> {rtl_text(status_label(tstatus))}",
                value_line("גודל", task.size()),
            ]
        )

    lines.extend(
        [
            value_line("מנוע", task.engine),
            value_line("מקור", listener.mode[0]),
            value_line("יעד", listener.mode[1]),
        ]
    )
    if tstatus in {
        MirrorStatus.STATUS_DOWNLOAD,
        MirrorStatus.STATUS_PAUSED,
        MirrorStatus.STATUS_QUEUEDL,
    } and (listener.is_torrent or listener.is_qbit or listener.is_nzb):
        lines.append(
            f"<b>{rtl_text('בחירת קבצים')}:</b> "
            f"{ltr_code(f'/{BotCommands.SelectCommand[1]}_{task.gid()[:8]}')}"
        )
    lines.append(
        f"🛑 <b>{rtl_text('עצירת המשימה')}:</b> "
        f"{ltr_code(f'/{BotCommands.CancelTaskCommand[1]}_{task.gid()[:8]}')}"
    )
    return "\n".join(lines)


async def get_readable_message(sid, is_user, page_no=1, status="All", page_step=1):
    msg = ""
    button = None

    tasks = await get_specific_tasks(status, sid if is_user else None)

    STATUS_LIMIT = Config.STATUS_LIMIT
    tasks_no = len(tasks)
    pages = (max(tasks_no, 1) + STATUS_LIMIT - 1) // STATUS_LIMIT
    if page_no > pages:
        page_no = (page_no - 1) % pages + 1
        status_dict[sid]["page_no"] = page_no
    elif page_no < 1:
        page_no = pages - (abs(page_no) % pages)
        status_dict[sid]["page_no"] = page_no
    start_position = (page_no - 1) * STATUS_LIMIT

    for index, task in enumerate(
        tasks[start_position : STATUS_LIMIT + start_position], start=1
    ):
        if status != "All":
            tstatus = status
        elif iscoroutinefunction(task.status):
            tstatus = await task.status()
        else:
            tstatus = task.status()
        elapsed = time() - task.listener.message.date.timestamp()
        msg += _task_status_card(index + start_position, task, tstatus, elapsed)
        msg += "\n\n"

    if len(msg) == 0:
        if status == "All":
            return None, None
        else:
            msg = f"{rtl_text('אין כרגע משימות פעילות במצב')} {rtl_text(status_label(status))}.\n\n"

    msg += f"📊 <b><u>{rtl_text('מצב מערכת')}</u></b>\n"
    buttons = ButtonMaker()
    if not is_user:
        buttons.data_button(
            "📜 סקירת משימות",
            f"status {sid} ov",
            position="header",
            style=ButtonStyle.PRIMARY,
        )
    if len(tasks) > STATUS_LIMIT:
        msg += (
            f"<b>{rtl_text('עמוד')}:</b> {ltr_code(f'{page_no}/{pages}')} · "
            f"<b>{rtl_text('משימות')}:</b> {ltr_code(tasks_no)} · "
            f"<b>{rtl_text('קפיצה')}:</b> {ltr_code(page_step)}\n"
        )
        buttons.data_button("⬅️ הקודם", f"status {sid} pre", position="header")
        buttons.data_button("הבא ➡️", f"status {sid} nex", position="header")
        if tasks_no > 30:
            for i in [1, 2, 4, 6, 8, 10, 15]:
                buttons.data_button(i, f"status {sid} ps {i}", position="footer")
    if status != "All" or tasks_no > 20:
        for label, status_value in list(STATUSES.items()):
            if status_value != status:
                buttons.data_button(label, f"status {sid} st {status_value}")
    buttons.data_button(
        "♻️ רענון", f"status {sid} ref", position="header", style=ButtonStyle.PRIMARY
    )
    button = buttons.build_menu(8)
    free_disk = get_readable_file_size(disk_usage(DOWNLOAD_DIR).free)
    free_percent = round(100 - disk_usage(DOWNLOAD_DIR).percent, 1)
    msg += (
        f"<b>{rtl_text('מעבד')}:</b> {ltr_code(f'{cpu_percent()}%')} · "
        f"<b>{rtl_text('זיכרון')}:</b> {ltr_code(f'{virtual_memory().percent}%')}\n"
        f"<b>{rtl_text('אחסון פנוי')}:</b> {ltr_code(f'{free_disk} ({free_percent}%)')} · "
        f"<b>{rtl_text('זמן פעילות')}:</b> {ltr_code(get_readable_time(time() - bot_start_time))}"
    )
    return msg, button
