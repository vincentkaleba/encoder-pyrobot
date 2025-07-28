from isocode import settings, logger
from isocode.utils.database.database import Database
from typing import Any, Dict, List, Union, Optional

async def get_database() -> Database:
    """Return a database instance with connection pooling"""
    return Database(settings.MONGODB_URI, settings.SESSION)

# ==================== User Management ====================
async def if_user_exist(user_id: int) -> bool:
    """Check if a user exists in the database"""
    db = await get_database()
    return await db.is_user_exist(user_id)

async def add_user(user_id: int):
    """Add a new user with default settings"""
    db = await get_database()
    await db.get_or_create_user(user_id)

async def total_users_count() -> int:
    """Get total number of users"""
    db = await get_database()
    return await db.total_users_count()

async def get_all_users() -> List[Dict[str, Any]]:
    """Get all users from the database"""
    db = await get_database()
    return await db.get_all_users()

async def delete_user(user_id: int):
    """Delete a user from the database"""
    db = await get_database()
    await db.delete_user(user_id)

# ==================== User Settings ====================
async def get_user_settings(user_id: int) -> Dict[str, Any]:
    """Get all settings for a user"""
    db = await get_database()
    return await db.get_or_create_user(user_id)

async def update_user_settings(user_id: int, settings: Dict[str, Any]):
    """Update multiple settings for a user"""
    db = await get_database()
    for key, value in settings.items():
        await db.update_user_setting(user_id, key, value)

async def get_setting(user_id: int, setting_name: str) -> Any:
    """Get a specific setting for a user"""
    db = await get_database()
    return await db.get_user_setting(user_id, setting_name)

async def set_setting(user_id: int, setting_name: str, value: Any):
    """Set a specific setting for a user"""
    db = await get_database()
    await db.update_user_setting(user_id, setting_name, value)

# ==================== Specific Settings Shortcuts ====================
# Upload as Document
async def get_upload_as_doc(user_id: int) -> bool:
    return await get_setting(user_id, "upload_as_doc")

async def set_upload_as_doc(user_id: int, value: bool):
    await set_setting(user_id, "upload_as_doc", value)

# Resize
async def get_resize(user_id: int) -> bool:
    return await get_setting(user_id, "resize")

async def set_resize(user_id: int, value: bool):
    await set_setting(user_id, "resize", value)

# Frame Rate
async def get_frame(user_id: int) -> str:
    return await get_setting(user_id, "frame")

async def set_frame(user_id: int, value: str):
    await set_setting(user_id, "frame", value)

# Resolution
async def get_resolution(user_id: int) -> str:
    return await get_setting(user_id, "resolution")

async def set_resolution(user_id: int, value: str):
    await set_setting(user_id, "resolution", value)

# Video Bits
async def get_bits(user_id: int) -> bool:
    return await get_setting(user_id, "bits")

async def set_bits(user_id: int, value: bool):
    await set_setting(user_id, "bits", value)

# Subtitles
async def get_subtitles(user_id: int) -> bool:
    return await get_setting(user_id, "subtitles")

async def set_subtitles(user_id: int, value: bool):
    await set_setting(user_id, "subtitles", value)

# Sample Rate
async def get_samplerate(user_id: int) -> str:
    return await get_setting(user_id, "sample")

async def set_samplerate(user_id: int, value: str):
    await set_setting(user_id, "sample", value)

# File Extensions
async def get_extensions(user_id: int) -> str:
    return await get_setting(user_id, "extensions")

async def set_extensions(user_id: int, value: str):
    await set_setting(user_id, "extensions", value)

# Bit Rate
async def get_bitrate(user_id: int) -> str:
    return await get_setting(user_id, "bitrate")

async def set_bitrate(user_id: int, value: str):
    await set_setting(user_id, "bitrate", value)

# Reframe
async def get_reframe(user_id: int) -> str:
    return await get_setting(user_id, "reframe")

async def set_reframe(user_id: int, value: str):
    await set_setting(user_id, "reframe", value)

# Audio Codec
async def get_audio(user_id: int) -> str:
    return await get_setting(user_id, "audio")

async def set_audio(user_id: int, value: str):
    await set_setting(user_id, "audio", value)

# Audio Channels
async def get_channels(user_id: int) -> str:
    return await get_setting(user_id, "channels")

