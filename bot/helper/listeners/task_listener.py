from asyncio import create_task, gather, sleep
from time import time
from mimetypes import guess_type
from contextlib import suppress
from os import path as ospath
from pyrogram.enums import ButtonStyle

from aiofiles.os import listdir, remove, path as aiopath
from niquests import utils as rutils

from ... import (
    intervals,
    task_dict,
    task_dict_lock,
    LOGGER,
    non_queued_up,
    non_queued_dl,
    queued_up,
    queued_dl,
    queue_dict_lock,
    same_directory_lock,
    DOWNLOAD_DIR,
)
from ...modules.metadata import apply_metadata_title
from ..common import TaskConfig
from ...core.tg_client import TgClient
from ...core.config_manager import Config
from ...core.torrent_manager import TorrentManager
from ..ext_utils.bot_utils import sync_to_async
from ..ext_utils.links_utils import encode_slink
from ..ext_utils.db_handler import database
from ..ext_utils.files_utils import (
    clean_target,
    create_recursive_symlink,
    get_path_size,
    join_files,
    remove_excluded_files,
    move_and_merge,
)
from ..ext_utils.links_utils import is_gdrive_id
from ..ext_utils.status_utils import get_readable_file_size, get_readable_time
from ..ext_utils.status_view import ltr_code, ltr_text, rtl_text
from ..ext_utils.task_message_view import (
    completion_summary,
    count_line,
    failure_summary,
    linked_file_line,
    owner_line,
    rtl_block,
    section_title,
    technical_line,
    type_line,
)
from ..ext_utils.task_manager import check_running_tasks, start_from_queued
from ..ext_utils.task_cleanup import (
    clean_task_paths,
    ensure_terminal_cleanup,
    release_process_memory,
)
from ..mirror_leech_utils.uphoster_utils.multi_upload import MultiUphosterUpload
from ..mirror_leech_utils.gdrive_utils.upload import GoogleDriveUpload
from ..mirror_leech_utils.rclone_utils.transfer import RcloneTransferHelper
from ..mirror_leech_utils.upload_utils.mega_upload import add_mega_upload
from ..mirror_leech_utils.status_utils.uphoster_status import UphosterStatus
from ..mirror_leech_utils.status_utils.gdrive_status import (
    GoogleDriveStatus,
)
from ..mirror_leech_utils.status_utils.queue_status import QueueStatus
from ..mirror_leech_utils.status_utils.rclone_status import RcloneStatus
from ..mirror_leech_utils.status_utils.telegram_status import TelegramStatus
from ..mirror_leech_utils.status_utils.yt_status import YtStatus
from ..mirror_leech_utils.upload_utils.telegram_uploader import TelegramUploader
from ..mirror_leech_utils.youtube_utils.youtube_upload import YouTubeUpload
from ..telegram_helper.button_build import ButtonMaker
from ..telegram_helper.message_utils import (
    delete_links,
    delete_message,
    delete_status,
    send_message,
    update_status_message,
)


