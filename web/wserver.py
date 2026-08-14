# ruff: noqa: E402
try:
    from uvloop import install

    install()
except ImportError:
    pass


from asyncio import new_event_loop, set_event_loop

bot_loop = new_event_loop()
set_event_loop(bot_loop)

from asyncio import sleep
from importlib import import_module
from os import environ
from re import compile as re_compile
from urllib.parse import parse_qs, urlparse
from hmac import compare_digest
from json import JSONDecodeError, loads
from pathlib import Path
from socket import create_connection
from time import time
from contextlib import asynccontextmanager
from inspect import isawaitable
from logging import INFO, WARNING, FileHandler, StreamHandler, basicConfig, getLogger

from aioaria2 import Aria2HttpClient
from aiohttp.client_exceptions import ClientError
from aioqbt.client import create_client
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from sabnzbdapi import SabnzbdClient
from aioqbt.exc import AQError

from web.nodes import extract_file_ids, make_tree
from aiohttp import ClientSession
from psutil import cpu_percent, disk_usage, virtual_memory

from bot import DOWNLOAD_DIR, task_dict, task_dict_lock
from web.health_state import read_release_id
from bot.helper.ext_utils.backup_control import (
    read_backup_settings,
    request_backup,
)
from bot.helper.ext_utils.cache_control import read_cache_status, request_cache_action
from bot.helper.ext_utils.links_utils import (
    is_magnet,
    is_url,
    normalize_external_link,
)
from bot.helper.ext_utils.residual_downloads import (
    clear_residual_downloads,
    residual_download_status,
)
from bot.helper.ext_utils.status_utils import get_task_by_gid
from bot.helper.ext_utils.telegram_delivery import normalize_telegram_channel
from bot.helper.ext_utils.task_control import (
    enqueue_task_request,
    read_task_request_status,
)
from bot.core.config_manager import Config
from bot.modules.guided_ui_model import (
    build_task_command,
    guided_text_mode,
    session_defaults,
)

getLogger("niquests").setLevel(WARNING)
getLogger("aiohttp").setLevel(WARNING)
getLogger("uvicorn").setLevel(WARNING)
getLogger("uvicorn.access").setLevel(WARNING)

basicConfig(
    format="[%(asctime)s] [%(levelname)s] - %(message)s",
    datefmt="%d-%b-%y %I:%M:%S %p",
    handlers=[FileHandler("log.txt"), StreamHandler()],
    level=INFO,
)

LOGGER = getLogger(__name__)

_SAFE_PATH = re_compile(r"^[A-Za-z0-9_./-]+$")
_SAFE_GID = re_compile(r"^[A-Za-z0-9_-]{1,64}$")
_SAFE_PIN = re_compile(r"^\d{4}$")
_SERVICE_PWD_SALT = b"wzmlx_v3_service_pwd_salt"
_PIN_SALT = b"wzmlx_v3_pin_salt"
_PIN_LEN = 4
_PIN_RATE_LIMIT = 5
_PIN_RATE_WINDOW = 60
_pin_attempts: dict = {}

_cached_secret_bytes = None


def _load_config():
    try:
        cfg = import_module("config")
    except ModuleNotFoundError:
        cfg = None
    bot_token = environ.get("BOT_TOKEN", "") or (
        getattr(cfg, "BOT_TOKEN", "") if cfg else ""
    )
    access_pwd = environ.get("WEB_ACCESS_PASSWORD", "") or (
        getattr(cfg, "WEB_ACCESS_PASSWORD", "") if cfg else ""
    )
    return bot_token, access_pwd


def _resolve_bot_id(token):
    if not token or not isinstance(token, str):
        return "0"
    token = token.strip()
    if not token:
        return "0"
    return (token.split(":", 1)[0] or "0").strip()


_BOT_TOKEN, _ACCESS_PASSWORD = _load_config()
_BOT_ID = _resolve_bot_id(_BOT_TOKEN)


