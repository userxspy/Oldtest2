import os
import time
import random
import asyncio
import requests
from hydrogram import Client, filters, enums
from hydrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from Script import script
from info import ADMINS, INDEX_CHANNELS, LOG_CHANNEL, PICS, REACTIONS, BIN_CHANNEL, URL
from utils import get_size, temp, get_readable_time, get_wish
from database.ia_filterdb import Media, get_file_details, delete_files

def upload_to_catbox(file_path):
    """कैटबॉक्स (Catbox.moe) पर फाइल अपलोड करने का सुपर-फास्ट मेथड"""
    try:
        url = "https://catbox.moe/user/api.php"
        data = {"reqtype": "fileupload", "userhash": ""}
        with open(file_path, "rb") as f:
            files = {"fileToUpload": f}
            response = requests.post(url, data=data, files=files)
            if response.status_code == 200:
                return response.text
    except Exception as e:
        print(f"Catbox Upload Error: {e}")
    return None

@Client.on_message(filters.command("start") & filters.incoming)
async def start(client, message):
    """सिर्फ एडमिंस के लिए बुनियादी लाइव स्टेटस और स्टार्ट हैंडलर"""
    if message.from_user.id not in ADMINS:
        return # गैर-एडमिंस के लिए बोट पूरी तरह से साइलेंट रहेगा

    try:
        await message.react(emoji=random.choice(REACTIONS), big=True)
    except Exception:
        await message.react(emoji="⚡️", big=True)

    mc = message.command[1] if len(message.command) == 2 else None

    # यदि एडमिन सीधे किसी फाइल लिंक (Text Mode Link) पर क्लिक करके आता है
    if mc:
        if mc.startswith("file") or mc.startswith("all"):
            try:
                # यूआरएल से सीधे फ़ाइल आईडी निकालें
                _, file_id = mc.split("_", 1)
            except ValueError:
                return await message.reply("अवैध लिंक! ❌")

            file_details = await get_file_details(file_id)
            if not file_details:
                return await message.reply("फाइल डेटाबेस में उपलब्ध नहीं है! 😕")
                
            file = file_details[0]
            cap = script.FILE_CAPTION.format(file_name=file.file_name, file_size=get_size(file.file_size))
            
            # --- 🟢 पुराना क्लासिक बटन सेटअप ---
            # सीधे प्लेयर लिंक देने के बजाय '🚀 Watch And Download ⚡' का कन्वर्टर बटन दें
            btn = [[
                InlineKeyboardButton("🚀 Watch And Download ⚡", callback_data=f"stream#{file.file_id}")
            ], [
                InlineKeyboardButton('🙅 क्लोज़', callback_data='close_data')
            ]]
            
            await client.send_cached_media(
                chat_id=message.from_user.id, 
                file_id=file.file_id, 
                caption=cap, 
                reply_markup=InlineKeyboardMarkup(btn)
            )
            return

    # सामान्य /start कमांड का रिपॉन्स
    buttons = [
        [InlineKeyboardButton('⚙️ कमांड्स की सूची (Commands)', callback_data='help')],
        [InlineKeyboardButton('🦹 हमारे बारे में (About)', callback_data='about')]
    ]
    await message.reply_photo(
        photo=random.choice(PICS),
        caption=script.START_TXT.format(message.from_user.mention, get_wish()),
        reply_markup=InlineKeyboardMarkup(buttons)
    )

@Client.on_message(filters.command('index_channels') & filters.incoming)
async def channels_info(bot, message):
    """इंडेक्स किए गए चैनल्स की स्थिति देखने का एडमिन कमांड"""
    if message.from_user.id not in ADMINS:
        return

    if not INDEX_CHANNELS:
        return await message.reply("INDEX_CHANNELS कॉन्फ़िगर नहीं किया गया है! ⚙️")
        
    text = '<b>📂 इंडेक्स किए गए चैनल्स (Indexed Channels):</b>\n\n'
    for id in INDEX_CHANNELS:
        try:
            chat = await bot.get_chat(id)
            text += f'🔹 {chat.title} (<code>{id}</code>)\n'
        except Exception:
            text += f'❌ {id} (चैनल नहीं मिला/बॉट एडमिन नहीं है)\n'
    text += f'\n<b>📊 कुल चैनल्स: {len(INDEX_CHANNELS)}</b>'
    await message.reply(text)

@Client.on_message(filters.command('stats') & filters.incoming)
async def stats(bot, message):
    """लाइव डेटाबेस साइज, फाइल्स काउंट और बॉट अपटाइम की स्थिति"""
    if message.from_user.id not in ADMINS:
        return

    try:
        await message.react(emoji=random.choice(REACTIONS), big=True)
    except Exception:
        await message.react(emoji="⚡️", big=True)

    files = await Media.count_documents()
    admins_count = len(ADMINS)
    uptime = get_readable_time(time.time() - temp.START_TIME)
    
    # मोंगोडीबी फ्री टियर स्टेट्स
    from database.users_chats_db import db
    u_size = get_size(await db.get_db_size())
    f_size = get_size(max(0, 536870912 - await db.get_db_size()))

    await message.reply_text(script.STATUS_TXT.format(files, admins_count, u_size, f_size, uptime))

