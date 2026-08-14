# ruff: noqa: F403, F405
mirror = """<b>Send link along with command line or </b>

/cmd link

<b>By replying to link/file</b>:

/cmd -n new name -e -up upload destination

<b>NOTE:</b>
1. Commands that start with <b>qb</b> are ONLY for torrents."""

yt = """<b>Send link along with command line</b>:

/cmd link
<b>By replying to link</b>:
/cmd -n new name -z password -opt x:y|x1:y1

Check here all supported <a href='https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md'>SITES</a>
Check all yt-dlp api options from this <a href='https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/YoutubeDL.py#L212'>FILE</a> or use this <a href='https://t.me/mltb_official_channel/177'>script</a> to convert cli arguments to api options."""

clone = """Send Gdrive|Gdot|Filepress|Filebee|Appdrive|Gdflix link or rclone path along with command or by replying to the link/rc_path by command.
Use -sync to use sync method in rclone. Example: /cmd rcl/rclone_path -up rcl/rclone_path/rc -sync"""

new_name = """<b>New Name</b>: -n

/cmd link -n new name
Note: Doesn't work with torrents"""

multi_link = """<b>Multi links only by replying to first link/file</b>: -i

/cmd -i 10(number of links/files)"""

same_dir = """<b>Move file(s)/folder(s) to new folder</b>: -m

You can use this arg also to move multiple links/torrents contents to the same directory, so all links will be uploaded together as one task

/cmd link -m new folder (only one link inside new folder)
/cmd -i 10(number of links/files) -m folder name (all links contents in one folder)
/cmd -b -m folder name (reply to batch of message/file(each link on new line))

While using bulk you can also use this arg with different folder name along with the links in message or file batch
Example:
link1 -m folder1
link2 -m folder1
link3 -m folder2
link4 -m folder2
link5 -m folder3
link6
so link1 and link2 content will be uploaded from same folder which is folder1
link3 and link4 content will be uploaded from same folder also which is folder2
link5 will be uploaded alone inside new folder named folder3
link6 will get uploaded normally alone
"""

thumb = """<b>Thumbnail for current task</b>: -t

/cmd link -t image-url or tg-message-link (doc or photo) or none (file without thumb)
Supports any direct image URL (jpg, png, webp, etc.) or a Telegram message link containing a photo/document."""

split_size = """<b>Split size for current task</b>: -sp

/cmd link -sp (500mb or 2gb or 4000000000)
Note: Only mb and gb are supported or write in bytes without unit!"""

upload = """<b>Upload Destination</b>: -up

/cmd link -up rcl/gdl (rcl: to select rclone config, remote & path | gdl: To select token.pickle, gdrive id) using buttons
You can directly add the upload path: -up remote:dir/subdir or -up Gdrive_id or -up id/username (telegram) or -up id/username|topic_id (telegram)
If DEFAULT_UPLOAD is `rc` then you can pass up: `gd` to upload using gdrive tools to GDRIVE_ID.
If DEFAULT_UPLOAD is `gd` then you can pass up: `rc` to upload to RCLONE_PATH.

If you want to add path or gdrive manually from your config/token (UPLOADED FROM USETTING) add mrcc: for rclone and mtp: before the path/gdrive_id without space.
/cmd link -up mrcc:main:dump or -up mtp:gdrive_id <strong>or you can simply edit upload using owner/user token/config from usetting without adding mtp: or mrcc: before the upload path/id</strong>

To add leech destination:
-up id/@username/pm
-up b:id/@username/pm (b: means leech by bot) (id or username of the chat or write pm means private message so bot will send the files in private to you)
when you should use b:(leech by bot)? When your default settings is leech by user and you want to leech by bot for specific task.
-up u:id/@username(u: means leech by user) This in case OWNER added USER_STRING_SESSION.
-up h:id/@username(hybrid leech) h: to upload files by bot and user based on file size.
-up id/@username|topic_id(leech in specific chat and topic) add | without space and write topic id after chat id or username.

In case you want to specify whether using token.pickle or service accounts you can add tp:gdrive_id (using token.pickle) or sa:gdrive_id (using service accounts) or mtp:gdrive_id (using token.pickle uploaded from usetting).
DEFAULT_UPLOAD doesn't affect on leech cmds.
"""

