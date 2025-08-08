import inspect
from isocode import settings, logger
from isocode.utils.database.database import (
    Tune,
    User,
    VideoCodec,
    AudioCodec,
    Preset,
    Resolution,
    SubtitleAction,
    AudioTrackAction,
    Database,
    VideoFormat,
    HWAccel,
    UserRole,
    UserStatus
)
from typing import Any, Dict, List, Union, Optional
from enum import Enum
import asyncio


async def get_database() -> Database:
    """Return a database instance with connection pooling"""
    return Database(settings.MONGODB_URI, settings.SESSION)


# ==================== User Management ====================
async def if_user_exist(user_id: int) -> bool:
    """Check if a user exists in the database"""
    db = await get_database()
    user = await db.get_or_create_user(user_id)
    return user is not None


async def add_user(user_id: int):
    """Add a new user with default settings"""
    db = await get_database()
    await db.get_or_create_user(user_id)


async def total_users_count() -> int:
    """Get total number of users"""
    db = await get_database()
    return await db.users.count_documents({})


async def get_all_users() -> List[User]:
    """Get all users from the database"""
    db = await get_database()
    users = []
    async for user_data in db.users.find({}):
        users.append(User(**user_data))
    return users


async def delete_user(user_id: int):
    """Delete a user from the database"""
    db = await get_database()
    await db.users.delete_one({"user_id": user_id})


# ==================== User Settings ====================
async def get_or_create_user(user_id: int) -> User:
    """Get user object with all settings"""
    db = await get_database()
    return await db.get_or_create_user(user_id)


async def update_user(user: User):
    """Update user object in database"""
    db = await get_database()
    await db.update_user(user)


async def get_or_create_user_settings(user_id: int) -> Dict[str, Any]:
    """Get all settings for a user as a dictionary"""
    user = await get_or_create_user(user_id)
    return user.model_dump(by_alias=True, exclude={"id"})


async def update_user_settings(user_id: int, settings: Dict[str, Any]):
    """Update multiple settings for a user"""
    user = await get_or_create_user(user_id)

    # Mise à jour sélective des paramètres avec validation
    for key, value in settings.items():
        if hasattr(user, key):
            # Conversion des valeurs enum si nécessaire
            field_info = user.model_fields.get(key)
            if field_info and inspect.isclass(field_info.annotation) and issubclass(field_info.annotation, Enum):
                if isinstance(value, str):
                    # Try to get enum member by name or value
                    if value in field_info.annotation._member_names_:
                        value = field_info.annotation[value]
                    else:
                        # Try to match by value
                        for member in field_info.annotation:
                            if member.value == value:
                                value = member
                                break
                        else:
                            # Fallback to first member
                            value = list(field_info.annotation)[0]
                elif isinstance(value, int):
                    # Get by index
                    members = list(field_info.annotation)
                    if 0 <= value < len(members):
                        value = members[value]
                    else:
                        value = members[0]
            setattr(user, key, value)

    await update_user(user)

async def set_metadata(user_id: int, metadata: Dict[str, Any]):
    """Set metadata for a user"""
    user = await get_or_create_user(user_id)
    user.metadata = metadata
    await update_user(user)

async def get_metadata(user_id: int) -> Optional[Dict[str, Any]]:
    """Get metadata for a user"""
    user = await get_or_create_user(user_id)
    return user.metadata if user.metadata else None


async def get_setting(user_id: int, setting_name: str) -> Any:
    """Get a specific setting for a user"""
    user = await get_or_create_user(user_id)
    return getattr(user, setting_name, None)


async def set_setting(user_id: int, setting_name: str, value: Any):
    """Set a specific setting for a user"""
    await update_user_settings(user_id, {setting_name: value})

async def trigger_setting_change(user_id: int, setting_name: str, value: Any):
    """
    Change the value of an enum setting for a user to its next value.
    If the setting is not an enum, set the provided value directly.
    """
    user = await get_or_create_user(user_id)
    field_info = user.model_fields.get(setting_name)
    if field_info and issubclass(field_info.annotation, Enum):
        enum_cls = field_info.annotation
        current_value = getattr(user, setting_name)
        enum_members = list(enum_cls)
        try:
            idx = enum_members.index(current_value)
            next_value = enum_members[(idx + 1) % len(enum_members)]
        except ValueError:
            next_value = enum_members[0]
        await set_setting(user_id, setting_name, next_value)
    else:
        await set_setting(user_id, setting_name, value)


# ==================== Admin Management ====================
async def set_admin_status(user_id: int, is_admin: bool):
    """Set admin status for a user"""
    db = await get_database()
    await db.set_admin_status(user_id, is_admin)


async def is_user_admin(user_id: int) -> bool:
    """Check if user is admin"""
    user = await get_or_create_user(user_id)
    return user.is_admin


