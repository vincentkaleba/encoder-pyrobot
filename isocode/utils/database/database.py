from enum import Enum
from typing import List, Tuple, Optional, Dict, Any, Union
from pydantic import BaseModel, Field
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
from pydantic_core import core_schema
from pydantic import GetCoreSchemaHandler, ConfigDict
from datetime import datetime
import asyncio

from enum import Enum
from typing import List, Optional, Tuple

# ==================== Codec Enumérations Intégrées ====================
class VideoCodec(str, Enum):
    """Codecs vidéo supportés avec leurs paramètres FFmpeg"""
    H264 = "libx264"
    H265 = "libx265"
    VP8 = "libvpx"
    H264_NVENC = "h264_nvenc"
    H265_NVENC = "hevc_nvenc"
    AV1 = "libaom-av1"
    VP9 = "libvpx-vp9"
    MPEG4 = "mpeg4"
    COPY = "copy"

    @property
    def ffmpeg_name(self) -> str:
        return self.value

    @property
    def display_name(self) -> str:
        names = {
            "libx264": "H.264",
            "libx265": "H.265/HEVC",
            "libvpx": "VP8",
            "h264_nvenc": "H.264 (NVENC)",
            "hevc_nvenc": "H.265/HEVC (NVENC)",
            "libaom-av1": "AV1",
            "libvpx-vp9": "VP9",
            "mpeg4": "MPEG-4",
            "copy": "Copier (sans conversion)"
        }
        return names[self.value]

    @classmethod
    def supported_formats(cls) -> List[Tuple[str, str]]:
        return [(codec.name, codec.display_name) for codec in cls]

    @classmethod
    def from_ffmpeg_name(cls, name: str) -> Optional['VideoCodec']:
        mapping = {codec.value: codec for codec in cls}
        return mapping.get(name)

class AudioCodec(str, Enum):
    """Codecs audio supportés avec leurs paramètres"""
    AAC = "aac"
    OPUS = "opus"
    MP3 = "mp3"
    FLAC = "flac"
    AC3 = "ac3"
    COPY = "copy"

    @property
    def ffmpeg_name(self) -> str:
        return self.value

    @property
    def display_name(self) -> str:
        names = {
            "aac": "AAC",
            "opus": "Opus",
            "mp3": "MP3",
            "flac": "FLAC (sans perte)",
            "ac3": "Dolby Digital",
            "copy": "Copier (sans conversion)"
        }
        return names[self.value]

    @property
    def supported_bitrates(self) -> List[str]:
        if self == AudioCodec.OPUS:
            return ["32k", "64k", "96k", "128k", "192k", "256k"]
        return ["64k", "96k", "128k", "192k", "256k", "320k"]

    @classmethod
    def normalized_name(cls, name: str) -> Optional['AudioCodec']:
        """Normalise le nom du codec audio (ex: 'mp3' -> AudioCodec.MP3)"""
        mapping = {
            "aac": cls.AAC,
            "opus": cls.OPUS,
            "mp3": cls.MP3,
            "flac": cls.FLAC,
            "ac3": cls.AC3,
            "copy": cls.COPY
        }
        return mapping.get(name.lower())

class Preset(str, Enum):
    """Presets de compression H.264/H.265"""
    ULTRAFAST = "ultrafast"
    SUPERFAST = "superfast"
    VERYFAST = "veryfast"
    FASTER = "faster"
    FAST = "fast"
    MEDIUM = "medium"
    SLOW = "slow"
    SLOWER = "slower"
    VERYSLOW = "veryslow"

    @property
    def ffmpeg_name(self) -> str:
        return self.value

    @property
    def display_name(self) -> str:
        return self.value.capitalize()

    @property
    def compression_factor(self) -> float:
        factors = {
            "ultrafast": 0.3,
            "superfast": 0.5,
            "veryfast": 0.7,
            "faster": 0.8,
            "fast": 0.9,
            "medium": 1.0,
            "slow": 1.2,
            "slower": 1.5,
            "veryslow": 2.0,
        }
        return factors[self.value]