def _service_pwd(service):
    from hashlib import sha256
    from hmac import new as hmac_new
    from secrets import token_bytes

    global _cached_secret_bytes
    if not _ACCESS_PASSWORD:
        if _cached_secret_bytes is None:
            _cached_secret_bytes = token_bytes(32)
        secret = _cached_secret_bytes
    elif isinstance(_ACCESS_PASSWORD, str):
        secret = _ACCESS_PASSWORD.encode("utf-8")
    else:
        secret = _ACCESS_PASSWORD
    msg = f"{_BOT_ID}:{service}".encode("utf-8")
    digest = hmac_new(_SERVICE_PWD_SALT, msg, sha256)
    digest.update(secret)
    raw = digest.hexdigest()
    return raw[:20] + raw[-4:]


def _derive_pin(gid):
    from hashlib import sha256
    from hmac import new as hmac_new

    sig = hmac_new(
        _PIN_SALT,
        f"{gid}|{_BOT_ID}".encode("utf-8"),
        sha256,
    ).hexdigest()
    digits = "".join(c for c in sig if c.isdigit())[:_PIN_LEN]
    if len(digits) < _PIN_LEN:
        digits = (digits + sig).ljust(_PIN_LEN, "0")[:_PIN_LEN]
    return digits


def _pin_rate_limited(gid):
    now = time()
    cutoff = now - _PIN_RATE_WINDOW
    attempts = _pin_attempts.get(gid, [])
    attempts = [t for t in attempts if t > cutoff]
    if attempts:
        _pin_attempts[gid] = attempts
    else:
        _pin_attempts.pop(gid, None)
    if len(_pin_attempts) > 10000:
        stale = [
            g for g, ts in _pin_attempts.items() if not ts or (ts and ts[-1] < cutoff)
        ]
        for g in stale:
            _pin_attempts.pop(g, None)
    return len(attempts) >= _PIN_RATE_LIMIT


def _record_pin_attempt(gid):
    from time import time

    _pin_attempts.setdefault(gid, []).append(time())


def _verify_pin(gid, pin):
    from hashlib import sha256
    from hmac import new as hmac_new

    if not gid or not pin:
        return False
    if not _SAFE_PIN.match(pin):
        return False
    expected = _derive_pin(gid)
    if not expected:
        return False
    return (
        hmac_new(_PIN_SALT, expected.encode(), sha256).hexdigest()
        == hmac_new(_PIN_SALT, pin.encode(), sha256).hexdigest()
    )


