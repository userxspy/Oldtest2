import re
import time
import asyncio
from hydrogram import Client, filters, enums
from hydrogram.errors import FloodWait
from info import ADMINS
from database.ia_filterdb import save_file
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from utils import temp, get_readable_time

lock = asyncio.Lock()

@Client.on_callback_query(filters.regex(r'^index'))
async def index_files(bot, query):
    """चैनल इंडेक्सिंग शुरू करने या रद्द करने का कॉलबैक हैंडलर"""
    data_parts = query.data.split("#")
    ident = data_parts[1]
    chat_id = data_parts[2]
    
    # मोंगोडीबी इंडेक्स क्रेडेंशियल्स पार्सिंग
    try:
        chat = int(chat_id)
    except ValueError:
        chat = chat_id

    if ident == 'yes':
        lst_msg_id = int(data_parts[3])
        skip = int(data_parts[4])
        msg = query.message
        await msg.edit("<b>चैनल इंडेक्सिंग शुरू हो रही है... ⏱️</b>")
        await index_files_to_db(lst_msg_id, chat, msg, bot, skip)
        
    elif ident == 'cancel':
        # ग्लोबल ओवरलैप से बचने के लिए विशिष्ट सेट ऑब्जेक्ट में चैट आईडी जोड़ें
        if not hasattr(temp, 'INDEX_CANCEL'):
            temp.INDEX_CANCEL = set()
        temp.INDEX_CANCEL.add(str(chat))
        await query.message.edit("<b>प्रोग्रेस: इंडेक्सिंग को रद्द (Cancel) किया जा रहा है... 🛑</b>")

