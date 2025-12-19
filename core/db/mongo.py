import os
import logging
from motor.motor_asyncio import AsyncIOMotorClient

logger = logging.getLogger("UniversalAIGateway")

class MongoManager:
    client: AsyncIOMotorClient = None
    db = None

    def connect(self):
        mongo_url = os.getenv("MONGO_URL", "mongodb://localhost:27017")
        db_name = os.getenv("MONGO_DB_NAME", "magic_proxy_db")

        logger.info(f"Connecting to MongoDB at {mongo_url} (DB: {db_name})...")
        try:
            self.client = AsyncIOMotorClient(mongo_url)
            self.db = self.client[db_name]
            logger.info("MongoDB connection established.")
        except Exception as e:
            logger.error(f"Could not connect to MongoDB: {e}")
            raise

    def close(self):
        if self.client:
            self.client.close()
            logger.info("MongoDB connection closed.")

db_manager = MongoManager()

async def get_database():
    return db_manager.db
