"""שולח הודעת Rich Message שקטה לבעל הבוט ומדפיס רק תוצאת בדיקה לא סודית."""

import asyncio
import json

from aiohttp import ClientSession

from bot.core.config_manager import Config

Config.load()


async def main() -> None:
    payload = {
        "chat_id": Config.OWNER_ID,
        "rich_message": {
            "html": "<h2>בדיקת WZML-X</h2><p>הממשק העברי והחיבור לשרת פעילים.</p>",
            "is_rtl": True,
            "skip_entity_detection": False,
        },
        "disable_notification": True,
    }
    url = f"{Config.LOCAL_BOT_API_BASE.rstrip('/')}/bot{Config.BOT_TOKEN}/sendRichMessage"
    async with ClientSession() as session, session.post(url, json=payload) as response:
        data = await response.json(content_type=None)
        print(
            json.dumps(
                {
                    "status": response.status,
                    "ok": data.get("ok"),
                    "description": data.get("description"),
                },
                ensure_ascii=False,
            )
        )
        if response.status != 200 or data.get("ok") is not True:
            raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