user_download = """<b>User Download</b>: link

/cmd tp:link to download using owner token.pickle in case service account enabled.
/cmd sa:link to download using service account in case service account disabled.
/cmd tp:gdrive_id to download using token.pickle and file_id in case service account enabled.
/cmd sa:gdrive_id to download using service account and file_id in case service account disabled.
/cmd mtp:gdrive_id or mtp:link to download using user token.pickle uploaded from usetting
/cmd mrcc:remote:path to download using user rclone config uploaded from usetting
you can simply edit upload using owner/user token/config from usetting without adding mtp: or mrcc: before the path/id"""

rcf = """<b>Rclone Flags</b>: -rcf

/cmd link|path|rcl -up path|rcl -rcf --buffer-size:8M|--drive-starred-only|key|key:value
This will override all other flags except --exclude
Check here all <a href='https://rclone.org/flags/'>RcloneFlags</a>."""

bulk = """<b>Bulk Download</b>: -b

Bulk can be used only by replying to text message or text file contains links separated by new line.
Example:
link1 -n new name -up remote1:path1 -rcf |key:value|key:value
link2 -z -n new name -up remote2:path2
link3 -e -n new name -up remote2:path2
Reply to this example by this cmd -> /cmd -b(bulk)

Note: Any arg along with the cmd will be set to all links
/cmd -b -up remote: -z -m folder name (all links contents in one zipped folder uploaded to one destination)
so you can't set different upload destinations along with link in case you have added -m along with cmd
You can set start and end of the links from the bulk like seed, with -b start:end or only end by -b :end or only start by -b start.
The default start is from zero(first link) to inf."""

rclone_dl = """<b>Rclone Download</b>:

Treat rclone paths exactly like links
/cmd main:dump/ubuntu.iso or rcl(To select config, remote and path)
Users can add their own rclone from user settings
If you want to add path manually from your config add mrcc: before the path without space
/cmd mrcc:main:dump/ubuntu.iso
You can simply edit using owner/user config from usetting without adding mrcc: before the path"""

extract_zip = """<b>Extract/Zip</b>: -e -z

/cmd link -e password (extract password protected)
/cmd link -z password (zip password protected)
/cmd link -z password -e (extract and zip password protected)
Note: When both extract and zip added with cmd it will extract first and then zip, so always extract first"""

join = """<b>Join Splitted Files</b>: -j

This option will only work before extract and zip, so mostly it will be used with -m argument (samedir)
By Reply:
/cmd -i 3 -j -m folder name
/cmd -b -j -m folder name
if u have link(folder) have splitted files:
/cmd link -j"""

tg_links = """<b>TG Links</b>:

Treat links like any direct link
Some links need user access so you must add USER_SESSION_STRING for it.
Three types of links:
Public: https://t.me/channel_name/message_id
Private: tg://openmessage?user_id=xxxxxx&message_id=xxxxx
Super: https://t.me/c/channel_id/message_id
Range: https://t.me/channel_name/first_message_id-last_message_id
Range Example: tg://openmessage?user_id=xxxxxx&message_id=555-560 or https://t.me/channel_name/100-150
Note: Range link will work only by replying cmd to it"""

sample_video = """<b>Sample Video</b>: -sv

Create sample video for one video or folder of videos.
/cmd -sv (it will take the default values which 60sec sample duration and part duration is 4sec).
You can control those values. Example: /cmd -sv 70:5(sample-duration:part-duration) or /cmd -sv :5 or /cmd -sv 70."""

screenshot = """<b>ScreenShots</b>: -ss

Create screenshots for one video or folder of videos.
/cmd -ss (it will take the default values which is 10 photos).
You can control this value. Example: /cmd -ss 6."""

seed = """<b>Bittorrent seed</b>: -d

/cmd link -d ratio:seed_time or by replying to file/link
To specify ratio and seed time add -d ratio:time.
Example: -d 0.7:10 (ratio and time) or -d 0.7 (only ratio) or -d :10 (only time) where time in minutes"""

zip_arg = """<b>Zip</b>: -z password

/cmd link -z (zip)
/cmd link -z password (zip password protected)"""

qual = """<b>Quality Buttons</b>: -s

In case default quality added from yt-dlp options using format option and you need to select quality for specific link or links with multi links feature.
/cmd link -s"""

yt_opt = """<b>Options</b>: -opt

/cmd link -opt {"format": "bv*+mergeall[vcodec=none]", "nocheckcertificate": True, "playliststart": 10, "fragment_retries": float("inf"), "matchtitle": "S13", "writesubtitles": True, "live_from_start": True, "postprocessor_args": {"ffmpeg": ["-threads", "4"]}, "wait_for_video": (5, 100), "download_ranges": [{"start_time": 0, "end_time": 10}]}

Check all yt-dlp api options from this <a href='https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/YoutubeDL.py#L184'>FILE</a> or use this <a href='https://t.me/mltb_official_channel/177'>script</a> to convert cli arguments to api options."""

