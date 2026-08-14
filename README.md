<div dir="rtl" align="right">

<p align="center">
  <img src="docs/WZML-X.png" alt="הלוגו של WZML-X HE" width="420">
</p>

<h1 align="center">WZML-X HE — המהדורה של יוסף</h1>

<p align="center">
  בוט Telegram ומרכז שליטה עברי להורדה, העלאה, ניהול משימות, GoFile, גיבוי ושחזור מלאים.
</p>

<p align="center">
  <a href="https://github.com/yosefhalp/WZML-X/tree/wzv3"><img src="https://img.shields.io/badge/Branch-wzv3-181717?style=for-the-badge&logo=github" alt="ענף העבודה"></a>
  <a href="https://github.com/yosefhalp/WZML-X/search?l=python"><img src="https://img.shields.io/github/languages/top/yosefhalp/WZML-X?style=for-the-badge&logo=python&label=Python" alt="Python"></a>
  <a href="https://github.com/yosefhalp/WZML-X/blob/wzv3/docker-compose.server.yml"><img src="https://img.shields.io/badge/Docker-Compose-2496ED?style=for-the-badge&logo=docker&logoColor=white" alt="Docker Compose"></a>
  <a href="https://github.com/yosefhalp/WZML-X/blob/wzv3/LICENSE"><img src="https://img.shields.io/badge/License-AGPL--3.0-blue?style=for-the-badge" alt="AGPL-3.0"></a>
</p>

> [!IMPORTANT]
> זהו פרויקט עצמאי ומותאם של יוסף (`yosefhalp`), המבוסס על WZML-X המקורי. הממשק, זרימת המשימות, המסירה ל־Telegram, GoFile, ניהול השרת, הגיבוי והבדיקות הורחבו ושונו עבור סביבת ההפעלה הזאת.

## מה יש בפרויקט

| תחום | המימוש במהדורה הזאת |
|---|---|
| שפה ונגישות | תפריטים, סטטוסים, הצלחות ושגיאות בעברית; RTL לערכים עבריים ובידוד LTR לקישורים, מזהים, גדלים וזמנים |
| הפעלת משימה | אשף מודרך בבוט ובדשבורד, לצד הפקודות המתקדמות של WZML-X |
| כמה קישורים | זיהוי הודעה מרובת שורות ומיפוי למנגנון Bulk הקיים, כולל מעקב נפרד אחר כל קישור |
| מקורות הורדה | קישור ישיר/Aria2,‏ qBittorrent,‏ JDownloader,‏ yt-dlp,‏ NZB/SABnzbd,‏ Mega וקובצי Telegram |
| יעדי העלאה | Telegram,‏ GoFile,‏ Rclone,‏ Google Drive,‏ Mega ויעדים נוספים שהוגדרו בקונפיגורציה |
| מסירת Telegram | בחירה מפורשת בין Bot ל־Userbot Premium כמקור העלאה, ובין הצ׳אט הפרטי עם הבוט לערוץ כיעד |
| Premium | User Session מאומת מאפשר חלקים של עד `4,194,304,000` בייט — כ־3.9GiB |
| GoFile | העלאה ללא Token קיים, שמירת Token בעלות ופרטי תיקייה, הצגת קבצים ומחיקה לבעלים בלבד |
| בחירת קבצים | מסך מוגן בקוד אישי לבחירת קובצי Torrent/NZB ומשימות מנוע פעילות |
| מרכז שליטה | מצב שירותים, משימות, יצירת משימה, ביטול, מטמון, שאריות הורדה, גיבויים וקישורי מנועים |
| מצב שרת | CPU,‏ RAM,‏ דיסק, Docker, שירותים ובדיקת מהירות מתוך ממשק נגיש |
| ניקוי | קבצי משימה נמחקים לאחר הצלחה או כשל; ניקוי שאריות חסום בזמן משימה פעילה |
| גיבוי | גיבוי מצב או גיבוי מלא הכולל קוד, סודות, Sessions,‏ MongoDB,‏ Images ו־Worker השחזור |
| בריאות Telegram | `/health` מחזיר הצלחה רק כאשר גם השרת וגם חיבור MTProto לבוט פעילים |

## זרימת העבודה

```mermaid
flowchart LR
    U["משתמש ב-Telegram או בדשבורד"] --> Q["בקשת משימה מאומתת"]
    Q --> D["Aria2 / qBittorrent / JDownloader / NZB / yt-dlp"]
    D --> P["עיבוד, בחירת קבצים ופיצול"]
    P --> T["Telegram: Bot או Userbot Premium"]
    P --> G["GoFile עם בעלות וניהול קבצים"]
    P --> C["Rclone / Google Drive / Mega"]
    T --> X["מחיקת קבצי המשימה ושחרור זיכרון"]
    G --> X
    C --> X
    M[("MongoDB")] --> Q
    B["Worker גיבוי יומי"] --> M
    B --> R["ערכת שחזור מלאה"]
```

