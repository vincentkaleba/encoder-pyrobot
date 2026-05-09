from pydantic import Field, model_validator
from typing import List, Optional, Union
from pydantic_settings import BaseSettings

import logging

class Settings(BaseSettings):
    # BOT SETTINGS
    BOT_NAME: str = "Pro_robot"
    BOT_TOKEN: str

    API_ID: int
    API_HASH: str

    # SESSION
    SESSION_STRING: Optional[str] = None
    SESSION: Optional[str] = None
    USERBOT_ENABLED: bool = True
    SESSION_DIR: str = "sessions"

    def __init__(self, **values):
        super().__init__(**values)
        import os
        if not os.path.exists(self.SESSION_DIR):
            os.makedirs(self.SESSION_DIR, exist_ok=True)

    # DATABASE
    MONGODB_URI: str


    # DIRECTORIES & URLS
    DRIVE_DIR: str = ""
    INDEX_URI: str = ""

    DOWNLOAD_DIR: str = ""
    ENCODE_DIR: str = ""

    # PERMISSIONS & USERS
    OWNER_ID: str
    SUDO_USERS: List[Union[str, int]] = Field(default_factory=list)

    # LOGGING & AUTH
    LOG_DIR: str = ""
    LOG_CHANNELS: List[Union[str, int]] = Field(default_factory=list)
    DUMP_CHAT: Optional[str] = None
    AUTHORIZED_CHATS: List[Union[str, int]] = Field(default_factory=list)

    # AUTO DELETE
    AUTODELETE_MESSAGES: bool = False
    AUTODELETE_MESSAGES_TIMEOUT: int = 3600
    START_TIME: Optional[float] = None

    # FILE UPLOAD SETTINGS
    TG_SPLIT_SIZE: int = 2 # in GB
    AS_DOCUMENT: bool = False
    FILE_BASE_NAME: bool = False
    BASE_NAME: str = ""

    # TORRENT DIRECT LINK
    TORRENT_DIRECT_LINK_LIMIT: int = 10 # in GB

    # lOGGING
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    LOG_FILE: Optional[str] = None
    # MISC
    ISOCODE_VERSION: str = "1.0.0"
    ISO_CODE: str = "fr"

    # ENCODER
    ENCODER_MAX_CONCURRENT: int = 2

    @model_validator(mode="before")
    def _coerce_lists(cls, values: dict):
        """Normalize env values for list fields into lists of strings.

        Handles cases where the env provides JSON arrays, comma-separated
        strings, single ints, or actual lists (from dotenv parsers).
        """
        import json

        def ensure_list_of_str(key: str):
            if key not in values:
                return
            v = values.get(key)
            if isinstance(v, str):
                # try JSON first (e.g. "[1,2]")
                try:
                    parsed = json.loads(v)
                    v = parsed
                except Exception:
                    # fallback to comma separated
                    v = [p.strip() for p in v.split(",") if p.strip()]
            # now coerce to list of strings
            if isinstance(v, (list, tuple)):
                values[key] = [str(x) for x in v]
            else:
                values[key] = [str(v)]

        for k in ("SUDO_USERS", "LOG_CHANNELS", "AUTHORIZED_CHATS"):
            ensure_list_of_str(k)

        return values

    @model_validator(mode="after")
    def _normalize_list_types(cls, model):
        """Ensure the three list fields are always lists of strings after validation.

        Some env parsing or settings loading can yield ints or mixed types; convert
        them to strings so the rest of the code can rely on a consistent type.
        """
        for k in ("SUDO_USERS", "LOG_CHANNELS", "AUTHORIZED_CHATS"):
            v = getattr(model, k, None)
            if v is None:
                continue
            try:
                normalized = [str(x) for x in v]
            except Exception:
                normalized = []
            setattr(model, k, normalized)

        return model

    class Config:
        env_file = ".env"

settings = Settings()
