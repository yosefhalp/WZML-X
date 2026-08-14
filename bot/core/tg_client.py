from ast import literal_eval
from pyrogram import Client, enums
from pyrogram.errors import FloodWait
from asyncio import Lock, gather, sleep, wait_for
from datetime import datetime, timezone
from hashlib import sha256
from inspect import signature
from json import dumps
from os import chmod, chown, replace
from pathlib import Path
from re import fullmatch
from time import time

from .. import LOGGER, bot_loop
from .config_manager import Config

_DB_PARTITION_SALT = b"wzmlx_v3_db_partition_salt"


def db_partition_id(bot_id):
    raw = sha256(_DB_PARTITION_SALT + str(bot_id).encode("utf-8")).hexdigest()
    return f"p_{raw[:24]}"


class TgClient:
    _lock = Lock()
    _hlock = Lock()
    _ulock = Lock()

    bot = None
    user = None
    helper_bots = {}
    helper_loads = {}
    helper_users = {}
    helper_user_loads = {}

    BNAME = ""
    ID = 0
    PARTITION = ""
    IS_PREMIUM_USER = False
    MAX_SPLIT_SIZE = 2097152000
    START_TIMEOUT = 45
    HEALTH_INTERVAL = 30
    HEALTH_PATH = Path("/usr/src/app/runtime/control/telegram-health.json")

    @classmethod
    def _bot_session_path(cls):
        """מחזיר נתיב יציב שנמצא בכרך accounts ונכלל בגיבוי המלא."""

        return Path("/usr/src/app/accounts") / f"WZ-Bot{cls.ID}.session-string"

    @classmethod
    def _load_bot_session_string(cls):
        """טוען Session שמור בלי להציג אותו בלוג ובלי לקבל תוכן לא תקין."""

        try:
            value = cls._bot_session_path().read_text(encoding="utf-8").strip()
            if len(value) >= 200 and fullmatch(r"[A-Za-z0-9_-]+", value):
                return value
        except OSError:
            pass
        return ""

    @classmethod
    async def _save_bot_session_string(cls):
        """מייצא את החיבור הפעיל אטומית כדי שההפעלה הבאה לא תאשר בוט מחדש."""

        value = await cls.bot.export_session_string()
        if len(value) < 200 or not fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError("התקבל Session לא תקין מלקוח הבוט")
        path = cls._bot_session_path()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory_owner = path.parent.stat()
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(value, encoding="utf-8")
        # הקונטיינר פועל כ-root, אך עובד הגיבוי פועל כמשתמש המארח. הבעלות
        # נלקחת מתיקיית ה-volume כדי שהקובץ יישאר סודי ועדיין יהיה בר־גיבוי.
        chown(temporary, directory_owner.st_uid, directory_owner.st_gid)
        chmod(temporary, 0o600)
        replace(temporary, path)

    @classmethod
    async def _stop_client_safely(cls, client):
        """סוגר לקוח תקוע בזמן מוגבל, בלי לתת לכשל הסגירה לחסום את האתחול."""
        if client is None:
            return
        try:
            await wait_for(client.stop(), timeout=10)
        except Exception:
            pass

    @classmethod
    def _quarantine_bot_sessions(cls):
        """מעביר מפתחות Bot פסולים להסגר במקום למחוק אותם לצמיתות."""
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        root = Path("/usr/src/app/accounts")
        moved = []
        for suffix in (".session-string", ".session", ".session-journal", ".session-wal", ".session-shm", ".session.lock"):
            source = root / f"WZ-Bot{cls.ID}{suffix}"
            if not source.exists():
                continue
            target = source.with_name(f"{source.name}.invalid-{stamp}")
            replace(source, target)
            chmod(target, 0o600)
            moved.append(target.name)
        if moved:
            LOGGER.warning("Session הבוט הפסול הועבר להסגר; ייווצר חיבור חדש מהטוקן.")
        return moved

    @classmethod
    def _write_telegram_health(cls, ok, detail=""):
        """כותב אטומית מצב Telegram שממשק הבריאות יכול לקרוא מתהליך נפרד."""
        path = cls.HEALTH_PATH
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        owner = path.parent.stat()
        temporary = path.with_suffix(".json.new")
        payload = {"ok": bool(ok), "updated_at": time(), "detail": str(detail)[:120]}
        temporary.write_text(dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
        chown(temporary, owner.st_uid, owner.st_gid)
        chmod(temporary, 0o600)
        replace(temporary, path)

    @classmethod
    async def telegram_health_watchdog(cls):
        """בודק חיבור MTProto אמיתי כדי שאתר פעיל לא יסתיר Bot מנותק."""
        last_ok = None
        while True:
            try:
                if cls.bot is None or not cls.bot.is_connected:
                    raise ConnectionError("לקוח הבוט אינו מחובר")
                await wait_for(cls.bot.get_me(), timeout=12)
                cls._write_telegram_health(True, "connected")
                if last_ok is False:
                    LOGGER.info("חיבור Telegram חזר לפעילות.")
                last_ok = True
            except Exception as error:
                cls._write_telegram_health(False, type(error).__name__)
                if last_ok is not False:
                    LOGGER.error(f"בדיקת חיבור Telegram נכשלה: {type(error).__name__}")
                last_ok = False
            await sleep(cls.HEALTH_INTERVAL)

    @classmethod
    def wztgClient(cls, *args, proxy=None, **kwargs):
        # לקוחות שמקבלים Session String יכולים להישאר בזיכרון, משום שהמחרוזת
        # עצמה היא ה-Session השמור. לקוח הבוט הראשי חייב Session בדיסק כדי
        # שהפעלה מחדש לא תיצור בכל פעם הרשאת MTProto חדשה ותגרום ל-FloodWait.
        persistent_session = bool(kwargs.pop("persistent_session", False))
        kwargs["api_id"] = Config.TELEGRAM_API
        kwargs["api_hash"] = Config.TELEGRAM_HASH
        kwargs["proxy"] = Config.TG_PROXY if proxy is None else proxy
        kwargs["parse_mode"] = enums.ParseMode.HTML
        kwargs["in_memory"] = not persistent_session
        for param, value in {
            "max_concurrent_transmissions": 100,
            "skip_updates": False,
        }.items():
            if param in signature(Client.__init__).parameters:
                kwargs[param] = value
        return Client(*args, **kwargs)

    @classmethod
    def _parse_proxies(cls, raw):
        if not raw:
            return []
        proxies = []
        for line in raw.split("\n"):
            line = line.strip()
            if not line:
                proxies.append(None)
                continue
            try:
                parsed = literal_eval(line)
                proxies.append(parsed if isinstance(parsed, dict) else None)
            except (ValueError, SyntaxError):
                proxies.append(None)
        return proxies

    @classmethod
    async def _retry_hclient(cls, no, b_token, delay, proxy=None):
        await sleep(delay)
        try:
            hbot = cls.wztgClient(
                f"WZ-HBot{no}",
                bot_token=b_token,
                no_updates=True,
                proxy=proxy,
            )
            await wait_for(hbot.start(), timeout=cls.START_TIMEOUT)
            LOGGER.info(f"Helper Bot [@{hbot.me.username}] Started!")
            cls.helper_bots[no], cls.helper_loads[no] = hbot, 0
        except FloodWait as e:
            LOGGER.warning(f"Helper Bot{no} FloodWait: Retrying in {e.value}s...")
            bot_loop.create_task(cls._retry_hclient(no, b_token, e.value, proxy))
        except Exception as e:
            LOGGER.error(f"Failed to start helper bot {no} from HELPER_TOKENS. {e}")

    @classmethod
    async def start_hclient(cls, no, b_token, proxy=None):
        try:
            hbot = cls.wztgClient(
                f"WZ-HBot{no}",
                bot_token=b_token,
                no_updates=True,
                proxy=proxy,
            )
            await wait_for(hbot.start(), timeout=cls.START_TIMEOUT)
            LOGGER.info(f"Helper Bot [@{hbot.me.username}] Started!")
            cls.helper_bots[no], cls.helper_loads[no] = hbot, 0
        except FloodWait as e:
            LOGGER.warning(
                f"Helper Bot{no} FloodWait: Retrying in {e.value}s (non-blocking)..."
            )
            bot_loop.create_task(cls._retry_hclient(no, b_token, e.value, proxy))
        except Exception as e:
            LOGGER.error(f"Failed to start helper bot {no} from HELPER_TOKENS. {e}")
            cls.helper_bots.pop(no, None)

    @classmethod
    async def start_helper_bots(cls):
        if not Config.HELPER_TOKENS:
            return
        LOGGER.info("Generating helper client from HELPER_TOKENS")
        bot_proxies = cls._parse_proxies(Config.HELPER_BOT_PROXIES)
        async with cls._hlock:
            await gather(
                *(
                    cls.start_hclient(
                        no,
                        b_token,
                        bot_proxies[no - 1]
                        if bot_proxies and no - 1 < len(bot_proxies)
                        else None,
                    )
                    for no, b_token in enumerate(Config.HELPER_TOKENS.split(), start=1)
                )
            )

    @classmethod
    async def _retry_huser(cls, no, session_string, delay, proxy=None):
        await sleep(delay)
        try:
            huser = cls.wztgClient(
                f"WZ-HUser{no}",
                session_string=session_string,
                sleep_threshold=60,
                no_updates=True,
                proxy=proxy,
            )
            await wait_for(huser.start(), timeout=cls.START_TIMEOUT)
            uname = huser.me.username or huser.me.first_name
            LOGGER.info(f"Helper User [{uname}] Started!")
            cls.helper_users[no], cls.helper_user_loads[no] = huser, 0
        except FloodWait as e:
            LOGGER.warning(f"Helper User{no} FloodWait: Retrying in {e.value}s...")
            bot_loop.create_task(cls._retry_huser(no, session_string, e.value, proxy))
        except Exception as e:
            LOGGER.error(f"Failed to start helper user {no} from HELPER_STRINGS. {e}")

    @classmethod
    async def start_huser(cls, no, session_string, proxy=None):
        try:
            huser = cls.wztgClient(
                f"WZ-HUser{no}",
                session_string=session_string,
                sleep_threshold=60,
                no_updates=True,
                proxy=proxy,
            )
            await wait_for(huser.start(), timeout=cls.START_TIMEOUT)
            uname = huser.me.username or huser.me.first_name
            LOGGER.info(f"Helper User [{uname}] Started!")
            cls.helper_users[no], cls.helper_user_loads[no] = huser, 0
        except FloodWait as e:
            LOGGER.warning(
                f"Helper User{no} FloodWait: Retrying in {e.value}s (non-blocking)..."
            )
            bot_loop.create_task(cls._retry_huser(no, session_string, e.value, proxy))
        except Exception as e:
            LOGGER.error(f"Failed to start helper user {no} from HELPER_STRINGS. {e}")
            cls.helper_users.pop(no, None)

    @classmethod
    async def start_helper_users(cls):
        if not Config.HELPER_STRINGS:
            return
        LOGGER.info("Generating helper client from HELPER_STRINGS")
        user_proxies = cls._parse_proxies(Config.HELPER_USER_PROXIES)
        async with cls._ulock:
            await gather(
                *(
                    cls.start_huser(
                        no,
                        session_string,
                        user_proxies[no - 1]
                        if user_proxies and no - 1 < len(user_proxies)
                        else None,
                    )
                    for no, session_string in enumerate(
                        Config.HELPER_STRINGS.split(), start=1
                    )
                )
            )

    @classmethod
    async def start_bot(cls):
        LOGGER.info("Generating client from BOT_TOKEN")
        cls.ID = Config.BOT_TOKEN.split(":", 1)[0]
        cls.PARTITION = db_partition_id(cls.ID)
        saved_session = cls._load_bot_session_string()
        client_options = {
            "bot_token": Config.BOT_TOKEN,
            "workdir": "/usr/src/app/accounts",
        }
        if saved_session:
            # Session String שמור משחזר את אותה הרשאת MTProto בלי יצירת auth key חדש.
            client_options["session_string"] = saved_session
        else:
            # בפריסה ראשונה Pyrogram יוצר SQLite קבוע, ולא מסד זמני בזיכרון.
            client_options["persistent_session"] = True
        cls.bot = cls.wztgClient(f"WZ-Bot{cls.ID}", **client_options)
        try:
            try:
                await wait_for(cls.bot.start(), timeout=cls.START_TIMEOUT)
            except FloodWait as e:
                LOGGER.warning(f"FloodWait: Sleeping for {e.value} seconds...")
                await sleep(e.value)
                await wait_for(cls.bot.start(), timeout=cls.START_TIMEOUT)
        except Exception as error:
            if not saved_session:
                raise
            LOGGER.error(
                "Session הבוט השמור אינו מתחבר; עובר אוטומטית לחיבור חדש מהטוקן: "
                f"{type(error).__name__}"
            )
            await cls._stop_client_safely(cls.bot)
            cls._quarantine_bot_sessions()
            cls.bot = cls.wztgClient(
                f"WZ-Bot{cls.ID}",
                bot_token=Config.BOT_TOKEN,
                workdir="/usr/src/app/accounts",
                persistent_session=True,
            )
            await wait_for(cls.bot.start(), timeout=cls.START_TIMEOUT)
        cls.BNAME = cls.bot.me.username
        cls.ID = Config.BOT_TOKEN.split(":", 1)[0]
        try:
            await cls._save_bot_session_string()
        except Exception as error:
            LOGGER.warning(f"Bot Session could not be persisted: {error}")
        LOGGER.info(f"WZ Bot : [@{cls.BNAME}] Started!")
        cls._write_telegram_health(True, "started")

    @classmethod
    async def _retry_user(cls, delay):
        await sleep(delay)
        try:
            cls.user = cls.wztgClient(
                "WZ-User",
                session_string=Config.USER_SESSION_STRING,
                sleep_threshold=60,
                no_updates=True,
            )
            await wait_for(cls.user.start(), timeout=cls.START_TIMEOUT)
            cls.IS_PREMIUM_USER = cls.user.me.is_premium
            if cls.IS_PREMIUM_USER:
                cls.MAX_SPLIT_SIZE = 4194304000
            uname = cls.user.me.username or cls.user.me.first_name
            LOGGER.info(f"WZ User : [{uname}] Started!")
        except FloodWait as e:
            LOGGER.warning(f"User client FloodWait: Retrying in {e.value}s...")
            bot_loop.create_task(cls._retry_user(e.value))
        except Exception as e:
            LOGGER.error(f"Failed to start client from USER_SESSION_STRING. {e}")
            await cls._stop_client_safely(cls.user)
            cls.IS_PREMIUM_USER = False
            cls.MAX_SPLIT_SIZE = 2097152000
            cls.user = None

    @classmethod
    async def start_user(cls):
        if Config.USER_SESSION_STRING:
            LOGGER.info("Generating client from USER_SESSION_STRING")
            try:
                cls.user = cls.wztgClient(
                    "WZ-User",
                    session_string=Config.USER_SESSION_STRING,
                    sleep_threshold=60,
                    no_updates=True,
                )
                await wait_for(cls.user.start(), timeout=cls.START_TIMEOUT)
                cls.IS_PREMIUM_USER = cls.user.me.is_premium
                if cls.IS_PREMIUM_USER:
                    cls.MAX_SPLIT_SIZE = 4194304000
                uname = cls.user.me.username or cls.user.me.first_name
                LOGGER.info(f"WZ User : [{uname}] Started!")
            except FloodWait as e:
                LOGGER.warning(
                    f"User client FloodWait: Retrying in {e.value}s (non-blocking)..."
                )
                bot_loop.create_task(cls._retry_user(e.value))
            except Exception as e:
                LOGGER.error(
                    "Userbot Session אינו תקין או שאינו זמין; הבוט הראשי ימשיך לעלות: "
                    f"{type(e).__name__}"
                )
                await cls._stop_client_safely(cls.user)
                cls.IS_PREMIUM_USER = False
                cls.MAX_SPLIT_SIZE = 2097152000
                cls.user = None

    @classmethod
    async def stop(cls):
        async with cls._lock:
            clients = []
            if cls.bot:
                clients.append(cls.bot.stop())
                cls.bot = None
            if cls.user:
                clients.append(cls.user.stop())
                cls.user = None
            if cls.helper_bots:
                clients.extend(h_bot.stop() for h_bot in cls.helper_bots.values())
                cls.helper_bots = {}
            if cls.helper_users:
                clients.extend(h_user.stop() for h_user in cls.helper_users.values())
                cls.helper_users = {}
            if clients:
                await gather(*clients, return_exceptions=True)
            LOGGER.info("All Client(s) stopped")

    @classmethod
    async def reload(cls):
        async with cls._lock:
            # restart() מנתק תחילה את הלקוח שמקבל את הפקודה. אם החיבור החדש
            # נכשל, הבוט נשאר חי ב-Docker אך אינו מקבל הודעות. get_me מאמת ומרענן
            # את החיבור הקיים בלי פעולה הרסנית; WZGram מטפל בחיבור מחדש בעצמו.
            clients = [cls.bot]
            clients.extend(cls.helper_bots.values())
            if cls.user:
                clients.append(cls.user)
            clients.extend(cls.helper_users.values())
            disconnected = [
                client for client in clients if client is not None and not client.is_connected
            ]
            if disconnected:
                raise ConnectionError(f"{len(disconnected)} חיבורי Telegram מנותקים")
            checks = [
                wait_for(client.get_me(), timeout=12)
                for client in clients
                if client is not None and client.is_connected
            ]
            if not checks:
                raise ConnectionError("אין חיבור Telegram פעיל")
            results = await gather(*checks, return_exceptions=True)
            failures = [result for result in results if isinstance(result, Exception)]
            if failures:
                raise ConnectionError(f"{len(failures)} חיבורי Telegram נכשלו בבדיקה")
            cls._write_telegram_health(True, "verified")
            LOGGER.info("All Telegram Client(s) verified")
