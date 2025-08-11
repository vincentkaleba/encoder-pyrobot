from pyrogram import Client
from pyrogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ParseMode
from isocode.plugins.cmd import MEDIA_MAP, get_uptime
from isocode.utils.database.database import AudioCodec
from isocode.utils.isoutils.msg import BotMessage
from isocode.utils.telegram.keyboard import concat_kbs, create_inline_kb, create_web_kb
from isocode import logger
from isocode.utils.isoutils.dbutils import (
    get_or_create_user,
    if_user_exist,
    add_user,
    set_setting,
    get_setting,
    get_resolution,
    get_video_codec,
    get_audio_codec,
    get_preset,
    get_crf,
    get_upload_as_doc,
    get_audio_bitrate,
    get_threads,
    get_hwaccel,
    get_subtitle_action,
    get_audio_track_action,
    get_extensions,
    get_tune,
    get_aspect,
    get_cabac,
    get_metadata,
    get_watermark,
    get_hardsub,
    get_subtitles,
    get_normalize_audio,
    get_pix_fmt,
    get_channels,
    get_reframe,
    get_daily_limit,
    get_max_file,
)
from isocode.utils.isoutils.progress import stylize_value
import psutil
import os
import subprocess
import re
import base64
from isocode.config import settings
from isocode.utils.telegram.media import send_media

# ==================== Constantes et configurations ====================
close_kb = create_inline_kb([[("❌ ᴄʟᴏsᴇ", "close")]])

# Liste des formats de pixels supportés
PIX_FMT_OPTIONS = [
    "yuv420p",
    "yuvj420p",
    "yuv422p",
    "yuvj422p",
    "yuv444p",
    "yuvj444p",
    "nv12",
    "nv21",
    "rgb24",
    "bgr24",
    "argb",
    "rgba",
]

# Liste des taux d'échantillonnage audio
SAMPLE_RATE_OPTIONS = ["44100", "48000", "88200", "96000"]

# Liste des modèles de canaux audio
CHANNEL_OPTIONS = ["mono", "stereo", "2.1", "5.1", "7.1"]

# Mapping pour raccourcir les noms de paramètres dans callback_data (si nécessaire)
SHORT_SETTING_MAP = {
    "crf": "crf",
    "threads": "th",
    "daily_limit": "dl",
    "max_file": "mf",
    "pix_fmt": "px",
    "channels": "ch",
    "audio_bitrate": "ab",
    "selected_subtitle_track": "st",
}

# Options pour les paramètres (sous-menus)
SETTING_CYCLE_OPTIONS = {
    "video_codec": ["libx264", "libx265", "libvpx", "h264_nvenc", "hevc_nvenc"],
    "resolution": ["original", "480p", "720p", "1080p", "1440p", "2160p"],
    "preset": [
        "ultrafast",
        "superfast",
        "veryfast",
        "faster",
        "fast",
        "medium",
        "slow",
        "slower",
        "veryslow",
    ],
    "hwaccel": ["none", "auto", "cuda", "vaapi", "dxva2", "qsv"],
    # audio_codec values come from AudioCodec enum
    "audio_codec": [c.value for c in AudioCodec],
    "audio_track_action": [
        "all",
        "first",
        "none",
        "track_2",
        "track_3",
        "track_4",
        "track_5",
        "track_6",
        "track_7",
        "track_8",
        "track_9",
        "track_10",
    ],
    "subtitle_action": ["none", "burn", "extract", "embed"],
    "extensions": ["mp4", "mkv", "webm", "mov"],
    "reframe": ["0", "24", "30", "48", "60"],
    "tune": [
        "none",
        "film",
        "animation",
        "grain",
        "stillimage",
        "fastdecode",
        "zerolatency",
    ],
    "aspect": ["original", "16:9", "4:3", "21:9"],
}

# Mapping des noms courts vers les vrais noms de paramètres (pour compatibilité)
SETTING_NAME_MAP = {
    "subaction": "subtitle_action",
    "audio_track": "audio_track_action",
    "format": "extensions",
    "subs_track": "selected_subtitle_track",
}

