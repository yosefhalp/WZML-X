"""מאמת רשומות GoFile חיות ומנקה רק תוכני smoke שנוצרו בבדיקה."""

from asyncio import run
from datetime import datetime, timezone

from pymongo import AsyncMongoClient

import config as deploy_config
from bot.helper.ext_utils.gofile_delete import GONE_OUTCOMES, delete_content


async def main():
    mongo = AsyncMongoClient(deploy_config.DATABASE_URL)
    collection = mongo.wzmlx.gofile_uploads
    cleaned_smoke = 0
    try:
        real_record = await collection.find_one(
            {"name": {"$regex": "^Reacher S04E03"}, "status": "active"},
            sort=[("created_at", -1)],
        )
        print(f"real_record_saved={bool(real_record)}")
        print(f"real_owner_token_saved={bool(real_record and real_record.get('guest_token'))}")
        print(f"real_content_ids_saved={bool(real_record and real_record.get('content_ids'))}")
        print(f"real_public_link_saved={bool(real_record and real_record.get('link'))}")

        cursor = collection.find(
            {"name": {"$regex": "^wzmlx-gofile-smoke-"}, "status": "active"}
        )
        async for record in cursor:
            targets = (
                [record["folder_id"]]
                if record.get("delete_scope") == "folder" and record.get("folder_id")
                else list(record.get("content_ids") or [])
            )
            outcomes = []
            for target in targets:
                outcome, _ = await delete_content(record.get("guest_token"), target)
                outcomes.append(outcome)
            if outcomes and all(value in GONE_OUTCOMES for value in outcomes):
                await collection.update_one(
                    {"_id": record["_id"]},
                    {
                        "$set": {
                            "status": "deleted",
                            "deleted_at": datetime.now(timezone.utc),
                        },
                        "$unset": {"guest_token": ""},
                    },
                )
                cleaned_smoke += 1
        print(f"smoke_records_cleaned={cleaned_smoke}")
    finally:
        await mongo.close()


if __name__ == "__main__":
    run(main())