async def set_channels(user_id: int, value: str):
    await set_setting(user_id, "channels", value)

# Metadata Watermark
async def get_metadata_w(user_id: int) -> bool:
    return await get_setting(user_id, "metadata")

async def set_metadata_w(user_id: int, value: bool):
    await set_setting(user_id, "metadata", value)

# Watermark
async def get_watermark(user_id: int) -> bool:
    return await get_setting(user_id, "watermark")

async def set_watermark(user_id: int, value: bool):
    await set_setting(user_id, "watermark", value)

# Preset
async def get_preset(user_id: int) -> str:
    return await get_setting(user_id, "preset")

async def set_preset(user_id: int, value: str):
    await set_setting(user_id, "preset", value)

# Hard Sub
async def get_hardsub(user_id: int) -> bool:
    return await get_setting(user_id, "hardsub")

async def set_hardsub(user_id: int, value: bool):
    await set_setting(user_id, "hardsub", value)

# HEVC
async def get_hevc(user_id: int) -> bool:
    return await get_setting(user_id, "hevc")

async def set_hevc(user_id: int, value: bool):
    await set_setting(user_id, "hevc", value)

# Tune
async def get_tune(user_id: int) -> bool:
    return await get_setting(user_id, "tune")

async def set_tune(user_id: int, value: bool):
    await set_setting(user_id, "tune", value)

# CABAC
async def get_cabac(user_id: int) -> bool:
    return await get_setting(user_id, "cabac")

async def set_cabac(user_id: int, value: bool):
    await set_setting(user_id, "cabac", value)

# Aspect Ratio
async def get_aspect(user_id: int) -> bool:
    return await get_setting(user_id, "aspect")

async def set_aspect(user_id: int, value: bool):
    await set_setting(user_id, "aspect", value)

# Google Drive
async def get_drive(user_id: int) -> bool:
    return await get_setting(user_id, "drive")

async def set_drive(user_id: int, value: bool):
    await set_setting(user_id, "drive", value)

# CRF (Quality Factor)
async def get_crf(user_id: int) -> int:
    return await get_setting(user_id, "crf")

async def set_crf(user_id: int, value: int):
    await set_setting(user_id, "crf", value)

# subs_id (Subtitles ID)
async def get_subs_id(user_id: int) -> int:
    return await get_setting(user_id, "subs_id")

# ==================== System Settings ====================
async def get_killed_status() -> bool:
    """Get system kill switch status"""
    db = await get_database()
    return await db.get_killed_status()

async def set_killed_status(status: bool):
    """Set system kill switch status"""
    db = await get_database()
    await db.set_killed_status(status)

async def get_auth_chat() -> str:
    """Get authorized chat ID"""
    db = await get_database()
    return await db.get_chat()

async def set_auth_chat(chat_id: str):
    """Set authorized chat ID"""
    db = await get_database()
    await db.set_chat(chat_id)

async def get_sudo_users() -> List[str]:
    """Get list of sudo users"""
    db = await get_database()
    return await db.get_sudo()

async def set_sudo_users(users: Union[str, List[str]]):
    """Set sudo users"""
    db = await get_database()
    await db.set_sudo(users)

async def add_sudo_user(user_id: str):
    """Add a sudo user"""
    db = await get_database()
    await db.add_sudo_user(user_id)

async def remove_sudo_user(user_id: str):
    """Remove a sudo user"""
    db = await get_database()
    await db.remove_sudo_user(user_id)

# ==================== Batch Operations ====================
async def migrate_users(old_db_uri: str, old_db_name: str):
    """Migrate users from old database to new structure"""
    from motor.motor_asyncio import AsyncIOMotorClient

    logger.info("Starting user migration...")
    old_client = AsyncIOMotorClient(old_db_uri)
    old_db = old_client[old_db_name]
    old_users = old_db.users

    new_db = await get_database()

    async for user in old_users.find():
        user_id = user.get('id')
        if user_id:
            # Transform old user data to new format
            new_settings = {}
            for key in new_db.default_user_settings().keys():
                if key in user:
                    new_settings[key] = user[key]

            # Update or create user in new database
            await update_user_settings(user_id, new_settings)

    logger.info(f"User migration completed successfully")