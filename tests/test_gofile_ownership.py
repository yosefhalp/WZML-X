import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


STORE_MODULE = _load(
    "gofile_store_test",
    ROOT / "bot" / "helper" / "ext_utils" / "gofile_store.py",
)
DELETE_MODULE = _load(
    "gofile_delete_test",
    ROOT / "bot" / "helper" / "ext_utils" / "gofile_delete.py",
)


class _Cursor:
    def __init__(self, rows):
        self.rows = list(rows)

    def sort(self, _field, _direction):
        return self

    def skip(self, count):
        self.rows = self.rows[count:]
        return self

    def limit(self, count):
        self.rows = self.rows[:count]
        return self

    def __aiter__(self):
        self.iterator = iter(self.rows)
        return self

    async def __anext__(self):
        try:
            return next(self.iterator)
        except StopIteration as error:
            raise StopAsyncIteration from error


class _Collection:
    """מימוש Mongo קטן לבדיקת סינון בעלות ושדות סודיים."""

    def __init__(self):
        self.rows = []

    async def create_index(self, *_args, **_kwargs):
        return "ok"

    async def insert_one(self, row):
        self.rows.append(dict(row))
        return SimpleNamespace(inserted_id=row["_id"])

    def find(self, query, projection=None):
        rows = [row for row in self.rows if all(row.get(k) == v for k, v in query.items())]
        if projection:
            rows = [{key: row[key] for key, enabled in projection.items() if enabled and key in row} for row in rows]
        return _Cursor(rows)

    async def find_one(self, query, projection=None):
        rows = self.find(query, projection).rows
        return rows[0] if rows else None

    async def update_one(self, query, update):
        for row in self.rows:
            if all(row.get(k) == v for k, v in query.items()):
                row.update(update.get("$set", {}))
                for key in update.get("$unset", {}):
                    row.pop(key, None)
                return SimpleNamespace(modified_count=1)
        return SimpleNamespace(modified_count=0)


class GoFileOwnershipTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.collection = _Collection()
        database = SimpleNamespace(db=SimpleNamespace(gofile_uploads=self.collection))
        self.store = STORE_MODULE.GoFileStore(database)
        self.saved = await self.store.save_upload(
            user_id=17,
            name="movie.mkv",
            size=3900000000,
            link="https://gofile.io/d/example",
            mode="file",
            job_id="44",
            content_ids=["content-1"],
            folder_id="folder-1",
            guest_token="secret-owner-token",
            delete_scope="folder",
        )

    async def test_public_results_never_expose_token(self):
        self.assertNotIn("guest_token", self.saved)
        listed = await self.store.list_for_user(17)
        public = await self.store.get_owned(17, self.saved["_id"])
        self.assertNotIn("guest_token", listed[0])
        self.assertNotIn("guest_token", public)
        self.assertNotIn("content_ids", public)

    async def test_secret_is_available_only_after_owner_filter(self):
        private = await self.store.get_owned(17, self.saved["_id"], include_secret=True)
        stranger = await self.store.get_owned(18, self.saved["_id"], include_secret=True)
        self.assertEqual("secret-owner-token", private["guest_token"])
        self.assertIsNone(stranger)

    async def test_delete_reloads_owner_and_clears_token(self):
        with patch.object(
            DELETE_MODULE,
            "delete_content",
            new=AsyncMock(return_value=(DELETE_MODULE.DELETED, "נמחק")),
        ) as delete:
            outcome, _detail = await DELETE_MODULE.delete_owned_upload(
                self.store, 17, self.saved["_id"]
            )
        self.assertEqual(DELETE_MODULE.DELETED, outcome)
        delete.assert_awaited_once_with("secret-owner-token", "folder-1")
        private = await self.store.get_owned(17, self.saved["_id"], include_secret=True)
        self.assertEqual("deleted", private["status"])
        self.assertNotIn("guest_token", private)

    async def test_stranger_cannot_trigger_network_delete(self):
        with patch.object(DELETE_MODULE, "delete_content", new=AsyncMock()) as delete:
            outcome, _detail = await DELETE_MODULE.delete_owned_upload(
                self.store, 999, self.saved["_id"]
            )
        self.assertEqual(DELETE_MODULE.ERROR, outcome)
        delete.assert_not_awaited()


class GoFileIntegrationContractTests(TestCase):
    def test_uploader_saves_ownership_before_success_callback(self):
        path = (
            ROOT
            / "bot"
            / "helper"
            / "mirror_leech_utils"
            / "uphoster_utils"
            / "uploaders_utils"
            / "gofile_uploader.py"
        )
        source = path.read_text(encoding="utf-8")
        persist = source.index("await self._persist_ownership(link, mime_type)")
        callback = source.index("await self.listener.on_upload_complete(", persist)
        self.assertLess(persist, callback)

    def test_callback_parser_covers_every_gofile_action(self):
        model = _load("guided_ui_model_gofile_test", ROOT / "bot" / "modules" / "guided_ui_model.py")
        record_id = "a" * 32
        values = [
            "ui gofile",
            "ui gofile refresh",
            "ui gofile page 5",
            f"ui gofile add {record_id}",
            f"ui gofile deleteconfirm {record_id}",
            f"ui gofile delete {record_id}",
        ]
        for value in values:
            with self.subTest(value=value):
                self.assertEqual("gofile", model.parse_ui_callback(value)[0])
        for value in ("ui gofile page -1", "ui gofile delete bad", "ui gofile unknown"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    model.parse_ui_callback(value)
