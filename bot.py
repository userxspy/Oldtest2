import os
import time
import asyncio
from typing import Union, Optional, AsyncGenerator

# 1. सबसे पहले uvloop को लागू करें ताकि C-Level की नेटिव स्पीड मिले
try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except ImportError:
    pass

from hydrogram import Client, types
from hydrogram.errors import FloodWait
from aiohttp import web

from web import web_app
from info import LOG_CHANNEL, API_ID, API_HASH, BOT_TOKEN, PORT, BIN_CHANNEL, ADMINS
from utils import temp, get_readable_time

class Bot(Client):
    def __init__(self):
        super().__init__(
            name='Auto_Filter_Bot',
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=BOT_TOKEN,
            plugins={"root": "plugins"}
        )

    async def start(self):
        temp.START_TIME = time.time()
        
        # पुराना MongoDB का सिन्क्रोनस PING लॉजिक हटा दिया, क्योंकि Motor उसे खुद संभाल लेता है।
        await super().start()
        
        # रीस्टार्ट मैसेज हैंडलर
        if os.path.exists('restart.txt'):
            try:
                with open("restart.txt") as file:
                    chat_id, msg_id = map(int, file.read().split())
                await self.edit_message_text(chat_id=chat_id, message_id=msg_id, text='Restarted Successfully!')
            except Exception:
                pass
            try:
                os.remove('restart.txt')
            except Exception:
                pass
            
        temp.BOT = self
        me = await self.get_me()
        temp.ME = me.id
        temp.U_NAME = me.username
        temp.B_NAME = me.first_name
        
        print(f"🔥 {me.first_name} Admin-Only Mode में स्टार्ट हो गया है!")

        # aiohttp वेब सर्वर को स्टार्ट करें (स्ट्रीमिंग इंजन के लिए)
        app = web.AppRunner(web_app)
        await app.setup()
        await web.TCPSite(app, "0.0.0.0", PORT).start()
        print(f"🌐 स्ट्रीमिंग वेब सर्वर पोर्ट {PORT} पर एक्टिव है!")
        
        # एडमिन और चैनल्स वेरिफिकेशन लॉग्स
        try:
            await self.send_message(chat_id=LOG_CHANNEL, text=f"<b>✅ {me.mention} रीस्टार्ट हो गया है! (Admin Only Model)</b>")
        except Exception:
            print("Error - LOG_CHANNEL चेक करें, बॉट एडमिन होना जरूरी है।")
            exit()
            
        try:
            m = await self.send_message(chat_id=BIN_CHANNEL, text="⚡ ʙɪɴ ᴄʜᴀɴɴᴇʟ ᴛᴇsᴛ")
            await m.delete()
        except Exception:
            print("Error - BIN_CHANNEL चेक करें, बॉट एडमिन होना जरूरी है।")
            exit()
            
        # सिर्फ एक्टिव एडमिंस को अलर्ट भेजें
        for admin in ADMINS:
            try:
                await self.send_message(chat_id=admin, text="<b>🔥 ✅ बॉट सफलतापूर्वक रीस्टार्ट हो गया है!</b>")
            except Exception:
                pass

    async def stop(self, *args):
        await super().stop()
        print("Bot Stopped! Bye...")

    async def iter_messages(self, chat_id: Union[int, str], limit: int, offset: int = 0) -> Optional[AsyncGenerator["types.Message", None]]:
        """चैनल मैसेजेस को इंडेक्सिंग के लिए बिना लैग के एक-एक करके फेज (Iterate) करने का ऑप्टिमाइज्ड मेथड"""
        current = offset
        while True:
            new_diff = min(200, limit - current)
            if new_diff <= 0:
                return
            messages = await self.get_messages(chat_id, list(range(current, current + new_diff + 1)))
            for message in messages:
                yield message
                current += 1

# --- 🚀 UVLOOP + SCRIPT LIFECYCLE FIX ---
async def main():
    app = Bot()
    await app.start()
    try:
        # कस्टमाइज्ड कीप-अलाइव लूप ताकि कोयाब कंटेनर को कभी शटडाउन न करे
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        await app.stop()

if __name__ == "__main__":
    try:
        # asyncio.run() का उपयोग करके 'MainThread' में एक क्लीन न्यू इवेंट लूप असाइन करें
        asyncio.run(main())
    except FloodWait as vp:
        print(f"Flood Wait आ गया है, {get_readable_time(vp.value)} के लिए स्लीप कर रहे हैं...")
        time.sleep(vp.value)
        asyncio.run(main())
