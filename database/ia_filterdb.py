import re
import base64
import logging
from struct import pack
from hydrogram.file_id import FileId
from pymongo.errors import DuplicateKeyError
from motor.motor_asyncio import AsyncIOMotorClient
from info import DATABASE_URL, DATABASE_NAME, COLLECTION_NAME, MAX_BTN

# डेटाबेस कनेक्शन सेटअप
client = AsyncIOMotorClient(DATABASE_URL)
db = client[DATABASE_NAME]
col = db[COLLECTION_NAME]

async def ensure_indexes():
    """बॉट स्टार्ट होते ही मोंगोडीबी में सर्चिंग फास्ट करने के लिए इंडेक्स सुनिश्चित करें"""
    try:
        # फ़ाइल नेम और कैप्शन पर टेक्स्ट इंडेक्स
        await col.create_index([("file_name", "text"), ("caption", "text")])
        await col.create_index([("file_id", 1)])
    except Exception as e:
        logging.error(f"Index Creation Error: {e}")

class Media:
    """पुराने मॉडल की कम्पैटिबिलिटी बनाए रखने के लिए एक क्लीन क्लास संरचना"""
    def __init__(self, data):
        self.file_id = data.get('_id')
        self.file_name = data.get('file_name')
        self.file_size = data.get('file_size')
        self.caption = data.get('caption', '')

    @staticmethod
    async def count_documents(filter_query=None):
        return await col.count_documents(filter_query or {})

    @staticmethod
    def find(filter_query=None):
        return col.find(filter_query or {})

async def save_file(media):
    """डेटाबेस में फ़ाइल सुरक्षित करें - बिना किसी भारी वैलीडेशन ओवरहेड के"""
    file_id = unpack_new_file_id(media.file_id)
    
    # अनचाहे सिम्बल्स को साफ करें
    file_name = re.sub(r"@\w+|(_|\-|\.|\+)", " ", str(media.file_name))
    file_caption = re.sub(r"@\w+|(_|\-|\.|\+)", " ", str(media.caption)) if media.caption else ""

    document = {
        "_id": file_id,
        "file_name": file_name,
        "file_size": media.file_size,
        "caption": file_caption
    }

    try:
        await col.insert_one(document)
        print(f'Saved - {file_name}')
        return 'suc'
    except DuplicateKeyError:
        print(f'Already Saved - {file_name}')
        return 'dup'
    except Exception as e:
        print(f'Saving Error - {file_name}: {e}')
        return 'err'

async def get_search_results(query, max_results=MAX_BTN, offset=0):
    """मोंगोडीबी लेवल पर ही पेजिनेशन और फास्ट सर्चिंग लॉजिक (No Lang Feature)"""
    query = str(query).strip()
    
    if not query:
        filter_dict = {}
    else:
        # कीवर्ड्स को अलग-अलग तोड़कर खोजना ताकि सर्चिंग एकदम सटीक और तेज हो
        keywords = query.split()
        regex_patterns = [re.compile(re.escape(kw), re.IGNORECASE) for kw in keywords]
        filter_dict = {"$and": [{"file_name": regex} for regex in regex_patterns]}

    # हालिया फाइल्स को सबसे ऊपर दिखाने के लिए नेचुरल सॉर्ट
    cursor = col.find(filter_dict).sort("$natural", -1).skip(offset).limit(max_results)
    
    files_data = await cursor.to_list(length=max_results)
    files = [Media(data) for data in files_data]
    
    total_results = await col.count_documents(filter_dict)
    
    next_offset = offset + max_results
    if next_offset >= total_results:
        next_offset = ''
        
    return files, next_offset, total_results

async def delete_files(query):
    """क्वेरी के आधार पर डेटाबेस से फाइल्स ढूँढना (डिलीट कन्फर्मेशन के लिए)"""
    query = query.strip()
    if not query:
        filter_dict = {}
    else:
        keywords = query.split()
        regex_patterns = [re.compile(re.escape(kw), re.IGNORECASE) for kw in keywords]
        filter_dict = {"$and": [{"file_name": regex} for regex in regex_patterns]}
        
    total = await col.count_documents(filter_dict)
    cursor = col.find(filter_dict)
    files = [Media(data) async for data in cursor]
    return total, files

async def get_file_details(query):
    """फाइल आईडी के आधार पर सिंगल फ़ाइल विवरण निकालना"""
    cursor = col.find({'_id': query})
    files_data = await cursor.to_list(length=1)
    return [Media(data) for data in files_data]

def encode_file_id(s: bytes) -> str:
    r = b""
    n = 0
    for i in s + bytes([22]) + bytes([4]):
        if i == 0:
            n += 1
        else:
            if n:
                r += b"\x00" + bytes([n])
                n = 0
            r += bytes([i])
    return base64.urlsafe_b64encode(r).decode().rstrip("=")

def unpack_new_file_id(new_file_id):
    decoded = FileId.decode(new_file_id)
    file_id = encode_file_id(
        pack(
            "<iiqq",
            int(decoded.file_type),
            decoded.dc_id,
            decoded.media_id,
            decoded.access_hash
        )
    )
    return file_id
