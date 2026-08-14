"""בניית הודעות מחזור חיי משימה בעברית ובכיווניות יציבה."""

from html import escape

from .status_view import LRI, PDI, RLI, ltr_code, ltr_text, rtl_text


def rtl_block(html: str) -> str:
    """עוטף מסך שלם בכיוון עברי בלי לשנות את תגיות ה-HTML שבו."""

    return f"{RLI}{html}{PDI}"


def technical_line(label: str, value) -> str:
    """בונה שורה עברית שערכה הטכני נשאר משמאל לימין."""

    return f"<b>{rtl_text(label)}:</b> {ltr_code(value)}"


def safe_name(value) -> str:
    """מציג שם קובץ או תיקייה כערך טכני בטוח."""

    return ltr_code(value or "ללא שם")


def completion_summary(*, name, size, elapsed, input_mode, output_mode) -> str:
    """מחזיר את החלק המשותף לכל הודעת סיום מוצלח."""

    return "\n".join(
        [
            "<b>✅ המשימה הושלמה בהצלחה</b>",
            "",
            technical_line("שם", name),
            technical_line("גודל", size),
            technical_line("זמן כולל", elapsed),
            technical_line("מצב קלט", input_mode),
            technical_line("מצב פלט", output_mode),
        ]
    )


def owner_line(owner_html) -> str:
    """מציג את יוזם המשימה; הערך נבנה קודם בידי מנגנון האזכור של הבוט."""

    return f"<b>{rtl_text('בוצע עבור')}:</b> {owner_html}"


def count_line(label: str, value) -> str:
    """מציג מונה בלי היפוך ספרות בתוך RTL."""

    return technical_line(label, value)


def type_line(value) -> str:
    """מציג סוג קובץ או תיקייה כערך טכני מבודד."""

    return technical_line("סוג", value)


def section_title(title: str) -> str:
    """כותרת קצרה למקטע בתוך הודעת תוצאה."""

    return f"<b><u>{rtl_text(title)}</u></b>"


def linked_file_line(index: int, link, name) -> str:
    """בונה קישור קובץ בטוח בלי שהשם או המספור יתהפכו."""

    safe_url = escape(str(link or ""), quote=True)
    return f"{ltr_text(index)}. <a href='{safe_url}'>{ltr_text(name)}</a>"


def failure_summary(
    *,
    title,
    reason,
    size,
    elapsed,
    input_mode,
    output_mode,
    owner_html,
) -> str:
    """מחזיר הודעת עצירה או שגיאה אחידה וברורה."""

    lines = [
        f"<b>⚠️ {escape(str(title or 'המשימה נעצרה'))}</b>",
        "",
        f"<b>{rtl_text('סיבה')}:</b> {rtl_text(reason or 'שגיאה לא ידועה')}",
        technical_line("גודל", size),
        technical_line("זמן עד העצירה", elapsed),
        technical_line("מצב קלט", input_mode),
        technical_line("מצב פלט", output_mode),
        owner_line(owner_html),
    ]
    return rtl_block("\n".join(lines))
