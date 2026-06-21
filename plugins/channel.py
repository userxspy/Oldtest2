from hydrogram import Client, filters
from info import INDEX_CHANNELS
from database.ia_filterdb import save_file

# सिर्फ डॉक्यूमेंट, वीडियो और ऑडियो फाइल्स को ही कैप्चर करेंगे
MEDIA_FILTER = filters.document | filters.video | filters.audio

@Client.on_message(filters.chat(INDEX_CHANNELS) & MEDIA_FILTER & filters.incoming)
async def auto_channel_indexer(bot, message):
    """इंडेक्स चैनल्स में आने वाली नई फाइल्स को ऑटोमैटिकली डेटाबेस में लाइव सेव करने का इंजन"""
    # मैसेज में से असली मीडिया टाइप को ढूंढें
    media = message.document or message.video or message.audio
    if not media:
        return

    # कैप्शन अटैच करें और बिना किसी वैलीडेशन ओवरहेड के सीधे मोटर ड्राइवर से सेव करें
    media.caption = message.caption or ""
    await save_file(media)
