import urllib.parse
import aiofiles
from info import BIN_CHANNEL, URL
from utils import temp
from web.utils.custom_dl import TGCustomYield

async def media_watch(message_id):
    """HTML प्लेयर टेम्पलेट को बिना किसी नेमिंग क्रैश के लाइव रेंडर करने का इंजन"""
    try:
        # टेलीग्राम के बिन चैनल से मैसेज और फाइल की प्रॉपर्टीज फेच करें
        media_msg = await temp.BOT.get_messages(BIN_CHANNEL, message_id)
        file_properties = await TGCustomYield().generate_file_properties(media_msg)
        file_name, mime_type = file_properties.file_name, file_properties.mime_type
        
        # डायरेक्ट डाउनलोड यूआरएल जनरेट करें
        src = urllib.parse.urljoin(URL, f'download/{message_id}')
        tag = mime_type.split('/')[0].strip()
        
        # केवल वीडियो फाइल्स को ही प्लेयर पेज पर रेंडर होने की अनुमति दें
        if tag == 'video':
            async with aiofiles.open('web/template/watch.html', mode='r', encoding='utf-8') as r:
                template_content = await r.read()
                
                # पुराना % फ़ॉर्मेटिंग हटाकर सुरक्षित .format() लागू किया गया है
                # ध्यान दें: आपकी watch.html में {heading}, {file_name}, {src}, {tag} वेरिएबल्स होने चाहिए
                html = template_content.format(
                    heading=f"Watch - {file_name}",
                    file_name=file_name,
                    src=src,
                    tag=tag
                )
        else:
            html = '<h1 align="center" style="color:red; margin-top:20%;">❌ यह फ़ाइल ऑनलाइन स्ट्रीम करने योग्य नहीं है!</h1>'
            
    except Exception as e:
        print(f"Render Template Error: {e}")
        html = '<h1 align="center" style="color:red; margin-top:20%;">❌ प्लेयर लोड करने में त्रुटि हुई!</h1>'
        
    return html