convert_media = """<b>Convert Media</b>: -ca -cv
/cmd link -ca mp3 -cv mp4 (convert all audios to mp3 and all videos to mp4)
/cmd link -ca mp3 (convert all audios to mp3)
/cmd link -cv mp4 (convert all videos to mp4)
/cmd link -ca mp3 + flac ogg (convert only flac and ogg audios to mp3)
/cmd link -cv mkv - webm flv (convert all videos to mp4 except webm and flv)"""

force_start = """<b>Force Start</b>: -f -fd -fu
/cmd link -f (force download and upload)
/cmd link -fd (force download only)
/cmd link -fu (force upload directly after download finish)"""

gdrive = """<b>Gdrive</b>: link
If DEFAULT_UPLOAD is `rc` then you can pass up: `gd` to upload using gdrive tools to GDRIVE_ID.
/cmd gdriveLink or gdl or gdriveId -up gdl or gdriveId or gd
/cmd tp:gdriveLink or tp:gdriveId -up tp:gdriveId or gdl or gd (to use token.pickle if service account enabled)
/cmd sa:gdriveLink or sa:gdriveId -p sa:gdriveId or gdl or gd (to use service account if service account disabled)
/cmd mtp:gdriveLink or mtp:gdriveId -up mtp:gdriveId or gdl or gd(if you have added upload gdriveId from usetting) (to use user token.pickle that uploaded by usetting)
You can simply edit using owner/user token from usetting without adding mtp: before the id"""

rclone_cl = """<b>Rclone</b>: path
If DEFAULT_UPLOAD is `gd` then you can pass up: `rc` to upload to RCLONE_PATH.
/cmd rcl/rclone_path -up rcl/rclone_path/rc -rcf flagkey:flagvalue|flagkey|flagkey:flagvalue
/cmd rcl or rclone_path -up rclone_path or rc or rcl
/cmd mrcc:rclone_path -up rcl or rc(if you have add rclone path from usetting) (to use user config)
You can simply edit using owner/user config from usetting without adding mrcc: before the path"""

name_swap = r"""<b>Name Substitution</b>: -ns
/cmd link -ns script/code/s | mirror/leech | tea/ /s | clone | cpu/ | \[mltb\]/mltb | \\text\\/text/s
This will affect on all files. Format: wordToReplace/wordToReplaceWith/sensitiveCase
Word Substitutions. You can add pattern instead of normal text. Timeout: 60 sec
NOTE: You must add \ before any character, those are the characters: \^$.|?*+()[]{}-
1. script will get replaced by code with sensitive case
2. mirror will get replaced by leech
4. tea will get replaced by space with sensitive case
5. clone will get removed
6. cpu will get replaced by space
7. [mltb] will get replaced by mltb
8. \text\ will get replaced by text with sensitive case
"""

transmission = """<b>Tg transmission</b>: -hl -ut -bt
/cmd link -hl (both: user for >2GB, bot for ≤2GB)
/cmd link -bt (bot only)
/cmd link -ut (user only)"""

thumbnail_layout = """Thumbnail Layout: -tl
/cmd link -tl 3x3 (widthxheight) 3 photos in row and 3 photos in column"""

leech_as = """<b>Leech as</b>: -doc -med
/cmd link -doc (Leech as document)
/cmd link -med (Leech as media)"""

ffmpeg_cmds = """<b>FFmpeg Commands</b>: -ff
list of lists of ffmpeg commands. You can set multiple ffmpeg commands for all files before upload. Don't write ffmpeg at beginning, start directly with the arguments.
Notes:
1. Add <code>-del</code> to the list(s) which you want from the bot to delete the original files after command run complete!
3. To execute one of pre-added lists in bot like: ({"subtitle": ["-i mltb.mkv -c copy -c:s srt mltb.mkv"]}), you must use -ff subtitle (list key)
Examples: ["-i mltb.mkv -c copy -c:s srt mltb.mkv", "-i mltb.video -c copy -c:s srt mltb", "-i mltb.m4a -c:a libmp3lame -q:a 2 mltb.mp3", "-i mltb.audio -c:a libmp3lame -q:a 2 mltb.mp3", "-i mltb -map 0:a -c copy mltb.mka -map 0:s -c copy mltb.srt"]
Here I will explain how to use mltb.* which is reference to files you want to work on.
1. First cmd: the input is mltb.mkv so this cmd will work only on mkv videos and the output is mltb.mkv also so all outputs are mkv. -del will delete the original media after complete run of the cmd.
2. Second cmd: the input is mltb.video so this cmd will work on all videos and the output is only mltb so the extension is the same as input files.
3. Third cmd: the input is mltb.m4a so this cmd will work only on m4a audios and the output is mltb.mp3 so the output extension is mp3.
4. Fourth cmd: the input is mltb.audio so this cmd will work on all audios and the output is mltb.mp3 so the output extension is mp3."""