# ==================== FFmpeg Preferences ====================
async def get_ffmpeg_settings(user_id: int) -> Dict[str, Any]:
    """Get structured FFmpeg settings"""
    db = await get_database()
    return await db.get_ffmpeg_settings(user_id)


async def set_audio_preferences(
    user_id: int,
    action: Optional[Union[str, AudioTrackAction]] = None,
    track: Optional[str] = None,
    bitrate: Optional[str] = None,
):
    """Set audio processing preferences"""
    db = await get_database()

    # Convert string to Enum if needed
    if action and isinstance(action, str):
        action = (
            AudioTrackAction[action]
            if action in AudioTrackAction._member_names_
            else AudioTrackAction(action)
        )

    await db.set_audio_preferences(user_id, action, track, bitrate)


async def set_subtitle_preferences(
    user_id: int,
    action: Optional[Union[str, SubtitleAction]] = None,
    track: Optional[str] = None,
):
    """Set subtitle processing preferences"""
    db = await get_database()

    # Convert string to Enum if needed
    if action and isinstance(action, str):
        action = (
            SubtitleAction[action] if action in SubtitleAction._member_names_ else SubtitleAction(action)
        )

    await db.set_subtitle_preferences(user_id, action, track)

async def get_subtitle_action(user_id: int) -> SubtitleAction:
    """Get subtitle action for a user"""
    user = await get_or_create_user(user_id)
    return user.subtitle_action

async def get_normalize_audio(user_id: int) -> bool:
    """Get whether audio normalization is enabled for a user"""
    user = await get_or_create_user(user_id)
    return user.normalize_audio

async def get_pix_fmt(user_id: int) -> str:
    """Get pixel format for a user"""
    user = await get_or_create_user(user_id)
    return user.pix_fmt

async def get_daily_limit(user_id: int) -> int:
    """Get daily limit for a user"""
    user = await get_or_create_user(user_id)
    return user.daily_limit

async def get_max_file(user_id: int) -> int:
    """Get maximum file size for a user"""
    user = await get_or_create_user(user_id)
    return user.daily_limit

async def get_metadata(user_id: int) -> bool:
    """Get whether metadata is enabled for a user"""
    user = await get_or_create_user(user_id)
    return user.metadata

# ==================== Specific Settings Shortcuts ====================
# Upload as Document
async def get_upload_as_doc(user_id: int) -> bool:
    user = await get_or_create_user(user_id)
    return user.upload_as_doc


async def set_upload_as_doc(user_id: int, value: bool):
    await set_setting(user_id, "upload_as_doc", value)


# Resize
async def get_resize(user_id: int) -> bool:
    user = await get_or_create_user(user_id)
    return user.resize


async def set_resize(user_id: int, value: bool):
    await set_setting(user_id, "resize", value)


# Frame Rate
async def get_frame(user_id: int) -> str:
    user = await get_or_create_user(user_id)
    return user.frame


async def set_frame(user_id: int, value: str):
    await set_setting(user_id, "frame", value)


# Resolution
async def get_resolution(user_id: int) -> Resolution:
    user = await get_or_create_user(user_id)
    return user.resolution


async def set_resolution(user_id: int, value: Union[str, Resolution]):
    if isinstance(value, str):
        value = (
            Resolution[value]
            if value in Resolution._member_names_
            else Resolution(value)
        )
    await set_setting(user_id, "resolution", value)


# Video Bits
async def get_bits(user_id: int) -> bool:
    user = await get_or_create_user(user_id)
    return user.bits


async def set_bits(user_id: int, value: bool):
    await set_setting(user_id, "bits", value)


# Subtitles
async def get_subtitles(user_id: int) -> bool:
    user = await get_or_create_user(user_id)
    return user.subtitles


async def set_subtitles(user_id: int, value: bool):
    await set_setting(user_id, "subtitles", value)


# Sample Rate
async def get_samplerate(user_id: int) -> str:
    user = await get_or_create_user(user_id)
    return user.sample


async def set_samplerate(user_id: int, value: str):
    await set_setting(user_id, "sample", value)


# File Extensions
async def get_extensions(user_id: int) -> VideoFormat:
    user = await get_or_create_user(user_id)
    return user.extensions

# Video Codec
async def get_video_codec(user_id: int) -> VideoCodec:
    user = await get_or_create_user(user_id)
    return user.video_codec

async def set_video_codec(user_id: int, value: Union[str, VideoCodec]):
    if isinstance(value, str):
        value = (
            VideoCodec[value]
            if value in VideoCodec._member_names_
            else VideoCodec(value)
        )
    await set_setting(user_id, "video_codec", value)


async def set_extensions(user_id: int, value: Union[str, VideoFormat]):
    if isinstance(value, str):
        value = (
            VideoFormat[value]
            if value in VideoFormat._member_names_
            else VideoFormat(value)
        )
    await set_setting(user_id, "extensions", value)


