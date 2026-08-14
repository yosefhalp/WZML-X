from asyncio import sleep
from time import time
from secrets import token_hex

from pyrogram.errors import FloodWait, InputUserDeactivated, UserIsBlocked

from ..core.config_manager import Config
from ..core.tg_client import TgClient
from ..helper.ext_utils.bot_utils import new_task
from ..helper.ext_utils.db_handler import database
from ..helper.ext_utils.status_utils import get_readable_time
from ..helper.telegram_helper.message_utils import (
    edit_message,
    send_message,
)

bc_cache = {}


async def delete_broadcast(bc_id, message):
    if bc_id not in bc_cache:
        return await send_message(message, "Invalid Broadcast ID!")

    temp_wait = await send_message(
        message, "<i>Deleting the Broadcasted Message! Please Wait ...</i>"
    )
    total, success, failed = 0, 0, 0
    msgs = bc_cache.get(bc_id, [])
    for uid, msg_id in msgs:
        try:
            await (await TgClient.bot.get_messages(uid, msg_id)).delete()
            success += 1
        except FloodWait as e:
            await sleep(e.value)
            await (await TgClient.bot.get_messages(uid, msg_id)).delete()
            success += 1
        except Exception as e:
            print(f"Error deleting message for user {uid}: {e}")
            failed += 1
        total += 1
    return await edit_message(
        temp_wait,
        f"""⌬  <b><i>נתוני מחיקת ההפצה</i></b>
┠ <b>סה״כ משתמשים:</b> <code>{total}</code>
┠ <b>הצלחה:</b> <code>{success}</code>
┖ <b>ניסיונות שנכשלו:</b> <code>{failed}</code>

<b>מזהה הפצה:</b> <code>{bc_id}</code>""",
    )


async def edit_broadcast(bc_id, message, rply):
    if bc_id not in bc_cache:
        return await send_message(message, "Invalid Broadcast ID!")

    temp_wait = await send_message(
        message, "<i>Editing the Broadcasted Message! Please Wait ...</i>"
    )
    total, success, failed = 0, 0, 0
    for uid, msg_id in bc_cache[bc_id]:
        msg = await TgClient.bot.get_messages(uid, msg_id)
        if hasattr(msg, "forward_from"):
            return await edit_message(
                temp_wait,
                "<i>Forwarded Messages can't be Edited, Only can be Deleted!</i>",
            )
        try:
            await msg.edit(
                text=rply.text,
                entities=rply.entities,
                reply_markup=rply.reply_markup,
            )
            await sleep(0.3)
            success += 1
        except FloodWait as e:
            await sleep(e.value)
            await msg.edit(
                text=rply.text,
                entities=rply.entities,
                reply_markup=rply.reply_markup,
            )
            success += 1
        except Exception as e:
            print(f"Error editing message for user {uid}: {e}")
            failed += 1
        total += 1
    return await edit_message(
        temp_wait,
        f"""⌬  <b><i>נתוני עריכת ההפצה</i></b>
┠ <b>סה״כ משתמשים:</b> <code>{total}</code>
┠ <b>הצלחה:</b> <code>{success}</code>
┖ <b>ניסיונות שנכשלו:</b> <code>{failed}</code>

<b>מזהה הפצה:</b> <code>{bc_id}</code>""",
    )


@new_task
async def broadcast(_, message):
    bc_id, forwarded, quietly, deleted, edited = "", False, False, False, False
    if not Config.DATABASE_URL:
        return await send_message(
            message, "DATABASE_URL not provided to fetch PM Users!"
        )
    rply = message.reply_to_message
    if len(message.command) > 1:
        if not message.command[1].startswith("-"):
            bc_id = (
                message.command[1] if bc_cache.get(message.command[1], False) else ""
            )
            if not bc_id:
                return await send_message(
                    message,
                    "<i>Broadcast ID not found! After Restart, you can't edit or delete broadcasted messages...</i>",
                )
        for arg in message.command:
            if arg in ["-f", "-forward"] and rply:
                forwarded = True
            if arg in ["-q", "-quiet"] and rply:
                quietly = True
            elif arg in ["-d", "-delete"] and bc_id:
                deleted = True
            elif arg in ["-e", "-edit"] and bc_id and rply:
                edited = True
    if not bc_id and not rply:
        return await send_message(
            message,
            """<b>כדי להפיץ הודעה, השיבו לה והפעילו:</b>
/broadcast bc_id -d -e -f -q

<b>העברת ההודעה עם תג המקור:</b> <code>-f</code> או <code>-forward</code>
/cmd [reply_msg] -f

<b>הפצה שקטה:</b> <code>-q</code> או <code>-quiet</code>
/cmd [reply_msg] -q -f

<b>עריכת הפצה קיימת:</b> <code>-e</code> או <code>-edit</code>
/cmd [reply_edited_msg] broadcast_id -e

<b>מחיקת הפצה קיימת:</b> <code>-d</code> או <code>-delete</code>
/bc broadcast_id -d

<b>הערות:</b>
1. אפשר לערוך או למחוק הפצה רק עד להפעלה מחדש של הבוט.
2. אי אפשר לערוך הודעה שהועברה; אפשר רק למחוק אותה.""",
        )
    if deleted:
        return await delete_broadcast(bc_id, message)
    elif edited:
        return await edit_broadcast(bc_id, message, rply)

    # Broadcasting logic
    start_time = time()
    status = """⌬  <b><i>נתוני ההפצה</i></b>
┠ <b>סה״כ משתמשים:</b> <code>{t}</code>
┠ <b>הצלחה:</b> <code>{s}</code>
┠ <b>משתמשים שחסמו את הבוט:</b> <code>{b}</code>
┠ <b>חשבונות שנמחקו:</b> <code>{d}</code>
┖ <b>ניסיונות שנכשלו:</b> <code>{u}</code>"""
    updater = time()
    bc_hash, bc_msgs = token_hex(5), []
    pls_wait = await send_message(message, status.format(t=0, s=0, b=0, d=0, u=0))
    t, s, b, d, u = 0, 0, 0, 0, 0
    for uid in await database.get_pm_uids():
        try:
            bc_msg = (
                await rply.forward(uid, disable_notification=quietly)
                if forwarded
                else await rply.copy(uid, disable_notification=quietly)
            )
            s += 1
        except FloodWait as e:
            await sleep(e.value * 1.1)
            bc_msg = (
                await rply.forward(uid, disable_notification=quietly)
                if forwarded
                else await rply.copy(uid, disable_notification=quietly)
            )
            s += 1
        except UserIsBlocked:
            await database.rm_pm_user(uid)
            b += 1
        except InputUserDeactivated:
            await database.rm_pm_user(uid)
            d += 1
        except Exception as e:
            print(f"Error broadcasting message to user {uid}: {e}")
            u += 1
        if bc_msg:
            bc_msgs.append((uid, bc_msg.id))
        t += 1
        if (time() - updater) > 10:
            await edit_message(pls_wait, status.format(t=t, s=s, b=b, d=d, u=u))
            updater = time()
    bc_cache[bc_hash] = bc_msgs
    await edit_message(
        pls_wait,
        f"{status.format(t=t, s=s, b=b, d=d, u=u)}\n\n<b>זמן שחלף:</b> <code>{get_readable_time(time() - start_time)}</code>\n<b>מזהה הפצה:</b> <code>{bc_hash}</code>",
    )
