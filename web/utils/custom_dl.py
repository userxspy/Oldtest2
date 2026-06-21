import math
from typing import Union
from hydrogram.types import Message
from hydrogram import Client, utils, raw
from hydrogram.session import Session, Auth
from hydrogram.errors import AuthBytesInvalid
from hydrogram.file_id import FileId, FileType, ThumbnailSource
from utils import temp

async def chunk_size(length):
    """बाइट साइज के आधार पर ऑप्टिमाइज्ड डेटा चंक साइज की गणना"""
    return 2 ** max(min(math.ceil(math.log2(length / 1024)), 10), 2) * 1024

async def offset_fix(offset, chunksize):
    """बाइट ऑफसेट को फिक्स करने का मेथड"""
    offset -= offset % chunksize
    return offset

class TGCustomYield:
    def __init__(self):
        """टेलीग्राम सर्वर से डायरेक्ट मीडिया चंक्स फेच करके वीडियो स्ट्रीम करने का इंजन"""
        self.main_bot = temp.BOT

    @staticmethod
    async def generate_file_properties(msg: Message):
        """मैसेज से फ़ाइल आईडी डीकोड करना और प्रॉपर्टीज सेट करना"""
        media = getattr(msg, msg.media.value, None)
        file_id_obj = FileId.decode(media.file_id)

        # Routes के क्रैश को रोकने के लिए एट्रिब्यूट्स सेट करें
        setattr(file_id_obj, "file_size", getattr(media, "file_size", 0))
        setattr(file_id_obj, "mime_type", getattr(media, "mime_type", ""))
        setattr(file_id_obj, "file_name", getattr(media, "file_name", ""))

        return file_id_obj

    async def generate_media_session(self, client: Client, msg: Message):
        """Hydrogram के अनुसार मीडिया डेटा सेंटर (DC) सत्र उत्पन्न करना"""
        data = await self.generate_file_properties(msg)
        media_session = client.media_sessions.get(data.dc_id, None)

        if media_session is None:
            # Hydrogram स्टोरेज और टेस्ट मोड कम्पैटिबिलिटी फिक्स
            is_test_mode = await client.storage.test_mode()
            if data.dc_id != await client.storage.dc_id():
                media_session = Session(
                    client, data.dc_id, await Auth(client, data.dc_id, is_test_mode).create(),
                    is_test_mode, is_media=True
                )
                await media_session.start()

                for _ in range(3):
                    exported_auth = await client.invoke(
                        raw.functions.auth.ExportAuthorization(dc_id=data.dc_id)
                    )
                    try:
                        await media_session.send(
                            raw.functions.auth.ImportAuthorization(
                                id=exported_auth.id,
                                bytes=exported_auth.bytes
                            )
                        )
                    except AuthBytesInvalid:
                        continue
                    else:
                        break
                else:
                    await media_session.stop()
                    raise AuthBytesInvalid
            else:
                media_session = Session(
                    client, data.dc_id, await client.storage.auth_key(),
                    is_test_mode, is_media=True
                )
                await media_session.start()

            client.media_sessions[data.dc_id] = media_session

        return media_session

    @staticmethod
    async def get_location(file_id: FileId):
        """फ़ाइल आईडी के आधार पर टेलीग्राम का इनपुट फ़ाइल लोकेशन ऑब्जेक्ट जनरेट करना"""
        file_type = file_id.file_type

        if file_type == FileType.CHAT_PHOTO:
            if file_id.chat_id > 0:
                peer = raw.types.InputPeerUser(
                    user_id=file_id.chat_id,
                    access_hash=file_id.chat_access_hash
                )
            else:
                if file_id.chat_access_hash == 0:
                    peer = raw.types.InputPeerChat(chat_id=-file_id.chat_id)
                else:
                    peer = raw.types.InputPeerChannel(
                        channel_id=utils.get_channel_id(file_id.chat_id),
                        access_hash=file_id.chat_access_hash
                    )
            location = raw.types.InputPeerPhotoFileLocation(
                peer=peer,
                volume_id=file_id.volume_id,
                local_id=file_id.local_id,
                big=file_id.thumbnail_source == ThumbnailSource.CHAT_PHOTO_BIG
            )
        elif file_type == FileType.PHOTO:
            location = raw.types.InputPhotoFileLocation(
                id=file_id.media_id,
                access_hash=file_id.access_hash,
                file_reference=file_id.file_reference,
                thumb_size=file_id.thumbnail_size
            )
        else:
            location = raw.types.InputDocumentFileLocation(
                id=file_id.media_id,
                access_hash=file_id.access_hash,
                file_reference=file_id.file_reference,
                thumb_size=file_id.thumbnail_size
            )
        return location

    async def yield_file(self, media_msg: Message, offset: int, first_part_cut: int,
                         last_part_cut: int, part_count: int, chunk_size: int) -> Union[bytes, None]:
        """टेलीग्राम सर्वर से डेटा पैकेट्स (Bytes) रीड करके प्लेयर को लाइव स्ट्रीम यील्ड करना"""
        client = self.main_bot
        data = await self.generate_file_properties(media_msg)
        media_session = await self.generate_media_session(client, media_msg)

        current_part = 1
        location = await self.get_location(data)

        r = await media_session.send(
            raw.functions.upload.GetFile(
                location=location,
                offset=offset,
                limit=chunk_size
            ),
        )

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

                r = await media_session.send(
                    raw.functions.upload.GetFile(
                        location=location,
                        offset=offset,
                        limit=chunk_size
                    ),
                )
                current_part += 1
