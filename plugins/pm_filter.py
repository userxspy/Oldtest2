import asyncio
import math
from hydrogram import Client, filters, enums
from hydrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from Script import script
from info import ADMINS, MAX_BTN, BIN_CHANNEL, URL
from utils import get_size, temp
from database.ia_filterdb import get_search_results, get_file_details

BUTTONS = {}

@Client.on_message(filters.private & filters.text & filters.incoming)
async def pm_search(client, message):
    """सिर्फ एडमिंस के लिए पर्सनल चैट में मूवी/फाइल सर्च हैंडलर"""
    if message.from_user.id not in ADMINS:
        return # गैर-एडमिंस के लिए बोट पूरी तरह से साइलेंट रहेगा

    search = message.text.strip()
    s = await message.reply(f"<b><i>🔍 `{search}` को डेटाबेस में खोजा जा रहा है...</i></b>", quote=True)
    
    files, offset, total_results = await get_search_results(search)
    if not files:
        await s.edit_text(script.NOT_FILE_TXT.format(message.from_user.mention, search))
        return

    req = message.from_user.id
    key = f"{message.chat.id}-{message.id}"
    BUTTONS[key] = search

    # फ़ाइल बटन जनरेशन (बिना किसी शॉर्टलिंक या विज्ञापन के डायरेक्ट फाइल्स)
    btn = [[InlineKeyboardButton(text=f"📂 [{get_size(file.file_size)}] {file.file_name}", callback_data=f"file#{file.file_id}#{req}")] for file in files]
    
    # यदि और भी ज्यादा रिजल्ट्स उपलब्ध हैं तो पेजिनेशन बटन जोड़ें
    if offset != "":
        btn.append([
            InlineKeyboardButton(text=f"🗓 1/{math.ceil(int(total_results) / MAX_BTN)}", callback_data="buttons"),
            InlineKeyboardButton(text="NEXT ⏩", callback_data=f"next_{req}_{key}_{offset}")
        ])
    
    btn.append([InlineKeyboardButton("🙅 क्लोज़", callback_data=f"close#{req}")])
    
    cap = f"<b>✅ सर्च रिजल्ट्स:- {search}\n🎬 कुल {total_results} फाइलें मिलीं 👇</b>"
    await s.edit_text(cap, reply_markup=InlineKeyboardMarkup(btn))

@Client.on_callback_query(filters.regex(r"^next"))
async def next_page(bot, query):
    """नेक्स्ट और बैक पेजिनेशन हैंडलर (Next/Back Pages)"""
    ident, req, key, offset = query.data.split("_")
    if int(req) != query.from_user.id:
        return await query.answer("यह आपके लिए नहीं है! ❌", show_alert=True)
        
    search = BUTTONS.get(key)
    if not search:
        return await query.answer("कृपया दोबारा नया नाम लिखकर सर्च करें! 🔄", show_alert=True)

    files, n_offset, total = await get_search_results(search, offset=int(offset))
    
    btn = [[InlineKeyboardButton(text=f"📂 [{get_size(file.file_size)}] {file.file_name}", callback_data=f"file#{file.file_id}#{req}")] for file in files]
    
    off_set = int(offset) - MAX_BTN if int(offset) > 0 else None
    current_page = math.ceil(int(offset) / MAX_BTN) + 1
    total_pages = math.ceil(total / MAX_BTN)

    p_buttons = []
    if off_set is not None or int(offset) > 0:
        p_buttons.append(InlineKeyboardButton("⏪ BACK", callback_data=f"next_{req}_{key}_{max(0, int(offset)-MAX_BTN)}"))
    
    p_buttons.append(InlineKeyboardButton(f"🗓 {current_page}/{total_pages}", callback_data="buttons"))
    
    if n_offset != "":
        p_buttons.append(InlineKeyboardButton("NEXT ⏩", callback_data=f"next_{req}_{key}_{n_offset}"))
        
    btn.append(p_buttons)
    btn.append([InlineKeyboardButton("🙅 क्लोज़", callback_data=f"close#{req}")])
    
    cap = f"<b>✅ सर्च रिजल्ट्स:- {search}\n🎬 कुल {total} फाइलें मिलीं 👇</b>"
    await query.message.edit_text(cap, reply_markup=InlineKeyboardMarkup(btn))

@Client.on_callback_query()
async def cb_handler(client: Client, query: CallbackQuery):
    """सभी आवश्यक एडमिन कॉलबैक क्लिक्स को हैंडल करने का सिंगल क्लीन फंक्शन"""
    data = query.data
    user_id = query.from_user.id

    if data.startswith("file"):
        _, file_id, req = data.split("#")
        if int(req) != user_id:
            return await query.answer("यह आपके लिए नहीं है! ❌", show_alert=True)
            
        await query.answer("फाइल विवरण लोड हो रहा है... ⏱️")
        file_details = await get_file_details(file_id)
        if not file_details:
            return await query.message.reply("फाइल डेटाबेस में नहीं मिली!")
            
        file = file_details[0]
        cap = script.FILE_CAPTION.format(file_name=file.file_name, file_size=get_size(file.file_size))
        
        # डायरेक्ट स्ट्रीम बटन (बिना किसी वेरिफिकेशन या प्रीमियम रुकावट के)
        btn = [[
            InlineKeyboardButton("⚡ Watch Online", url=f"{URL}watch/{file.file_id}"),
            InlineKeyboardButton("🚀 Fast Download", url=f"{URL}download/{file.file_id}")
        ]] if BIN_CHANNEL else []
        
        # सीधे इनबॉक्स में फाइल सेंड करें
        await client.send_cached_media(chat_id=user_id, file_id=file.file_id, caption=cap, reply_markup=InlineKeyboardMarkup(btn))

    elif data.startswith("close"):
        _, req = data.split("#")
        if int(req) == user_id:
            await query.message.delete()
        else:
            await query.answer("यह आपके लिए नहीं है! ❌", show_alert=True)

    elif data == "buttons":
        await query.answer("⚙️", show_alert=False)
