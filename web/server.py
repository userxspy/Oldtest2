import math
import secrets
import mimetypes
import aiofiles
from typing import Union
from urllib.parse import quote
from aiohttp import web

from hydrogram import Client, raw
from hydrogram.session import Session, Auth
from hydrogram.errors import AuthBytesInvalid
from hydrogram.file_id import FileId, FileType
from hydrogram.types import Message

from info import URL, BIN_CHANNEL
from utils import temp

routes = web.RouteTableDef()

# ==========================================
# 🚀 CORE STREAMING & CHUNK YIELDER ENGINE
# ==========================================

async def chunk_size(length):
    return 2 ** max(min(math.ceil(math.log2(length / 1024)), 10), 2) * 1024

async def offset_fix(offset, chunksize):
    offset -= offset % chunksize
    return offset

class TGCustomYield:
    def __init__(self):
        self.client = temp.BOT

    @staticmethod
    async def generate_file_properties(msg: Message):
        """Decodes fresh file IDs and object properties from live Telegram messages"""
        media = msg.document or msg.video or msg.audio
        file_id_obj = FileId.decode(media.file_id)
        
        setattr(file_id_obj, "file_size", getattr(media, "file_size", 0))
        setattr(file_id_obj, "mime_type", getattr(media, "mime_type", ""))
        setattr(file_id_obj, "file_name", getattr(media, "file_name", ""))
        return file_id_obj

    async def generate_media_session(self, client: Client, file_id_obj: FileId):
        media_session = client.media_sessions.get(file_id_obj.dc_id, None)
        if media_session is None:
            is_test_mode = await client.storage.test_mode()
            if file_id_obj.dc_id != await client.storage.dc_id():
                media_session = Session(
                    client, file_id_obj.dc_id, await Auth(client, file_id_obj.dc_id, is_test_mode).create(),
                    is_test_mode, is_media=True
                )
                await media_session.start()
                for _ in range(3):
                    exported_auth = await client.invoke(raw.functions.auth.ExportAuthorization(dc_id=file_id_obj.dc_id))
                    try:
                        await media_session.send(raw.functions.auth.ImportAuthorization(id=exported_auth.id, bytes=exported_auth.bytes))
                    except AuthBytesInvalid:
                        continue
                    else:
                        break
                else:
                    await media_session.stop()
                    raise AuthBytesInvalid
            else:
                media_session = Session(
                    client, file_id_obj.dc_id, await client.storage.auth_key(),
                    is_test_mode, is_media=True
                )
                await media_session.start()
            client.media_sessions[file_id_obj.dc_id] = media_session
        return media_session

    @staticmethod
    async def get_location(file_id: FileId):
        if file_id.file_type == FileType.PHOTO:
            return raw.types.InputPhotoFileLocation(
                id=file_id.media_id, access_hash=file_id.access_hash,
                file_reference=file_id.file_reference, thumb_size=file_id.thumbnail_size
            )
        else:
            return raw.types.InputDocumentFileLocation(
                id=file_id.media_id, access_hash=file_id.access_hash,
                file_reference=file_id.file_reference, thumb_size=file_id.thumbnail_size
            )

    async def yield_file(self, file_id_obj: FileId, offset: int, first_part_cut: int,
                         last_part_cut: int, part_count: int, chunk_size: int) -> Union[bytes, None]:
        media_session = await self.generate_media_session(self.client, file_id_obj)
        current_part = 1
        location = await self.get_location(file_id_obj)

        r = await media_session.send(raw.functions.upload.GetFile(location=location, offset=offset, limit=chunk_size))
        if isinstance(r, raw.types.upload.File):
            while current_part <= part_count:
                chunk = r.bytes
                if not chunk:
                    break
                offset += chunk_size
                if part_count == 1:
                    yield chunk[first_part_cut:last_part_cut]
                    break
                if current_part == 1:
                    yield chunk[first_part_cut:]
                if 1 < current_part <= part_count:
                    yield chunk
                r = await media_session.send(raw.functions.upload.GetFile(location=location, offset=offset, limit=chunk_size))
                current_part += 1

# ==========================================
# 🛠️ HIGH PERFORMANCE ROUTING CONTROLLERS
# ==========================================

@routes.get("/", allow_head=True)
async def root_route_handler(request):
    return web.Response(text='<h1 align="center"><b>🚀 High-Performance Stream Server Active</b></h1>', content_type='text/html')

@routes.get("/watch/{message_id}")
async def watch_handler(request):
    """Renders the custom cinematic video player based on BIN_CHANNEL message ID"""
    try:
        message_id = int(request.match_info['message_id'])
        media_msg = await temp.BOT.get_messages(BIN_CHANNEL, message_id)
        if not media_msg or media_msg.empty:
            return web.Response(text="<h1>This file has been deleted from the server! ❌</h1>", content_type='text/html')

        file_properties = await TGCustomYield.generate_file_properties(media_msg)
        file_name = file_properties.file_name
        src = f"{URL}download/{message_id}"
        mime_type = file_properties.mime_type or 'video/mp4'
        tag = mime_type.split('/')[0].strip()

        if tag == 'video':
            async with aiofiles.open('web/template/watch.html', mode='r', encoding='utf-8') as r:
                template_content = await r.read()
                
            # Fixed: Replaced old {tag} parameter with the required {mime_type} mapping
            html = template_content.format(
                heading=f"Watch - {file_name}",
                file_name=file_name,
                src=src,
                mime_type=mime_type
            )
            return web.Response(text=html, content_type='text/html')
        else:
            return web.Response(text="<h1>This file format is not supported for online streaming! 😕</h1>", content_type='text/html')
    except Exception as e:
        return web.Response(text=f"<h1>Watch Engine Error: {e}</h1>", content_type='text/html')

@routes.get("/download/{message_id}")
async def download_handler(request):
    """Direct high-speed chunk streamer using BIN_CHANNEL fresh references"""
    try:
        message_id = int(request.match_info['message_id'])
        media_msg = await temp.BOT.get_messages(BIN_CHANNEL, message_id)
        if not media_msg or media_msg.empty:
            return web.Response(text="<h1>File not found! ❌</h1>", content_type='text/html')

        file_properties = await TGCustomYield.generate_file_properties(media_msg)
        media_obj = media_msg.document or media_msg.video or media_msg.audio
        file_id_obj = FileId.decode(media_obj.file_id)
        file_size = file_properties.file_size

        range_header = request.headers.get('Range', 0)
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
        
        body = TGCustomYield().yield_file(file_id_obj, offset, first_part_cut, last_part_cut, part_count, new_chunk_size)
        mime_type = file_properties.mime_type or 'application/octet-stream'
        safe_file_name = quote(file_properties.file_name)

        headers = {
            "Content-Type": mime_type,
            "Content-Range": f"bytes {from_bytes}-{until_bytes}/{file_size}",
            "Content-Disposition": f"attachment; filename=\"{file_properties.file_name}\"; filename*=UTF-8''{safe_file_name}",
            "Accept-Ranges": "bytes",
        }
        return web.Response(status=206 if range_header else 200, body=body, headers=headers)
    except Exception as e:
        return web.Response(text=f"<h1>Streaming Core Error: {e}</h1>", content_type='text/html')