class Tune(str, Enum):
    """Options de tuning pour l'encodage"""
    FILM = "film"
    ANIMATION = "animation"
    GRAIN = "grain"
    STILLIMAGE = "stillimage"
    FASTDECODE = "fastdecode"
    ZEROLATENCY = "zerolatency"
    NONE = "none"

    @property
    def ffmpeg_name(self) -> str:
        return self.value

    @property
    def display_name(self) -> str:
        names = {
            "film": "Film",
            "animation": "Animation",
            "grain": "Grain cinéma",
            "stillimage": "Image fixe",
            "fastdecode": "Décodage rapide",
            "zerolatency": "Latence zéro",
            "none": "Aucun"
        }
        return names[self.value]

class Resolution(str, Enum):
    """Résolutions vidéo supportées (normalisées)"""
    ORIGINAL = "original"
    SD = "480p"
    HD = "720p"
    FHD = "1080p"
    QHD = "1440p"
    UHD_4K = "2160p"

    @property
    def ffmpeg_name(self) -> str:
        mapping = {
            "original": "",
            "480p": "854:480",
            "720p": "1280:720",
            "1080p": "1920:1080",
            "1440p": "2560:1440",
            "2160p": "3840:2160"
        }
        return mapping[self.value]

    @property
    def display_name(self) -> str:
        names = {
            "original": "Originale",
            "480p": "SD (480p)",
            "720p": "HD (720p)",
            "1080p": "Full HD (1080p)",
            "1440p": "QHD (1440p)",
            "2160p": "4K UHD (2160p)"
        }
        return names[self.value]

    @property
    def width(self) -> int:
        mapping = {
            "original": 0,
            "480p": 854,
            "720p": 1280,
            "1080p": 1920,
            "1440p": 2560,
            "2160p": 3840
        }
        return mapping[self.value]

    @property
    def height(self) -> int:
        mapping = {
            "original": 0,
            "480p": 480,
            "720p": 720,
            "1080p": 1080,
            "1440p": 1440,
            "2160p": 2160
        }
        return mapping[self.value]

class VideoFormat(str, Enum):
    """Conteneurs multimédia supportés"""
    MP4 = "mp4"
    MKV = "mkv"
    WEBM = "webm"
    MOV = "mov"
    AVI = "avi"

    @property
    def ffmpeg_name(self) -> str:
        # Retourne le format sans le point pour FFmpeg
        return self.value

    @property
    def display_name(self) -> str:
        return self.value.upper()

    @property
    def compatible_codecs(self) -> List[VideoCodec]:
        compatibility = {
            ".mp4": [VideoCodec.H264, VideoCodec.H265, VideoCodec.COPY, VideoCodec.H264_NVENC, VideoCodec.H265_NVENC],
            ".mkv": [VideoCodec.H264, VideoCodec.H265, VideoCodec.AV1, VideoCodec.VP9, VideoCodec.COPY, VideoCodec.H264_NVENC, VideoCodec.H265_NVENC],
            ".webm": [VideoCodec.VP9, VideoCodec.AV1, VideoCodec.COPY],
            ".mov": [VideoCodec.H264, VideoCodec.H265, VideoCodec.COPY, VideoCodec.H264_NVENC, VideoCodec.H265_NVENC],
            ".avi": [VideoCodec.H264, VideoCodec.COPY, VideoCodec.H264_NVENC]
        }
        return compatibility[self.value]

class SubtitleAction(str, Enum):
    """Actions disponibles pour les sous-titres"""
    NONE = "none"
    BURN = "burn"
    EMBED = "embed"
    EXTRACT = "extract"
    COPY = "copy"

    @property
    def ffmpeg_name(self) -> str:
        return self.value

    @property
    def display_name(self) -> str:
        names = {
            "none": "Ignorer",
            "burn": "Incuster",
            "embed": "Intégrer",
            "extract": "Extraire",
            "copy": "Copier"
        }
        return names[self.value]