@Client.on_message(filters.command('delete') & filters.incoming)
async def delete_file(bot, message):
    """कीवर्ड या क्वेरी के माध्यम से विशिष्ट फाइलें डिलीज करने का एडमिन पैनल"""
    if message.from_user.id not in ADMINS:
        return

    try:
        query = message.text.split(" ", 1)[1].strip()
    except IndexError:
        return await message.reply_text("<b>कमांड अधूरा है!\nउपयोग करें: <code>/delete कीवर्ड</code></b>")
        
    msg = await message.reply_text('खोजा जा रहा है... ⏱️')
    total, _ = await delete_files(query)
    
    if int(total) == 0:
        return await msg.edit('डेटाबेस में इस नाम से कोई फाइल नहीं मिली! ❌')
        
    btn = [
        [InlineKeyboardButton("✅ हाँ, डिलीट करें", callback_data=f"delete_{query}")],
        [InlineKeyboardButton("❌ रद्द करें", callback_data="close_data")]
    ]
    await msg.edit(f"🔍 आपकी क्वेरी <code>{query}</code> पर कुल <b>{total}</b> फाइलें मिलीं।\n\nक्या आप सच में इन्हें डेटाबेस से डिलीट करना चाहते हैं?", reply_markup=InlineKeyboardMarkup(btn))

@Client.on_message(filters.command('delete_all') & filters.incoming)
async def delete_all_index(bot, message):
    """पूरे डेटाबेस को एक क्लिक में साफ (Drop Collection) करने का सुपर कमांड"""
    if message.from_user.id not in ADMINS:
        return

    btn = [
        [InlineKeyboardButton("⚠️ हाँ, पूरा डेटाबेस उड़ाएं", callback_data="delete_all")],
        [InlineKeyboardButton("❌ रद्द करें", callback_data="close_data")]
    ]
    files = await Media.count_documents()
    if int(files) == 0:
        return await message.reply_text('डेटाबेस पहले से ही खाली है! 🗃️')
        
    await message.reply_text(f'❗ <b>चेतावनी:</b> डेटाबेस में कुल <b>{files}</b> फाइलें सेव हैं।\nक्या आप सच में पूरा डेटाबेस डिलीट करना चाहते हैं?', reply_markup=InlineKeyboardMarkup(btn))

@Client.on_message(filters.command(['catbox', 'tm', 'telegraph']) & filters.incoming)
async def catbox_uploader(bot, message):
    """200MB तक की मीडिया फाइल को तुरंत कैटबॉक्स यूआरएल में बदलने का फीचर"""
    if message.from_user.id not in ADMINS:
        return

    reply = message.reply_to_message
    if not reply or not (reply.photo or reply.video or reply.document):
        return await message.reply('कृपया किसी फोटो, वीडियो या डॉक्यूमेंट पर रिप्लाई करें! 📂')
        
    file = reply.photo or reply.video or reply.document
    if file.file_size > 209715200:
        return await message.reply_text("<b>फाइल साइज 200MB से कम होना अनिवार्य है! ❌</b>")
        
    status_msg = await message.reply_text("<b>प्रोग्रेस: डाउनलोड किया जा रहा है... ⏱️</b>")
    try:
        path = await reply.download()
    except Exception as e:
        return await status_msg.edit_text(f"डाउनलोड एरर: {e}")

    await status_msg.edit_text("<b>प्रोग्रेस: कैटबॉक्स पर अपलोड किया जा रहा है... 🚀</b>")
    response = upload_to_catbox(path)
    
    try:
        os.remove(path)
    except Exception:
        pass
        
    if response:
        await status_msg.edit_text(f"<b>❤️ आपका कैटबॉक्स लिंक तैयार है 👇</b>\n\n<code>{response.strip()}</code>", disable_web_page_preview=True)
    else:
        await status_msg.edit_text("अपलोड विफल! कृपया पुनः प्रयास करें। ❌")

@Client.on_message(filters.command('ping') & filters.incoming)
async def ping(client, message):
    """बॉट का लाइव नेटवर्क रिस्पॉन्स टाइम (Ping latency) जांचें"""
    if message.from_user.id not in ADMINS:
        return
        
    start_time = time.monotonic()
    msg = await message.reply("⚡")
    end_time = time.monotonic()
    await msg.edit(f'<b>⏱️ रिस्पॉन्स स्पीड: {round((end_time - start_time) * 1000)} ms</b>')

@Client.on_message(filters.command('id') & filters.incoming)
async def showid(client, message):
    """यूज़र आईडी या रिप्लाई किए गए फॉरवर्डेड मैसेज चैनल की आईडी निकालें"""
    if message.from_user.id not in ADMINS:
        return

    if message.reply_to_message:
        reply = message.reply_to_message
        if reply.forward_from_chat:
            return await message.reply_text(f"📣 फॉरवर्डेड चैनल/चैट का नाम: <b>{reply.forward_from_chat.title}</b>\n🆔 आईडी: <code>{reply.forward_from_chat.id}</code>")
        elif reply.from_user:
            return await message.reply_text(f"🦹 यूज़र: {reply.from_user.mention}\n🆔 आईडी: <code>{reply.from_user.id}</code>")
            
    await message.reply_text(f'<b>🦹 आपकी टेलीग्राम आईडी: <code>{message.from_user.id}</code>\n💬 इस प्राइवेट चैट की आईडी: <code>{message.chat.id}</code></b>')
