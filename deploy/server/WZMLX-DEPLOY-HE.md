# פריסה ניידת של WZML-X

GitHub מכיל קוד ודוגמאות בלבד. סודות, כתובת שרת, מפתחות SSH ומצב הריצה נשמרים מחוץ למאגר.

## שלושת הקבצים והתפקיד שלהם

- `deployment.env`: מפת השרת הפרטית. היא מגדירה תיקיית root, שמות Compose וקונטיינרים, פורטים, נתיבי הסודות וחיבור Local Bot API.
- `controller.env`: פרופיל המחשב שמפעיל את הפריסה. הוא מכיל יעד SSH, מפתח פרטי, `known_hosts` מוצמד ונתיב למפת השרת.
- תיקיית `shared/` בשרת: כספת המצב הקבוע. בה נשמרים `config.py`, קובצי ENV, MongoDB, Sessions, accounts, הגדרות Worker ונתוני ריצה.

מעתיקים את `deployment.env.example` ואת `controller.env.example` לתיקייה פרטית מחוץ למאגר, ממלאים נתיבים ושומרים בהרשאת 0600 ב־Linux. אין להוסיף את הקבצים הפרטיים ל־Git.

## פריסה ראשונה ועדכונים

מהמחשב המקומי, מתוך שורש המאגר:

```text
python deploy/server/deployctl.py --profile <controller.env> preflight
python deploy/server/deployctl.py --profile <controller.env> bootstrap
python deploy/server/deployctl.py --profile <controller.env> deploy
python deploy/server/deployctl.py --profile <controller.env> status
```

`deploy` אורז רק קבצים עקובים או קבצים חדשים שאינם מוחרגים ב־`.gitignore`. הוא מעלה release חדש, מאמת Compose, בונה, מחליף את `current`, מפעיל מחדש ומבצע health check. בכשל הוא מחזיר אוטומטית את ה־release הקודם ואינו מעדכן את קובץ המצב.

Rollback יזום:

```text
python deploy/server/deployctl.py --profile <controller.env> rollback
```

ניקוי מעבדת בדיקה בלבד דורש התאמה מדויקת בין שם הפרופיל לבין סמן הבעלות בשרת:

```text
python deploy/server/deployctl.py --profile <controller.env> cleanup
```

הניקוי אינו מוחק volumes ואינו נוגע ב־Local Bot API חיצוני.

## Local Bot API

`WZMLX_BOT_API_MODE=external` הוא מצב ברירת המחדל המומלץ כאשר קיים שירות מרכזי. הפריסה בודקת את הכתובת שב־`WZMLX_BOT_API_BASE_URL`, אך אינה מקימה, עוצרת או מוחקת את השירות.

`WZMLX_BOT_API_MODE=managed` מיועד רק לשרת שבו WZML-X הוא הבעלים המפורש של השירות. שמות הקונטיינר, ה־volume והפורט חייבים להיות ייחודיים בפרופיל.

## מעבר לשרת חדש

1. יוצרים גיבוי מלא ומאומת בשרת המקור.
2. יוצרים זהות `age` פרטית ושומרים אותה מחוץ ל־Git.
3. מצפינים את הגיבוי ואת מפת המקור באמצעות `migration_bundle.py create`.
4. מאמתים באמצעות `migration_bundle.py verify`.
5. מחלצים באמצעות `migration_bundle.py extract`, עם `target-root`, שם, בסיס פורטים וכתובת Local Bot API של היעד.
6. כלי החילוץ יוצר `deployment.env` חדש; הוא אינו מעתיק נתיבים מוחלטים מהשרת הישן.
7. מבצעים bootstrap, שחזור, deploy ובדיקות. שרת המקור נשאר פעיל עד cutover מאושר.

החבילה כוללת manifest וטביעת SHA-256 לכל רכיב, ומוצפנת כולה. מפתח SSH לעולם אינו נכלל בה.

## גיבוי ושחזור

כאשר `WZMLX_DEPLOYMENT_ENV` מוגדר, `full-backup.sh` ו־`full-restore.sh` קוראים את השמות והנתיבים ממפת הפריסה. במצב Bot API חיצוני נשמר חוזה החיבור בלבד; המטמון הזמני והשירות המשותף אינם מועתקים.

לפני שחזור אמיתי חובה לאמת את החבילה ולהגדיר `CONFIRM_RESTORE=YES`. דריסה של יעד קיים דורשת גם `ALLOW_RESTORE_OVERWRITE=YES`.