class AudioTrackAction(str, Enum):
    """Actions disponibles pour les pistes audio"""
    ALL = "all"
    FIRST = "first"
    NONE = "none"
    TRACK_2 = "track_2"
    TRACK_3 = "track_3"
    TRACK_4 = "track_4"
    TRACK_5 = "track_5"
    TRACK_6 = "track_6"
    TRACK_7 = "track_7"
    TRACK_8 = "track_8"
    TRACK_9 = "track_9"
    TRACK_10 = "track_10"

    @property
    def ffmpeg_name(self) -> str:
        return self.value

    @property
    def display_name(self) -> str:
        names = {
            "all": "Toutes les pistes",
            "first": "Première piste",
            "none": "Désactivé",
            "track_2": "Piste 2",
            "track_3": "Piste 3",
            "track_4": "Piste 4",
            "track_5": "Piste 5",
            "track_6": "Piste 6",
            "track_7": "Piste 7",
            "track_8": "Piste 8",
            "track_9": "Piste 9",
            "track_10": "Piste 10"
        }
        return names[self.value]

class HWAccel(str, Enum):
    """Accélération matérielle"""
    AUTO = "auto"
    NONE = "none"
    CUDA = "cuda"
    VAAPI = "vaapi"
    DXVA2 = "dxva2"
    QSV = "qsv"

    @property
    def ffmpeg_name(self) -> str:
        return self.value

class ReframeOption(str, Enum):
    """Options de changement de fréquence d'images"""
    KEEP_ORIGINAL = "0"
    FPS_24 = "24"
    FPS_30 = "30"
    FPS_48 = "48"
    FPS_60 = "60"

    @property
    def display_name(self) -> str:
        names = {
            "0": "Originale",
            "24": "24 FPS",
            "30": "30 FPS",
            "48": "48 FPS",
            "60": "60 FPS"
        }
        return names[self.value]

    @property
    def fps_value(self) -> float:
        return float(self.value) if self.value != "0" else 0.0
# ==================== Modèle Pydantic ====================
class PyObjectId(ObjectId):
    @classmethod
    def __get_pydantic_core_schema__(cls, _source, handler: GetCoreSchemaHandler) -> core_schema.CoreSchema:
        return core_schema.no_info_after_validator_function(cls.validate, core_schema.str_schema())

    @classmethod
    def validate(cls, v):
        if isinstance(v, ObjectId):
            return v
        if isinstance(v, str) and ObjectId.is_valid(v):
            return ObjectId(v)
        raise ValueError("Invalid ObjectId")

class UserRole(str, Enum):
    USER = "user"
    ADMIN = "admin"
    SUPER_ADMIN = "super_admin"

class UserStatus(str, Enum):
    ACTIVE = "active"
    BANNED = "banned"
    RESTRICTED = "restricted"

# ==================== Modèle metadata ====================

class MediaMetadata(BaseModel):
    # 🎵 Métadonnées audio
    title: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    album_artist: Optional[str] = None
    track: Optional[str] = None
    disc: Optional[str] = None
    genre: Optional[str] = None
    date: Optional[str] = None  # ou `int` si année uniquement
    year: Optional[str] = None
    comment: Optional[str] = None
    composer: Optional[str] = None
    lyricist: Optional[str] = None
    lyrics: Optional[str] = None
    publisher: Optional[str] = None
    copyright: Optional[str] = None
    encoded_by: Optional[str] = 'Hyosh EncoderBot'
    encoder: Optional[str] = None
    language: Optional[str] = None

    # 🎬 Métadonnées vidéo/séries
    show: Optional[str] = None
    season_number: Optional[int] = None
    episode_id: Optional[str] = None
    episode_sort: Optional[int] = None
    network: Optional[str] = None
    director: Optional[str] = None
    producer: Optional[str] = None
    synopsis: Optional[str] = None
    description: Optional[str] = None
    grouping: Optional[str] = None

    # 🌐 Autres tags
    category: Optional[str] = None
    location: Optional[str] = None
    creation_time: Optional[str] = None  # peut être ISO 8601
    software: Optional[str] = None
    comment_eng: Optional[str] = Field(None, alias="comment-eng")

    model_config = ConfigDict(populate_by_name=True)

