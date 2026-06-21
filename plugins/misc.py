import random
from hydrogram import Client, filters, enums
from info import PICS
from utils import temp

# ==========================================
# 1. ADMIN ONLY - ID FETCHING ENGINE
# ==========================================

@Client.on_message(filters.command('id') & filters.incoming)
async def showid(client, message):
    """यूज़र आईडी, ग्रुप आईडी या फॉरवर्ड किए गए चैनल/मैसेज की आईडी निकालने का कमांड"""
    chat_type = message.chat.type
    
    # 1. यदि किसी मैसेज पर रिप्लाई करके आईडी मांगी गई हो
    if message.reply_to_message:
        reply = message.reply_to_message
        if reply.forward_from_chat:
            return await message.reply_text(
                f"📣 <b>फॉरवर्डेड चैनल/चैट विवरण:</b>\n"
                f"🔹 नाम: <b>{reply.forward_from_chat.title}</b>\n"
                f"🆔 आईडी (ID): <code>{reply.forward_from_chat.id}</code>"
            )
        elif reply.from_user:
            return await message.reply_text(
                f"🦹 <b>यूज़र विवरण:</b>\n"
                f"🔹 नाम: {reply.from_user.mention}\n"
                f"🆔 यूज़र आईडी: <code>{reply.from_user.id}</code>"
            )

    # 2. सामान्य रूप से चैट टाइप के आधार पर आईडी देना
    if chat_type == enums.ChatType.PRIVATE:
        await message.reply_text(f'<b>🦹 आपकी टेलीग्राम आईडी: <code>{message.from_user.id}</code>\n💬 इस प्राइवेट चैट की आईडी: <code>{message.chat.id}</code></b>')

    elif chat_type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        await message.reply_text(f'<b>👫 इस ग्रुप की आईडी (Group ID): <code>{message.chat.id}</code></b>')

    elif chat_type == enums.ChatType.CHANNEL:
        await message.reply_text(f'<b>📣 इस चैनल की आईडी (Channel ID): <code>{message.chat.id}</code></b>')


# ==========================================
# 2. CHAT MEMBER UPDATED HANDLER (No Links)
# ==========================================

@Client.on_chat_member_updated(filters.group)
async def welcome(bot, message):
    """ग्रुप में बॉट के ऐड होने पर क्लीन वेलकम मैसेज भेजना (No Links)"""
    if message.new_chat_member and not message.old_chat_member:
        # यदि बॉट खुद किसी ग्रुप में ऐड हुआ है
        if message.new_chat_member.user.id == temp.ME:
            user = message.from_user.mention if message.from_user else "Dear Owner/Admin"
            
            # बिना किसी बाहरी लिंक्स या बटन्स के सिर्फ एक साधारण फोटो अलर्ट
            await bot.send_photo(
                chat_id=message.chat.id, 
                photo=random.choice(PICS), 
                caption=f"👋 Hello {user},\n\nमुझे <b>'{message.chat.title}'</b> ग्रुप में जोड़ने के लिए धन्यवाद! कृपया मुझे एडमिन (Admin) बना दें ताकि मैं फाइल्स को सही ढंग से फ़िल्टर कर सकूं। 😘"
            )
