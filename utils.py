import asyncio
import re
import pytz
from datetime import datetime

class temp(object):
    """बॉट के लाइव सेशन का स्टेट मैनेजर (सिर्फ एडमिन-ओनली जरूरी वेरिएबल्स)"""
    START_TIME = 0
    ME = None
    CANCEL = False
    U_NAME = None
    B_NAME = None
    FILES = {}
    BOT = None

def get_size(size):
    """फ़ाइल साइज को Bytes से KB, MB, GB में बदलने का तेज़ मेथड"""
    units = ["Bytes", "KB", "MB", "GB", "TB"]
    size = float(size)
    i = 0
    while size >= 1024.0 and i < len(units) - 1:
        i += 1
        size /= 1024.0
    return "%.2f %s" % (size, units[i])

def get_readable_time(seconds):
    """बॉट के लाइव अपटाइम (Uptime) को पढ़ने योग्य बनाने का फंक्शन"""
    periods = [('d', 86400), ('h', 3600), ('m', 60), ('s', 1)]
    result = ''
    for period_name, period_seconds in periods:
        if seconds >= period_seconds:
            period_value, seconds = divmod(seconds, period_seconds)
            result += f'{int(period_value)}{period_name}'
    return result if result else '0s'

def get_wish():
    """समय के अनुसार एडमिन को विश करने का फंक्शन (जैसे: Good Morning)"""
    tz = pytz.timezone('Asia/Kolkata') # टाइमज़ोन को इंडिया (Kolkata) पर सेट कर दिया गया है
    time_now = datetime.now(tz)
    now = time_now.strftime("%H")
    if now < "12":
        return "ɢᴏᴏᴅ ᴍᴏʀɴɪɴɢ 🌞"
    elif now < "18":
        return "ɢᴏᴏᴅ ᴀꜰᴛᴇʀɴᴏᴏɴ 🌗"
    else:
        return "ɢᴏᴏᴅ ᴇᴠᴇɴɪɴɢ 🌘"

async def get_seconds(time_string):
    """टाइम स्ट्रिंग (जैसे: 5m, 1h) को सेकंड्स में बदलने का क्लीन फंक्शन"""
    def extract_value_and_unit(ts):
        value = ""
        index = 0
        while index < len(ts) and ts[index].isdigit():
            value += ts[index]
            index += 1
        unit = ts[index:].strip().lower()
        return int(value) if value else 0, unit
    
    value, unit = extract_value_and_unit(time_string)

    if unit in ['s', 'sec', 'secs']:
        return value
    elif unit in ['min', 'mins', 'm']:
        return value * 60
    elif unit in ['hour', 'hours', 'h']:
        return value * 3600
    elif unit in ['day', 'days', 'd']:
        return value * 86400
    elif unit in ['month', 'months']:
        return value * 86400 * 30
    elif unit in ['year', 'years']:
        return value * 86400 * 365
    return 0
