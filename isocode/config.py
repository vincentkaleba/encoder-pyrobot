from pydantic import Field, validator
from typing import List, Optional
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # -----------------
    # BOT SETTINGS
    BOT_NAME: str = "Pro_robot"
    BOT_TOKEN: str

    API_ID: int
    API_HASH: str

    # -----------------
    # SESSION
    SESSION_STRING: Optional[str] = None
    SESSION: Optional[str] = None
    USERBOT_ENABLED: bool = True
    SESSION_DIR: str = "sessions"

    # -----------------
    # DATABASE
    MONGODB_URI: str

    # -----------------
    # DIRECTORIES & URLS
    DRIVE_DIR: str = ""
    INDEX_URI: str = ""
    DOWNLOAD_DIR: str = ""
    ENCODE_DIR: str = ""

    # -----------------
    # PERMISSIONS & USERS
    OWNER_ID: str
    SUDO_USERS: List[int] = Field(default_factory=list)

    # -----------------
    # LOGGING & AUTH
    LOG_DIR: str = ""
    LOG_CHANNELS: List[int] = Field(default_factory=list)
    DUMP_CHAT: Optional[str] = None
    AUTHORIZED_CHATS: List[int] = Field(default_factory=list)

    # -----------------
    # AUTO DELETE
    AUTODELETE_MESSAGES: bool = False
    AUTODELETE_MESSAGES_TIMEOUT: int = 3600
    START_TIME: Optional[float] = None

    # -----------------
    # FILE UPLOAD SETTINGS
    TG_SPLIT_SIZE: int = 2  # in GB
    AS_DOCUMENT: bool = False
    FILE_BASE_NAME: bool = False
    BASE_NAME: str = ""

    # -----------------
    # TORRENT DIRECT LINK
    TORRENT_DIRECT_LINK_LIMIT: int = 10  # in GB

    # -----------------
    # LOGGING
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    LOG_FILE: Optional[str] = None

    # -----------------
    # MISC
    ISOCODE_VERSION: str = "1.0.0"
    ISO_CODE: str = "fr"

    # -----------------
    # Validators pour les listes
    @validator("SUDO_USERS", "LOG_CHANNELS", "AUTHORIZED_CHATS", pre=True)
    def parse_list(cls, v):
        """
        Transforme les valeurs des .env en liste d'entiers.
        Accepte:
            - int seul -> [int]
            - string "1,2,3" -> [1,2,3]
            - None -> []
        """
        if v is None:
            return []
        if isinstance(v, int):
            return [v]
        if isinstance(v, str):
            return [int(i.strip()) for i in v.split(",") if i.strip()]
        # si c'est déjà une liste d'int
        return v

    class Config:
        env_file = ".env"

# -----------------
# Instance globale
settings = Settings()