# ==================== Modèle Utilisateur ====================

class User(BaseModel):
    id: Optional[PyObjectId] = Field(alias="_id", default=None)
    user_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    language: str = "fr"

    # Gestion des permissions et statut
    is_admin: bool = False
    roles: List[UserRole] = Field(default_factory=lambda: [UserRole.USER])
    status: UserStatus = UserStatus.ACTIVE
    permissions: List[str] = Field(default_factory=list)

    # Historique d'activité
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_activity: datetime = Field(default_factory=datetime.utcnow)
    command_count: int = 0

    # Paramètres d'encodage
    extensions: VideoFormat = VideoFormat.MKV
    video_codec: VideoCodec = VideoCodec.H265
    audio_codec: AudioCodec = AudioCodec.AAC
    preset: Preset = Preset.SUPERFAST
    tune: Tune = Tune.FILM
    resolution: Resolution = Resolution.ORIGINAL
    metadata_ars: Optional[MediaMetadata] = None
    crf: int = 22
    pix_fmt: str = "yuv420p"
    hwaccel: HWAccel = HWAccel.AUTO
    threads: int = Field(ge=0, default=0)
    extra_args: str = ""
    normalize_audio: bool = True
    audio_bitrate: str = "192k"

    # Gestion des pistes
    audio_track_action: AudioTrackAction = AudioTrackAction.FIRST
    selected_audio_track: Optional[str] = None
    subtitle_action: SubtitleAction = SubtitleAction.EMBED
    selected_subtitle_track: Optional[str] = None

    # Flags supplémentaires
    aspect: bool = False
    cabac: bool = False
    bits: bool = False
    drive: bool = False
    metadata: bool = True
    hardsub: bool = False
    watermark: bool = False
    subtitles: bool = True
    upload_as_doc: bool = False
    resize: bool = False
    subs_id: int = 0
    channels: str = "2"  # Nombre de canaux audio
    reframe: str = "0"  # Reframes pour H.264/H.265

    # Limites d'utilisation
    daily_limit: int = 10
    max_file_size: int = 2000  # Mo

    model_config = ConfigDict(
        json_encoders={ObjectId: str},
        use_enum_values=True,
        populate_by_name=True,
        arbitrary_types_allowed=True
    )

    def update_activity(self, command: Optional[str] = None):
        self.last_activity = datetime.utcnow()
        if command:
            self.command_count += 1

    def set_admin(self, is_admin: bool):
        self.is_admin = is_admin
        if is_admin and UserRole.ADMIN not in self.roles:
            self.roles.append(UserRole.ADMIN)
        elif not is_admin and UserRole.ADMIN in self.roles:
            self.roles.remove(UserRole.ADMIN)
        self.update_activity()

    def has_permission(self, permission: str) -> bool:
        return self.is_admin or permission in self.permissions

    def get_ffmpeg_base_params(self) -> Dict[str, Any]:
        return {
            "video_codec": self.video_codec.ffmpeg_name,
            "audio_codec": self.audio_codec.ffmpeg_name,
            "preset": self.preset.ffmpeg_name,
            "crf": self.crf,
            "pix_fmt": self.pix_fmt,
            "tune": self.tune.ffmpeg_name if self.tune != Tune.NONE else None,
            "hwaccel": self.hwaccel.ffmpeg_name if self.hwaccel != HWAccel.NONE else None,
            "threads": self.threads,
            "extra_args": self.extra_args,
            "audio_bitrate": self.audio_bitrate
        }

    def get_audio_track_params(self) -> Dict[str, Any]:
        return {
            "action": self.audio_track_action.ffmpeg_name,
            "selected_track": self.selected_audio_track,
            "bitrate": self.audio_bitrate
        }

    def get_subtitle_params(self) -> Dict[str, Any]:
        return {
            "action": self.subtitle_action.ffmpeg_name,
            "selected_track": self.selected_subtitle_track
        }

