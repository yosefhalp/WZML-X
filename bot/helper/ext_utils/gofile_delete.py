"""מחיקת תוכן GoFile באמצעות הטוקן שנשמר בזמן ההעלאה."""

from aiohttp import ClientSession


DELETED = "deleted"
ALREADY_GONE = "already_gone"
UNAUTHORIZED = "unauthorized"
INVALID = "invalid"
ERROR = "error"
GONE_OUTCOMES = {DELETED, ALREADY_GONE}


async def delete_content(token, content_id):
    """מוחק מזהה יחיד ומחזיר תוצאה יציבה שאינה חושפת את הטוקן."""

    token = str(token or "").strip()
    content_id = str(content_id or "").strip()
    if not token or not content_id:
        return ERROR, "חסרים פרטי הבעלות הנדרשים למחיקה."
    try:
        async with ClientSession() as session:
            async with session.delete(
                "https://api.gofile.io/contents",
                headers={"Authorization": f"Bearer {token}"},
                json={"contentsId": content_id},
                timeout=30,
            ) as response:
                status = response.status
                try:
                    payload = await response.json()
                except Exception:
                    payload = {}
    except Exception:
        return ERROR, "לא הצלחתי להגיע ל-GoFile כרגע. אפשר לנסות שוב בעוד רגע."

    if status == 401:
        return UNAUTHORIZED, "GoFile דחה את מפתח הבעלות השמור."
    if status == 400:
        return INVALID, "מזהה התוכן השמור אינו תקין."
    if status != 200 or str(payload.get("status") or "").lower() != "ok":
        return ERROR, f"GoFile לא אישר את המחיקה (HTTP {status})."
    results = payload.get("data")
    if not isinstance(results, dict) or not results:
        return ALREADY_GONE, "התוכן כבר לא היה קיים ב-GoFile."
    entry = results.get(content_id)
    if isinstance(entry, dict) and str(entry.get("status") or "").lower() == "ok":
        return DELETED, "התוכן נמחק מ-GoFile."
    if entry is None:
        return ALREADY_GONE, "התוכן כבר לא היה קיים ב-GoFile."
    return ERROR, "GoFile החזיר תשובה שלא ניתן היה לאמת."


async def delete_owned_upload(store, user_id, record_id):
    """בודק בעלות בצד השרת, מוחק את היעד ורק אז משנה את MongoDB."""

    record = await store.get_owned(user_id, record_id, include_secret=True)
    if not record:
        return ERROR, "לא מצאתי את ההעלאה הזו בחשבון שלך."
    if record.get("status") == "deleted":
        return ALREADY_GONE, "ההעלאה כבר סומנה כמחוקה."
    token = record.get("guest_token") or ""
    if record.get("delete_scope") == "folder" and record.get("folder_id"):
        targets = [record["folder_id"]]
    else:
        targets = list(record.get("content_ids") or [])
    if not targets:
        return ERROR, "לא נשמר מזהה תוכן שניתן למחוק."

    final_outcome = DELETED
    detail = "התוכן נמחק מ-GoFile."
    for target in targets:
        outcome, detail = await delete_content(token, target)
        if outcome not in GONE_OUTCOMES:
            return outcome, detail
        if outcome == ALREADY_GONE:
            final_outcome = ALREADY_GONE
    await store.mark_deleted(user_id, record_id)
    return final_outcome, detail
