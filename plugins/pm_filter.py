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
    """सिर्फ एडमिंस के लिए पर्सनल चैट में मूवी/फाइल सर्च हैंडलर (प्योर टेक्स्ट मोड)"""
    if message.from_user.id not in ADMINS:
        return # गैर-एडमिंस के लिए बोट पूरी तरह से साइलेंट रहेगा

    search = message.text.strip()
    s = await message.reply(f"<b><i>🔍 `{search}` को डेटा规范 में खोजा जा रहा है...</i></b>", quote=True)
    
    files, offset, total_results = await get_search_results(search)
    if not files:
        await s.edit_text(script.NOT_FILE_TXT.format(message.from_user.mention, search))
        return

    req = message.from_user.id
    key = f"{message.chat.id}-{message.id}"
    BUTTONS[key] = search

    # --- 🟢 बटन मोड खत्म, प्योर टेक्स्ट हाइपरलिंक्स फॉर्मेशन ---
    files_link = ""
    for file in files:
        files_link += f"\n\n📁 <a href='https://t.me/{temp.U_NAME}?start=file_{file.file_id}'>[{get_size(file.file_size)}] {file.file_name}</a>"

    # बटन लेआउट में अब केवल पेजिनेशन और क्लोज बटन होंगे, कोई फाइल बटन नहीं!
    btn = []
    if offset != "":
        btn.append([
            InlineKeyboardButton(text=f"🗓 1/{math.ceil(int(total_results) / MAX_BTN)}", callback_data="buttons"),
            InlineKeyboardButton(text="NEXT ⏩", callback_data=f"next_{req}_{key}_{offset}")
        ])
    
    btn.append([InlineKeyboardButton("🙅 क्लोज़", callback_data=f"close#{req}")])
    
    cap = f"<b>✅ सर्च रिजल्ट्स:- {search}\n🎬 कुल {total_results} फाइलें मिलीं 👇</b>{files_link}"
    await s.edit_text(
        text=cap, 
        reply_markup=InlineKeyboardMarkup(btn), 
        disable_web_page_preview=True, 
        parse_mode=enums.ParseMode.HTML
    )


@Client.on_callback_query(filters.regex(r"^next"))
async def next_page(bot, query):
    """नेक्स्ट और बैक पेजिनेशन हैंडलर (Text Mode Results)"""
    ident, req, key, offset = query.data.split("_")
    if int(req) != query.from_user.id:
        return await query.answer("यह आपके लिए नहीं है! ❌", show_alert=True)
        
    search = BUTTONS.get(key)
    if not search:
        return await query.answer("कृपया दोबारा नया नाम लिखकर सर्च करें! 🔄", show_alert=True)

    files, n_offset, total = await get_search_results(search, offset=int(offset))
    if not files:
        return

    # पेजिनेशन के लिए टेक्स्ट लिंक्स का निर्माण
    files_link = ""
    for file in files:
        files_link += f"\n\n📁 <a href='https://t.me/{temp.U_NAME}?start=file_{file.file_id}'>[{get_size(file.file_size)}] {file.file_name}</a>"
        
    current_page = math.ceil(int(offset) / MAX_BTN) + 1
    total_pages = math.ceil(total / MAX_BTN)

    p_buttons = []
    if int(offset) > 0:
        p_buttons.append(InlineKeyboardButton("⏪ BACK", callback_data=f"next_{req}_{key}_{max(0, int(offset)-MAX_BTN)}"))
    
    p_buttons.append(InlineKeyboardButton(f"🗓 {current_page}/{total_pages}", callback_data="buttons"))
    
    if n_offset != "":
        p_buttons.append(InlineKeyboardButton("NEXT ⏩", callback_data=f"next_{req}_{key}_{n_offset}"))
        
    btn = [p_buttons, [InlineKeyboardButton("🙅 क्लोज़", callback_data=f"close#{req}")]]
    
    cap = f"<b>✅ सर्च रिजल्ट्स:- {search}\n🎬 कुल {total} फाइलें मिलीं 👇</b>{files_link}"
    await query.message.edit_text(
        text=cap, 
        reply_markup=InlineKeyboardMarkup(btn), 
        disable_web_page_preview=True, 
        parse_mode=enums.ParseMode.HTML
    )


@Client.on_callback_query()
async def cb_handler(client: Client, query: CallbackQuery):
    """सभी आवश्यक एडमिन कॉलबैक क्लिक्स को हैंडल करने का सिंगल क्लीन फंक्शन"""
    data = query.data
    user_id = query.from_user.id

    # --- 🚀 लाइव स्ट्रीमिंग कनवर्टर (Convert to Integer Link on Click) ---
    if data.startswith("stream"):
        file_id = data.split('#', 1)[1]
        await query.answer("स्ट्रीमिंग लिंक्स जनरेट हो रही हैं... ⏱️")
        
        # फाइल को BIN_CHANNEL में भेजकर फ्रेश इंटीजर message_id प्राप्त करें
        msg = await client.send_cached_media(chat_id=BIN_CHANNEL, file_id=file_id)
        
        watch = f"{URL}watch/{msg.id}"
        download = f"{URL}download/{msg.id}"
        
        # बटन को तुरंत लाइव स्ट्रीम लिंक्स के साथ बदलें
        btn = [[
            InlineKeyboardButton("⚡ Watch Online", url=watch),
            InlineKeyboardButton("🚀 Fast Download", url=download)
        ], [
            InlineKeyboardButton('🙅 क्लोज़', callback_data='close_data')
        ]]
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(btn))

    elif data.startswith("close"):
        _, req = data.split("#")
        if int(req) == user_id:
            await query.message.delete()
        else:
            await query.answer("यह आपके लिए नहीं है! ❌", show_alert=True)

    elif data == "close_data":
        await query.message.delete()

    elif data == "buttons":
        await query.answer("⚙️", show_alert=False)