# Liste de tous les noms de settings connus (pour résolution des noms sanitizés)
KNOWN_SETTING_NAMES = set(list(SETTING_CYCLE_OPTIONS.keys()) + [
    'pix_fmt', 'channels', 'audio_bitrate', 'selected_subtitle_track',
    'video_codec', 'subtitle_action', 'audio_codec', 'upload_as_doc',
    'hardsub', 'subtitles', 'normalize_audio', 'cabac', 'metadata', 'watermark',
    'crf', 'threads', 'daily_limit', 'max_file', 'audio_track_action'
])

# ==================== Classe de vérification matérielle ====================
class HardwareAcceleratorChecker:
    """Classe pour vérifier et gérer les accélérateurs matériels disponibles"""
    _instance = None
    available_accels = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.available_accels = None
        return cls._instance

    def check_cuda_available(self) -> bool:
        try:
            if os.path.exists("/dev/nvidia0") or os.path.exists("/dev/nvidiactl"):
                result = subprocess.run(
                    ["nvidia-smi", "-L"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                return "GPU" in result.stdout
            return False
        except Exception:
            return False

    def check_vaapi_available(self) -> bool:
        try:
            render_devices = [f for f in os.listdir("/dev/dri") if f.startswith("renderD")]
            if not render_devices:
                return False
            device = f"/dev/dri/{render_devices[0]}"
            return os.access(device, os.R_OK | os.W_OK)
        except Exception:
            return False

    def check_qsv_available(self) -> bool:
        try:
            card_devices = [f for f in os.listdir("/dev/dri") if f.startswith("card")]
            if not card_devices:
                return False
            device = f"/dev/dri/{card_devices[0]}"
            return os.access(device, os.R_OK | os.W_OK)
        except Exception:
            return False

    def check_dxva2_available(self) -> bool:
        try:
            return os.name == "nt"
        except Exception:
            return False

    def check_all(self):
        if self.available_accels is not None:
            return self.available_accels

        available = {"none", "auto"}
        if self.check_cuda_available():
            available.add("cuda")
        if self.check_vaapi_available():
            available.add("vaapi")
        if self.check_qsv_available():
            available.add("qsv")
        if self.check_dxva2_available():
            available.add("dxva2")

        valid_hwaccels = ["none", "auto", "cuda", "vaapi", "dxva2", "qsv"]
        self.available_accels = [accel for accel in valid_hwaccels if accel in available]
        logger.info(f"Accélérateurs matériels détectés: {self.available_accels}")
        return self.available_accels

    def get_available(self) -> list:
        if self.available_accels is None:
            return self.check_all()
        return self.available_accels

hw_accel_checker = HardwareAcceleratorChecker()


# ==================== Fonctions utilitaires ====================
async def get_current_settings(user_id: int) -> dict:
    settings_dict = {
        "video_codec": await get_video_codec(user_id),
        "audio_codec": await get_audio_codec(user_id),
        "preset": await get_preset(user_id),
        "crf": await get_crf(user_id),
        "resolution": await get_resolution(user_id),
        "upload_as_doc": await get_upload_as_doc(user_id),
        "audio_bitrate": await get_audio_bitrate(user_id),
        "threads": await get_threads(user_id),
        "hwaccel": await get_hwaccel(user_id),
        "subtitle_action": await get_subtitle_action(user_id),
        "selected_subtitle_track": await get_setting(user_id, "selected_subtitle_track"),
        "audio_track_action": await get_audio_track_action(user_id),
        "extensions": await get_extensions(user_id),
        "tune": await get_tune(user_id),
        "aspect": await get_aspect(user_id),
        "cabac": await get_cabac(user_id),
        "metadata": await get_metadata(user_id),
        "watermark": await get_watermark(user_id),
        "hardsub": await get_hardsub(user_id),
        "subtitles": await get_subtitles(user_id),
        "normalize_audio": await get_normalize_audio(user_id),
        "pix_fmt": await get_pix_fmt(user_id),
        "channels": await get_channels(user_id),
        "reframe": await get_reframe(user_id),
        "daily_limit": await get_daily_limit(user_id),
        "max_file": await get_max_file(user_id),
    }

    # Vérifier et corriger hwaccel si nécessaire
    available_accels = hw_accel_checker.get_available()
    current_hwaccel = settings_dict["hwaccel"]
    if current_hwaccel not in available_accels:
        await set_setting(user_id, "hwaccel", "none")
        settings_dict["hwaccel"] = "none"
        logger.warning(
            f"HWAccel '{current_hwaccel}' non disponible, réglé sur 'none' pour l'utilisateur {user_id}"
        )

    return settings_dict


def _sanitize_callback_token(value: str) -> str:
    """Remplace les caractères problématiques pour callback_data"""
    if value is None:
        return ""
    value = str(value)
    return re.sub(r"[^A-Za-z0-9\-_.]", "_", value)


def _resolve_setting_name_from_sanitized(sanitized: str) -> str:
    """Résout le nom réel du setting à partir du token sanitizé.
    Compare avec KNOWN_SETTING_NAMES et SETTING_NAME_MAP (clés et valeurs).
    Retourne sanitized si aucune correspondance trouvée (on essaye de sauver avec ce nom).
    """
    if not sanitized:
        return sanitized

    # direct match
    if sanitized in KNOWN_SETTING_NAMES:
        return sanitized

    # try to match by sanitizing known names
    for name in KNOWN_SETTING_NAMES:
        if _sanitize_callback_token(name) == sanitized:
            return name

    # also check SETTING_NAME_MAP keys and values
    for short, long in SETTING_NAME_MAP.items():
        if _sanitize_callback_token(short) == sanitized:
            return long
        if _sanitize_callback_token(long) == sanitized:
            return long

    # fallback: try common replacements
    alt = sanitized.replace('-', '_')
    for name in KNOWN_SETTING_NAMES:
        if name == alt:
            return name

    return sanitized


def _b64encode_value(val: str) -> str:
    """Encode la valeur en base64 urlsafe sans padding pour callback_data"""
    if val is None:
        val = ""
    b = val.encode("utf-8")
    enc = base64.urlsafe_b64encode(b).decode("utf-8").rstrip("=")
    return enc


def _b64decode_value(enc: str) -> str:
    """Decode la valeur base64 urlsafe, en ajoutant le padding si nécessaire"""
    if enc is None:
        return ""
    # add padding
    padding = 4 - (len(enc) % 4)
    if padding and padding != 4:
        enc += "=" * padding
    try:
        return base64.urlsafe_b64decode(enc.encode("utf-8")).decode("utf-8")
    except Exception:
        # fallback: return raw string if decode fails
        return enc


def create_adjustment_kb(setting_name: str, options: list, current_value: str) -> InlineKeyboardMarkup:
    """
    Crée un clavier d'ajustement pour un paramètre.
    callback_data: s_<sanitized_setting>::<base64_urlsafe(value)>
    On utilise '::' comme séparateur pour éviter les ambiguïtés avec les underscores.
    """
    buttons = []
    row = []

    safe_setting = _sanitize_callback_token(setting_name)

    for idx, option in enumerate(options):
        prefix = "• " if str(option) == str(current_value) else ""
        safe_option_enc = _b64encode_value(str(option))
        callback_data = f"s_{safe_setting}::{safe_option_enc}"
        row.append((f"{prefix}{option}", callback_data))

        if (idx + 1) % 3 == 0:
            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

    buttons.append([("↩ ʀᴇᴛᴏᴜʀ", "settings")])
    return create_inline_kb(buttons)


# ==================== Gestion de l'interface ====================
async def show_setting(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if not await if_user_exist(user_id):
        await add_user(user_id)

    user = await get_or_create_user(user_id)
    settings_dict = await get_current_settings(user_id)

    text = "⚙️ **sᴇᴛᴛɪɴɢs**\n"
    text += f"▫️ **ᴜᴛɪʟɪsᴀᴛᴇᴜʀ:** `{user.first_name or user.user_id}`\n"
    text += f"▫️ **ᴅᴇʀɴɪᴇʀᴇ ᴀᴄᴛɪᴠɪᴛᴇ́:** `{user.last_activity.strftime('%d/%m/%Y %H:%M') if user.last_activity else 'Jamais'}`\n"
    text += f"▫️ **ɴʙ ᴄᴏᴍᴍᴀɴᴅᴇs:** `{user.command_count}`"
    text += f"▫️ **ʟɪᴍɪᴛᴇ ᴊᴏᴜʀɴᴀʟɪᴇʀᴇ:** `{settings_dict['daily_limit']}/{settings_dict['max_file']}MB`\n"

    kbs = create_inline_kb(
        [
            # Section Vidéo
            [(" ↓↓ ᴘᴀʀᴀᴍᴇᴛʀᴇs ᴠɪᴅᴇᴏ ↓↓ ", "none_btn")],
            [
                (
                    f"ᴄᴏᴅᴇᴄ: {stylize_value(settings_dict['video_codec'])}",
                    "set_video_codec",
                ),
                (
                    f"ʀᴇs: {stylize_value(settings_dict['resolution'])}",
                    "set_resolution",
                ),
            ],
            [
                (f"ᴄʀꜰ: {stylize_value(settings_dict['crf'])}", "adjust_crf"),
                (f"ᴘʀᴇsᴇᴛ: {stylize_value(settings_dict['preset'])}", "set_preset"),
            ],
            [
                (f"ᴘɪx ꜰᴍᴛ: {stylize_value(settings_dict['pix_fmt'])}", "set_pix_fmt"),
                (f"ʜᴡᴀᴄᴄᴇʟ: {stylize_value(settings_dict['hwaccel'])}", "set_hwaccel"),
            ],
            [
                (f"ᴛᴜɴᴇ: {stylize_value(settings_dict['tune'])}", "set_tune"),
                (f"ᴀsᴘᴇᴄᴛ: {stylize_value(settings_dict['aspect'])}", "set_aspect"),
            ],
            [
                (f"ᴄᴀʙᴀᴄ: {stylize_value(settings_dict['cabac'])}", "toggle_cabac"),
                (f"ʀᴇғʀᴀᴍᴇ: {stylize_value(settings_dict['reframe'])}", "set_reframe"),
            ],
            # Section Audio
            [(" ↓↓ ᴘᴀʀᴀᴍᴇᴛʀᴇs ᴀᴜᴅɪᴏ ↓↓ ", "none_btn")],
            [
                (
                    f"ᴄᴏᴅᴇᴄ: {stylize_value(settings_dict['audio_codec'])}",
                    "set_audio_codec",
                ),
                (
                    f"ʙɪᴛʀᴀᴛᴇ: {stylize_value(settings_dict['audio_bitrate'])}",
                    "set_audio_bitrate",
                ),
            ],
            [
                (
                    f"ᴘɪsᴛᴇ: {stylize_value(settings_dict['audio_track_action'])}",
                    "set_audio_track",
                ),
                (
                    f"ɴᴏʀᴍ: {stylize_value(settings_dict['normalize_audio'])}",
                    "toggle_normalize",
                ),
            ],
            [
                (
                    f"ᴄʜᴀɴɴᴇʟs: {stylize_value(settings_dict['channels'])}",
                    "set_channels",
                ),
                (
                    f"ᴛʜʀᴇᴀᴅs: {stylize_value(settings_dict['threads'])}",
                    "adjust_threads",
                ),
            ],
            # Section Sous-titres
            [(" ↓↓ ᴘᴀʀᴀᴍᴇᴛʀᴇs sᴏᴜs-ᴛɪᴛʀᴇs ↓↓ ", "none_btn")],
            [
                (
                    f"ᴀᴄᴛɪᴏɴ: {stylize_value(settings_dict['subtitle_action'])}",
                    "set_subaction",
                ),
                (
                    f"ʜᴀʀᴅsᴜʙ: {stylize_value(settings_dict['hardsub'])}",
                    "toggle_hardsub",
                ),
            ],
            [
                (f"sᴜʙs: {stylize_value(settings_dict['subtitles'])}", "toggle_subs"),
                (
                    f"{stylize_value('Subs id:')} {stylize_value(settings_dict['selected_subtitle_track'])}",
                    "set_subs_track",
                ),
            ],
            # Section Autres paramètres
            [(" ↓↓ ᴀᴜᴛʀᴇs ᴘᴀʀᴀᴍᴇᴛʀᴇs ↓↓ ", "none_btn")],
            [
                (f"ғᴏʀᴍᴀᴛ: {stylize_value(settings_dict['extensions'])}", "set_format"),
                (
                    f"ᴜᴘʟᴏᴀᴅ: {'📁 Doc' if settings_dict['upload_as_doc'] else '📄 Video'}",
                    "toggle_uploaddoc",
                ),
            ],
            [
                (
                    f"ᴍᴇᴛᴀᴅᴀᴛᴀ: {stylize_value(settings_dict['metadata'])}",
                    "toggle_metadata",
                ),
                (
                    f"ᴡᴀᴛᴇʀᴍᴀʀᴋ: {stylize_value(settings_dict['watermark'])}",
                    "toggle_watermark",
                ),
            ],
            # Boutons de navigation
            [("↩ ʀᴇᴛᴏᴜʀ ", "start"), ("❌ ғᴇʀᴍᴇʀ ", "close")],
        ]
    )

    await callback_query.message.edit_text(
        text, reply_markup=kbs, parse_mode=ParseMode.MARKDOWN
    )


async def handle_callback_query(client: Client, callback_query: CallbackQuery):
    query_data = callback_query.data
    message = callback_query.message
    user_id = callback_query.from_user.id

    try:
        await callback_query.answer()
    except Exception:
        pass
    if not await if_user_exist(user_id):
        await add_user(user_id)
        logger.info(f"Nouvel utilisateur enregistré: {user_id}")

    try:
        if query_data == "close":
            await callback_query.message.delete()
            if message.reply_to_message:
                try:
                    await message.reply_to_message.delete()
                except Exception:
                    pass
            return

        elif query_data == "help":
            help_text = "📚 **ᴀɪᴅᴇ ᴇᴛ ᴄᴏᴍᴍᴀɴᴅᴇs**\n"
            help_text += "➻ ` /encode ` : ᴇɴᴄᴏᴅᴀɢᴇ ᴠɪᴅᴇ́ᴏ\n"
            help_text += "➻ ` /compress ` : ᴄᴏᴍᴘʀᴇssɪᴏɴ ᴠɪᴅᴇ́ᴏ\n"
            help_text += "➻ ` /merge ` : ғᴜsɪᴏɴɴᴇʀ ᴅᴇs ᴠɪᴅᴇ́ᴏs\n"
            help_text += "➻ ` /split ` : ᴅᴇ́ᴄᴏᴜᴘᴇʀ ᴜɴᴇ ᴠɪᴅᴇ́ᴏ\n"
            help_text += "➻ ` /subs ` : ᴍᴀɴᴀɢᴇᴍᴇɴᴛ sᴏᴜs-ᴛɪᴛʀᴇs\n"
            help_text += "➻ ` /chapters ` : ᴇ́ᴅɪᴛɪᴏɴ ᴅᴇs ᴄʜᴀᴘɪᴛʀᴇs\n"
            help_text += "➻ ` /convert ` : ᴄᴏɴᴠᴇʀsɪᴏɴ ғᴏʀᴍᴀᴛ\n"
            help_text += "➻ ` /leech ` : ᴛᴇ́ʟᴇ́ᴄʜᴬʀɢᴇᴍᴇɴᴛ ᴜʀʟ\n"
            help_text += "➻ ` /encode_uri ` : ᴍᴀɴɪᴘᴜʟᴀᴛɪᴏɴ ᴜʀʟ\n"
            help_text += "ᴘᴏᴜʀ ᴘʟᴜs ᴅ'ɪɴғᴏs : /about"

            kb = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "📢 ᴍɪsᴇs ᴀ ᴊᴏᴜʀs", url="https://t.me/hyoshcoder"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "❓ ᴘʀᴏʙʟᴇ́ᴍᴇs ?", url="https://t.me/hyoshcoder"
                        )
                    ],
                ]
            )
            tkb = concat_kbs([kb, close_kb])
            await callback_query.message.edit_text(
                text=help_text, parse_mode=ParseMode.MARKDOWN, reply_markup=tkb
            )

        elif query_data == "about":
            text = BotMessage.ALL_FUNCTIONS
            await callback_query.message.edit_text(
                text=text, parse_mode=ParseMode.MARKDOWN, reply_markup=close_kb
            )

        elif query_data == "status":
            status_text = "📊 **sᴛᴀᴛᴜs ᴅᴜ ʙᴏᴛ**\n"
            status_text += f"• ᴠᴇʀsɪᴏɴ : `{settings.ISOCODE_VERSION}`\n"
            status_text += f"• ᴜᴘᴛɪᴍᴇ : `{get_uptime()}`"

            try:
                status_text += f"• ᴄʜᴀʀɢᴇ : `{psutil.cpu_percent()}%`\n"
                status_text += f"• ʀᴀᴍ : `{psutil.virtual_memory().percent}%`\n"
            except Exception as e:
                logger.error(f"Erreur psutil: {e}")
                status_text += "• ᴍᴇ́ᴛʀɪϙᴜᴇs sʏsᴛᴇ̀ᴍᴇ : ɪɴᴅɪsᴘᴏɴɪʙʟᴇ"

            await callback_query.message.edit_text(
                text=status_text, parse_mode=ParseMode.MARKDOWN, reply_markup=close_kb
            )

        elif query_data == "settings":
            await show_setting(callback_query)

        elif query_data == "none_btn":
            await callback_query.message.edit_text(
                "Aucune action définie pour ce bouton",
                reply_markup=callback_query.message.reply_markup,
            )

        elif query_data.startswith("adjust_"):
            setting = query_data.replace("adjust_", "")
            current_value = await get_setting(user_id, setting)

            if setting == "crf":
                min_val, max_val, step = 0, 51, 2
                options = [str(i) for i in range(min_val, max_val + 1, step)]
            elif setting == "threads":
                options = [str(i) for i in range(0, 33, 4)]
            elif setting == "daily_limit":
                options = [str(i) for i in range(1, 21)]
            elif setting == "max_file":
                options = [str(i) for i in range(100, 5001, 100)]
            else:
                options = []

            kb = create_adjustment_kb(setting, options, str(current_value))
            text = f"🔧 **Ajustement du paramètre:** `{setting}`"
            text += f"▫️ **Valeur actuelle:** `{current_value}`"
            text += "Sélectionnez une nouvelle valeur:"

            await message.edit_text(
                stylize_value(text), reply_markup=kb, parse_mode=ParseMode.MARKDOWN
            )
            return

        # Gestion des sélections d'options (callback_data: s_<sanitized_setting>::<b64(value)>)
        elif query_data.startswith("s_"):
            body = query_data[2:]
            # On attend maintenant le séparateur '::' entre setting et valeur encodée
            if "::" in body:
                sanitized_setting, raw_enc_value = body.split("::", 1)
                value = _b64decode_value(raw_enc_value)
            else:
                # Fallback (ancienne logique) — utile si d'anciens callback_data existent
                last_underscore = body.rfind("_")
                if last_underscore == -1:
                    await callback_query.message.edit_text(
                        "Format de commande invalide",
                        reply_markup=callback_query.message.reply_markup,
                    )
                    return

                sanitized_setting = body[:last_underscore]
                raw_value = body[last_underscore + 1 :]
                value = raw_value.replace("_", " ")

            # Résoudre le nom réel du paramètre
            setting_name = _resolve_setting_name_from_sanitized(sanitized_setting)

            # verification spéciale pour hwaccel
            if setting_name == "hwaccel":
                available_accels = hw_accel_checker.get_available()
                if value not in available_accels:
                    await callback_query.message.edit_text(
                        f"⚠️ Accélérateur '{value}' non disponible! Réglé sur 'none'.",
                        reply_markup=callback_query.message.reply_markup,
                    )
                    value = "none"

            # Conversion spéciale pour les valeurs numériques
            if setting_name in ["crf", "threads", "daily_limit", "max_file"]:
                try:
                    value = int(value)
                except ValueError:
                    await callback_query.message.edit_text(
                        "Valeur numérique invalide",
                        reply_markup=callback_query.message.reply_markup,
                    )
                    return

            # Gestion AudioCodec enum pour audio_codec
            if setting_name == "audio_codec":
                codec_enum = AudioCodec.normalized_name(value)
                if codec_enum:
                    await set_setting(user_id, setting_name, codec_enum.value)
                else:
                    await set_setting(user_id, setting_name, value)
                await show_setting(callback_query)
                return

            # Sauvegarde normale (fonctionne aussi pour audio_track_action, aspect, ...)
            await set_setting(user_id, setting_name, value)
            await show_setting(callback_query)
            return

        # Toggles pour booléens
        elif query_data.startswith("toggle_"):
            setting_name = query_data.replace("toggle_", "")
            if setting_name == "uploaddoc":
                db_field = "upload_as_doc"
            elif setting_name == "subaction":
                db_field = "subtitle_action"
            elif setting_name == "normalize":
                db_field = "normalize_audio"
            elif setting_name == "hardsub":
                db_field = "hardsub"
            elif setting_name == "subs":
                db_field = "subtitles"
            elif setting_name == "metadata":
                db_field = "metadata"
            elif setting_name == "watermark":
                db_field = "watermark"
            elif setting_name == "cabac":
                db_field = "cabac"
            else:
                db_field = setting_name

            current_value = await get_setting(user_id, db_field)
            logger.info(
                f"Toggle setting: {db_field} for user {user_id}, current value: {current_value}"
            )
            try:
                new_value = not bool(current_value)
            except Exception:
                new_value = not current_value
            await set_setting(user_id, db_field, new_value)
            await show_setting(callback_query)
            return

        # Afficher sous-menu hwaccel
        elif query_data == "set_hwaccel":
            current = await get_hwaccel(user_id)
            available = hw_accel_checker.get_available()
            kb = create_adjustment_kb("hwaccel", available, current)

            text = "🚀 **Accélération matérielle (hwaccel)**\n"
            text += "Utilise le matériel pour accélérer l'encodage.\n"
            text += f"▫️ **Actuel:** `{current}`\n"
            text += f"▫️ **Disponible sur cette machine:**\n"
            for accel in ["cuda", "vaapi", "dxva2", "qsv"]:
                status = "✅" if accel in available else "❌"
                text += f"  - {status} {accel.upper()}"
            text += "Sélectionnez une nouvelle valeur:"

            await message.edit_text(
                stylize_value(text), reply_markup=kb, parse_mode=ParseMode.MARKDOWN
            )
            return

        # Ouvre sous-menus via set_<param>
        elif query_data.startswith("set_"):
            setting_key = query_data.replace("set_", "")
            # Map short keys to real names if present
            setting_name = SETTING_NAME_MAP.get(setting_key, setting_key)

            # cas spéciaux
            if setting_name == "audio_bitrate":
                codec = await get_audio_codec(user_id)
                codec_enum = None
                if isinstance(codec, AudioCodec):
                    codec_enum = codec
                else:
                    codec_enum = AudioCodec.normalized_name(str(codec))

                current = await get_audio_bitrate(user_id)
                if codec_enum:
                    options = codec_enum.supported_bitrates
                else:
                    options = ["64k", "96k", "128k", "192k", "256k", "320k"]

                kb = create_adjustment_kb("audio_bitrate", options, current)
                text = "🎵 **Débit audio (bitrate)**"
                text += "Qualité du son - plus élevé = meilleure qualité"
                text += f"▫️ **Codec:** `{codec}`"
                text += f"▫️ **Actuel:** `{current}`"
                text += "Options disponibles:"
                await message.edit_text(
                    stylize_value(text), reply_markup=kb, parse_mode=ParseMode.MARKDOWN
                )
                return

            if setting_name == "pix_fmt" or setting_key == "pix_fmt":
                current = await get_pix_fmt(user_id)
                kb = create_adjustment_kb("pix_fmt", PIX_FMT_OPTIONS, current)
                text = "🎨 **Format de pixel (pix_fmt)**\n"
                text += "Ce paramètre contrôle le format de couleur utilisé dans la vidéo.\n"
                text += f"▫️ **Actuel:** `{current}`\n"
                text += "Options disponibles:"
                await message.edit_text(
                    stylize_value(text), reply_markup=kb, parse_mode=ParseMode.MARKDOWN
                )
                return

            if setting_name == "channels" or setting_key == "channels":
                current = await get_channels(user_id)
                kb = create_adjustment_kb("channels", CHANNEL_OPTIONS, current)
                text = "🔊 **Configuration des canaux audio**"
                text += "Détermine la configuration des haut-parleurs pour le son."
                text += f"▫️ **Actuel:** `{current}`"
                text += "Options disponibles:"
                await message.edit_text(
                    stylize_value(text), reply_markup=kb, parse_mode=ParseMode.MARKDOWN
                )
                return

            if setting_key in ("subs_track", "set_subs_track", "selected_subtitle_track") or setting_name == "selected_subtitle_track":
                current_track = await get_setting(user_id, "selected_subtitle_track")
                options = [str(i) for i in range(1, 11)]
                kb = create_adjustment_kb("selected_subtitle_track", options, str(current_track))
                text = "📜 **Sélection de la piste de sous-titres**\n"
                text += "Sélectionnez la piste de sous-titres à utiliser (pour l'extraction, l'incorporation ou le hardsub).\n"
                text += f"▫️ **Piste actuelle:** `{current_track}`\n"
                text += "Options disponibles:"
                await message.edit_text(
                    stylize_value(text), reply_markup=kb, parse_mode=ParseMode.MARKDOWN
                )
                return

            # show selection menu for known cycle options (video_codec, audio_codec, subtitle_action, aspect...)
            if setting_name in SETTING_CYCLE_OPTIONS:
                options = SETTING_CYCLE_OPTIONS[setting_name]
                current_value = await get_setting(user_id, setting_name)
                kb = create_adjustment_kb(setting_name, options, current_value)

                text = f"🔧 **{setting_name} — sélection**"
                text += f"▫️ **Actuel:** `{current_value}`"
                text += "Sélectionnez une nouvelle valeur:"

                await message.edit_text(
                    stylize_value(text), reply_markup=kb, parse_mode=ParseMode.MARKDOWN
                )
            else:
                await callback_query.message.edit_text(
                    "Paramètre non configuré",
                    reply_markup=callback_query.message.reply_markup,
                )
            return

        elif query_data == "start":
            await callback_query.message.delete()
            kb = create_inline_kb(
                [
                    [("🛠️ ᴀɪᴅᴇ", "help"), ("❤️‍🩹 ᴀ ᴘʀᴏᴘᴏs", "about")],
                    [("⚙️ ᴘᴀʀᴀᴍᴇ̀ᴛʀᴇs", "settings"), ("📊 sᴛᴀᴛᴜs", "status")],
                ]
            )

            kb1 = create_web_kb(
                {
                    "📢 ᴍɪsᴇs ᴀ ᴊᴏᴜʀs": "https://t.me/hyoshcoder/",
                    "💬 sᴜᴘᴘᴏʀᴛ": "https://t.me/hyoshassistantbot",
                }
            )

            kb2 = create_web_kb({"🧑‍💻 ᴅᴇᴠᴇʟᴏᴘᴇᴜʀ": "https://t.me/hyoshcoder/"})

            kbs = concat_kbs([kb1, kb, kb2, close_kb])
            await send_media(
                client=client,
                media_type="photo",
                chat_id=message.chat.id,
                media=MEDIA_MAP["start"],
                caption=BotMessage.HOMME.format(mention=message.from_user.mention),
                reply_markup=kbs,
                parse_mode=ParseMode.HTML,
                reply_to=message.id,
            )

        elif query_data == "back_settings":
            await show_setting(callback_query)
            return

        else:
            await callback_query.message.edit_text(
                "❌ Action non reconnue ou non implémentée",
                reply_markup=callback_query.message.reply_markup,
            )
            return

    except Exception as e:
        logger.error(f"Callback error: {e}", exc_info=True)
        try:
            await callback_query.message.edit_text(
                "❌ Erreur lors du traitement de la demande",
                reply_markup=callback_query.message.reply_markup,
            )
        except Exception:
            pass