@Client.on_message(filters.forwarded & filters.private & filters.incoming & filters.user(ADMINS))
async def send_for_index(bot, message):
    """फॉरवर्डेड मैसेज या टेलीग्राम लिंक से इंडेक्सिंग ट्रिगर करने का एडमिन कमांड"""
    if lock.locked():
        return await message.reply('<b>कृपया पिछला इंडेक्सिंग टास्क पूरा होने तक प्रतीक्षा करें! ❌</b>')
        
    msg = message
    if msg.text and msg.text.startswith("https://t.me"):
        try:
            msg_link = msg.text.split("/")
            last_msg_id = int(msg_link[-1])
            chat_id = msg_link[-2]
            if chat_id.isnumeric():
                chat_id = int(("-100" + chat_id))
        except Exception:
            return await message.reply('<b>अवैध संदेश लिंक (Invalid Link)! ❌</b>')
    elif msg.forward_from_chat and msg.forward_from_chat.type == enums.ChatType.CHANNEL:
        last_msg_id = msg.forward_from_message_id
        chat_id = msg.forward_from_chat.username or msg.forward_from_chat.id
    else:
        return await message.reply('<b>यह कोई फॉरवर्डेड संदेश या वैध चैनल लिंक नहीं है! 📂</b>')

    try:
        chat = await bot.get_chat(chat_id)
    except Exception as e:
        return await message.reply(f'<b>त्रुटि (Error): {e}</b>')

    if chat.type != enums.ChatType.CHANNEL:
        return await message.reply("<b>मैं केवल टेलीग्राम चैनल्स को ही इंडेक्स कर सकता हूँ! 📣</b>")

    # pyromod (bot.listen) का उपयोग करके स्किप नंबर इनपुट लें
    s = await message.reply("<b>कितने संदेश स्किप करने हैं? (संख्या भेजें, उदा: 0):</b>")
    try:
        input_msg = await bot.listen(chat_id=message.chat.id, user_id=message.from_user.id, timeout=300)
        skip = int(input_msg.text)
        await s.delete()
    except asyncio.TimeoutError:
        await s.delete()
        return await message.reply("<b>समय समाप्त (Timeout)! कृपया पुनः प्रयास करें। ⏱️</b>")
    except ValueError:
        await s.delete()
        return await message.reply("<b>अवैध संख्या! इंडेक्सिंग रद्द की गई। ❌</b>")

    buttons = [
        [InlineKeyboardButton('✅ हाँ, शुरू करें', callback_data=f'index#yes#{chat_id}#{last_msg_id}#{skip}')],
        [InlineKeyboardButton('❌ बंद करें', callback_data='close_data')]
    ]
    await message.reply(
        f'<b>क्या आप <u>{chat.title}</u> चैनल को इंडेक्स करना चाहते हैं?\n📊 कुल मैसेजेस: <code>{last_msg_id}</code>\n⏩ स्किप संख्या: <code>{skip}</code></b>', 
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def index_files_to_db(lst_msg_id, chat, msg, bot, skip):
    """बिना किसी लैग के फाइल्स को डेटाबेस में सेव करने का मुख्य लूप"""
    start_time = time.time()
    total_files = 0
    duplicate = 0
    errors = 0
    deleted = 0
    no_media = 0
    unsupported = 0
    current = skip
    
    # सुनिश्चित करें कि INDEX_CANCEL सेट पहले से उपलब्ध है
    if not hasattr(temp, 'INDEX_CANCEL'):
        temp.INDEX_CANCEL = set()

    async with lock:
        try:
            # hydrogram का ऑप्टिमाइज्ड iter_messages लूप
            async for message in bot.iter_messages(chat, lst_msg_id, skip):
                time_taken = get_readable_time(time.time() - start_time)
                
                # विशिष्ट चैनल आईडी के आधार पर कैंसिलेशन चेक करें (No Global State Interruption Bug)
                if str(chat) in temp.INDEX_CANCEL:
                    temp.INDEX_CANCEL.remove(str(chat))
                    await msg.edit_text(
                        f"<b>🛑 सफलतापूर्वक रद्द किया गया (Cancelled)!</b>\n\n"
                        f"⏳ समय लगा: {time_taken}\n"
                        f"📂 कुल सेव्ड फ़ाइलें: <code>{total_files}</code>\n"
                        f"♻️ डुप्लीकेट स्किप्ड: <code>{duplicate}</code>\n"
                        f"🗑️ डिलीटेड स्किप्ड: <code>{deleted}</code>\n"
                        f"❌ नॉन-मीडिया स्किप्ड: <code>{no_media + unsupported}</code>\n"
                        f"⚠️ एरर्स (Errors): <code>{errors}</code>"
                    )
                    return

                current += 1
                
                # हर 30 मैसेज प्रोसेस होने पर प्रोग्रेस अपडेट करें
                if current % 30 == 0:
                    btn = [[InlineKeyboardButton('🛑 इंडेक्सिंग रोकें (CANCEL)', callback_data=f'index#cancel#{chat}#{lst_msg_id}#{skip}')]]
                    try:
                        await msg.edit_text(
                            text=f"<b>📊 इंडेक्सिंग प्रोग्रेस रिपोर्ट:</b>\n\n"
                                 f"🔹 कुल प्राप्त मैसेजेस: <code>{current}</code>\n"
                                 f"📥 कुल सेव्ड फ़ाइलें: <code>{total_files}</code>\n"
                                 f"♻️ डुप्लीकेट स्किप्ड: <code>{duplicate}</code>\n"
                                 f"🗑️ डिलीटेड स्किप्ड: <code>{deleted}</code>\n"
                                 f"⚠️ एरर्स (Errors): <code>{errors}</code>", 
                            reply_markup=InlineKeyboardMarkup(btn)
                        )
                    except FloodWait as e:
                        await asyncio.sleep(e.value)
                    except Exception:
                        pass

                # मीडिया वेरिफिकेशन फिल्टर्स
                if message.empty:
                    deleted += 1
                    continue
                elif not message.media:
                    no_media += 1
                    continue
                elif message.media not in [enums.MessageMediaType.VIDEO, enums.MessageMediaType.DOCUMENT]:
                    unsupported += 1
                    continue

                media = getattr(message, message.media.value, None)
                if not media:
                    unsupported += 1
                    continue

                media.caption = message.caption
                
                # बिना किसी umongo ओवरहेड के सीधे मोंगोडीबी में हाई-स्पीड सेव
                sts = await save_file(media)
                if sts == 'suc':
                    total_files += 1
                elif sts == 'dup':
                    duplicate += 1
                elif sts == 'err':
                    errors += 1

        except Exception as e:
            await msg.reply(f'<b>❌ एरर के कारण इंडेक्स टास्क बाधित हुआ:</b>\n<code>{e}</code>')
        else:
            time_taken = get_readable_time(time.time() - start_time)
            await msg.edit_text(
                f"<b>✅ चैनल सफलतापूर्वक इंडेक्स हो गया है!</b>\n\n"
                f"⏳ कुल समय लगा: {time_taken}\n"
                f"📥 डेटाबेस में सेव फ़ाइलें: <code>{total_files}</code>\n"
                f"♻️ डुप्लीकेट स्किप्ड: <code>{duplicate}</code>\n"
                f"🗑️ डिलीटेड स्किप्ड: <code>{deleted}</code>\n"
                f"❌ नॉन-मीडिया स्किप्ड: <code>{no_media + unsupported}</code>\n"
                f"⚠️ कुल एरर्स: <code>{errors}</code>"
            )