# Bit Rate
async def get_bitrate(user_id: int) -> str:
    user = await get_or_create_user(user_id)
    return user.bitrate


async def set_bitrate(user_id: int, value: str):
    await set_setting(user_id, "bitrate", value)


# Reframe
async def get_reframe(user_id: int) -> str:
    user = await get_or_create_user(user_id)
    return user.reframe


async def set_reframe(user_id: int, value: str):
    await set_setting(user_id, "reframe", value)


# Audio Codec
async def get_audio_codec(user_id: int) -> AudioCodec:
    user = await get_or_create_user(user_id)
    return user.audio_codec


async def set_audio_codec(user_id: int, value: Union[str, AudioCodec]):
    if isinstance(value, str):
        value = (
            AudioCodec[value]
            if value in AudioCodec._member_names_
            else AudioCodec(value)
        )
    await set_setting(user_id, "audio_codec", value)

async def get_audio_track_action(user_id: int) -> AudioTrackAction:
    user = await get_or_create_user(user_id)
    return user.audio_track_action


# Audio Channels
async def get_channels(user_id: int) -> str:
    user = await get_or_create_user(user_id)
    return user.channels


async def set_channels(user_id: int, value: str):
    await set_setting(user_id, "channels", value)


# Metadata Watermark
async def get_metadata_w(user_id: int) -> bool:
    user = await get_or_create_user(user_id)
    return user.metadata


async def set_metadata_w(user_id: int, value: bool):
    await set_setting(user_id, "metadata", value)


# Watermark
async def get_watermark(user_id: int) -> bool:
    user = await get_or_create_user(user_id)
    return user.watermark


async def set_watermark(user_id: int, value: bool):
    await set_setting(user_id, "watermark", value)


# Preset
async def get_preset(user_id: int) -> Preset:
    user = await get_or_create_user(user_id)
    return user.preset


async def set_preset(user_id: int, value: Union[str, Preset]):
    if isinstance(value, str):
        value = Preset[value] if value in Preset._member_names_ else Preset(value)
    await set_setting(user_id, "preset", value)


# Hard Sub
async def get_hardsub(user_id: int) -> bool:
    user = await get_or_create_user(user_id)
    return user.hardsub


async def set_hardsub(user_id: int, value: bool):
    await set_setting(user_id, "hardsub", value)


# HEVC (Note: This is now replaced by video_codec, but kept for backward compatibility)
async def get_hevc(user_id: int) -> bool:
    user = await get_or_create_user(user_id)
    return user.video_codec == VideoCodec.H265


async def set_hevc(user_id: int, value: bool):
    # If setting HEVC, set video_codec to H265, otherwise to H264
    video_codec = VideoCodec.H265 if value else VideoCodec.H264
    await set_setting(user_id, "video_codec", video_codec)


# Tune
async def get_tune(user_id: int) -> Tune:
    user = await get_or_create_user(user_id)
    return user.tune


async def set_tune(user_id: int, value: Union[str, Tune]):
    if isinstance(value, str):
        value = Tune[value] if value in Tune._member_names_ else Tune(value)
    await set_setting(user_id, "tune", value)


# CABAC
async def get_cabac(user_id: int) -> bool:
    user = await get_or_create_user(user_id)
    return user.cabac


async def set_cabac(user_id: int, value: bool):
    await set_setting(user_id, "cabac", value)


# Aspect Ratio
async def get_aspect(user_id: int) -> bool:
    user = await get_or_create_user(user_id)
    return user.aspect


async def set_aspect(user_id: int, value: bool):
    await set_setting(user_id, "aspect", value)


# Google Drive
async def get_drive(user_id: int) -> bool:
    user = await get_or_create_user(user_id)
    return user.drive


async def set_drive(user_id: int, value: bool):
    await set_setting(user_id, "drive", value)


# CRF (Quality Factor)
async def get_crf(user_id: int) -> int:
    user = await get_or_create_user(user_id)
    return user.crf


async def set_crf(user_id: int, value: int):
    await set_setting(user_id, "crf", value)


# subs_id (Subtitles ID)
async def get_subs_id(user_id: int) -> int:
    user = await get_or_create_user(user_id)
    return user.subs_id


async def set_subs_id(user_id: int, value: int):
    await set_setting(user_id, "subs_id", value)


# Audio Bitrate
async def get_audio_bitrate(user_id: int) -> str:
    user = await get_or_create_user(user_id)
    return user.audio_bitrate


async def set_audio_bitrate(user_id: int, value: str):
    await set_setting(user_id, "audio_bitrate", value)


# Hardware Acceleration
async def get_hwaccel(user_id: int) -> HWAccel:
    user = await get_or_create_user(user_id)
    return user.hwaccel


