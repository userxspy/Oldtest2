from motor.motor_asyncio import AsyncIOMotorClient
from info import DATABASE_NAME, DATABASE_URL

client = AsyncIOMotorClient(DATABASE_URL)
mydb = client[DATABASE_NAME]

class Database:
    def __init__(self):
        # सिर्फ वही कलेक्शंस रखेंगे जिनकी सच में जरूरत है
        self.col = mydb.Users
        self.botcol = mydb["bot_id"]

    def new_user(self, id, name):
        """नया यूज़र डिक्शनरी ऑब्जेक्ट बनाएँ (No Premium/No Ban Overheads)"""
        return dict(
            id=id,
            name=name
        )
    
    async def add_user(self, id, name):
        """डेटाबेस में नया एडमिन/यूज़र जोड़ें"""
        if not await self.is_user_exist(id):
            user = self.new_user(id, name)
            await self.col.insert_one(user)
    
    async def is_user_exist(self, id):
        """चेक करें कि यूज़र पहले से डेटाबेस में है या नहीं"""
        user = await self.col.find_one({'id': int(id)})
        return bool(user)
    
    async def total_users_count(self):
        """कुल रजिस्टर्ड यूज़र्स की संख्या निकालें"""
        return await self.col.count_documents({})

    async def get_all_users(self):
        """सभी यूज़र्स का कर्सर ऑब्जेक्ट प्राप्त करें"""
        return self.col.find({})
    
    async def delete_user(self, user_id):
        """डेटाबेस से किसी यूज़र को डिलीट करें"""
        await self.col.delete_many({'id': int(user_id)})
    
    async def get_db_size(self):
        """डेटाबेस का कुल साइज बाइट्स में प्राप्त करें"""
        return (await mydb.command("dbstats"))['dataSize']

    async def get_pm_search_status(self, bot_id):
        """चेक करें कि पर्सनल चैट (PM) में सर्च ऑन है या नहीं"""
        bot = await self.botcol.find_one({'id': bot_id})
        if bot and "bot_pm_search" in bot:
            return bot['bot_pm_search']
        return True # डिफ़ॉल्ट रूप से एडमिन के लिए हमेशा ऑन रहेगा

    async def update_pm_search_status(self, bot_id, enable):
        """पर्सनल चैट (PM) सर्च स्टेटस को ऑन या ऑफ करें"""
        await self.botcol.update_one(
            {'id': int(bot_id)}, 
            {'$set': {'bot_pm_search': enable}}, 
            upsert=True
        )

db = Database()