## התחלה מהירה בבוט

1. שולחים `/start` או `/menu`.
2. בוחרים **משימה חדשה**.
3. בוחרים מקור: אוטומטי, Torrent,‏ JDownloader,‏ YouTube,‏ NZB או קובץ.
4. בוחרים יעד: Telegram,‏ GoFile או אחסון ענן.
5. בהעלאה ל־Telegram בוחרים במפורש:
   - **Bot** — העלאה רגילה.
   - **Userbot Premium** — העלאה דרך החשבון המחובר, עד כ־3.9GiB לחלק.
   - **פרטי — הצ׳אט עם הבוט** — הקבצים מגיעים לבוט ולא להודעות שמורות.
   - **ערוץ** — לאחר הגדרת הערוץ והרשאות החשבון שמעלה.
6. שולחים קישור אחד, קובץ או כמה קישורים — קישור אחד בכל שורה.

הפקודות הוותיקות נשארו זמינות למשתמשים מתקדמים, למשל `/mirror`,‏ `/leech`,‏ `/qbleech`,‏ `/jdmirror`,‏ `/ytdlleech`,‏ `/nzbmirror`,‏ `/gofile`,‏ `/status` ו־`/server`.

## מרכז השליטה בדפדפן

מרכז השליטה פועל כברירת מחדל בפורט `8080` ומוגן באמצעות `WEB_ACCESS_PASSWORD`.

הדשבורד מאפשר:

- יצירה וביטול של משימות.
- בחירת מקור ויעד העלאה.
- הזנת כמה קישורים באותה משימה.
- צפייה במצב Bot,‏ Userbot, מנועי הורדה, MongoDB וגיבויים.
- סריקת מטמון לפני ניקוי, בלי לחשוף שמות קבצים רגישים.
- ניקוי שאריות של הורדות שנעצרו או נכשלו.
- הפעלת גיבוי מצב מהיר או גיבוי מלא.
- פתיחת qBittorrent או SABnzbd רק כאשר השירות זמין, ובאמצעות קישור מוגן.
- כניסה למסך בחירת הקבצים עם קוד התואם למשימה הפעילה.

נקודת הבריאות:

```text
GET /health
```

HTTP `200` פירושו שהשרת וחיבור Telegram פעילים. חיבור Telegram מנותק או בדיקה שהתיישנה מחזירים HTTP `503`.

## פריסה ב־Docker על שרת Linux או VPS

### דרישות

- שרת Linux עם Docker ו־Docker Compose.
- Bot Token של Telegram.
- `TELEGRAM_API` ו־`TELEGRAM_HASH`.
- מזהה בעלים `OWNER_ID`.
- MongoDB נגיש באמצעות `DATABASE_URL`.
- סיסמת דשבורד חזקה ב־`WEB_ACCESS_PASSWORD`.
- Local Telegram Bot API — מומלץ עבור קבצים גדולים ופריסת הייצור הזאת.

### התקנה

```bash
git clone https://github.com/yosefhalp/WZML-X.git
cd WZML-X
cp config_sample.py config.py
touch .env.server
chmod 600 config.py .env.server
```

ממלאים ב־`config.py` לפחות:

```python
BOT_TOKEN = ""
OWNER_ID = 0
TELEGRAM_API = 0
TELEGRAM_HASH = ""
```

ב־`.env.server` מגדירים את כתובת MongoDB ואת סיסמת הדשבורד. אין להעלות את הקובץ ל־Git:

```dotenv
DATABASE_URL=mongodb://USER:PASSWORD@HOST:27017/wzmlx
WEB_ACCESS_PASSWORD=CHANGE_ME
```

לפני הפריסה:

```bash
python3 deploy/server/validate_deployment_secrets.py
chmod +x deploy/server/*.sh
deploy/server/wzmlx-install.sh
```

בדיקת מצב:

```bash
deploy/server/wzmlx-status.sh
curl --fail http://127.0.0.1:8080/health
```

המדריך המלא נמצא ב־[`deploy/server/WZMLX-DEPLOY-HE.md`](deploy/server/WZMLX-DEPLOY-HE.md).

## חיבור Userbot Premium

1. שולחים לבוט בפרטי `/exportsession`.
2. משלימים טלפון, קוד Telegram וסיסמת אימות דו־שלבי אם קיימת.
3. שומרים את המחרוזת ב־`USER_SESSION_STRING` דרך הגדרות הבוט או MongoDB.
4. מפעילים מחדש ובודקים בלוג שמופיע `WZ User : [...] Started!`.
5. מגדירים `LEECH_SPLIT_SIZE = 4194304000` ברמה הכללית או האישית.

