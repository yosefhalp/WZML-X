# פריסת WZML-X ב־שרת Linux

החבילה הסודית כוללת את קוד הבוט, `config.py` ו־`.env.server`. אין להעלות אותה ל־GitHub או לשירות שיתוף ציבורי.

## התקנה

1. חלצו את החבילה בתיקייה פרטית בשרת.
2. הריצו `chmod +x deploy/server/*.sh`.
3. הריצו `deploy/server/wzmlx-install.sh`.
4. בדקו באמצעות `deploy/server/wzmlx-status.sh`.

הממשק מאזין בפורט `8080`. MongoDB ו־Telegram Bot API נגישים לבוט דרך כתובות מקומיות בלבד. המתקין מזהה MongoDB קיים; אם הוא חסר, הוא מקים אותו מהקבצים והסודות שבחבילה.

## גיבוי יומי מלא

המתקין מפעיל timer יומי בשעה 04:15 לפי שעון ישראל. כל גיבוי כולל קוד, סודות, נתוני ריצה, dump של MongoDB ותמונות Docker מלאות של WZML-X, MongoDB ו־Telegram Bot API.

- מצב התזמון: `systemctl --user list-timers wzmlx-full-backup.timer`
- הפעלה ידנית: `systemctl --user start wzmlx-full-backup.service`
- הגיבוי האחרון: `cat ~/wzmlx-backups/LATEST`
- אימות: `deploy/server/verify-full-backup.sh "$(cat ~/wzmlx-backups/LATEST)"`
- תרגיל שחזור מבודד: `deploy/server/restore-drill.sh`

נשמרים שני גיבויים מלאים. מטמון ההורדות הזמני של Telegram Bot API אינו נכלל, אך התמונה, ההזדהות והגדרות החיבור שלו כן נכללות. בעת שחזור נעשה שימוש חוזר בשירות `tg-bot-api` קיים ובריא; שירות חדש מוקם רק אם הוא חסר.

## עדכון

לפני החלפת החבילה, שמרו את `config.py`, את `.env.server`, את `accounts/` ואת `downloads/`. לאחר החילוץ הריצו שוב את סקריפט ההתקנה.