class TaskListener(TaskConfig):
    def __init__(self):
        super().__init__()

    async def clean(self):
        with suppress(Exception):
            if st := intervals["status"]:
                for intvl in list(st.values()):
                    intvl.cancel()
            intervals["status"].clear()
            await gather(TorrentManager.aria2.purgeDownloadResult(), delete_status())

    def clear(self):
        self.subname = ""
        self.subsize = 0
        self.files_to_proceed = []
        self.proceed_count = 0
        self.progress = True

    async def purge_task_files(self):
        """מוחק מיד את קבצי המשימה, ורק מתוך תיקיית ההורדות המוגדרת."""
        await clean_task_paths((self.dir, self.up_dir), DOWNLOAD_DIR, LOGGER)

    async def finalize_terminal_task(self):
        """מסיר את כל הפניות למשימה ומשחרר זיכרון, באופן בטוח לשימוש חוזר."""
        await self.purge_task_files()
        await self.remove_from_same_dir()
        async with task_dict_lock:
            task_dict.pop(self.mid, None)
            count = len(task_dict)
        async with queue_dict_lock:
            for queue in (queued_dl, queued_up):
                event = queue.pop(self.mid, None)
                if event:
                    event.set()
            non_queued_dl.discard(self.mid)
            non_queued_up.discard(self.mid)
        self.clear()
        if count == 0:
            await self.clean()
        else:
            with suppress(Exception):
                await update_status_message(self.message.chat.id)
        with suppress(Exception):
            await start_from_queued()
        # ההרצה הנדחית מתחילה רק אחרי יציאה מה־callback, כשהמחסנית כבר אינה
        # מחזיקה את אובייקטי ההעלאה הגדולים שהסתיימו.
        create_task(release_process_memory(LOGGER))

    async def remove_from_same_dir(self):
        async with task_dict_lock:
            same_dir = getattr(self, "same_dir", None)
            shared = same_dir.get(self.folder_name) if same_dir else None
            if shared and self.mid in shared["tasks"]:
                shared["tasks"].remove(self.mid)
                shared["total"] = max(0, shared["total"] - 1)

    async def on_download_start(self):
        mode_name = "שליחה ל־Telegram" if self.is_leech else "העלאה לענן"
        if self.bot_pm and self.is_super_chat:
            self.pm_msg = await send_message(
                self.user_id,
                f"""➲ <b><u>המשימה התחילה</u></b>
┃
┖ <b>קישור:</b> <a href='{self.source_url}'>לחצו כאן</a>
""",
            )
        if Config.LINKS_LOG_ID:
            await send_message(
                Config.LINKS_LOG_ID,
                f"""➲  <b><u>{mode_name} התחילה</u></b>
 ┃
 ┠ <b>משתמש:</b> {self.tag} ( #ID{self.user_id} )
 ┠ <b>קישור להודעה:</b> <a href='{self.message.link}'>לחצו כאן</a>
 ┗ <b>קישור:</b> <a href='{self.source_url}'>לחצו כאן</a>
 """,
            )
        if (
            self.is_super_chat
            and (Config.INC_TASK_NOTIFY or Config.INC_TASK_RESUME)
            and Config.DATABASE_URL
        ):
            await database.add_incomplete_task(
                self.message.chat.id,
                self.message.link,
                self.tag,
                self.message.text or "",
                self.user_id,
                self.message.reply_to_message.id
                if self.message.reply_to_message
                else 0,
                self.dump_msg_id,
            )

    async def on_download_complete(self):
        await sleep(2)
        if self.is_cancelled:
            return
        if self.dump_msg_id and Config.DATABASE_URL:
            await database.update_task_dump_msg(
                self.message.link, self.dump_chat, self.dump_msg_id
            )
        multi_links = False
        if (
            self.folder_name
            and self.same_dir
            and self.mid in self.same_dir[self.folder_name]["tasks"]
        ):
            async with same_directory_lock:
                while True:
                    async with task_dict_lock:
                        if self.mid not in self.same_dir[self.folder_name]["tasks"]:
                            return
                        if (
                            self.same_dir[self.folder_name]["total"] <= 1
                            or len(self.same_dir[self.folder_name]["tasks"]) > 1
                        ):
                            if self.same_dir[self.folder_name]["total"] > 1:
                                self.same_dir[self.folder_name]["tasks"].remove(
                                    self.mid
                                )
                                self.same_dir[self.folder_name]["total"] -= 1
                                spath = f"{self.dir}{self.folder_name}"
                                des_id = list(self.same_dir[self.folder_name]["tasks"])[
                                    0
                                ]
                                des_path = f"{DOWNLOAD_DIR}{des_id}{self.folder_name}"
                                LOGGER.info(f"Moving files from {self.mid} to {des_id}")
                                await move_and_merge(spath, des_path, self.mid)
                                multi_links = True
                            break
                    await sleep(1)
        async with task_dict_lock:
            if self.is_cancelled:
                return
            if self.mid not in task_dict:
                return
            download = task_dict[self.mid]
            self.name = download.name()
            gid = download.gid()
        LOGGER.info(f"Download completed: {self.name}")

        if not (self.is_torrent or self.is_qbit):
            self.seed = False

        if multi_links:
            self.seed = False
            await self.on_upload_error(
                f"הקובץ {self.name} ירד בהצלחה. ממתין לסיום שאר המשימות המאוחדות."
            )
            return
        elif self.same_dir:
            self.seed = False

        if self.folder_name:
            self.name = self.folder_name.strip("/").split("/", 1)[0]

        if not await aiopath.exists(f"{self.dir}/{self.name}"):
            try:
                files = await listdir(self.dir)
                self.name = files[-1]
                if self.name == "yt-dlp-thumb":
                    self.name = files[0]
            except Exception as e:
                await self.on_upload_error(str(e))
                return

        dl_path = f"{self.dir}/{self.name}"
        self.size = await get_path_size(dl_path)
        self.is_file = await aiopath.isfile(dl_path)

        if self.seed:
            up_dir = self.up_dir = f"{self.dir}10000"
            up_path = f"{self.up_dir}/{self.name}"
            await create_recursive_symlink(self.dir, self.up_dir)
            LOGGER.info(f"Shortcut created: {dl_path} -> {up_path}")
        else:
            up_dir = self.dir
            up_path = dl_path

        await remove_excluded_files(self.up_dir or self.dir, self.excluded_extensions)

        if not Config.QUEUE_ALL:
            async with queue_dict_lock:
                if self.mid in non_queued_dl:
                    non_queued_dl.remove(self.mid)
            await start_from_queued()

        if self.join and not self.is_file:
            await join_files(up_path)

        if self.extract and not self.is_nzb:
            up_path = await self.proceed_extract(up_path, gid)
            if self.is_cancelled:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
            self.size = await get_path_size(up_dir)
            self.clear()
            await remove_excluded_files(up_dir, self.excluded_extensions)

        if self.ffmpeg_cmds:
            up_path = await self.proceed_ffmpeg(
                up_path,
                gid,
            )
            if self.is_cancelled:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
            self.size = await get_path_size(up_dir)
            self.clear()

        if (
            (hasattr(self, "metadata_dict") and self.metadata_dict)
            or (hasattr(self, "audio_metadata_dict") and self.audio_metadata_dict)
            or (hasattr(self, "video_metadata_dict") and self.video_metadata_dict)
        ):
            up_path = await apply_metadata_title(
                self,
                up_path,
                gid,
                getattr(self, "metadata_dict", {}),
                getattr(self, "audio_metadata_dict", {}),
                getattr(self, "video_metadata_dict", {}),
            )
            if self.is_cancelled:
                return

            self.name = up_path.replace(f"{up_dir.rstrip('/')}/", "").split("/", 1)[0]
            self.size = await get_path_size(up_path)
            self.clear()

        if self.is_leech and self.is_file:
            fname = ospath.basename(up_path)
            self.file_details["filename"] = fname
            self.file_details["mime_type"] = (guess_type(fname))[
                0
            ] or "application/octet-stream"

        if self.name_swap:
            up_path = await self.substitute(up_path)
            if self.is_cancelled:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]

        if self.screen_shots:
            up_path = await self.generate_screenshots(up_path)
            if self.is_cancelled:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
            self.size = await get_path_size(up_dir)

        if self.convert_audio or self.convert_video:
            up_path = await self.convert_media(
                up_path,
                gid,
            )
            if self.is_cancelled:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
            self.size = await get_path_size(up_dir)
            self.clear()

        if self.sample_video:
            up_path = await self.generate_sample_video(up_path, gid)
            if self.is_cancelled:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
            self.size = await get_path_size(up_dir)
            self.clear()

        if self.compress:
            up_path = await self.proceed_compress(
                up_path,
                gid,
            )
            self.is_file = await aiopath.isfile(up_path)
            if self.is_cancelled:
                return
            self.clear()

        self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
        self.size = await get_path_size(up_dir)

        if self.is_leech and not self.compress:
            await self.proceed_split(up_path, gid)
            if self.is_cancelled:
                return
            self.clear()

        self.subproc = None

        add_to_queue, event = await check_running_tasks(self, "up")
        await start_from_queued()
        if add_to_queue:
            LOGGER.info(f"Added to Queue/Upload: {self.name}")
            async with task_dict_lock:
                task_dict[self.mid] = QueueStatus(self, gid, "Up")
            await event.wait()
            if self.is_cancelled:
                return
            LOGGER.info(f"Start from Queued/Upload: {self.name}")

        self.size = await get_path_size(up_dir)

        if self.is_yt:
            LOGGER.info(f"Up to yt Name: {self.name}")
            yt = YouTubeUpload(self, up_path)
            async with task_dict_lock:
                task_dict[self.mid] = YtStatus(self, yt, gid, "up")
            await gather(
                update_status_message(self.message.chat.id),
                sync_to_async(yt.upload),
            )
            del yt
        elif self.is_leech:
            LOGGER.info(f"Leech Name: {self.name}")
            tg = TelegramUploader(self, up_dir)
            async with task_dict_lock:
                task_dict[self.mid] = TelegramStatus(
                    self,
                    tg,
                    gid,
                    "up",
                    "hul" if Config.USE_HYPER and TgClient.helper_bots else "",
                )
            await gather(
                update_status_message(self.message.chat.id),
                tg.upload(),
            )
            del tg
        elif self.is_uphoster:
            LOGGER.info(f"Uphoster Upload Name: {self.name}")
            uphoster_service = self.user_dict.get("UPHOSTER_SERVICE", "gofile")
            services = uphoster_service.split(",")
            ddl = MultiUphosterUpload(
                self, up_path, services, self.folder_name.strip("/")
            )
            async with task_dict_lock:
                task_dict[self.mid] = UphosterStatus(self, ddl, gid, "up")
            await gather(
                update_status_message(self.message.chat.id),
                ddl.upload(),
            )
            del ddl
        elif is_gdrive_id(self.up_dest):
            LOGGER.info(f"Gdrive Upload Name: {self.name}")
            drive = GoogleDriveUpload(self, up_path)
            async with task_dict_lock:
                task_dict[self.mid] = GoogleDriveStatus(self, drive, gid, "up")
            await gather(
                update_status_message(self.message.chat.id),
                sync_to_async(drive.upload),
            )
            del drive
        elif self.up_dest == "mega:":
            LOGGER.info(f"Mega Upload Name: {self.name}")
            mega_email = self.user_dict.get("MEGA_EMAIL") or ""
            mega_password = self.user_dict.get("MEGA_PASSWORD") or ""
            await add_mega_upload(self, up_path, mega_email, mega_password, gid)
        else:
            LOGGER.info(f"Rclone Upload Name: {self.name}")
            RCTransfer = RcloneTransferHelper(self)
            async with task_dict_lock:
                task_dict[self.mid] = RcloneStatus(self, RCTransfer, gid, "up")
            await gather(
                update_status_message(self.message.chat.id),
                RCTransfer.upload(up_path),
            )
            del RCTransfer
        return

    @ensure_terminal_cleanup(preserve_while_seeding=True)
    async def on_upload_complete(
        self, link, files, folders, mime_type, rclone_path="", dir_id=""
    ):
        if not self.seed:
            await self.purge_task_files()
        if (
            self.is_super_chat
            and (Config.INC_TASK_NOTIFY or Config.INC_TASK_RESUME)
            and Config.DATABASE_URL
        ):
            await database.rm_complete_task(self.message.link)
        msg = completion_summary(
            name=self.name,
            size=get_readable_file_size(self.size),
            elapsed=get_readable_time(time() - self.message.date.timestamp()),
            input_mode=self.mode[0],
            output_mode=self.mode[1],
        )
        LOGGER.info(f"Task Done: {self.name}")
        if self.is_yt:
            buttons = ButtonMaker()
            if mime_type == "Folder/Playlist":
                msg += f"\n{type_line('רשימת השמעה')}"
                msg += f"\n{count_line('מספר סרטונים', files)}"
                if link:
                    buttons.url_button(
                        "🔗 פתיחת רשימת ההשמעה", link, style=ButtonStyle.PRIMARY
                    )
                user_message = (
                    f"{self.tag}\n✅ רשימת ההשמעה הועלתה ל־YouTube בהצלחה "
                    f"({ltr_code(files)} סרטונים)."
                )
            else:
                msg += f"\n{type_line('סרטון')}"
                if link:
                    buttons.url_button(
                        "🔗 פתיחת הסרטון", link, style=ButtonStyle.PRIMARY
                    )
                user_message = (
                    f"{self.tag}\n✅ הסרטון הועלה ל־YouTube בהצלחה."
                )

            msg += f"\n{owner_line(self.tag)}"

            button = buttons.build_menu(1) if link else None

            await send_message(self.user_id, rtl_block(msg), button)
            if Config.LEECH_DUMP_CHAT:
                await send_message(Config.LEECH_DUMP_CHAT, rtl_block(msg), button)
            await send_message(self.message, rtl_block(user_message), button)

        elif self.is_leech:
            msg += f"\n{count_line('מספר קבצים', folders)}"
            if mime_type != 0:
                msg += f"\n{count_line('קבצים פגומים', mime_type)}"
            msg += f"\n{owner_line(self.tag)}\n\n"

            if self.bot_pm:
                pmsg = msg
                pmsg += f"{section_title('פעולה שבוצעה')}\n"
                pmsg += "הקבצים נשלחו לשיחה הפרטית עם הבוט.\n\n"
                if self.is_super_chat:
                    await send_message(self.message, rtl_block(pmsg))

            if not files and not self.is_super_chat:
                await send_message(self.message, rtl_block(msg))
            else:
                log_chat = self.user_id if self.bot_pm else self.message
                msg += f"{section_title('רשימת קבצים')}\n"
                fmsg = ""
                for index, (link, name) in enumerate(files.items(), start=1):
                    fmsg += linked_file_line(index, link, name)
                    if Config.MEDIA_STORE and (
                        self.is_super_chat or Config.LEECH_DUMP_CHAT
                    ):
                        parts = link.split("/")[-2:]
                        if len(parts) == 2:
                            chat_id, msg_id = parts
                            if chat_id.isdigit():
                                chat_id = f"-100{chat_id}"
                            flink = f"https://t.me/{TgClient.BNAME}?start={encode_slink('file' + chat_id + '&&' + msg_id)}"
                            fmsg += (
                                f"\n<b>{rtl_text('גישה למדיה')}:</b> "
                                f"<a href='{flink}'>קישור שמור</a> | "
                                f"<a href='https://t.me/share/url?url={flink}'>שיתוף</a>"
                            )
                    fmsg += "\n"
                    if len(fmsg.encode() + msg.encode()) > 4000:
                        await send_message(log_chat, rtl_block(msg + fmsg))
                        await sleep(1)
                        fmsg = ""
                if fmsg != "":
                    await send_message(log_chat, rtl_block(msg + fmsg))
        else:
            msg += f"\n{type_line(mime_type)}"
            if mime_type == "Folder":
                msg += f"\n{count_line('תיקיות משנה', folders)}"
                msg += f"\n{count_line('מספר קבצים', files)}"

            multi_link_msg = ""
            multi_links = []
            if isinstance(link, dict) and not self.is_yt:
                for service, result in link.items():
                    if "error" in result:
                        multi_link_msg += f"{ltr_text(service.capitalize())}: שגיאה — {rtl_text(result['error'])}\n"
                    elif result.get("link"):
                        multi_links.append(
                            (f"קישור {service.capitalize()}", result["link"])
                        )
                multi_link_msg = multi_link_msg.strip()
                link = None

            if (
                link
                or rclone_path
                and Config.RCLONE_SERVE_URL
                and not self.private_link
                or multi_links
            ):
                buttons = ButtonMaker()
                if link and Config.SHOW_CLOUD_LINK:
                    if "mega.nz" in link:
                        btn_label = "🔗 קישור Mega"
                    else:
                        btn_label = "☁️ פתיחת הקישור"
                    buttons.url_button(btn_label, link, style=ButtonStyle.PRIMARY)
                elif multi_links:
                    for name, url in multi_links:
                        buttons.url_button(name, url)
                else:
                    msg += f"\n{technical_line('נתיב', rclone_path)}"
                if rclone_path and Config.RCLONE_SERVE_URL and not self.private_link:
                    remote, rpath = rclone_path.split(":", 1)
                    url_path = rutils.quote(f"{rpath}")
                    share_url = f"{Config.RCLONE_SERVE_URL}/{remote}/{url_path}"
                    if mime_type == "Folder":
                        share_url += "/"
                    buttons.url_button(
                        "🔗 קישור Rclone", share_url, style=ButtonStyle.PRIMARY
                    )
                if not rclone_path and dir_id:
                    INDEX_URL = self.user_dict.get("INDEX_URL", "") or ""
                    if not INDEX_URL:
                        INDEX_URL = Config.INDEX_URL or ""
                    if INDEX_URL and self.name:
                        safe_name = rutils.quote(self.name.strip("/"))
                        share_url = f"{INDEX_URL}/{safe_name}"
                        if mime_type == "Folder":
                            share_url += "/"
                        buttons.url_button(
                            "⚡ קישור אינדקס", share_url, style=ButtonStyle.PRIMARY
                        )
                        if mime_type.startswith(("image", "video", "audio")):
                            share_urls = f"{share_url}?a=view"
                            buttons.url_button(
                                "🌐 תצוגה בדפדפן", share_urls, style=ButtonStyle.PRIMARY
                            )
                button = buttons.build_menu(2)
            else:
                if not multi_link_msg and rclone_path:
                    msg += f"\n{technical_line('נתיב', rclone_path)}"
                button = None
            msg += f"\n{owner_line(self.tag)}\n\n"
            group_msg = msg

            if multi_link_msg:
                group_msg += multi_link_msg + "\n"
                msg += multi_link_msg + "\n"

            if self.bot_pm and self.is_super_chat:
                await send_message(self.user_id, rtl_block(msg), button)
                group_msg += (
                    f"{section_title('פעולה שבוצעה')}\n"
                    "הקישור נשלח לשיחה הפרטית עם הבוט.\n\n"
                )

            if hasattr(Config, "MIRROR_LOG_ID") and Config.MIRROR_LOG_ID:
                await send_message(Config.MIRROR_LOG_ID, rtl_block(msg), button)

            await send_message(self.message, rtl_block(group_msg), button)
        if self.seed:
            await clean_target(self.up_dir)
            async with queue_dict_lock:
                if self.mid in non_queued_up:
                    non_queued_up.remove(self.mid)
            await start_from_queued()
            return

        if self.pm_msg and not Config.DELETE_LINKS:
            await delete_message(self.pm_msg)

        await delete_links(self.message)

        async with task_dict_lock:
            if self.mid in task_dict:
                del task_dict[self.mid]
            count = len(task_dict)
        if count == 0:
            await self.clean()
        else:
            await update_status_message(self.message.chat.id)

        async with queue_dict_lock:
            if self.mid in non_queued_up:
                non_queued_up.remove(self.mid)

        await start_from_queued()

    @ensure_terminal_cleanup()
    async def on_download_error(self, error, button=None, is_limit=False):
        async with task_dict_lock:
            if self.mid in task_dict:
                del task_dict[self.mid]
            count = len(task_dict)
        await self.purge_task_files()
        await self.remove_from_same_dir()
        msg = failure_summary(
            title="חריגה מהמגבלה" if is_limit else "ההורדה נעצרה",
            reason=error,
            size=get_readable_file_size(self.size),
            elapsed=get_readable_time(time() - self.message.date.timestamp()),
            input_mode=self.mode[0],
            output_mode=self.mode[1],
            owner_html=self.tag,
        )

        await send_message(self.message, msg, button)
        await delete_links(self.message)
        if count == 0:
            await self.clean()
        else:
            await update_status_message(self.message.chat.id)

        if (
            self.is_super_chat
            and (Config.INC_TASK_NOTIFY or Config.INC_TASK_RESUME)
            and Config.DATABASE_URL
        ):
            await database.rm_complete_task(self.message.link)

        async with queue_dict_lock:
            if self.mid in queued_dl:
                queued_dl[self.mid].set()
                del queued_dl[self.mid]
            if self.mid in queued_up:
                queued_up[self.mid].set()
                del queued_up[self.mid]
            if self.mid in non_queued_dl:
                non_queued_dl.remove(self.mid)
            if self.mid in non_queued_up:
                non_queued_up.remove(self.mid)

        await start_from_queued()
        if self.thumb and await aiopath.exists(self.thumb):
            await remove(self.thumb)

    @ensure_terminal_cleanup()
    async def on_upload_error(self, error):
        async with task_dict_lock:
            if self.mid in task_dict:
                del task_dict[self.mid]
            count = len(task_dict)
        await self.purge_task_files()
        await send_message(
            self.message,
            failure_summary(
                title="ההעלאה נעצרה",
                reason=error,
                size=get_readable_file_size(self.size),
                elapsed=get_readable_time(
                    time() - self.message.date.timestamp()
                ),
                input_mode=self.mode[0],
                output_mode=self.mode[1],
                owner_html=self.tag,
            ),
        )
        await delete_links(self.message)
        if count == 0:
            await self.clean()
        else:
            await update_status_message(self.message.chat.id)

        if (
            self.is_super_chat
            and (Config.INC_TASK_NOTIFY or Config.INC_TASK_RESUME)
            and Config.DATABASE_URL
        ):
            await database.rm_complete_task(self.message.link)

        async with queue_dict_lock:
            if self.mid in queued_dl:
                queued_dl[self.mid].set()
                del queued_dl[self.mid]
            if self.mid in queued_up:
                queued_up[self.mid].set()
                del queued_up[self.mid]
            if self.mid in non_queued_dl:
                non_queued_dl.remove(self.mid)
            if self.mid in non_queued_up:
                non_queued_up.remove(self.mid)

        await start_from_queued()
        if self.thumb and await aiopath.exists(self.thumb):
            await remove(self.thumb)