aria2 = None
qbittorrent = None
sabnzbd_client = SabnzbdClient(
    host="http://localhost",
    api_key=_service_pwd("sabnzbd"),
    port="8070",
)
SERVICES = {
    "nzb": {"url": "http://localhost:8070/", "password": _service_pwd("sabnzbd")},
    "qbit": {"url": "http://localhost:8090", "password": _service_pwd("qbit")},
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global aria2, qbittorrent
    aria2 = Aria2HttpClient("http://localhost:6800/jsonrpc")
    qbittorrent = await create_client("http://localhost:8090/api/v2/")
    yield
    await aria2.close()
    await qbittorrent.close()


app = FastAPI(lifespan=lifespan)


templates = Jinja2Templates(directory="web/templates/")


async def re_verify(paused, resumed, hash_id):
    k = 0
    while True:
        res = await qbittorrent.torrents.files(hash_id)
        verify = True
        for i in res:
            if i.index in paused and i.priority != 0:
                verify = False
                break
            if i.index in resumed and i.priority == 0:
                verify = False
                break
        if verify:
            break
        LOGGER.info("Reverification Failed! Correcting stuff...")
        await sleep(0.5)
        if paused:
            try:
                await qbittorrent.torrents.file_prio(
                    hash=hash_id, id=paused, priority=0
                )
            except (ClientError, TimeoutError, Exception, AQError) as e:
                LOGGER.error(f"{e} Errored in reverification paused!")
        if resumed:
            try:
                await qbittorrent.torrents.file_prio(
                    hash=hash_id, id=resumed, priority=1
                )
            except (ClientError, TimeoutError, Exception, AQError) as e:
                LOGGER.error(f"{e} Errored in reverification resumed!")
        k += 1
        if k > 5:
            return False
    LOGGER.info(f"Verified! Hash: {hash_id}")
    return True


@app.get("/app/files", response_class=HTMLResponse)
async def files(request: Request):
    response = templates.TemplateResponse(request, "page.html")
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.api_route(
    "/app/files/torrent", methods=["GET", "POST"], response_class=HTMLResponse
)
async def handle_torrent(request: Request):
    params = request.query_params

    if not (gid := params.get("gid")):
        return JSONResponse(
            {
                "files": [],
                "engine": "",
                "error": "GID is missing",
                "message": "מזהה המשימה חסר. יש לפתוח מחדש את הקישור מתוך הבוט.",
            }
        )

    if not _SAFE_GID.match(gid):
        return JSONResponse(
            {
                "files": [],
                "engine": "",
                "error": "Invalid GID",
                "message": "מזהה המשימה אינו תקין או שהמשימה כבר הסתיימה.",
            }
        )

    if not (pin := params.get("pin")):
        return JSONResponse(
            {
                "files": [],
                "engine": "",
                "error": "Pin is missing",
                "message": "לא הוזן קוד גישה.",
            }
        )

    if _pin_rate_limited(gid):
        return JSONResponse(
            {
                "files": [],
                "engine": "",
                "error": "Too many attempts",
                "message": f"בוצעו יותר מדי ניסיונות. אפשר לנסות שוב בעוד {_PIN_RATE_WINDOW} שניות.",
            },
            status_code=429,
        )

    if not _verify_pin(gid, pin):
        _record_pin_attempt(gid)
        return JSONResponse(
            {
                "files": [],
                "engine": "",
                "error": "Invalid pin",
                "message": "קוד הגישה שגוי. יש לבדוק אותו ולנסות שוב.",
            }
        )
    _pin_attempts.pop(gid, None)

    if request.method == "POST":
        if not (mode := params.get("mode")):
            return JSONResponse(
                {
                    "files": [],
                    "engine": "",
                    "error": "Mode is not specified",
                    "message": "סוג הפעולה חסר בבקשה.",
                }
            )
        data = await request.json()
        if mode == "rename":
            if len(gid) > 20:
                await handle_rename(gid, data)
                content = {
                    "files": [],
                    "engine": "",
                    "error": "",
                    "message": "השם עודכן בהצלחה.",
                }
            else:
                content = {
                    "files": [],
                    "engine": "",
                    "error": "Rename failed.",
                    "message": "אי אפשר לשנות שם לקובץ בטורנט שמנוהל באמצעות aria2c.",
                }
        else:
            selected_files, unselected_files = extract_file_ids(data)
            if gid.startswith("SABnzbd_nzo"):
                await set_sabnzbd(gid, unselected_files)
            elif len(gid) > 20:
                await set_qbittorrent(gid, selected_files, unselected_files)
            else:
                selected_files = ",".join(selected_files)
                await set_aria2(gid, selected_files)
            content = {
                "files": [],
                "engine": "",
                "error": "",
                "message": "בחירת הקבצים נשמרה בהצלחה.",
            }
    else:
        try:
            if gid.startswith("SABnzbd_nzo"):
                res = await sabnzbd_client.get_files(gid)
                content = make_tree(res, "sabnzbd")
            elif len(gid) > 20:
                res = await qbittorrent.torrents.files(gid)
                content = make_tree(res, "qbittorrent")
            else:
                res = await aria2.getFiles(gid)
                op = await aria2.getOption(gid)
                fpath = f"{op['dir']}/"
                content = make_tree(res, "aria2", fpath)
        except (ClientError, TimeoutError, Exception, AQError) as e:
            LOGGER.error(str(e))
            content = {
                "files": [],
                "engine": "",
                "error": "Error getting files",
                "message": str(e),
            }
    return JSONResponse(content)


async def handle_rename(gid, data):
    try:
        _type = data["type"]
        del data["type"]
        if _type == "file":
            await qbittorrent.torrents.rename_file(hash=gid, **data)
        else:
            await qbittorrent.torrents.rename_folder(hash=gid, **data)
    except (ClientError, TimeoutError, Exception, AQError) as e:
        LOGGER.error(f"{e} Errored in renaming")


async def set_sabnzbd(gid, unselected_files):
    await sabnzbd_client.remove_file(gid, unselected_files)
    LOGGER.info(f"Verified! nzo_id: {gid}")


async def set_qbittorrent(gid, selected_files, unselected_files):
    if unselected_files:
        try:
            await qbittorrent.torrents.file_prio(
                hash=gid, id=unselected_files, priority=0
            )
        except (ClientError, TimeoutError, Exception, AQError) as e:
            LOGGER.error(f"{e} Errored in paused")
    if selected_files:
        try:
            await qbittorrent.torrents.file_prio(
                hash=gid, id=selected_files, priority=1
            )
        except (ClientError, TimeoutError, Exception, AQError) as e:
            LOGGER.error(f"{e} Errored in resumed")
    await sleep(0.5)
    if not await re_verify(unselected_files, selected_files, gid):
        LOGGER.error(f"Verification Failed! Hash: {gid}")


async def set_aria2(gid, selected_files):
    res = await aria2.changeOption(gid, {"select-file": selected_files})
    if res == "OK":
        LOGGER.info(f"Verified! Gid: {gid}")
    else:
        LOGGER.info(f"Verification Failed! Report! Gid: {gid}")


@app.get("/", response_class=HTMLResponse)
async def homepage(request: Request):
    authorized = _dashboard_authorized(request)
    response = templates.TemplateResponse(
        request,
        "landing.html",
        await _dashboard_context(authorized=authorized),
    )
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.post("/", response_class=HTMLResponse)
async def dashboard_login(request: Request):
    """מאמת את סיסמת לוח הניהול ושומר בדפדפן רק אסימון נגזר."""

    values = parse_qs((await request.body()).decode("utf-8", errors="replace"))
    password = (values.get("password") or [""])[0]
    if not _ACCESS_PASSWORD or not compare_digest(password, _ACCESS_PASSWORD):
        return templates.TemplateResponse(
            request,
            "landing.html",
            await _dashboard_context(
                authorized=False, error="הסיסמה אינה נכונה. אפשר לנסות שוב."
            ),
            status_code=403,
        )
    response = templates.TemplateResponse(
        request, "landing.html", await _dashboard_context(authorized=True)
    )
    response.set_cookie(
        "wzmlx_dashboard",
        _service_pwd("dashboard"),
        httponly=True,
        samesite="strict",
        secure=request.headers.get("x-forwarded-proto") == "https",
        max_age=60 * 60 * 24 * 7,
    )
    return response


@app.post("/logout", response_class=HTMLResponse)
async def dashboard_logout(request: Request):
    response = templates.TemplateResponse(
        request, "landing.html", await _dashboard_context(authorized=False)
    )
    response.delete_cookie("wzmlx_dashboard")
    return response


def _dashboard_authorized(request: Request) -> bool:
    """מאמת את עוגיית לוח הניהול בהשוואה קבועת זמן."""

    session_token = request.cookies.get("wzmlx_dashboard") or ""
    return bool(
        _ACCESS_PASSWORD
        and compare_digest(session_token, _service_pwd("dashboard"))
    )


def _csrf_valid(value: str) -> bool:
    """בודק אסימון פעולה נפרד כדי שאתר חיצוני לא יוכל ללחוץ בשם המשתמש."""

    return bool(value) and compare_digest(value, _service_pwd("dashboard-csrf"))


async def _active_task_rows() -> list[dict[str, str]]:
    """מחזיר את כל שלבי המשימות, כולל העלאה ועיבוד, בלי לחשוף קישורי מקור."""

    async with task_dict_lock:
        current = list(task_dict.items())
    rows: list[dict[str, str]] = []
    for mid, task in current:
        try:
            name = task.name()
            state = task.status()
            progress = task.progress()
            gid = task.gid()
            if isawaitable(name):
                name = await name
            if isawaitable(state):
                state = await state
            if isawaitable(progress):
                progress = await progress
            if isawaitable(gid):
                gid = await gid
            rows.append(
                {
                    "mid": str(mid),
                    "gid": str(gid or "")[:128],
                    "name": str(name or "משימה ללא שם")[:160],
                    "state": str(state or "פעילה")[:80],
                    "progress": str(progress or "")[:40],
                }
            )
        except Exception as error:
            LOGGER.warning("לא ניתן לקרוא משימה פעילה לדשבורד: %s", error)
    return rows


async def _dashboard_action_result(request: Request) -> tuple[str, bool]:
    """מבצע רק פעולות בעלים מרשימה סגורה ומחזיר הודעה להצגה בדשבורד."""

    values = parse_qs((await request.body()).decode("utf-8", errors="replace"))
    csrf = (values.get("csrf") or [""])[0]
    if not _csrf_valid(csrf):
        raise HTTPException(status_code=403, detail="אסימון הפעולה אינו תקין")
    action = (values.get("action") or [""])[0]
    if action in {"cache_scan", "cache_clean"}:
        request_id = request_cache_action(
            "scan" if action == "cache_scan" else "clean_safe"
        )
        return f"בקשת המטמון {request_id} נשלחה ל־Worker.", True
    if action in {"backup_state", "backup_full"}:
        settings = read_backup_settings()
        job_id = request_backup(
            chat_id=settings.daily_chat_id,
            include_images=action == "backup_full",
        )
        return f"בקשת הגיבוי {job_id} נשלחה ל־Worker.", True
    if action == "clean_downloads":
        async with task_dict_lock:
            active_ids = {str(mid) for mid in task_dict}
        selection = await _active_selection_tasks()
        if selection:
            active_ids.add("engine-active")
        result = clear_residual_downloads(Path(DOWNLOAD_DIR), active_task_ids=active_ids)
        return (
            f"נמחקו {result['removed_files']} קבצי שאריות, "
            f"בנפח {_human_size(result['removed_bytes'])}.",
            True,
        )
    if action == "cancel_task":
        gid = (values.get("gid") or [""])[0]
        if not gid or len(gid) > 128:
            raise ValueError("מזהה המשימה אינו תקין")
        task = await get_task_by_gid(gid)
        if task is None:
            raise ValueError("המשימה כבר הסתיימה או אינה קיימת")
        await task.task().cancel_task()
        return "בקשת הביטול הועברה למנוע המשימה.", True
    if action == "start_task":
        raw_links = (values.get("links") or [""])[0]
        links = [
            normalized
            for line in raw_links.splitlines()
            if (normalized := normalize_external_link(line))
        ]
        if not links or len(links) > 50:
            raise ValueError("יש להזין בין קישור אחד ל־50 קישורים")
        if any(not (is_url(link) or is_magnet(link)) for link in links):
            raise ValueError("לפחות אחד מהקישורים אינו כתובת או Magnet תקינים")
        mode = (values.get("mode") or ["auto"])[0]
        destination = (values.get("destination") or ["telegram"])[0]
        upload_source = (values.get("upload_source") or ["bot"])[0]
        upload_target = (values.get("upload_target") or ["private"])[0]
        upload_channel = (values.get("upload_channel") or [""])[0].strip()
        if mode not in {"auto", "torrent", "youtube", "usenet", "jdownloader"}:
            raise ValueError("מנוע המקור אינו מוכר")
        if destination not in {"telegram", "gofile", "cloud"}:
            raise ValueError("יעד ההעלאה אינו מוכר")
        if upload_source not in {"bot", "user"}:
            raise ValueError("מקור ההעלאה ל־Telegram אינו מוכר")
        if upload_target not in {"private", "channel"}:
            raise ValueError("יעד Telegram אינו מוכר")
        if destination == "telegram" and upload_target == "channel":
            upload_channel = normalize_telegram_channel(upload_channel)
        if mode == "torrent" and Config.DISABLE_TORRENTS:
            raise RuntimeError("qBittorrent מושבת בהגדרות הבוט")
        if mode == "usenet" and (Config.DISABLE_NZB or not Config.USENET_SERVERS):
            raise RuntimeError("SABnzbd פעיל, אך נדרש להגדיר חשבון Usenet לפני הפעלה")
        if mode == "jdownloader" and (
            Config.DISABLE_JD or not Config.JD_EMAIL or not Config.JD_PASS
        ):
            raise RuntimeError("JDownloader מושבת עד להגדרת חשבון MyJDownloader")
        session = session_defaults(mode)
        session["destination"] = destination
        if destination == "telegram":
            session["upload_source"] = upload_source
            session["upload_target"] = upload_target
            session["upload_channel"] = upload_channel
        text_mode = guided_text_mode("\n".join(links))
        session["bulk"] = text_mode["is_bulk"]
        command, _handler = build_task_command(session, text_mode["command_input"])
        request_id = enqueue_task_request(
            command=command,
            source_text="\n".join(links) if text_mode["is_bulk"] else "",
            requires_premium=destination == "telegram" and upload_source == "user",
        )
        return (
            f"בקשת המשימה {request_id} הועברה לתור הבוט עבור {len(links)} "
            f"קישורים דרך מנגנון {'Bulk' if text_mode['is_bulk'] else 'רגיל'}.",
            True,
        )
    raise ValueError("הפעולה אינה מוכרת")


@app.post("/dashboard/action", response_class=HTMLResponse)
async def dashboard_action(request: Request):
    """מרכז פעולות ה־Web; כל פעולה מחייבת Session וסימון CSRF תקינים."""

    if not _dashboard_authorized(request):
        raise HTTPException(status_code=403, detail="נדרשת כניסה ללוח הניהול")
    notice = ""
    notice_ok = False
    try:
        notice, notice_ok = await _dashboard_action_result(request)
    except HTTPException:
        raise
    except (ValueError, RuntimeError) as error:
        notice = " ".join(str(error or "הפעולה נכשלה").split())[:240]
    except Exception as error:
        LOGGER.exception("פעולת הדשבורד נכשלה: %s", type(error).__name__)
        notice = "הפעולה נכשלה. הפרטים נשמרו ביומן השרת בלי לחשוף מידע רגיש."
    response = templates.TemplateResponse(
        request,
        "landing.html",
        await _dashboard_context(
            authorized=True,
            notice=notice,
            notice_ok=notice_ok,
        ),
    )
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


@app.get("/health")
async def health():
    """מאמת שגם השרת וגם חיבור Telegram הראשי באמת פעילים."""

    marker = Path("/usr/src/app/runtime/control/telegram-health.json")
    try:
        telegram = loads(marker.read_text(encoding="utf-8"))
        marker_age = time() - float(telegram["updated_at"])
        telegram_ok = bool(telegram.get("ok")) and 0 <= marker_age <= 90
    except (OSError, JSONDecodeError, KeyError, TypeError, ValueError):
        telegram_ok = False
        marker_age = None
    payload = {
        "ok": telegram_ok,
        "service": "wzmlx",
        "release_id": read_release_id(),
        "telegram": "connected" if telegram_ok else "disconnected",
    }
    if marker_age is not None:
        payload["telegram_check_age_seconds"] = round(marker_age, 1)
    return JSONResponse(payload, status_code=200 if telegram_ok else 503)


def _port_ready(port: int) -> bool:
    try:
        with create_connection(("127.0.0.1", port), timeout=0.25):
            return True
    except OSError:
        return False


async def _active_selection_tasks() -> list[dict[str, str]]:
    """מחזיר רק משימות מנוע פעילות; כל קישור מקבל GID וקוד תואמים."""

    tasks: list[dict[str, str]] = []
    try:
        for torrent in await qbittorrent.torrents.info():
            gid = str(getattr(torrent, "hash", "") or "")
            if not _SAFE_GID.fullmatch(gid):
                continue
            name = str(getattr(torrent, "name", "") or "טורנט ללא שם")[:120]
            state = str(getattr(torrent, "state", "") or "פעיל")[:40]
            tasks.append(
                {
                    "engine": "qBittorrent",
                    "name": name,
                    "state": state,
                    "gid": gid,
                    "url": f"/app/files?gid={gid}&pin={_derive_pin(gid)}",
                }
            )
    except Exception as error:
        LOGGER.warning("לא ניתן לקרוא משימות qBittorrent לדשבורד: %s", error)
    try:
        aria_downloads = [
            *(await aria2.tellActive()),
            *(await aria2.tellWaiting(0, 100)),
        ]
        for download in aria_downloads:
            gid = str(download.get("gid", "") or "")
            if not _SAFE_GID.fullmatch(gid):
                continue
            files = download.get("files") or []
            path = str(files[0].get("path", "") if files else "")
            name = Path(path).name or "הורדת Aria2"
            tasks.append(
                {
                    "engine": "Aria2",
                    "name": name[:120],
                    "state": str(download.get("status", "פעיל"))[:40],
                    "gid": gid,
                    "url": f"/app/files?gid={gid}&pin={_derive_pin(gid)}",
                }
            )
    except Exception as error:
        LOGGER.warning("לא ניתן לקרוא משימות Aria2 לדשבורד: %s", error)
    try:
        queue = (await sabnzbd_client.get_downloads()).get("queue", {})
        for slot in queue.get("slots") or []:
            gid = str(slot.get("nzo_id", "") or "")
            if not _SAFE_GID.fullmatch(gid):
                continue
            tasks.append(
                {
                    "engine": "SABnzbd",
                    "name": str(slot.get("filename") or "משימת NZB")[:120],
                    "state": str(slot.get("status") or "פעיל")[:40],
                    "gid": gid,
                    "url": f"/app/files?gid={gid}&pin={_derive_pin(gid)}",
                }
            )
    except Exception as error:
        LOGGER.warning("לא ניתן לקרוא משימות SABnzbd לדשבורד: %s", error)
    return tasks[:100]


async def _dashboard_context(
    *,
    authorized: bool,
    error: str = "",
    notice: str = "",
    notice_ok: bool = False,
) -> dict:
    """אוסף רק נתוני תצוגה בטוחים; סודות לעולם אינם נשלחים לתבנית."""

    context = {
        "authorized": authorized,
        "error": error,
        "notice": notice,
        "notice_ok": notice_ok,
    }
    if not authorized:
        return context
    memory = virtual_memory()
    disk = disk_usage("/")
    backup = {}
    try:
        backup = loads(
            Path("runtime/control/backup-status.json").read_text(encoding="utf-8")
        )
    except (OSError, JSONDecodeError, TypeError):
        pass
    qbit_ready = _port_ready(8090)
    nzb_ready = _port_ready(8070)
    active_tasks = await _active_task_rows()
    selection_tasks = await _active_selection_tasks()
    active_ids = {row["mid"] for row in active_tasks}
    if selection_tasks and not active_tasks:
        active_ids.add("engine-active")
    residuals = residual_download_status(
        Path(DOWNLOAD_DIR),
        active_task_ids=active_ids,
    )
    cache = read_cache_status()
    task_request = read_task_request_status()
    context.update(
        {
            "cpu": round(cpu_percent(interval=0.15), 1),
            "memory": round(memory.percent, 1),
            "memory_used": _human_size(memory.used),
            "memory_total": _human_size(memory.total),
            "disk": round(disk.percent, 1),
            "disk_free": _human_size(disk.free),
            "services": [
                ("WZML-X", True),
                ("MongoDB", _port_ready(27017)),
                ("Telegram Bot API", _port_ready(8081)),
                ("qBittorrent", qbit_ready),
                ("SABnzbd", nzb_ready),
                ("Aria2", _port_ready(6800)),
            ],
            "backup_state": {
                "running": "מתבצע כעת",
                "success": "תקין",
                "failed": "נכשל",
            }.get(backup.get("state"), "אין מידע"),
            "backup_time": backup.get("finished_at") or "טרם נוצר",
            "backup_size": _human_size(backup.get("size_bytes", 0)),
            "backup_job": backup.get("job_id") or "—",
            "backup_mode": backup.get("mode") or "—",
            "cache": {
                "state": cache.state,
                "stage": cache.stage or "טרם נסרק",
                "python": _human_size(cache.python_bytes),
                "docker": _human_size(cache.docker_build_bytes),
                "reclaimable": _human_size(cache.docker_reclaimable_bytes),
                "bot_api": _human_size(cache.bot_api_bytes + cache.bot_api_protected_bytes),
                "scanned_at": cache.scanned_at or "טרם נסרק",
            },
            "residuals": {
                **residuals,
                "size": _human_size(residuals["bytes"]),
            },
            "active_tasks": active_tasks,
            "task_request": task_request,
            "csrf": _service_pwd("dashboard-csrf"),
            "qbit_url": f"/qbit/?pass={_service_pwd('qbit')}" if qbit_ready else "",
            "nzb_url": f"/nzb/?pass={_service_pwd('sabnzbd')}" if nzb_ready else "",
            "selection_tasks": selection_tasks,
            "engine_options": [
                ("auto", "זיהוי אוטומטי / Aria2", True),
                ("torrent", "Torrent / qBittorrent", not Config.DISABLE_TORRENTS),
                ("youtube", "וידאו / yt-dlp", not Config.DISABLE_YTDLP),
                (
                    "usenet",
                    "NZB / SABnzbd — נדרש חשבון Usenet"
                    if not Config.USENET_SERVERS
                    else "NZB / SABnzbd",
                    not Config.DISABLE_NZB and bool(Config.USENET_SERVERS),
                ),
                (
                    "jdownloader",
                    "JDownloader — נדרשת הגדרת חשבון"
                    if not Config.JD_EMAIL or not Config.JD_PASS
                    else "JDownloader",
                    not Config.DISABLE_JD and bool(Config.JD_EMAIL and Config.JD_PASS),
                ),
            ],
        }
    )
    return context


def _human_size(size) -> str:
    value = float(size or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
        value /= 1024


def rewrite_location(location: str, proxy_prefix: str) -> str:
    parsed = urlparse(location)
    if not parsed.netloc:
        return proxy_prefix + location
    if parsed.hostname in ["localhost", "127.0.0.1"]:
        return proxy_prefix + parsed.path
    return location


async def proxy_fetch(
    method: str, url: str, headers: dict, params: dict, body: bytes, proxy_prefix: str
):
    async with ClientSession(auto_decompress=True) as session:
        async with session.request(
            method,
            url,
            headers=headers,
            params=params,
            data=body,
            allow_redirects=False,
        ) as upstream:
            raw = [
                (k.lower().encode("latin-1"), v.encode("latin-1"))
                for k, v in upstream.headers.items()
                if k.lower() not in ("content-length", "content-encoding")
            ]
            if upstream.status in (301, 302, 303, 307, 308):
                loc = upstream.headers.get("Location")
                if loc:
                    new_loc = rewrite_location(loc, proxy_prefix)
                    raw = [
                        (k, new_loc.encode("latin-1") if k == b"location" else v)
                        for k, v in raw
                    ]
            body = (
                await upstream.read()
                if upstream.status not in (301, 302, 303, 307, 308)
                else b""
            )
            response = Response(content=body, status_code=upstream.status)
            response.raw_headers = raw
            return response


async def protected_proxy(
    service: str, path: str, request: Request, password: str = None
):
    from hmac import compare_digest

    service_info = SERVICES.get(service)
    if not service_info:
        raise HTTPException(status_code=404, detail="Service not found")
    if "password" in service_info:
        if password is None:
            password = request.query_params.get("pass") or request.cookies.get(
                f"{service}_pass"
            )
        if not password or not compare_digest(password, service_info["password"]):
            raise HTTPException(status_code=403, detail="Unauthorized access")
    if path:
        if not _SAFE_PATH.match(path):
            raise HTTPException(status_code=400, detail="Invalid path")
        if ".." in path.split("/"):
            raise HTTPException(status_code=400, detail="Invalid path")
    base = service_info["url"].rstrip("/")
    url = f"{base}/{path.lstrip('/')}" if path else f"{base}/"
    headers = {k: v for k, v in request.headers.items() if k.lower() != "host"}
    body = await request.body()
    params = {k: v for k, v in request.query_params.items() if k != "pass"}
    if "password" in service_info:
        params["apikey"] = service_info["password"]
    response = await proxy_fetch(
        request.method, url, headers, params, body, f"/{service}"
    )
    if "pass" in request.query_params:
        is_https = request.headers.get("x-forwarded-proto") == "https"
        response.set_cookie(
            f"{service}_pass",
            password,
            httponly=True,
            samesite="strict",
            secure=is_https,
        )
    return response


@app.api_route("/nzb/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def sabnzbd_proxy(path: str = "", request: Request = None):
    return await protected_proxy("nzb", path, request)


@app.api_route("/qbit/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def qbittorrent_proxy(path: str = "", request: Request = None):
    return await protected_proxy("qbit", path, request)


@app.exception_handler(Exception)
async def page_not_found(_, exc):
    return HTMLResponse(
        f"<h1 dir='rtl'>404: המשימה לא נמצאה.<br><br>פרטי השגיאה: {exc}</h1>",
        status_code=404,
    )
