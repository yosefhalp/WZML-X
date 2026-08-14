// יצירת משתמש ייעודי לבוט עם הרשאות רק למסד הנתונים שלו.
// פרטי המשתמש נקראים מקובץ הסודות המקומי ואינם נשמרים בקוד או ב־Git.
const database = db.getSiblingDB("wzmlx");

database.createUser({
  user: process.env.WZMLX_MONGO_USERNAME,
  pwd: process.env.WZMLX_MONGO_PASSWORD,
  roles: [{ role: "readWrite", db: "wzmlx" }],
});