# ==================== Base de données ====================
class Database:
    def __init__(self, uri, database_name):
        self._client = AsyncIOMotorClient(uri)
        self.db = self._client[database_name]
        self.users = self.db.users
        self.status = self.db.status
        asyncio.create_task(self.migrate_old_users())

    async def migrate_old_users(self):
        async for old_user in self.users.find({}):
            if "is_admin" not in old_user:
                new_user = User(**old_user)
                await self.users.replace_one({"_id": old_user["_id"]}, new_user.dict(by_alias=True))

    async def get_or_create_user(self, user_id: int) -> User:
        user_data = await self.users.find_one({"user_id": user_id})
        if not user_data:
            new_user = User(user_id=user_id)
            await self.users.insert_one(new_user.dict(by_alias=True))
            return new_user
        return User(**user_data)

    async def update_user(self, user: User) -> bool:
        user.last_activity = datetime.utcnow()

        result = await self.users.update_one(
            {"user_id": user.user_id},
            {"$set": user.dict(by_alias=True, exclude={"id"})}
        )
        return result.modified_count > 0

    async def get_metadata(self, user_id: int) -> Optional[MediaMetadata]:
        user = await self.get_or_create_user(user_id)
        return user.metadata_ars

    async def set_metadata(self, user_id: int, metadata: MediaMetadata):
        user = await self.get_or_create_user(user_id)
        user.metadata_ars = metadata
        await self.update_user(user)

    # Méthodes pour les paramètres
    async def set_video_setting(self, user_id: int, setting: str, value: Any):
        user = await self.get_or_create_user(user_id)
        if hasattr(user, setting):
            setattr(user, setting, value)
            await self.update_user(user)

    async def get_video_setting(self, user_id: int, setting: str) -> Any:
        user = await self.get_or_create_user(user_id)
        return getattr(user, setting, None)

    # Méthodes pour les paramètres status
    async def get_killed_status(self) -> bool:
        status = await self.status.find_one({"id": "killed"})
        return status.get("status", False) if status else False

    async def set_killed_status(self, status: bool):
        await self.status.update_one(
            {"id": "killed"},
            {"$set": {"status": status}},
            upsert=True
        )

    async def get_auth_chat(self) -> str:
        status = await self.status.find_one({"id": "auth"})
        if not status:
            await self.status.insert_one({"id": "auth", "chat": "5814104129"})
            return "5814104129"
        return status.get("chat", "5814104129")

    async def set_auth_chat(self, chat_id: str):
        await self.status.update_one(
            {"id": "auth"},
            {"$set": {"chat": chat_id}},
            upsert=True
        )

    async def get_sudo(self) -> str:
        status = await self.status.find_one({"id": "sudo"})
        if not status:
            await self.status.insert_one({"id": "sudo", "sudo": "5814104129"})
            return "5814104129"
        return status.get("sudo", "5814104129")

    async def set_sudo(self, sudo_id: str):
        await self.status.update_one(
            {"id": "sudo"},
            {"$set": {"sudo": sudo_id}},
            upsert=True
        )

    # Compatibilité avec les anciennes méthodes
    async def update_user_setting(self, user_id: int, setting_name: str, value: Any):
        user = await self.get_or_create_user(user_id)
        if hasattr(user, setting_name):
            setattr(user, setting_name, value)
            await self.update_user(user)

    async def get_or_create_user_setting(self, user_id: int, setting_name: str) -> Any:
        user = await self.get_or_create_user(user_id)
        return getattr(user, setting_name, None)

    # Méthodes supplémentaires
    async def set_admin_status(self, user_id: int, is_admin: bool):
        user = await self.get_or_create_user(user_id)
        user.set_admin(is_admin)
        await self.update_user(user)

    async def get_ffmpeg_settings(self, user_id: int) -> Dict[str, Any]:
        user = await self.get_or_create_user(user_id)
        return {
            "base": user.get_ffmpeg_base_params(),
            "audio": user.get_audio_track_params(),
            "subtitle": user.get_subtitle_params(),
            "resolution": user.resolution.value,
            "crf": user.crf
        }