metadata = """<b>Metadata</b>: -meta

Apply custom metadata to media files using pipe (|) separator.

<b>Format:</b> key=value|key2=value2|key3=value3

<b>Dynamic Variables:</b>
• <code>{filename}</code> - Original filename
• <code>{basename}</code> - Filename without extension  
• <code>{extension}</code> - File extension
• <code>{audiolang}</code> - Audio language (auto-detected or English)
• <code>{sublang}</code> - Subtitle language (auto-detected or none)
• <code>{year}</code> - Year extracted from filename

<b>Per-Stream Metadata:</b>
Set different metadata for audio/video/subtitle streams in User Settings > FFmpeg Settings:
• <b>Audio Metadata:</b> Applied to each audio stream
• <b>Video Metadata:</b> Applied to video streams  
• <b>Subtitle Metadata:</b> Applied to subtitle streams

<b>Examples:</b>
<code>/mirror link -meta title=My Movie|artist={audiolang} Version</code>
<code>/yt link -meta album={basename}|year={year}|genre=Action</code>

<b>Escape Pipes:</b> Use <code>\\|</code> to include literal pipe in values:
<code>title=Movie \\| Director's Cut</code>

<b>User Settings Example:</b>
• Audio Metadata: <code>language={audiolang}|title=Audio Track</code>
• Video Metadata: <code>title={basename}|year={year}</code>
• Subtitle Metadata: <code>language={sublang}|title=Subtitles</code>"""

YT_HELP_DICT = {
    "main": yt,
    "New-Name": f"{new_name}\nNote: Don't add file extension",
    "Zip": zip_arg,
    "Quality": qual,
    "Options": yt_opt,
    "Multi-Link": multi_link,
    "Same-Directory": same_dir,
    "Thumb": thumb,
    "Split-Size": split_size,
    "Upload-Destination": upload,
    "Rclone-Flags": rcf,
    "Bulk": bulk,
    "Sample-Video": sample_video,
    "Screenshot": screenshot,
    "Convert-Media": convert_media,
    "Force-Start": force_start,
    "Name-Swap": name_swap,
    "TG-Transmission": transmission,
    "Thumb-Layout": thumbnail_layout,
    "Leech-Type": leech_as,
    "FFmpeg-Cmds": ffmpeg_cmds,
    "Metadata": metadata,
}

MIRROR_HELP_DICT = {
    "main": mirror,
    "New-Name": new_name,
    "DL-Auth": "<b>Direct link authorization</b>: -au -ap\n\n/cmd link -au username -ap password",
    "Headers": "<b>Direct link custom headers</b>: -h\n\n/cmd link -h key: value key1: value1",
    "Extract/Zip": extract_zip,
    "Select-Files": "<b>Bittorrent/JDownloader/Sabnzbd File Selection</b>: -s\n\n/cmd link -s or by replying to file/link",
    "Torrent-Seed": seed,
    "Multi-Link": multi_link,
    "Same-Directory": same_dir,
    "Thumb": thumb,
    "Split-Size": split_size,
    "Upload-Destination": upload,
    "Rclone-Flags": rcf,
    "Bulk": bulk,
    "Join": join,
    "Rclone-DL": rclone_dl,
    "Tg-Links": tg_links,
    "Sample-Video": sample_video,
    "Screenshot": screenshot,
    "Convert-Media": convert_media,
    "Force-Start": force_start,
    "User-Download": user_download,
    "Name-Swap": name_swap,
    "TG-Transmission": transmission,
    "Thumb-Layout": thumbnail_layout,
    "Leech-Type": leech_as,
    "FFmpeg-Cmds": ffmpeg_cmds,
    "Metadata": metadata,
}

CLONE_HELP_DICT = {
    "main": clone,
    "Multi-Link": multi_link,
    "Bulk": bulk,
    "Gdrive": gdrive,
    "Rclone": rclone_cl,
}

