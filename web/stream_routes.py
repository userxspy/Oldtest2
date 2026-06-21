import math
import secrets
import mimetypes
from urllib.parse import quote
from info import BIN_CHANNEL
from utils import temp
from aiohttp import web
from web.utils.custom_dl import TGCustomYield, chunk_size, offset_fix
from web.utils.render_template import media_watch

routes = web.RouteTableDef()

# --- 1. style.css का स्टेटिक रूट फिक्स ---
# यह 'static' फोल्डर को वेब सर्वर पर मैप करेगा ताकि सीएसएस और इमेजेस प्लेयर में सही से लोड हों
try:
    routes.static('/static', './web/static')
except Exception:
    pass

@routes.get("/", allow_head=True)
async def root_route_handler(request):
    """बॉट के मेन डोमेन का रूट यूआरएल"""
    return web.Response(text='<h1 align="center"><b>🤖 Admin-Only Stream Server Live</b></h1>', content_type='text/html')


@routes.get("/watch/{message_id}")
async def watch_handler(request):
    """ऑनलाइन वीडियो प्लेयर (Watch Engine) रूट"""
    try:
        message_id = int(request.match_info['message_id'])
        return web.Response(text=await media_watch(message_id), content_type='text/html')
    except Exception as e:
        print(f"Watch Handler Error: {e}")
        return web.Response(text="<h1>Something went wrong inside Watch Engine</h1>", content_type='text/html')


@routes.get("/download/{message_id}")
async def download_handler(request):
    """फास्ट डाउनलोड (Direct Download Link) रूट"""
    try:
        message_id = int(request.match_info['message_id'])
        return await media_download(request, message_id)
    except Exception as e:
        print(f"Download Handler Error: {e}")
        return web.Response(text="<h1>Something went wrong inside Download Engine</h1>", content_type='text/html')
        

async def media_download(request, message_id: int):
    """टेलीग्राम से वीएलसी/एमएक्स प्लेयर में हाई-स्पीड डाटा चंक्स स्ट्रीम और डाउनलोड करने का कोर लॉजिक"""
    range_header = request.headers.get('Range', 0)
    media_msg = await temp.BOT.get_messages(BIN_CHANNEL, message_id)
    file_properties = await TGCustomYield().generate_file_properties(media_msg)
    file_size = file_properties.file_size

    if range_header:
        from_bytes, until_bytes = range_header.replace('bytes=', '').split('-')
        from_bytes = int(from_bytes)
        until_bytes = int(until_bytes) if until_bytes else file_size - 1
    else:
        from_bytes = request.http_range.start or 0
        until_bytes = request.http_range.stop or file_size - 1

    req_length = until_bytes - from_bytes

    new_chunk_size = await chunk_size(req_length)
    offset = await offset_fix(from_bytes, new_chunk_size)
    first_part_cut = from_bytes - offset
    last_part_cut = (until_bytes % new_chunk_size) + 1
    part_count = math.ceil(req_length / new_chunk_size)
    body = TGCustomYield().yield_file(media_msg, offset, first_part_cut, last_part_cut, part_count, new_chunk_size)

    file_name = file_properties.file_name if file_properties.file_name else f"{secrets.token_hex(2)}.mp4"
    mime_type = file_properties.mime_type if file_properties.mime_type else mimetypes.guess_type(file_name)[0] or 'application/octet-stream'

    # --- 2. % सिंबल और स्पेशल कैरेक्टर्स क्रैश फिक्स ---
    # urllib.parse.quote का उपयोग करके यूआरएल-सेफ नाम बनाएं और RFC 5987 स्टैंडर्ड हेडर लागू करें
    safe_file_name = quote(file_name)

    headers = {
        "Content-Type": mime_type,
        "Content-Range": f"bytes {from_bytes}-{until_bytes}/{file_size}",
        "Content-Disposition": f"attachment; filename=\"{file_name}\"; filename*=UTF-8''{safe_file_name}",
        "Accept-Ranges": "bytes",
    }

    return_resp = web.Response(
        status=206 if range_header else 200,
        body=body,
        headers=headers
    )

    if return_resp.status == 200:
        return_resp.headers.add("Content-Length", str(file_size))

    return return_resp
