#!/usr/bin/env python3
"""שומר את Session הבוט הפעיל מתוך התהליך הישן לפני החלפת הקונטיינר."""

from __future__ import annotations

import asyncio
import json
import urllib.request
from pathlib import Path

from pyrogram import Client

from config import BOT_TOKEN, TELEGRAM_API, TELEGRAM_HASH, USER_SESSION_STRING


async def main() -> None:
    """שולח פקודת אדמין שלא מחזירה את הסוד ומוודא שקובץ Session נוצר."""

    request = urllib.request.Request(
        f"http://127.0.0.1:8081/bot{BOT_TOKEN}/getMe",
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        bot_info = json.loads(response.read().decode("utf-8"))
    username = str(bot_info.get("result", {}).get("username", ""))
    if not username:
        raise RuntimeError("לא התקבל שם המשתמש של הבוט")
    bot_id = BOT_TOKEN.split(":", 1)[0]
    session_path = Path("accounts") / f"WZ-Bot{bot_id}.session-string"
    command = (
        "/aexec from pathlib import Path\n"
        "import os\n"
        "s = await bot.export_session_string()\n"
        "p = Path('/usr/src/app/accounts') / f'WZ-Bot{bot.me.id}.session-string'\n"
        "t = p.with_suffix(p.suffix + '.tmp')\n"
        "t.write_text(s, encoding='utf-8')\n"
        "owner = p.parent.stat()\n"
        "os.chown(t, owner.st_uid, owner.st_gid)\n"
        "os.chmod(t, 0o600)\n"
        "os.replace(t, p)\n"
        "return 'bot-session-saved'"
    )
    client = Client(
        "wzmlx-session-capture",
        api_id=TELEGRAM_API,
        api_hash=TELEGRAM_HASH,
        session_string=USER_SESSION_STRING,
        in_memory=True,
        no_updates=True,
    )
    async with client:
        sent = await client.send_message(f"@{username}", command)
        confirmed = False
        for _ in range(30):
            await asyncio.sleep(2)
            if session_path.is_file() and session_path.stat().st_size >= 200:
                confirmed = True
                break
        try:
            await sent.delete()
        except Exception:
            pass
    print(f"session_saved={confirmed}")
    if not confirmed:
        raise RuntimeError("הבוט לא אישר את שמירת ה־Session בזמן שהוקצב")


if __name__ == "__main__":
    asyncio.run(main())