RSS_HELP_MESSAGE = """
Use this format to add feed url:
Title1 link (required)
Title2 link -c cmd -inf xx -exf xx
Title3 link -c cmd -d ratio:time -z password

-c command -up mrcc:remote:path/subdir -rcf --buffer-size:8M|key|key:value
-inf For included words filter.
-exf For excluded words filter.
-stv true or false (sensitive filter)

Example: Title https://www.rss-url.com -inf 1080 or 720 or 144p|mkv or mp4|hevc -exf flv or web|xxx
This filter will parse links that its titles contain `(1080 or 720 or 144p) and (mkv or mp4) and hevc` and doesn't contain (flv or web) and xxx words. You can add whatever you want.

Another example: -inf  1080  or 720p|.web. or .webrip.|hevc or x264. This will parse titles that contain ( 1080  or 720p) and (.web. or .webrip.) and (hevc or x264). I have added space before and after 1080 to avoid wrong matching. If this `10805695` number in title it will match 1080 if added 1080 without spaces after it.

Filter Notes:
1. | means and.
2. Add `or` between similar keys, you can add it between qualities or between extensions, so don't add filter like this f: 1080|mp4 or 720|web because this will parse 1080 and (mp4 or 720) and web ... not (1080 and mp4) or (720 and web).
3. You can add `or` and `|` as much as you want.
4. Take a look at the title if it has a static special character after or before the qualities or extensions or whatever and use them in the filter to avoid wrong match.
Timeout: 60 sec.
"""

PASSWORD_ERROR_MESSAGE = """
<b>This link requires a password!</b>
- Insert <b>::</b> after the link and write the password after the sign.

<b>Example:</b> link::my password
"""

# דפי העזרה הבאים מחליפים את הנוסח הישן באנגלית, תוך שמירה על שמות הדגלים
# והפקודות כפי שהם כדי שאפשר יהיה להעתיק את הדוגמאות ישירות ל־Telegram.
_HE_COMMON_HELP = {
    "New-Name": "<b>שם חדש:</b> <code>-n שם</code>\nמשנה את שם הקובץ או התיקייה. אין להוסיף סיומת כשמשתמשים ב־YT-DLP.",
    "Zip": "<b>דחיסה:</b> <code>-z</code> או <code>-z סיסמה</code>\nדוחס את התוצאה לקובץ ZIP, עם סיסמה לפי הצורך.",
    "Extract/Zip": "<b>חילוץ או דחיסה:</b> <code>-e</code> לחילוץ, <code>-z</code> לדחיסה. אפשר לצרף סיסמה אחרי הדגל.",
    "Multi-Link": "<b>מספר קישורים:</b> <code>-i מספר</code>\nמעבד מספר הודעות רצופות החל מההודעה הנוכחית.",
    "Same-Directory": "<b>תיקייה משותפת:</b> <code>-m שם</code>\nמרכז מספר הורדות באותה תיקיית יעד.",
    "Thumb": "<b>תמונה ממוזערת:</b> <code>-t קישור</code>\nאפשר להשתמש בקישור ישיר לתמונה או בתמונה שנשמרה בהגדרות המשתמש.",
    "Split-Size": "<b>גודל פיצול:</b> <code>-sp גודל</code>\nקובע את גודל החלקים בשליחה ל־Telegram. לדוגמה: <code>-sp 2G</code>.",
    "Upload-Destination": "<b>יעד העלאה:</b> <code>-up יעד</code>\nאפשר לבחור Google Drive, נתיב Rclone, Telegram או שירות אחסון שהוגדר.",
    "Rclone-Flags": "<b>דגלי Rclone:</b> <code>-rcf דגלים</code>\nיש להפריד בין דגלים באמצעות <code>|</code>. לדוגמה: <code>-rcf --buffer-size:8M|--transfers:4</code>.",
    "Bulk": "<b>עיבוד רשימה:</b> <code>-b</code>\nקורא קישורים מקובץ טקסט או מהודעה ומפעיל אותם ברצף.",
    "Sample-Video": "<b>סרטון דוגמה:</b> <code>-sv</code>\nיוצר קטע דוגמה קצר מקובץ הווידאו.",
    "Screenshot": "<b>צילומי מסך:</b> <code>-ss מספר</code>\nיוצר את מספר צילומי המסך המבוקש מהווידאו.",
    "Convert-Media": "<b>המרת מדיה:</b> <code>-ca</code> לשמע או <code>-cv</code> לווידאו, בצירוף הפורמט הרצוי.",
    "Force-Start": "<b>הפעלה מיידית:</b> <code>-f</code>\nמדלג על תור ההורדה או ההעלאה, בהתאם להרשאות.",
    "Name-Swap": "<b>החלפת טקסט בשם:</b> <code>-ns טקסט1/טקסט2</code>\nמחליף או מסיר חלקים משמות הקבצים.",
    "TG-Transmission": "<b>אופן השליחה ל־Telegram:</b> מאפשר לבחור מסמך, מדיה, קבוצה או העברה בהתאם להגדרות המשתמש.",
    "Thumb-Layout": "<b>פריסת תמונות ממוזערות:</b> קובעת כיצד תמונות ממוזערות יוצגו בהודעות מדיה וקבוצות.",
    "Leech-Type": "<b>סוג השליחה:</b> קובע אם לשלוח כקובץ, וידאו, שמע או מדיה לפי סוג הקובץ.",
    "FFmpeg-Cmds": "<b>פקודות FFmpeg:</b> <code>-ff פקודה</code>\nמפעיל עיבוד FFmpeg מותאם. מומלץ לבדוק תחילה על קובץ קטן.",
    "Metadata": "<b>מטא־דאטה:</b> <code>-meta מפתח=ערך</code>\nאפשר להוסיף כמה ערכים ולהפריד ביניהם באמצעות <code>|</code>.",
}

