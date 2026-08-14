# חבילת MongoDB של WZML-X

החבילה כוללת את קובצי הפריסה ואת הסודות הדרושים להפעלה מיידית. אין להעלות אותה ל־GitHub, ל־Drive ציבורי או לשירות שיתוף קבצים.

## התקנה מיידית

1. חלצו את ה־ZIP בשרת Linux שבו מותקנים Docker ו־Docker Compose.
2. היכנסו לתיקייה שחולצה.
3. הריצו `chmod +x *.sh`.
4. הריצו `./install.sh`.

MongoDB נשמר בנפח Docker בשם `wzmlx-mongo-data`, מוגבל ל־512MB זיכרון וחשוף במארח רק ב־`127.0.0.1:27017`.

## גישה מהמחשב

פתחו מנהרת SSH והשאירו את החלון פתוח:

```text
ssh -L 27017:127.0.0.1:27017 <user>@<server>
```

לאחר מכן אפשר להשתמש ב־MongoDB Compass עם כתובת החיבור שבקובץ `DATABASE_URL.secret`, אבל יש להחליף את שם המארח `wzmlx-mongodb` ב־`127.0.0.1`.

## שימוש מתוך WZML-X

כאשר WZML-X מחובר לרשת Docker בשם `wzmlx-internal`, משתמשים בכתובת המדויקת שבקובץ `DATABASE_URL.secret`.

## תחזוקה

- בדיקת מצב: `./status.sh`
- יצירת גיבוי: `./backup.sh`
- שחזור: `./restore.sh backups/שם-הגיבוי.archive.gz`
- עצירה ללא מחיקת מידע: `docker compose -f mongodb.compose.yml down`

אין להריץ `down -v`, משום שהאפשרות `-v` מוחקת את נפח הנתונים.