async def set_hwaccel(user_id: int, value: Union[str, HWAccel]):
    if isinstance(value, str):
        value = HWAccel[value] if value in HWAccel._member_names_ else HWAccel(value)
    await set_setting(user_id, "hwaccel", value)


# Threads
async def get_threads(user_id: int) -> int:
    user = await get_or_create_user(user_id)
    return user.threads


async def set_threads(user_id: int, value: int):
    await set_setting(user_id, "threads", value)


# Extra FFmpeg Arguments
async def get_extra_args(user_id: int) -> str:
    user = await get_or_create_user(user_id)
    return user.extra_args


async def set_extra_args(user_id: int, value: str):
    await set_setting(user_id, "extra_args", value)


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
    return await db.get_auth_chat()


async def set_auth_chat(chat_id: str):
    """Set authorized chat ID"""
    db = await get_database()
    await db.set_auth_chat(chat_id)


async def get_sudo_users() -> str:
    """Get sudo users configuration"""
    db = await get_database()
    return await db.get_sudo()


async def set_sudo_users(sudo_id: str):
    """Set sudo users"""
    db = await get_database()
    await db.set_sudo(sudo_id)


# ==================== Batch Operations ====================
async def migrate_users(old_db_uri: str, old_db_name: str):
    """Migrate users from old database to new structure"""
    from motor.motor_asyncio import AsyncIOMotorClient

    logger.info("Starting user migration...")
    old_client = AsyncIOMotorClient(old_db_uri)
    old_db = old_client[old_db_name]
    old_users = old_db.users

    new_db = await get_database()

    async for user_data in old_users.find():
        user_id = user_data.get("id")
        if user_id:
            # Créer un nouvel utilisateur dans le nouveau système
            new_user = await new_db.get_or_create_user(user_id)

            # Mapper les anciens champs vers les nouveaux
            field_mapping = {
                "extensions": "extensions",
                "hevc": "video_codec",  # Conversion spéciale: hevc (bool) -> video_codec (enum)
                "preset": "preset",
                "crf": "crf",
                "resolution": "resolution",
                "upload_as_doc": "upload_as_doc",
                "resize": "resize",
                "frame": "frame",
                "bits": "bits",
                "subtitles": "subtitles",
                "sample": "sample",
                "bitrate": "bitrate",
                "reframe": "reframe",
                "audio": "audio_codec",
                "channels": "channels",
                "metadata": "metadata",
                "watermark": "watermark",
                "hardsub": "hardsub",
                "tune": "tune",
                "cabac": "cabac",
                "aspect": "aspect",
                "drive": "drive",
                "subs_id": "subs_id",
                "hwaccel": "hwaccel",
                "threads": "threads",
                "extra_args": "extra_args",
                "audio_bitrate": "audio_bitrate",
            }

            updates = {}
            for old_field, new_field in field_mapping.items():
                if old_field in user_data:
                    # Conversions spéciales
                    if old_field == "hevc":
                        # Convertir booléen hevc en VideoCodec
                        updates["video_codec"] = (
                            VideoCodec.H265 if user_data["hevc"] else VideoCodec.H264
                        )
                    elif old_field == "extensions":
                        # Convertir l'extension en format vidéo
                        try:
                            updates["extensions"] = VideoFormat[
                                user_data["extensions"].upper()
                            ]
                        except KeyError:
                            updates["extensions"] = VideoFormat.MKV
                    elif old_field == "audio":
                        # Convertir l'ancien codec audio
                        try:
                            updates["audio_codec"] = AudioCodec[
                                user_data["audio"].upper()
                            ]
                        except KeyError:
                            updates["audio_codec"] = AudioCodec.AAC
                    elif old_field == "preset":
                        # Convertir l'ancien preset
                        try:
                            updates["preset"] = Preset[user_data["preset"].upper()]
                        except KeyError:
                            updates["preset"] = Preset.MEDIUM
                    elif old_field == "tune":
                        # Convertir l'ancien tune
                        try:
                            updates["tune"] = Tune[user_data["tune"].upper()]
                        except KeyError:
                            updates["tune"] = Tune.NONE
                    elif old_field == "hwaccel":
                        # Convertir l'accélération matérielle
                        try:
                            updates["hwaccel"] = HWAccel[user_data["hwaccel"].upper()]
                        except KeyError:
                            updates["hwaccel"] = HWAccel.AUTO
                    else:
                        updates[new_field] = user_data[old_field]

            if updates:
                await update_user_settings(user_id, updates)

    logger.info(f"User migration completed successfully")


# ==================== Initialization ====================
async def initialize_database():
    """Initialize database with default settings"""
    db = await get_database()

    # Créer les entrées système si elles n'existent pas
    await db.get_killed_status()
    await db.get_auth_chat()
    await db.get_sudo()

    logger.info("Database initialization completed")


# Exécuter l'initialisation au démarrage
# asyncio.create_task(initialize_database())