YT_HELP_DICT = {
    "main": "<b>הורדה באמצעות YT-DLP</b>\n\n<code>/ytdl קישור [אפשרויות]</code>\nאפשר להוריד וידאו או שמע מאתרים נתמכים, לבחור איכות ולשלוח לענן או ל־Telegram.",
    **_HE_COMMON_HELP,
    "Quality": "<b>איכות:</b> <code>-q איכות</code>\nאפשר לבחור איכות מהתפריט או לציין ערך נתמך של YT-DLP.",
    "Options": "<b>אפשרויות YT-DLP:</b> <code>-opt מפתח:ערך</code>\nיש להפריד בין אפשרויות באמצעות <code>|</code>. השתמשו רק באפשרויות שאתם מכירים.",
}

MIRROR_HELP_DICT = {
    "main": "<b>הורדה והעלאה</b>\n\n<code>/mirror קישור [אפשרויות]</code>\nהפקודה מורידה קישור, טורנט או קובץ ומעלה אותו ליעד שנבחר.",
    **_HE_COMMON_HELP,
    "DL-Auth": "<b>אימות לקישור ישיר:</b> <code>-au משתמש -ap סיסמה</code>.",
    "Headers": "<b>כותרות HTTP:</b> <code>-h key: value</code>\nאפשר לצרף מספר כותרות לפי דרישות האתר.",
    "Select-Files": "<b>בחירת קבצים:</b> <code>-s</code>\nפותח מסך לבחירת קבצים בטורנט, JDownloader או SABnzbd.",
    "Torrent-Seed": "<b>שיתוף טורנט:</b> <code>-d יחס:זמן</code>\nממשיך לשתף לאחר ההורדה לפי היחס או הזמן שהוגדרו.",
    "Join": "<b>איחוד חלקים:</b> <code>-j</code>\nמאחד קבצים מפוצלים לפני ההעלאה.",
    "Rclone-DL": "<b>הורדה מ־Rclone:</b> יש לשלוח נתיב בפורמט <code>remote:path</code> או לבחור מהתפריט.",
    "Tg-Links": "<b>קישורי Telegram:</b> אפשר להשיב לקובץ או להשתמש בקישור להודעה שאליה יש לבוט גישה.",
    "User-Download": "<b>הורדה בחשבון משתמש:</b> משתמשת בחיבור המשתמש האישי כשהאפשרות הוגדרה ואושרה.",
}

CLONE_HELP_DICT = {
    "main": "<b>שכפול קבצים</b>\n\n<code>/clone קישור [אפשרויות]</code>\nמשכפל קובץ או תיקייה בין יעדי Google Drive או Rclone.",
    "Multi-Link": _HE_COMMON_HELP["Multi-Link"],
    "Bulk": _HE_COMMON_HELP["Bulk"],
    "Gdrive": "<b>Google Drive:</b> יש לשלוח קישור לקובץ או לתיקייה ולבחור יעד העלאה מורשה.",
    "Rclone": "<b>Rclone:</b> יש לשלוח מקור ויעד בפורמט <code>remote:path</code> בהתאם להגדרות הבוט.",
}

