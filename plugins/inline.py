from hydrogram import Client
from hydrogram.enums import emoji # <- hydrogram के अनुसार सही इम्पोर्ट पाथ
from hydrogram.types import InlineQueryResultCachedDocument, InlineQuery
from database.ia_filterdb import get_search_results
from utils import get_size
from info import CACHE_TIME, ADMINS, FILE_CAPTION

cache_time = CACHE_TIME

@Client.on_inline_query()
async def inline_search(bot, query):
    """सिर्फ एडमिंस के लिए इनलाइन क्वेरी के माध्यम से फ़ाइलें खोजने का ऑप्टिमाइज्ड इंजन"""
    # यदि सर्च करने वाला टेलीग्राम यूज़र एडमिन नहीं है, तो रिजल्ट्स नहीं दिखेंगे
    if query.from_user.id not in ADMINS:
        await query.answer(
            results=[],
            cache_time=0,
            switch_pm_text="⚠️ यह बॉट केवल एडमिंस के लिए कॉन्फ़िगर है!",
            switch_pm_parameter="start"
        )
        return

    results = []
    string = query.query.strip()
    offset = int(query.offset or 0)
    
    # अपडेटेड ia_filterdb मेथड के अनुसार फ़ाइलें प्राप्त करें
    files, next_offset, total = await get_search_results(string, offset=offset)

    for file in files:
        f_caption = FILE_CAPTION.format(
            file_name=file.file_name,
            file_size=get_size(file.file_size),
            caption=file.caption
        )
        results.append(
            InlineQueryResultCachedDocument(
                title=file.file_name,
                document_file_id=file.file_id,
                caption=f_caption,
                description=f'साइज: {get_size(file.file_size)}'
            )
        )

    if results:
        switch_pm_text = f"{emoji.FILE_FOLDER} कुल रिजल्ट्स - {total}"
        if string:
            switch_pm_text += f' (कीवर्ड: {string})'
        
        await query.answer(
            results=results,
            is_personal=True,
            cache_time=cache_time,
            switch_pm_text=switch_pm_text,
            switch_pm_parameter="start",
            next_offset=str(next_offset)
        )
    else:
        switch_pm_text = f'{emoji.CROSS_MARK} कोई रिजल्ट नहीं मिला!'
        if string:
            switch_pm_text += f' (कीवर्ड: {string})'
            
        await query.answer(
            results=[],
            is_personal=True,
            cache_time=cache_time,
            switch_pm_text=switch_pm_text,
            switch_pm_parameter="start"
        )
