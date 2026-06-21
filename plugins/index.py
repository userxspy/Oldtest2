import re
import time
import asyncio
from hydrogram import Client, filters, enums
from hydrogram.errors import FloodWait
from hydrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from info import ADMINS
from database.ia_filterdb import save_file
from utils import temp, get_readable_time

lock = asyncio.Lock()

@Client.on_callback_query(filters.regex(r'^index'))
async def index_files(bot, query):
    """Callback handler to start or cancel channel indexing tasks"""
    data_parts = query.data.split("#")
    ident = data_parts[1]
    chat_id = data_parts[2]
    
    try:
        chat = int(chat_id)
    except ValueError:
        chat = chat_id

    if ident == 'yes':
        lst_msg_id = int(data_parts[3])
        skip = int(data_parts[4])
        msg = query.message
        await msg.edit("<b>Channel indexing is starting... ⏱️</b>")
        await index_files_to_db(lst_msg_id, chat, msg, bot, skip)
        
    elif ident == 'cancel':
        if not hasattr(temp, 'INDEX_CANCEL'):
            temp.INDEX_CANCEL = set()
        temp.INDEX_CANCEL.add(str(chat))
        await query.message.edit("<b>Progress: Canceling the indexing task... 🛑</b>")

@Client.on_message(filters.forwarded & filters.private & filters.incoming & filters.user(ADMINS))
async def send_for_index(bot, message):
    """Triggers indexing from a forwarded message or a valid telegram link"""
    if lock.locked():
        return await message.reply('<b>Please wait until the previous indexing task is completed! ❌</b>')
        
    msg = message
    if msg.text and msg.text.startswith("https://t.me"):
        try:
            msg_link = msg.text.split("/")
            last_msg_id = int(msg_link[-1])
            chat_id = msg_link[-2]
            if chat_id.isnumeric():
                chat_id = int(("-100" + chat_id))
        except Exception:
            return await message.reply('<b>Invalid message link! ❌</b>')
    elif msg.forward_from_chat and msg.forward_from_chat.type == enums.ChatType.CHANNEL:
        last_msg_id = msg.forward_from_message_id
        chat_id = msg.forward_from_chat.username or msg.forward_from_chat.id
    else:
        return await message.reply('<b>This is not a forwarded message or a valid channel link! 📂</b>')

    try:
        chat = await bot.get_chat(chat_id)
    except Exception as e:
        return await message.reply(f'<b>Error: {e}</b>')

    if chat.type != enums.ChatType.CHANNEL:
        return await message.reply("<b>I can only index Telegram channels! 📣</b>")

    s = await message.reply("<b>How many messages do you want to skip? (Send a number, e.g., 0):</b>")
    try:
        input_msg = await bot.listen(chat_id=message.chat.id, user_id=message.from_user.id, timeout=300)
        skip = int(input_msg.text)
        await s.delete()
    except asyncio.TimeoutError:
        await s.delete()
        return await message.reply("<b>Timeout! Please try again. ⏱️</b>")
    except ValueError:
        await s.delete()
        return await message.reply("<b>Invalid number! Indexing canceled. ❌</b>")

    buttons = [
        [InlineKeyboardButton('✅ Yes, Start', callback_data=f'index#yes#{chat_id}#{last_msg_id}#{skip}')],
        [InlineKeyboardButton('❌ Close', callback_data='close_data')]
    ]
    await message.reply(
        f'<b>Do you want to index the channel <u>{chat.title}</u>?\n📊 Total Messages: <code>{last_msg_id}</code>\n⏩ Skip Count: <code>{skip}</code></b>', 
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def index_files_to_db(lst_msg_id, chat, msg, bot, skip):
    """Core optimization loop to parse and save files to MongoDB without lag"""
    start_time = time.time()
    total_files = 0
    duplicate = 0
    errors = 0
    deleted = 0
    no_media = 0
    unsupported = 0
    current = skip
    
    if not hasattr(temp, 'INDEX_CANCEL'):
        temp.INDEX_CANCEL = set()

    async with lock:
        try:
            async for message in bot.iter_messages(chat, lst_msg_id, skip):
                time_taken = get_readable_time(time.time() - start_time)
                
                if str(chat) in temp.INDEX_CANCEL:
                    temp.INDEX_CANCEL.remove(str(chat))
                    await msg.edit_text(
                        f"<b>🛑 Indexing Task Cancelled Successfully!</b>\n\n"
                        f"⏳ Time Taken: {time_taken}\n"
                        f"📂 Total Saved Files: <code>{total_files}</code>\n"
                        f"♻️ Duplicates Skipped: <code>{duplicate}</code>\n"
                        f"🗑️ Deleted Skipped: <code>{deleted}</code>\n"
                        f"❌ Non-Media Skipped: <code>{no_media + unsupported}</code>\n"
                        f"⚠️ Errors: <code>{errors}</code>"
                    )
                    return

                current += 1
                
                if current % 30 == 0:
                    btn = [[InlineKeyboardButton('🛑 STOP INDEXING (CANCEL)', callback_data=f'index#cancel#{chat}#{lst_msg_id}#{skip}')]]
                    try:
                        await msg.edit_text(
                            text=f"<b>📊 Indexing Progress Report:</b>\n\n"
                                 f"🔹 Total Processed Messages: <code>{current}</code>\n"
                                 f"📥 Total Saved Files: <code>{total_files}</code>\n"
                                 f"♻️ Duplicates Skipped: <code>{duplicate}</code>\n"
                                 f"🗑️ Deleted Skipped: <code>{deleted}</code>\n"
                                 f"⚠️ Errors: <code>{errors}</code>", 
                            reply_markup=InlineKeyboardMarkup(btn)
                        )
                    except FloodWait as e:
                        await asyncio.sleep(e.value)
                    except Exception:
                        pass

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
                
                sts = await save_file(media)
                if sts == 'suc':
                    total_files += 1
                elif sts == 'dup':
                    duplicate += 1
                elif sts == 'err':
                    errors += 1

        except Exception as e:
            await msg.reply(f'<b>❌ Index task interrupted due to an error:</b>\n<code>{e}</code>')
        else:
            time_taken = get_readable_time(time.time() - start_time)
            await msg.edit_text(
                f"<b>✅ Channel Indexed Successfully!</b>\n\n"
                f"⏳ Total Time Taken: {time_taken}\n"
                f"📥 Files Saved in Database: <code>{total_files}</code>\n"
                f"♻️ Duplicates Skipped: <code>{duplicate}</code>\n"
                f"🗑️ Deleted Skipped: <code>{deleted}</code>\n"
                f"❌ Non-Media Skipped: <code>{no_media + unsupported}</code>\n"
                f"⚠️ Total Errors: <code>{errors}</code>"
            )