RSS_HELP_MESSAGE = """
<b>הוספת מקור RSS</b>

כל שורה כוללת שם וקישור:
<code>שם https://example.com/feed</code>

אפשרויות שימושיות:
<code>-c</code> פקודה להפעלה
<code>-inf</code> מילים שחייבות להופיע
<code>-exf</code> מילים שאסור שיופיעו
<code>-d יחס:זמן</code> תנאי שיתוף
<code>-z סיסמה</code> דחיסה

במסננים, <code>|</code> פירושו "וגם" והמילה <code>or</code> פירושה "או".
דוגמה: <code>-inf 1080 or 720|mkv or mp4|hevc -exf flv or web</code>
זמן ההמתנה להזנת הנתונים הוא 60 שניות.
"""

PASSWORD_ERROR_MESSAGE = """
<b>הקישור דורש סיסמה.</b>
יש להוסיף <b>::</b> אחרי הקישור ולכתוב אחריו את הסיסמה.

<b>דוגמה:</b> <code>link::my password</code>
"""


def get_bot_commands():
    from ...core.plugin_manager import get_plugin_manager

    static_commands = {
        "Mirror": "[קישור/קובץ] הורדה והעלאה ליעד ענן",
        "QbMirror": "[מגנט/טורנט] הורדה באמצעות qBittorrent והעלאה לענן",
        "Ytdl": "[קישור] הורדת YouTube, רשתות חברתיות ואתרים הנתמכים ב־yt-dlp",
        "UpHoster": "[קישור/טורנט] הורדה והעלאה ישירה ל־GoFile או לשירות אחסון אחר",
        "Leech": "[קישור/קובץ] הורדה ושליחה אל Telegram",
        "QbLeech": "[מגנט/טורנט] הורדה באמצעות qBittorrent ושליחה ל־Telegram",
        "YtdlLeech": "[קישור] הורדת תוכן באמצעות yt-dlp ושליחה ל־Telegram",
        "Clone": "[קישור] העתקת קובץ או תיקייה אל Google Drive",
        "UserSet": "הגדרות אישיות",
        "ForceStart": "[מזהה/תגובה] הפעלה מיידית של משימה מהתור",
        "Count": "[קישור] ספירת קבצים ותיקיות ב־Google Drive",
        "List": "[חיפוש] חיפוש קבצים ב־Google Drive",
        "Search": "[חיפוש] חיפוש טורנטים",
        "MediaInfo": "[תגובה/קישור] הצגת מידע טכני על קובץ מדיה",
        "Select": "[מזהה/תגובה] בחירת קבצים מתוך טורנט או NZB",
        "Ping": "בדיקת זמינות וזמן תגובה של הבוט",
        "Status": "[מזהה/me] מצב משימות ההורדה וההעלאה",
        "Stats": "מצב שרת מלא, משאבים ובדיקת מהירות",
        "Rss": "ניהול מקורות RSS אישיים",
        "IMDB": "[שם/מזהה] מידע על סרט או סדרה",
        "CancelAll": "ביטול משימות פעילות",
        "Help": "רשימת פקודות והסבר שימוש",
        "BotSet": "[SUDO] הגדרות וניהול הבוט",
        "Log": "[SUDO] הצגת לוגים לאבחון תקלות",
        "Restart": "[SUDO] הפעלה מחדש של הבוט",
        "RestartSessions": "[SUDO] הפעלה מחדש של חיבורי המשתמשים",
        "GenPyroSess": "[SUDO] יצירת מחרוזת התחברות של Pyrogram",
    }

    commands = static_commands.copy()

    plugin_manager = get_plugin_manager()
    if plugin_manager:
        for plugin_info in plugin_manager.list_plugins():
            if plugin_info.enabled and plugin_info.commands:
                for cmd in plugin_info.commands:
                    key = cmd.capitalize()
                    if key not in commands:
                        commands[key] = (
                            plugin_info.description or f"פקודת תוסף: {cmd}"
                        )

    return commands


BOT_COMMANDS = get_bot_commands()


