import os
import time
import random
import asyncio
from hydrogram import Client, filters, enums
from hydrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from Script import script
from info import ADMINS, INDEX_CHANNELS, LOG_CHANNEL, PICS, REACTIONS, BIN_CHANNEL, URL
from utils import get_size, temp, get_readable_time, get_wish
from database.ia_filterdb import Media, get_file_details, delete_files

@Client.on_message(filters.command("start") & filters.incoming)
async def start(client, message):
    """Basic live status and start handler for admins only"""
    if message.from_user.id not in ADMINS:
        return  # Bot remains completely silent for non-admins

    try:
        await message.react(emoji=random.choice(REACTIONS), big=True)
    except Exception:
        await message.react(emoji="⚡️", big=True)

    mc = message.command[1] if len(message.command) == 2 else None

    # If admin comes via clickable text mode link from PM search
    if mc:
        if mc.startswith("file") or mc.startswith("all"):
            try:
                # Extract file ID directly from the deep link URL parameter
                _, file_id = mc.split("_", 1)
            except ValueError:
                return await message.reply("Invalid Link! ❌")

            file_details = await get_file_details(file_id)
            if not file_details:
                return await message.reply("File not found in database! 😕")
                
            file = file_details[0]
            cap = script.FILE_CAPTION.format(file_name=file.file_name)
            
            # Replaced direct streaming links with the premium dynamic converter button
            btn = [[
                InlineKeyboardButton("🚀 Watch And Download ⚡", callback_data=f"stream#{file.file_id}")
            ], [
                InlineKeyboardButton("🙅 Close", callback_data="close_data")
            ]]
            
            await client.send_cached_media(
                chat_id=message.from_user.id, 
                file_id=file.file_id, 
                caption=cap, 
                reply_markup=InlineKeyboardMarkup(btn)
            )
            return

    # Normal /start command UI response
    buttons = [
        [InlineKeyboardButton("⚙️ Commands List", callback_data="help")],
        [InlineKeyboardButton("🦹 About Us", callback_data="about")]
    ]
    await message.reply_photo(
        photo=random.choice(PICS),
        caption=script.START_TXT.format(message.from_user.mention, get_wish()),
        reply_markup=InlineKeyboardMarkup(buttons)
    )

@Client.on_message(filters.command('index_channels') & filters.incoming)
async def channels_info(bot, message):
    """Checks the live connection status of all indexed channels"""
    if message.from_user.id not in ADMINS:
        return

    if not INDEX_CHANNELS:
        return await message.reply("INDEX_CHANNELS is not configured! ⚙️")
        
    text = '<b>📂 Indexed Channels:</b>\n\n'
    for id in INDEX_CHANNELS:
        try:
            chat = await bot.get_chat(id)
            text += f'🔹 {chat.title} (<code>{id}</code>)\n'
        except Exception:
            text += f'❌ {id} (Channel not found / Bot is not admin)\n'
    text += f'\n<b>📊 Total Channels: {len(INDEX_CHANNELS)}</b>'
    await message.reply(text)

@Client.on_message(filters.command('stats') & filters.incoming)
async def stats(bot, message):
    """Displays live database size, document counts, and current bot uptime"""
    if message.from_user.id not in ADMINS:
        return

    try:
        await message.react(emoji=random.choice(REACTIONS), big=True)
    except Exception:
        await message.react(emoji="⚡️", big=True)

    files = await Media.count_documents()
    admins_count = len(ADMINS)
    uptime = get_readable_time(time.time() - temp.START_TIME)
    
    # MongoDB storage calculation statistics
    from database.users_chats_db import db
    u_size = get_size(await db.get_db_size())
    f_size = get_size(max(0, 536870912 - await db.get_db_size()))

    await message.reply_text(script.STATUS_TXT.format(files, admins_count, u_size, f_size, uptime))

@Client.on_message(filters.command('delete') & filters.incoming)
async def delete_file(bot, message):
    """Admin panel to safely delete specific files using matching keywords"""
    if message.from_user.id not in ADMINS:
        return

    try:
        query = message.text.split(" ", 1)[1].strip()
    except IndexError:
        return await message.reply_text("<b>Command Incomplete!\nUsage: <code>/delete keyword</code></b>")
        
    msg = await message.reply_text('Searching... ⏱️')
    total, _ = await delete_files(query)
    
    if int(total) == 0:
        return await msg.edit('No files found in the database with this keyword! ❌')
        
    btn = [
        [InlineKeyboardButton("✅ Yes, Delete", callback_data=f"delete_{query}")],
        [InlineKeyboardButton("❌ Cancel", callback_data="close_data")]
    ]
    await msg.edit(f"🔍 Found total <b>{total}</b> files for your query: <code>{query}</code>.\n\nAre you sure you want to delete them from the database permanently?", reply_markup=InlineKeyboardMarkup(btn))

@Client.on_message(filters.command('delete_all') & filters.incoming)
async def delete_all_index(bot, message):
    """Super-destructive command to clear the entire database collection index"""
    if message.from_user.id not in ADMINS:
        return

    btn = [
        [InlineKeyboardButton("⚠️ Yes, Wipe Entire Database", callback_data="delete_all")],
        [InlineKeyboardButton("❌ Cancel", callback_data="close_data")]
    ]
    files = await Media.count_documents()
    if int(files) == 0:
        return await message.reply_text('Database is already empty! 🗃️')
        
    await message.reply_text(f'❗ <b>Warning:</b> Total <b>{files}</b> files are saved in the database.\nAre you absolutely sure you want to delete the entire database?', reply_markup=InlineKeyboardMarkup(btn))

@Client.on_message(filters.command('ping') & filters.incoming)
async def ping(client, message):
    """Measures the active network latency response speed of the bot"""
    if message.from_user.id not in ADMINS:
        return
        
    start_time = time.monotonic()
    msg = await message.reply("⚡")
    end_time = time.monotonic()
    await msg.edit(f'<b>⏱️ Response Speed: {round((end_time - start_time) * 1000)} ms</b>')

@Client.on_message(filters.command('id') & filters.incoming)
async def showid(client, message):
    """Extracts target user ID or the forwarded channel/chat parameters"""
    if message.from_user.id not in ADMINS:
        return

    if message.reply_to_message:
        reply = message.reply_to_message
        if reply.forward_from_chat:
            return await message.reply_text(f"📣 Forwarded Channel/Chat Name: <b>{reply.forward_from_chat.title}</b>\n🆔 ID: <code>{reply.forward_from_chat.id}</code>")
        elif reply.from_user:
            return await message.reply_text(f"🦹 User: {reply.from_user.mention}\n🆔 ID: <code>{reply.from_user.id}</code>")
            
    await message.reply_text(f'<b>🦹 Your Telegram ID: <code>{message.from_user.id}</code>\n💬 This Private Chat ID: <code>{message.chat.id}</code></b>')
