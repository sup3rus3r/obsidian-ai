from motor.motor_asyncio import AsyncIOMotorClient
from typing import Optional
import os

MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "obsidian")

client: Optional[AsyncIOMotorClient] = None
db = None


async def connect_to_mongo():
    global client, db
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[MONGO_DB_NAME]


async def close_mongo_connection():
    global client
    if client:
        client.close()


def get_database():
    return db
