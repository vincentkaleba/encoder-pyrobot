from .config import settings
import logging
import os

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

def ensure_abs_path(path: str, default_subdir: str) -> str:
    """
    Retourne un chemin absolu fiable à partir de `path` ou `default_subdir`.
    """
    if not path:
        return os.path.join(BASE_DIR, default_subdir)
    return path if os.path.isabs(path) else os.path.join(BASE_DIR, path)

encode_dir = ensure_abs_path(settings.ENCODE_DIR, "encode")
os.makedirs(encode_dir, exist_ok=True)

download_dir = ensure_abs_path(settings.DOWNLOAD_DIR, "download")
os.makedirs(download_dir, exist_ok=True)

async def get_config():
    return settings

video_mimetype = [
    "video/x-flv", "video/mp4", "application/x-mpegURL", "video/MP2T",
    "video/3gpp", "video/quicktime", "video/x-msvideo", "video/x-ms-wmv",
    "video/x-matroska", "video/webm", "video/x-m4v", "video/quicktime", "video/mpeg"
]

data = []

def setup_logger(name: str = None):
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))
    formatter = logging.Formatter(settings.LOG_FORMAT)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    if settings.LOG_FILE:
        log_path = ensure_abs_path(settings.LOG_FILE, "logs/pro_robot.log")
        log_dir = os.path.dirname(log_path)
        os.makedirs(log_dir, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    logger.propagate = False
    return logger

logger = setup_logger("Pro_robot")