def get_help_string():
    from ..telegram_helper.bot_commands import BotCommands

    descriptions = {
        "Mirror": "הורדת קישור או קובץ והעלאתו ליעד ענן.",
        "QbMirror": "הורדת טורנט באמצעות qBittorrent והעלאתו לענן.",
        "JdMirror": "הורדה באמצעות JDownloader והעלאה לענן.",
        "NzbMirror": "הורדת NZB באמצעות SABnzbd והעלאה לענן.",
        "Ytdl": "הורדת קישור הנתמך ב־yt-dlp והעלאה לענן.",
        "UpHoster": "הורדת קישור, קובץ או טורנט והעלאה ישירה ל־GoFile או לשירות אחסון אחר.",
        "Leech": "הורדה ושליחת הקבצים אל Telegram.",
        "QbLeech": "הורדת טורנט באמצעות qBittorrent ושליחה ל־Telegram.",
        "JdLeech": "הורדה באמצעות JDownloader ושליחה ל־Telegram.",
        "NzbLeech": "הורדת NZB באמצעות SABnzbd ושליחה ל־Telegram.",
        "YtdlLeech": "הורדת קישור הנתמך ב־yt-dlp ושליחה ל־Telegram.",
        "Clone": "העתקת קובץ או תיקייה אל Google Drive.",
        "Count": "ספירת קבצים ותיקיות ב־Google Drive.",
        "Delete": "מחיקת קובץ או תיקייה מ־Google Drive. לבעלים ולמנהלים בלבד.",
        "UserSet": "פתיחת ההגדרות האישיות.",
        "BotSet": "פתיחת הגדרות הבוט. למנהלים בלבד.",
        "Select": "בחירת קבצים מתוך משימת טורנט או NZB.",
        "CancelTask": "ביטול משימה לפי מזהה או באמצעות תגובה להודעה.",
        "ForceStart": "הפעלה מיידית של משימה שממתינה בתור.",
        "CancelAll": "ביטול משימות לפי המצב שלהן.",
        "List": "חיפוש קבצים ב־Google Drive.",
        "Search": "חיפוש טורנטים.",
        "MediaInfo": "הצגת מידע טכני על קובץ מדיה.",
        "Status": "הצגת מצב ההורדות וההעלאות הפעילות.",
        "Stats": "מצב שרת מלא, משאבים, תהליכים ובדיקת מהירות.",
        "Ping": "בדיקת זמינות וזמן התגובה של הבוט.",
        "Authorize": "מתן הרשאה למשתמש או לצ'אט. למנהלים בלבד.",
        "UnAuthorize": "הסרת הרשאה ממשתמש או מצ'אט. למנהלים בלבד.",
        "Users": "הצגת הגדרות משתמשים. למנהלים בלבד.",
        "AddSudo": "הוספת מנהל. לבעלים בלבד.",
        "RmSudo": "הסרת מנהל. לבעלים בלבד.",
        "BlackList": "חסימת משתמש. למנהלים בלבד.",
        "RmBlackList": "הסרת משתמש מרשימת החסימה. למנהלים בלבד.",
        "AddImage": "הוספת תמונה לגלריה באמצעות תגובה לתמונה או לקישור.",
        "Images": "צפייה וניהול של גלריית התמונות.",
        "Restart": "הפעלה מחדש ועדכון של הבוט. למנהלים בלבד.",
        "RestartSessions": "הפעלה מחדש של חיבורי המשתמשים. למנהלים בלבד.",
        "Log": "הורדה או צפייה בלוג האבחון. למנהלים בלבד.",
        "Shell": "הרצת פקודות מערכת. לבעלים בלבד.",
        "AExec": "הרצת קוד אסינכרוני. לבעלים בלבד.",
        "Exec": "הרצת קוד סינכרוני. לבעלים בלבד.",
        "ClearLocals": "ניקוי משתנים שנשמרו מהרצות קוד. לבעלים בלבד.",
        "Rss": "פתיחת תפריט מקורות ה־RSS.",
        "GenPyroSess": "יצירת מחרוזת התחברות של Pyrogram. למנהלים בלבד.",
        "IMDB": "חיפוש מידע על סרט או סדרה.",
    }
    help_lines = [
        "<b>פקודות הבוט</b>",
        "שלחו פקודה ללא פרמטרים כדי לקבל הסבר ודוגמאות.",
    ]

    for key in BotCommands.get_commands():
        cmd_attr = getattr(BotCommands, f"{key}Command", None)
        if not cmd_attr:
            continue
        cmd_str = (
            f"/{' או /'.join(cmd_attr)}"
            if isinstance(cmd_attr, list)
            else f"/{cmd_attr}"
        )
        description = descriptions.get(key) or BOT_COMMANDS.get(key)
        if description:
            help_lines.append(f"\n<b>{cmd_str}</b>\n{description}")

    return "\n".join(help_lines)


help_string = get_help_string()
