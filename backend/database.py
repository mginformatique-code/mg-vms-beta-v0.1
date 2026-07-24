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
    await db.equipment.create_index("site_id")
    await db.equipment.create_index("parent_id")
    await db.audit_logs.create_index("timestamp")
    await db.login_attempts.create_index("identifier", unique=True)
    await db.password_reset_tokens.create_index("token", unique=True)
    # Journal lifecycle des streams (persistance des transitions notables)
    await db.stream_lifecycle_journal.create_index([("camera_id", 1), ("ts", -1)])
    await db.stream_lifecycle_journal.create_index("ts")
