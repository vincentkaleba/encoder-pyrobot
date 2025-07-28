from .config import settings
import logging
import os


async def get_config():
    """
    Returns the settings configuration.
    """
    return settings


video_mimetype = [
    "video/x-flv",
    "video/mp4",
    "application/x-mpegURL",
    "video/MP2T",
    "video/3gpp",
    "video/quicktime",
    "video/x-msvideo",
    "video/x-ms-wmv",
    "video/x-matroska",
    "video/webm",
    "video/x-m4v",
    "video/quicktime",
    "video/mpeg"
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
    log_dir = os.path.dirname(settings.LOG_FILE)
    if log_dir and not os.path.exists(log_dir):
      os.makedirs(log_dir)
    file_handler = logging.FileHandler(settings.LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
  logger.propagate = False
  return logger

logger = setup_logger("Pro_robot")


