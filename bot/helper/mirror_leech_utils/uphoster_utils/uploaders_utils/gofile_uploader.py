from json import JSONDecodeError
from logging import getLogger
from os import path as ospath
from os import walk as oswalk

from aiofiles.os import path as aiopath
from aiohttp import ClientSession
from aiohttp.client_exceptions import ContentTypeError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from bot.core.config_manager import Config
from bot.helper.ext_utils.bot_utils import sync_to_async
from bot.helper.ext_utils.gofile_store import live_gofile_store

from ..base import BaseUpload
from ..common import ProgressFileReader

LOGGER = getLogger(__name__)


class GoFileUpload(BaseUpload):
    SERVICE_NAME = "GoFile"
    _TOKEN_KEY = "GOFILE_TOKEN"
    _CONFIG_KEY = "GOFILE_API"

    def __init__(self, listener, path, folder_name=""):
        super().__init__(listener, path, folder_name)
        self.api_url = "https://api.gofile.io/"
        from bot import user_data

        user_dict = user_data.get(self.listener.user_id, {})
        self.folder_id = (
            user_dict.get("GOFILE_FOLDER_ID") or Config.GOFILE_FOLDER_ID or ""
        )
        self.zone = str(getattr(Config, "GOFILE_ZONE", "eu") or "eu").lower()
        self._server_candidates = None
        self._started_with_token = bool(self.token)
        self._content_ids = []
        self._parent_folder = ""
        self._created_folder_id = ""
        self._reuse_record = None
        self._reuse_record_id = str(
            getattr(self.listener, "gofile_target_id", "") or ""
        )
        self.auto_create = (
            user_dict.get("GOFILE_AUTO_CREATE_FOLDER")
            if "GOFILE_AUTO_CREATE_FOLDER" in user_dict
            else Config.GOFILE_AUTO_CREATE_FOLDER
        )

    @staticmethod
    async def is_goapi(token):
        if token is None:
            return False
        headers = {"Authorization": f"Bearer {token}"}
        async with (
            ClientSession() as session,
            session.get(
                "https://api.gofile.io/accounts/website", headers=headers
            ) as resp,
        ):
            res = await resp.json()
            return res.get("status") == "ok"

    async def __resp_handler(self, response):
        if (api_resp := response.get("status", "")) == "ok":
            return response["data"]
        reason = api_resp.removeprefix("error-") if api_resp else "unknown"
        raise Exception(f"GoFile דחה את הבקשה: {reason}")

    async def __getServers(self):
        async with ClientSession() as session:
            async with session.get(f"{self.api_url}servers") as resp:
                data = await self.__resp_handler(await resp.json())

        servers = []
        for key in ("servers", "serversAllZone"):
            for item in data.get(key, []) or []:
                if not isinstance(item, dict) or not item.get("name"):
                    continue
                server = {
                    "name": str(item["name"]).strip().lower(),
                    "zone": str(item.get("zone") or "").strip().lower(),
                }
                if server["name"] not in {row["name"] for row in servers}:
                    servers.append(server)

        preferred = [row["name"] for row in servers if row["zone"] == self.zone]
        fallback = [row["name"] for row in servers if row["name"] not in preferred]
        ordered = preferred + fallback
        if "upload" not in ordered:
            ordered.append("upload")
        return ordered

    @staticmethod
    def __upload_url(server):
        if server == "upload" or server.startswith("upload-"):
            return f"https://{server}.gofile.io/uploadfile"
        return f"https://{server}.gofile.io/contents/uploadFile"

    async def __getAccount(self, check_account=False):
        if self.token is None:
            raise Exception("GoFile API token not found!")
        headers = {"Authorization": f"Bearer {self.token}"}
        async with (
            ClientSession() as session,
            session.get(f"{self.api_url}accounts/website", headers=headers) as resp,
        ):
            res = await resp.json()
            if check_account:
                return res["status"] == "ok"
            return await self.__resp_handler(res)

    async def __setOptions(self, contentId, option, value):
        if self.token is None:
            raise Exception("GoFile API token not found!")
        if option not in [
            "name",
            "description",
            "tags",
            "public",
            "expiry",
            "password",
        ]:
            raise Exception(f"Invalid GoFile Option Specified: {option}")
        headers = {"Authorization": f"Bearer {self.token}"}
        async with (
            ClientSession() as session,
            session.put(
                url=f"{self.api_url}contents/{contentId}/update",
                json={"attribute": option, "attributeValue": value},
                headers=headers,
            ) as resp,
        ):
            return await self.__resp_handler(await resp.json())

    @retry(
        wait=wait_exponential(multiplier=2, min=4, max=8),
        stop=stop_after_attempt(2),
        retry=retry_if_exception_type(Exception),
    )
    async def upload_aiohttp(self, url, file_path, req_file, data):
        with ProgressFileReader(
            filename=file_path, read_callback=self._progress_callback
        ) as file:
            data[req_file] = file
            async with ClientSession() as session:
                async with session.post(url, data=data) as resp:
                    if resp.status == 200:
                        try:
                            return await resp.json()
                        except (ContentTypeError, JSONDecodeError):
                            return {
                                "status": "ok",
                                "data": {"downloadPage": "Uploaded"},
                            }
                    else:
                        raise Exception(f"HTTP {resp.status}: {await resp.text()}")
        return None

    async def create_folder(self, parentFolderId, folderName=None):
        if self.token is None:
            raise Exception("GoFile API token not found!")
        headers = {"Authorization": f"Bearer {self.token}"}
        body = {"parentFolderId": parentFolderId}
        if folderName:
            body["folderName"] = folderName
        async with (
            ClientSession() as session,
            session.post(
                url=f"{self.api_url}contents/createfolder",
                json=body,
                headers=headers,
            ) as resp,
        ):
            result = await self.__resp_handler(await resp.json())
        folder_id = str(result.get("id") or result.get("folderId") or "").strip()
        if folder_id and folder_id not in self._content_ids:
            self._content_ids.append(folder_id)
        return result

    def _remember_upload_result(self, result):
        """שומר מיד את פרטי הבעלות שחוזרים מההעלאה, לפני כל callback נוסף."""

        content_id = str(
            result.get("id") or result.get("fileId") or result.get("contentId") or ""
        ).strip()
        if content_id and content_id not in self._content_ids:
            self._content_ids.append(content_id)
        parent = str(result.get("parentFolder") or "").strip()
        if parent:
            self._parent_folder = parent
        generated_token = str(result.get("guestToken") or "").strip()
        if generated_token and not self.token:
            self.token = generated_token

    async def upload_file(
        self,
        path: str,
        folderId: str = "",
        description: str = "",
        password: str = "",
        tags: str = "",
        expire: str = "",
    ):
        if password and len(password) < 4:
            raise ValueError("Password Length must be greater than 4")
        req_dict = {}
        if self.token:
            req_dict["token"] = self.token
        if folderId:
            req_dict["folderId"] = folderId
        if description:
            req_dict["description"] = description
        if password:
            req_dict["password"] = password
        if tags:
            req_dict["tags"] = tags
        if expire:
            req_dict["expire"] = expire
        if self.listener.is_cancelled:
            return None
        if self._server_candidates is None:
            self._server_candidates = await self.__getServers()

        last_error = None
        for server in self._server_candidates[:3]:
            if self.listener.is_cancelled:
                return None
            try:
                upload_file = await self.upload_aiohttp(
                    self.__upload_url(server),
                    path,
                    "file",
                    req_dict.copy(),
                )
                result = await self.__resp_handler(upload_file)
                self._remember_upload_result(result)
                LOGGER.info("GoFile upload server selected: %s", server)
                return result
            except Exception as error:
                last_error = error
                LOGGER.warning("GoFile upload failed via %s; trying fallback", server)

        raise Exception("ההעלאה ל־GoFile נכשלה בכל שרתי ה־fallback") from last_error

    async def _upload_dir(
        self, input_directory, parent_folder_id=None, root_folder_id=None
    ):
        if parent_folder_id is None:
            if self.folder_id:
                parent_folder_id = self.folder_id
                main_folder_code = self.folder_id
            else:
                if root_folder_id is None:
                    account_data = await self.__getAccount()
                    root_folder_id = account_data["rootFolder"]
                folder_data = await self.create_folder(
                    root_folder_id, self.folder_name or ospath.basename(input_directory)
                )
                parent_folder_id = folder_data.get("id") or folder_data["folderId"]
                self._created_folder_id = str(parent_folder_id)
                await self.__setOptions(
                    contentId=parent_folder_id,
                    option="public",
                    value="true",
                )
                main_folder_code = folder_data["code"]
        else:
            main_folder_code = None

        folder_ids = {".": parent_folder_id}
        for root, _dirs, files in await sync_to_async(oswalk, input_directory):
            if self.listener.is_cancelled:
                break
            rel_path = ospath.relpath(root, input_directory)
            current_folder_id = folder_ids.get(
                ospath.dirname(rel_path), parent_folder_id
            )
            if rel_path != ".":
                folder_name = ospath.basename(rel_path)
                curr_folder_data = await self.create_folder(
                    current_folder_id, folder_name
                )
                curr_folder_id = (
                    curr_folder_data.get("id") or curr_folder_data["folderId"]
                )
                await self.__setOptions(
                    contentId=curr_folder_id,
                    option="public",
                    value="true",
                )
                folder_ids[rel_path] = curr_folder_id
                current_folder_id = curr_folder_id
                self.total_folders += 1
            for file in files:
                if self.listener.is_cancelled:
                    break
                file_path = ospath.join(root, file)
                await self.upload_file(file_path, current_folder_id)
                self.total_files += 1
        return main_folder_code

    async def _validate_token(self):
        # GoFile יוצר זהות אורח בהעלאה הראשונה, ולכן טוקן חשבון הוא אפשרי
        # אך אינו נדרש. אם הוגדר טוקן, נשמרת ההתנהגות של חשבון קבוע.
        return

    async def _upload_guest_dir(self):
        """מעלה תיקייה תחת זהות אורח אחת, בלי להשתמש בבריכת טוקנים."""

        files = []
        for root, _dirs, names in await sync_to_async(oswalk, self._path):
            for name in names:
                files.append(ospath.join(root, name))
        if not files:
            raise ValueError("התיקייה שנבחרה ריקה")

        first_result = await self.upload_file(files[0])
        guest_token = str(first_result.get("guestToken") or "").strip()
        parent_folder = str(first_result.get("parentFolder") or "").strip()
        link = str(first_result.get("downloadPage") or "").strip()
        if not guest_token or not parent_folder or not link:
            raise ValueError("GoFile לא החזיר זהות אורח מלאה להעלאת התיקייה")

        # הטוקן נוצר עבור ההעלאה הנוכחית בלבד. בסיום הוא נשמר ב-MongoDB ולא
        # נחשף בהודעה, כדי שניתן יהיה למחוק או להוסיף לאותה תיקייה בעתיד.
        self.token = guest_token
        self.total_files = 1
        for file_path in files[1:]:
            if self.listener.is_cancelled:
                return None
            await self.upload_file(file_path, parent_folder)
            self.total_files += 1
        return link

    async def _load_reuse_target(self):
        """טוען תיקייה שמורה לפי משתמש ומזהה פנימי, בלי להעביר טוקן בפקודה."""

        if not self._reuse_record_id:
            return None
        record = await live_gofile_store().get_owned(
            self.listener.user_id,
            self._reuse_record_id,
            include_secret=True,
        )
        if not record or record.get("status") != "active":
            raise ValueError("תיקיית GoFile שנבחרה אינה זמינה עוד")
        if not record.get("guest_token") or not record.get("folder_id"):
            raise ValueError("לתיקיית GoFile שנבחרה חסרים פרטי בעלות")
        self._reuse_record = record
        self.token = record["guest_token"]
        self.folder_id = record["folder_id"]
        return record

    async def _persist_ownership(self, link, mime_type):
        """שומר את הטוקן והמזהים לפני שליחת הודעת ההצלחה למשתמש."""

        if self._reuse_record:
            delete_scope = "contents"
            folder_id = self._reuse_record["folder_id"]
        elif not self._started_with_token:
            delete_scope = "folder"
            folder_id = self._parent_folder
        elif self._created_folder_id:
            delete_scope = "folder"
            folder_id = self._created_folder_id
        else:
            delete_scope = "contents"
            folder_id = self.folder_id or self._parent_folder
        await live_gofile_store().save_upload(
            user_id=self.listener.user_id,
            name=self.listener.name,
            size=getattr(self.listener, "size", 0),
            link=link,
            mode="folder" if mime_type == "Folder" else "file",
            job_id=getattr(self.listener, "mid", ""),
            content_ids=self._content_ids,
            folder_id=folder_id,
            guest_token=self.token,
            delete_scope=delete_scope,
            reused_from=self._reuse_record_id,
        )

    async def _upload_process(self):
        reuse_record = await self._load_reuse_target()
        account_data = None
        if self.token and not reuse_record:
            try:
                account_data = await self.__getAccount()
            except Exception as e:
                raise Exception(f"שגיאה בחשבון GoFile: {e}") from e

        if reuse_record and await aiopath.isfile(self._path):
            file_result = await self.upload_file(
                path=self._path,
                folderId=reuse_record["folder_id"],
            )
            if not file_result:
                raise ValueError("הוספת הקובץ לתיקיית GoFile נכשלה")
            link = reuse_record["link"]
            mime_type = "File"
            self.total_files = 1
        elif reuse_record and await aiopath.isdir(self._path):
            await self._upload_dir(
                self._path,
                parent_folder_id=reuse_record["folder_id"],
            )
            link = reuse_record["link"]
            mime_type = "Folder"
        elif await aiopath.isfile(self._path):
            folder_id = self.folder_id if account_data else ""
            folder_code = ""
            if account_data and not folder_id and self.auto_create:
                folder_data = await self.create_folder(
                    account_data["rootFolder"], self.folder_name or None
                )
                folder_id = folder_data.get("id") or folder_data["folderId"]
                await self.__setOptions(
                    contentId=folder_id,
                    option="public",
                    value="true",
                )
                folder_code = folder_data.get("code", "")
            elif account_data:
                folder_id = folder_id or account_data["rootFolder"]
            file_result = await self.upload_file(path=self._path, folderId=folder_id)
            if file_result and file_result.get("downloadPage"):
                link = (
                    f"https://gofile.io/d/{folder_code}"
                    if folder_code
                    else file_result["downloadPage"]
                )
                mime_type = "File"
                self.total_files = 1
            else:
                raise ValueError("העלאת הקובץ ל־GoFile נכשלה")
        elif await aiopath.isdir(self._path):
            if account_data:
                folder_code = await self._upload_dir(
                    self._path, root_folder_id=account_data["rootFolder"]
                )
                if folder_code:
                    link = f"https://gofile.io/d/{folder_code}"
                else:
                    raise ValueError("העלאת התיקייה ל־GoFile נכשלה")
            else:
                link = await self._upload_guest_dir()
                if not link:
                    return
            mime_type = "Folder"
        else:
            raise ValueError("נתיב הקובץ או התיקייה אינו תקין")

        if self.listener.is_cancelled:
            return

        await self._persist_ownership(link, mime_type)
        LOGGER.info(f"Uploaded To GoFile: {self.listener.name}")
        await self.listener.on_upload_complete(
            link,
            self.total_files,
            self.total_folders,
            mime_type,
            dir_id="",
        )
