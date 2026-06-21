import asyncio
import math
from hydrogram import Client, filters, enums
from hydrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from Script import script
from info import ADMINS, MAX_BTN, BIN_CHANNEL, URL
from utils import get_size, temp
from database.ia_filterdb import get_search_results, get_file_details

BUTTONS = {}

@Client.on_message(filters.private & filters.text & filters.incoming & ~filters.regex(r"^/"))
async def pm_search(client, message):
    """Handles movie/file search in PM instantly without intermediate searching status"""
    if message.from_user.id not in ADMINS:
        return  # Bot remains completely silent for non-admins

    search = message.text.strip()
    
    # Fetch results directly from MongoDB first to eliminate intermediate message latency
    files, offset, total_results = await get_search_results(search)
    if not files:
        await message.reply(script.NOT_FILE_TXT.format(message.from_user.mention, search), quote=True)
        return

    req = message.from_user.id
    key = f"{message.chat.id}-{message.id}"
    BUTTONS[key] = search

    # Text mode clickable HTML hyperlinks formation
    files_link = ""
    for file in files:
        files_link += f"\n\n📁 <a href='https://t.me/{temp.U_NAME}?start=file_{file.file_id}'>[{get_size(file.file_size)}] {file.file_name}</a>"

    btn = []
    if offset != "":
        btn.append([
            InlineKeyboardButton(text=f"🗓 1/{math.ceil(int(total_results) / MAX_BTN)}", callback_data="buttons"),
            InlineKeyboardButton(text="NEXT ⏩", callback_data=f"next_{req}_{key}_{offset}")
        ])
    
    btn.append([InlineKeyboardButton("🙅 Close", callback_data=f"close#{req}")])
    
    caption = f"<b>✅ Search Results:- {search}\n🎬 Total {total_results} files found 👇</b>{files_link}"
    
    # Direct reply to ensure lightning fast loading speed
    await message.reply(
        text=caption, 
        reply_markup=InlineKeyboardMarkup(btn), 
        disable_web_page_preview=True, 
        parse_mode=enums.ParseMode.HTML,
        quote=True
    )


@Client.on_callback_query(filters.regex(r"^next"))
async def next_page(bot, query):
    """Handles pagination for Next and Back pages (Text Mode Results)"""
    ident, req, key, offset = query.data.split("_")
    if int(req) != query.from_user.id:
        return await query.answer("This is not for you! ❌", show_alert=True)
        
    search = BUTTONS.get(key)
    if not search:
        return await query.answer("Please search again with a new keyword! 🔄", show_alert=True)

    files, n_offset, total = await get_search_results(search, offset=int(offset))
    if not files:
        return

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
        
    btn = [p_buttons, [InlineKeyboardButton("🙅 Close", callback_data=f"close#{req}")]]
    
    caption = f"<b>✅ Search Results:- {search}\n🎬 Total {total} files found 👇</b>{files_link}"
    await query.message.edit_text(
        text=caption, 
        reply_markup=InlineKeyboardMarkup(btn), 
        disable_web_page_preview=True, 
        parse_mode=enums.ParseMode.HTML
    )


@Client.on_callback_query()
async def cb_handler(client: Client, query: CallbackQuery):
    """Handles all necessary callback clicks securely"""
    data = query.data
    user_id = query.from_user.id

    # On-the-fly streaming converter
    if data.startswith("stream"):
        file_id = data.split('#', 1)[1]
        await query.answer("Generating streaming links... ⏱️")
        
        # Forward file to BIN_CHANNEL to fetch fresh integer message ID
        msg = await client.send_cached_media(chat_id=BIN_CHANNEL, file_id=file_id)
        
        watch = f"{URL}watch/{msg.id}"
        download = f"{URL}download/{msg.id}"
        
        btn = [[
            InlineKeyboardButton("⚡ Watch Online", url=watch),
            InlineKeyboardButton("🚀 Fast Download", url=download)
        ], [
            InlineKeyboardButton("🙅 Close", callback_data="close_data")
        ]]
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(btn))

    # Handled 'close_data' explicitly first to avoid string unpacking value errors
    elif data == "close_data":
        await query.message.delete()

    elif data.startswith("close"):
        _, req = data.split("#")
        if int(req) == user_id:
            await query.message.delete()
        else:
            await query.answer("This is not for you! ❌", show_alert=True)

    elif data == "buttons":
        await query.answer("⚙️", show_alert=False)
