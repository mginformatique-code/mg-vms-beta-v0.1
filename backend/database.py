import os
from motor.motor_asyncio import AsyncIOMotorClient

mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]


async def create_indexes():
    await db.users.create_index("email", unique=True)
    await db.cameras.create_index("site_id")
    await db.plates.create_index("plate")
    await db.plates.create_index("timestamp")
    await db.events.create_index("timestamp")
    await db.recordings.create_index("camera_id")
    await db.recordings.create_index("start")
    await db.audit_logs.create_index("timestamp")
    await db.login_attempts.create_index("identifier", unique=True)
    await db.password_reset_tokens.create_index("token", unique=True)
