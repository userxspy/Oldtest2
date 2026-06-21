class script(object):

    START_TXT = """<b>Hey {}, <i>{}</i>

I am your personal auto filter bot. Send me the movie or file name to get direct links instantly... ⚡️</b>"""

    STATUS_TXT = """🗃️ <b>Database Status (Bot Stats):</b>

📂 Total Files: <code>{}</code>
🦹 Total Admins: <code>{}</code>
🚀 Used Storage: <code>{}</code>
🗂️ Free Storage: <code>{}</code>
⏰ Uptime: <code>{}</code>"""

    NOT_FILE_TXT = """👋 <b>Hey {},

No file found in the database with the keyword <code>{}</code>! 🥲

👉 Please check the spelling or search again with the correct name.</b>"""

    # Only bold file name as requested
    FILE_CAPTION = """<b>{file_name}</b>"""

    HELP_TXT = """<b>Note - Click the button below for correct information about the commands. ⚙️</b>"""

    ADMIN_COMMAND_TXT = """<b>🤖 Admin Commands List:</b>

🔹 /index_channels - Check indexed channels
🔹 /stats - View live status of bot and database
🔹 /delete - Delete files using a specific query
🔹 /delete_all - Delete all indexed files from database
🔹 /restart - Restart the bot
🔹 /set_pm_search - Turn PM search on or off (on/off)"""

    USER_COMMAND_TXT = """<b>🛠️ Configuration Commands:</b>

🔹 /start - Check live status of the bot
🔹 /set_caption - Set a custom file caption
🔹 /id - View your user ID or the ID of a replied message"""
