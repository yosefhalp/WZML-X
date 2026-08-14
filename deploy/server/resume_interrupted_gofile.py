"""מפעיל מחדש משימת GoFile שנקטעה בזמן פריסה, דרך חשבון הבעלים."""

from asyncio import run

from aiohttp import ClientSession
from pyrogram import Client

import config as deploy_config


SOURCE_URL = "http://46.224.230.226:8080/d/FHJja8TbqkNUNTocTdttYYah"


async def main():
    bot_token = deploy_config.BOT_TOKEN
    async with ClientSession() as http:
        async with http.get(f"https://api.telegram.org/bot{bot_token}/getMe") as response:
            bot_data = await response.json()
    bot_peer = f"@{bot_data['result']['username']}"
    user = Client(
        "WZ-RecoverGoFile-User",
        api_id=deploy_config.TELEGRAM_API,
        api_hash=deploy_config.TELEGRAM_HASH,
        session_string=deploy_config.USER_SESSION_STRING,
        in_memory=True,
        no_updates=True,
    )
    try:
        await user.start()
        message = await user.send_message(
            bot_peer,
            f"/gofile {SOURCE_URL}",
            disable_notification=True,
        )
        print(f"recovery_command_sent={bool(message.id)}")
    finally:
        if user.is_connected:
            await user.stop()


if __name__ == "__main__":
    run(main())