> [!CAUTION]
> Session String מאפשר גישה לחשבון Telegram. אין לפרסם אותו, לצרף אותו ל־Issue, לשמור אותו ב־README או לבצע לו commit. אם הוא נחשף — מבטלים אותו ב־Telegram ומפיקים חדש.

## GoFile

- אין חובה לספק Token מראש: העלאה ראשונה יכולה ליצור זהות אורח.
- לאחר ההעלאה נשמרים Token, מזהה התוכן, תיקיית האב ובעלות המשתמש ב־MongoDB.
- רק הבעלים רשאי לקבל את הסוד או להפעיל מחיקה ברשת.
- אפשר לפתוח את התיקייה, להציג את הקבצים ולהשתמש שוב באותה זהות.
- תוצאת העלאה מוצגת כהודעה עשירה; Token אינו נחשף בתוצאה הציבורית.

## גיבוי ושחזור

קיימים שני מצבים:

- **גיבוי מצב** — קוד, הגדרות, Sessions, סודות ו־dump של MongoDB, ללא Docker Images.
- **גיבוי מלא** — כל האמור לעיל וגם Images של WZML-X,‏ MongoDB ו־Telegram Bot API.

הערכה כוללת גם את Worker הגיבוי, המתקין שלו, `restore.sh`, קובץ manifest ו־SHA-256. לפני מסירה מתבצעים אימות שלמות ותרגיל שחזור מבודד.

פקודות שימושיות:

```bash
systemctl --user status wzmlx-backup-worker.service
cat ~/wzmlx-backups/LATEST
deploy/server/verify-full-backup.sh "$(cat ~/wzmlx-backups/LATEST)"
deploy/server/restore-drill.sh
```

גיבויים מלאים מכילים סודות. יש לשמור אותם באחסון פרטי בלבד.

## אבטחה

- סודות, Sessions, גיבויים, קובצי MongoDB והורדות מוחרגים מ־Git.
- קובצי Session נשמרים בהרשאות `0600`.
- כפתורי דשבורד שמשנים מצב משתמשים ב־CSRF.
- קישורי מנועים נוצרים מסיסמאות נגזרות ואינם נרשמים בלוג.
- ניקוי שאריות אינו פועל בזמן משימה פעילה.
- כשל ב־User Session אינו מפיל את הבוט הראשי.
- Session Bot פסול מועבר להסגר ומוחלף בחיבור קבוע חדש מה־Bot Token.

## בדיקות

חבילת הבדיקות מכסה בין השאר:

- RTL ו־LTR במסכי סטטוס, השלמה וכשל.
- מסירה פרטית ללא זליגה להודעות שמורות.
- Bulk וכמה קישורים באותה משימה.
- GoFile, בעלות ומחיקה.
- גיבוי, שחזור, Worker והודעה עשירה.
- ניקוי מטמון ושאריות.
- דשבורד, CSRF, גלילה וקישורי מנועים.
- Sessions,‏ Premium ובריאות Telegram.

הרצה:

```bash
python -m pytest -s -q tests
```

## מבנה הפרויקט

| נתיב | תפקיד |
|---|---|
| `bot/` | ליבת הבוט, מנועי המשימות, Telegram,‏ GoFile, סטטוסים וממשקי ההגדרות |
| `web/` | FastAPI, מרכז השליטה ומסכי בחירת הקבצים |
| `deploy/server/` | התקנה, MongoDB, גיבוי, שחזור, אימות וכלי smoke test |
| `tests/` | בדיקות חוזה ורגרסיה לזרימות שהותאמו |
| `plugins/` | תוספים אופציונליים, כולל בדיקת מהירות |
| `gen_scripts/` | כלי עזר ל־Sessions,‏ Drive ו־Tokens |

## קרדיטים ורישיון

ההתאמה העברית, מרכז השליטה, זרימות הניהול, GoFile, הגיבוי והקשחת הפריסה במהדורה הזאת מנוהלים בידי [יוסף — `yosefhalp`](https://github.com/yosefhalp).

הפרויקט מבוסס על:

- [WZML-X המקורי](https://github.com/SilentDemonSD/WZML-X) מאת SilentDemonSD והתורמים.
- [mirror-leech-telegram-bot](https://github.com/anasty17/mirror-leech-telegram-bot) מאת anasty17 והתורמים.

השינויים מופצים תחת תנאי [GNU AGPL-3.0](LICENSE). הקרדיטים למקור נשמרים בהתאם להיסטוריית Git ולרישיון.

</div>
