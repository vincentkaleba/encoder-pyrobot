

from enum import Enum
import re
from typing import Any


def create_progress_bar(percent: float, length: int = 10) -> str:
    """
    Crée une barre de progression visuelle.
    """
    progress = min(100, max(0, percent))
    filled = int(progress / 100 * length)
    empty = length - filled
    return f"[{'█' * filled}{'░' * empty}]"

def humanbytes(size: float) -> str:
    """
    Convertit des octets en format lisible
    """
    units = ["B", "Ko", "Mo", "Go", "To"]
    index = 0
    while size >= 1024 and index < len(units) - 1:
        size /= 1024
        index += 1
    return f"{size:.2f} {units[index]}"

# Dictionnaire de mapping pour la stylisation Unicode
TAG_PATTERN = re.compile(r'(<[^>]+>)')
UNICODE_MAPPING = {
    # Lettres
    'a': 'ᴀ', 'b': 'ʙ', 'c': 'ᴄ', 'd': 'ᴅ', 'e': 'ᴇ', 'f': 'ꜰ',
    'g': 'ɢ', 'h': 'ʜ', 'i': 'ɪ', 'j': 'ᴊ', 'k': 'ᴋ', 'l': 'ʟ',
    'm': 'ᴍ', 'n': 'ɴ', 'o': 'ᴏ', 'p': 'ᴘ', 'q': 'ǫ', 'r': 'ʀ',
    's': 'ꜱ', 't': 'ᴛ', 'u': 'ᴜ', 'v': 'ᴠ', 'w': 'ᴡ', 'x': 'x',
    'y': 'ʏ', 'z': 'ᴢ', ' ': ' ',

    # Chiffres
    '0': '𝟢', '1': '𝟣', '2': '𝟤', '3': '𝟥', '4': '𝟦',
    '5': '𝟧', '6': '𝟨', '7': '𝟩', '8': '𝟪', '9': '𝟫',

    # Symboles spéciaux
    ':': '꞉', '-': '−', '_': 'ˍ',

    # Valeurs spécifiques
    'libx264': 'ʟɪʙx𝟤𝟨𝟦',
    'libx265': 'ʟɪʙx𝟤𝟨𝟧',
    'libaom-av1': 'ʟɪʙᴀᴏᴍ−ᴀᴠ𝟣',
    'libvpx-vp9': 'ʟɪʙᴠᴘx−ᴠᴘ𝟫',
    'aac': 'ᴀᴀᴄ',
    'libopus': 'ʟɪʙᴏᴘᴜꜱ',
    'copy': 'ᴄᴏᴘʏ',
    'auto': 'ᴀᴜᴛᴏ',
    'source': 'ꜱᴏᴜʀᴄᴇ',
    'on': 'ᴏɴ',
    'off': 'ᴏꜰꜰ',
    'OG': 'ᴏɢ',
    'original': 'ᴏʀɪɢɪɴᴀʟ',
    'embed': 'ᴇᴍʙᴇᴅ',
    'burn': 'ʙᴜʀɴ',
    'extract': 'ᴇxᴛʀᴀᴄᴛ',
    'select': 'ꜱᴇʟᴇᴄᴛ',
    'first': 'ꜰɪʀꜱᴛ',
    'copy_all': 'ᴄᴏᴘʏ ᴀʟʟ',
    'film': 'ꜰɪʟᴍ',
    'none': 'ɴᴏɴᴇ',
    'sf': 'ꜱꜰ',
    'yuv420p': 'ʏᴜᴠ𝟦𝟤𝟢ᴘ',
    'pass': 'ᴘᴀꜱꜱ',
    '\n': '\n',

}

def stylize_value(value: Any) -> str:
    """Stylise le texte mais laisse les balises HTML intactes."""
    if isinstance(value, bool):
        return 'ᴏɴ' if value else 'ᴏꜰꜰ'

    if isinstance(value, Enum):
        value = value.value

    str_value = str(value)

    parts = TAG_PATTERN.split(str_value)

    styled_parts = []
    for part in parts:
        if TAG_PATTERN.fullmatch(part):
            styled_parts.append(part)
        else:
            if part in UNICODE_MAPPING:
                styled_parts.append(UNICODE_MAPPING[part])
            else:
                styled_parts.append(''.join(UNICODE_MAPPING.get(c, c) for c in part.lower()))

    return ''.join(styled_parts)