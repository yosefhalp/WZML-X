"""כלי תצוגה דו־כיוונית למסכי סטטוס בעברית."""

from html import escape


LRI = "\u2066"
RLI = "\u2067"
PDI = "\u2069"

STATUS_LABELS = {
    "All": "הכול",
    "Upload": "מעלה",
    "Download": "מוריד",
    "Clone": "מעתיק",
    "QueueDl": "ממתין להורדה",
    "QueueUp": "ממתין להעלאה",
    "Pause": "מושהה",
    "Archive": "אורז",
    "Extract": "מחלץ",
    "Split": "מפצל",
    "CheckUp": "בודק",
    "Seed": "משתף",
    "SamVid": "יוצר סרטון דוגמה",
    "Convert": "ממיר מדיה",
    "FFmpeg": "מעבד באמצעות FFmpeg",
    "YouTube": "מעבד YouTube",
    "Metadata": "כותב מטא־דאטה",
}


def ltr_text(value) -> str:
    """מבודד ערך טכני משמאל לימין ומגן על HTML שמגיע מבחוץ."""

    return f"{LRI}{escape(str(value or ''), quote=True)}{PDI}"


def ltr_code(value) -> str:
    """מציג מספר, גודל, מהירות, זמן או פקודה בלי שה-RTL יהפוך אותם."""

    return f"<code>{ltr_text(value)}</code>"


def rtl_text(value) -> str:
    """מבודד טקסט עברי מימין לשמאל ומגן על HTML שמגיע מבחוץ."""

    return f"{RLI}{escape(str(value or ''), quote=True)}{PDI}"


def rtl_html(value) -> str:
    """מבודד קטע HTML בטוח שכבר נבנה על ידי Telegram או הקוד המקומי."""

    return f"{RLI}{str(value or '')}{PDI}"


def status_label(value) -> str:
    """מתרגם מצב פנימי לעברית ומשאיר ערך לא מוכר מבודד ובטוח."""

    return STATUS_LABELS.get(str(value), str(value or "לא ידוע"))


def value_line(label: str, value, *, code: bool = True) -> str:
    """בונה שורת תווית עברית עם ערך LTR מבודד."""

    rendered = ltr_code(value) if code else ltr_text(value)
    return f"<b>{rtl_text(label)}:</b> {rendered}"
