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
)
from isocode.utils.isoutils.progress import stylize_value
import psutil
import os
import subprocess
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

# Mapping pour raccourcir les noms de paramètres dans callback_data
SHORT_SETTING_MAP = {
    "crf": "crf",
    "threads": "th",
    "daily_limit": "dl",
    "max_file": "mf",
    "pix_fmt": "px",
    "channels": "ch",
    "audio_bitrate": "ab",
}

LONG_SETTING_MAP = {v: k for k, v in SHORT_SETTING_MAP.items()}

# Options pour les paramètres cycliques
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
    "audio_codec": ["aac", "opus", "mp3", "flac", "ac3", "copy"],
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
}

# Mapping des noms courts vers les vrais noms de paramètres
SETTING_NAME_MAP = {
    "format": "extensions",
}

# Cache pour la disponibilité des accélérateurs matériels
_available_hwaccels = None

# ==================== Fonctions de vérification matérielle ====================
def check_cuda_available() -> bool:
    """Vérifie physiquement la présence d'un GPU NVIDIA avec CUDA"""
    try:
        # Vérifie l'existence du périphérique NVIDIA
        if os.path.exists("/dev/nvidia0") or os.path.exists("/dev/nvidiactl"):
            # Vérifie que le driver fonctionne
            result = subprocess.run(
                ["nvidia-smi", "-L"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            return "GPU" in result.stdout
        return False
    except Exception:
        return False

def check_vaapi_available() -> bool:
    """Vérifie physiquement la présence d'un périphérique VA-API"""
    try:
        # Liste les périphériques de rendu
        render_devices = [
            f for f in os.listdir("/dev/dri")
            if f.startswith("renderD")
        ]
        if not render_devices:
            return False

        # Vérifie les permissions sur le premier périphérique
        device = f"/dev/dri/{render_devices[0]}"
        return os.access(device, os.R_OK | os.W_OK)
    except Exception:
        return False

def check_qsv_available() -> bool:
    """Vérifie physiquement la présence d'un périphérique Intel Quick Sync"""
    try:
        # Vérifie les périphériques Intel
        card_devices = [
            f for f in os.listdir("/dev/dri")
            if f.startswith("card")
        ]
        if not card_devices:
            return False

        # Vérifie les permissions sur le premier périphérique
        device = f"/dev/dri/{card_devices[0]}"
        return os.access(device, os.R_OK | os.W_OK)
    except Exception:
        return False

def check_dxva2_available() -> bool:
    """Vérifie si DXVA2 est disponible (Windows uniquement)"""
    try:
        return os.name == "nt"
    except Exception:
        return False

async def get_available_hwaccels() -> list:
    """Récupère la liste des accélérateurs matériels réellement disponibles"""
    global _available_hwaccels

    if _available_hwaccels is not None:
        return _available_hwaccels

    # Toujours disponibles
    available = {"none", "auto"}

    # Vérifications matérielles
    if check_cuda_available():
        available.add("cuda")
    if check_vaapi_available():
        available.add("vaapi")
    if check_qsv_available():
        available.add("qsv")
    if check_dxva2_available():
        available.add("dxva2")

    # Filtre et ordonne les options valides
    valid_hwaccels = ["none", "auto", "cuda", "vaapi", "dxva2", "qsv"]
    _available_hwaccels = [accel for accel in valid_hwaccels if accel in available]

    logger.info(f"Accélérateurs matériels détectés: {_available_hwaccels}")
    return _available_hwaccels

# ==================== Fonctions utilitaires ====================
async def get_current_settings(user_id: int) -> dict:
    """Récupère tous les paramètres actuels de l'utilisateur"""
    # Récupérer une seule fois l'objet User pour éviter de multiples lectures DB
    user = await get_or_create_user(user_id)

    settings_dict = {
        "video_codec": getattr(user, 'video_codec', None).ffmpeg_name if getattr(user, 'video_codec', None) else None,
        "audio_codec": getattr(user, 'audio_codec', None).ffmpeg_name if getattr(user, 'audio_codec', None) else None,
        "preset": getattr(user, 'preset', None).ffmpeg_name if getattr(user, 'preset', None) else None,
        "crf": getattr(user, 'crf', 22),
        "resolution": getattr(user, 'resolution', None).value if getattr(user, 'resolution', None) else None,
        "upload_as_doc": getattr(user, 'upload_as_doc', False),
        "audio_bitrate": getattr(user, 'audio_bitrate', '192k'),
        "threads": getattr(user, 'threads', 0),
        "hwaccel": getattr(user, 'hwaccel', None).ffmpeg_name if getattr(user, 'hwaccel', None) else None,
        "extensions": getattr(user, 'extensions', None).value if getattr(user, 'extensions', None) else None,
        "tune": getattr(user, 'tune', None).ffmpeg_name if getattr(user, 'tune', None) else None,
        "aspect": getattr(user, 'aspect', False),
        "cabac": getattr(user, 'cabac', False),
        "metadata": getattr(user, 'metadata', True),
        "watermark": getattr(user, 'watermark', False),
        "hardsub": getattr(user, 'hardsub', False),
        "subtitles": getattr(user, 'subtitles', True),
        "normalize_audio": getattr(user, 'normalize_audio', True),
        "pix_fmt": getattr(user, 'pix_fmt', 'yuv420p'),
        "channels": getattr(user, 'channels', '2'),
        "reframe": getattr(user, 'reframe', '0'),
        "daily_limit": getattr(user, 'daily_limit', 10),
        "max_file": getattr(user, 'max_file_size', getattr(user, 'max_file', 2000)),
    }

    # Vérifier et corriger hwaccel si nécessaire
    available_accels = await get_available_hwaccels()
    current_hwaccel = settings_dict["hwaccel"]

    if current_hwaccel not in available_accels:
        await set_setting(user_id, "hwaccel", "none")
        settings_dict["hwaccel"] = "none"
        logger.warning(
            f"HWAccel '{current_hwaccel}' non disponible, réglé sur 'none' pour l'utilisateur {user_id}"
        )

    return settings_dict

def create_adjustment_kb(
    setting_name: str, options: list, current_value: str
) -> InlineKeyboardMarkup:
    """Crée un clavier d'ajustement pour un paramètre avec callback_data optimisé"""
    buttons = []
    row = []
    short_name = SHORT_SETTING_MAP.get(setting_name, setting_name[:3])

    for idx, option in enumerate(options):
        # Mettre en évidence la valeur actuelle
        prefix = "• " if option == current_value else ""
        callback_data = f"s_{short_name}_{option.replace(' ', '_')}"

        row.append((f"{prefix}{option}", callback_data))

        # Nouvelle ligne tous les 2-3 éléments
        if (idx + 1) % 3 == 0 or idx == len(options) - 1:
            buttons.append(row)
            row = []

    buttons.append([("↩ ʀᴇᴛᴏᴜʀ", "settings")])
    return create_inline_kb(buttons)


# ==================== Gestion de l'interface ====================
async def show_setting(callback_query: CallbackQuery):
    """Affiche le menu des paramètres avec les valeurs actuelles"""
    user_id = callback_query.from_user.id
    if not await if_user_exist(user_id):
        await add_user(user_id)

    user = await get_or_create_user(user_id)
    settings_dict = await get_current_settings(user_id)

    text = "⚙️ **sᴇᴛᴛɪɴɢs**\n\n"
    text += f"▫️ **ᴜᴛɪʟɪsᴀᴛᴇᴜʀ:** `{user.first_name or user.user_id}`\n"
    text += f"▫️ **ᴅᴇʀɴɪᴇʀᴇ ᴀᴄᴛɪᴠɪᴛᴇ́:** `{user.last_activity.strftime('%d/%m/%Y %H:%M') if user.last_activity else 'Jamais'}`\n"
    text += f"▫️ **ɴʙ ᴄᴏᴍᴍᴀɴᴅᴇs:** `{user.command_count}`\n"
    text += f"▫️ **ʟɪᴍɪᴛᴇ ᴊᴏᴜʀɴᴀʟɪᴇʀᴇ:** `{settings_dict['daily_limit']}/{settings_dict['max_file']}MB`\n\n"

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
                (f"ᴘɪx ꜰᴍᴛ: {stylize_value(settings_dict['pix_fmt'])}", "setpix_fmt"),
                (f"ʜᴡᴀᴄᴄᴇʟ: {stylize_value(settings_dict['hwaccel'])}", "set_hwaccel"),
            ],
            [
                (f"ᴛᴜɴᴇ: {stylize_value(settings_dict['tune'])}", "set_tune"),
                (f"ᴀsᴘᴇᴄᴛ: {stylize_value(settings_dict['aspect'])}", "toggle_aspect"),
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
                    "setaudio_bitrate",
                ),
            ],
            [
                (
                    f"ɴᴏʀᴍ: {stylize_value(settings_dict['normalize_audio'])}",
                    "toggle_normalize",
                ),
                (
                    f"ᴄʜᴀɴɴᴇʟs: {stylize_value(settings_dict['channels'])}",
                    "setchannels",
                ),
            ],
            [
                (
                    f"ᴛʜʀᴇᴀᴅs: {stylize_value(settings_dict['threads'])}",
                    "adjust_threads",
                ),
            ],
            # Section Sous-titres (la sélection se fait maintenant via l'interface interactive par tâche)
            [(" ↓↓ ᴘᴀʀᴀᴍᴇᴛʀᴇs sᴏᴜs-ᴛɪᴛʀᴇs ↓↓ ", "none_btn")],
            [
                (f"sᴜʙs ᴇᴍʙᴇᴅ: {stylize_value(settings_dict['subtitles'])}", "toggle_subs"),
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

@Client.on_callback_query()
async def handle_callback_query(client: Client, callback_query: CallbackQuery):
    """Handle callback queries from inline keyboards."""
    query_data = callback_query.data
    message = callback_query.message
    user_id = callback_query.from_user.id

    # ── Délégation prioritaire aux callbacks de sélection de pistes ──────────
    if query_data and query_data.startswith("trk_"):
        from isocode.plugins.track_selection import handle_track_callback
        await handle_track_callback(client, callback_query)
        return
    # ─────────────────────────────────────────────────────────────────────────

    if not await if_user_exist(user_id):
        await add_user(user_id)
        logger.info(f"Nouvel utilisateur enregistré: {user_id}")

    # Précharger l'objet user et les settings pour éviter plusieurs appels DB
    user = await get_or_create_user(user_id)
    settings_dict = await get_current_settings(user_id)

    try:
        if query_data == "close":
            await callback_query.message.delete()

            if message.reply_to_message:
                try:
                    await message.reply_to_message.delete()
                except Exception as e:
                    logger.warning(f"Failed to delete replied-to message: {e}")
            return

        elif query_data == "help":
            help_text = "📚 **ᴀɪᴅᴇ ᴇᴛ ᴄᴏᴍᴍᴀɴᴅᴇs**\n\n"
            help_text += "➻ ` /encode ` : ᴇɴᴄᴏᴅᴀɢᴇ ᴠɪᴅᴇ́ᴏ\n"
            help_text += "➻ ` /compress ` : ᴄᴏᴍᴘʀᴇssɪᴏɴ ᴠɪᴅᴇ́ᴏ\n"
            help_text += "➻ ` /merge ` : ғᴜsɪᴏɴɴᴇʀ ᴅᴇs ᴠɪᴅᴇ́ᴏs\n"
            help_text += "➻ ` /split ` : ᴅᴇ́ᴄᴏᴜᴘᴇʀ ᴜɴᴇ ᴠɪᴅᴇ́ᴏ\n"
            help_text += "➻ ` /subs ` : ᴍᴀɴᴀɢᴇᴍᴇɴᴛ sᴏᴜs-ᴛɪᴛʀᴇs\n"
            help_text += "➻ ` /chapters ` : ᴇ́ᴅɪᴛɪᴏɴ ᴅᴇs ᴄʜᴀᴘɪᴛʀᴇs\n"
            help_text += "➻ ` /convert ` : ᴄᴏɴᴠᴇʀsɪᴏɴ ғᴏʀᴍᴀᴛ\n"
            help_text += "➻ ` /leech ` : ᴛᴇ́ʟᴇ́ᴄʜᴀʀɢᴇᴍᴇɴᴛ ᴜʀʟ\n"
            help_text += "➻ ` /encode_uri ` : ᴍᴀɴɪᴘᴜʟᴀᴛɪᴏɴ ᴜʀʟ\n\n"
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
            status_text = "📊 **sᴛᴀᴛᴜs ᴅᴜ ʙᴏᴛ**\n\n"
            status_text += f"• ᴠᴇʀsɪᴏɴ : `{settings.ISOCODE_VERSION}`\n"
            status_text += f"• ᴜᴘᴛɪᴍᴇ : `{get_uptime()}`\n"

            try:
                status_text += f"• ᴄʜᴀʀɢᴇ : `{psutil.cpu_percent()}%`\n"
                status_text += f"• ʀᴀᴍ : `{psutil.virtual_memory().percent}%`"
            except Exception as e:
                logger.error(f"Erreur psutil: {e}")
                status_text += "• ᴍᴇ́ᴛʀɪϙᴜᴇs sʏsᴛᴇ̀ᴍᴇ : ɪɴᴅɪsᴘᴏɴɪʙʟᴇ"

            await callback_query.message.edit_text(
                text=status_text, parse_mode=ParseMode.MARKDOWN, reply_markup=close_kb
            )

        elif query_data == "settings":
            await show_setting(callback_query)

        elif query_data == "none_btn":
            await callback_query.answer(
                "Aucune action définie pour ce bouton", show_alert=True
            )

        elif query_data.startswith("adjust_"):
            setting = query_data.replace("adjust_", "")
            current_value = settings_dict.get(setting)

            # Détermine les options en fonction du paramètre
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
            text = f"🔧 **Ajustement du paramètre:** `{setting}`\n"
            text += f"▫️ **Valeur actuelle:** `{current_value}`\n\n"
            text += "Sélectionnez une nouvelle valeur:"

            await message.edit_text(
                stylize_value(text), reply_markup=kb, parse_mode=ParseMode.MARKDOWN
            )
            return

        # Gestion des sélections d'options avec callback_data optimisé
        elif query_data.startswith("s_"):
            parts = query_data.split("_", 2)
            if len(parts) < 3:
                await callback_query.answer(
                    "Format de commande invalide", show_alert=True
                )
                return

            short_name = parts[1]
            value = parts[2].replace("_", " ")
            setting_name = LONG_SETTING_MAP.get(short_name, short_name)

            # Vérification spéciale pour hwaccel
            if setting_name == "hwaccel":
                available_accels = await get_available_hwaccels()
                if value not in available_accels:
                    value = "none"
                    await callback_query.answer(
                        f"⚠️ Accélérateur '{value}' non disponible! Réglé sur 'none'.",
                        show_alert=True
                    )

            # Conversion spéciale pour les valeurs numériques
            if setting_name in ["crf", "threads", "daily_limit", "max_file"]:
                try:
                    value = int(value)
                except ValueError:
                    await callback_query.answer(
                        "Valeur numérique invalide", show_alert=True
                    )
                    return

            await set_setting(user_id, setting_name, value)
            await callback_query.answer(
                f"✅ Paramètre mis à jour: {setting_name} = {value}"
            )
            await show_setting(callback_query)
            return

        # Gestion des bascules (toggle)
        elif query_data.startswith("toggle_"):
            setting_name = query_data.replace("toggle_", "")
            if setting_name == "uploaddoc":
                db_field = "upload_as_doc"
            elif setting_name == "subaction":
                db_field = "subtitle_action"
            elif setting_name == "normalize":
                db_field = "normalize_audio"
            else:
                db_field = setting_name
            current_value = settings_dict.get(db_field)
            logger.info(
                f"Toggle setting: {db_field} for user {user_id}, current value: {current_value}"
            )
            new_value = not current_value
            await set_setting(user_id, db_field, new_value)

            status = "activé" if new_value else "désactivé"
            await callback_query.answer(f"✅ {setting_name.capitalize()} {status}")
            await show_setting(callback_query)
            return

        # Gestion spéciale pour hwaccel
        elif query_data == "set_hwaccel":
            current = settings_dict.get("hwaccel")
            available = await get_available_hwaccels()
            kb = create_adjustment_kb("hwaccel", available, current)

            # Créer le texte informatif
            text = "🚀 **Accélération matérielle (hwaccel)**\n\n"
            text += "Utilise le matériel pour accélérer l'encodage.\n\n"
            text += f"▫️ **Actuel:** `{current}`\n"
            text += f"▫️ **Disponible sur cette machine:**\n"

            # Ajouter des icônes pour chaque accélérateur
            for accel in ["cuda", "vaapi", "dxva2", "qsv"]:
                status = "✅" if accel in available else "❌"
                text += f"  - {status} {accel.upper()}\n"

            text += "\nSélectionnez une nouvelle valeur:"

            await message.edit_text(
                stylize_value(text), reply_markup=kb, parse_mode=ParseMode.MARKDOWN
            )
            return

        elif query_data.startswith("set_"):
            setting_key = query_data.replace("set_", "")

            setting_name = SETTING_NAME_MAP.get(setting_key, setting_key)

            if setting_name in SETTING_CYCLE_OPTIONS:
                options = SETTING_CYCLE_OPTIONS[setting_name]
                current_value = settings_dict.get(setting_name)

                try:
                    idx = options.index(current_value)
                    next_idx = (idx + 1) % len(options)
                    new_value = options[next_idx]
                except ValueError:
                    new_value = options[0]

                await set_setting(user_id, setting_name, new_value)
                await callback_query.answer(f"✅ {setting_name} = {new_value}")
                await show_setting(callback_query)
            else:
                await callback_query.answer("Paramètre non configuré", show_alert=True)

        # Actions spéciales pour les paramètres complexes
        elif query_data == "setpix_fmt":
            current = settings_dict.get("pix_fmt")
            kb = create_adjustment_kb("pix_fmt", PIX_FMT_OPTIONS, current)
            text = "🎨 **Format de pixel (pix_fmt)**\n\n"
            text += (
                "Ce paramètre contrôle le format de couleur utilisé dans la vidéo.\n"
            )
            text += f"▫️ **Actuel:** `{current}`\n\n"
            text += "Options disponibles:"
            await message.edit_text(
                stylize_value(text), reply_markup=kb, parse_mode=ParseMode.MARKDOWN
            )
            return

        elif query_data == "setchannels":
            current = settings_dict.get("channels")
            kb = create_adjustment_kb("channels", CHANNEL_OPTIONS, current)
            text = "🔊 **Configuration des canaux audio**\n\n"
            text += "Détermine la configuration des haut-parleurs pour le son.\n"
            text += f"▫️ **Actuel:** `{current}`\n\n"
            text += "Options disponibles:"
            await message.edit_text(
                stylize_value(text), reply_markup=kb, parse_mode=ParseMode.MARKDOWN
            )
            return

        elif query_data == "setaudio_bitrate":
            codec = settings_dict.get("audio_codec")
            current = settings_dict.get("audio_bitrate")

            # Options spécifiques au codec
            if codec == AudioCodec.OPUS:
                options = ["32k", "64k", "96k", "128k", "192k", "256k"]
            else:
                options = ["64k", "96k", "128k", "192k", "256k", "320k"]

            kb = create_adjustment_kb("audio_bitrate", options, current)
            text = "🎵 **Débit audio (bitrate)**\n\n"
            text += "Qualité du son - plus élevé = meilleure qualité\n"
            text += f"▫️ **Codec:** `{codec}`\n"
            text += f"▫️ **Actuel:** `{current}`\n\n"
            text += "Options disponibles:"
            await message.edit_text(
                stylize_value(text), reply_markup=kb, parse_mode=ParseMode.MARKDOWN
            )
            return


        elif query_data == "start":
            await callback_query.message.delete()
            kb = create_inline_kb(
                [
                    [("🛠️ ᴀɪᴅᴇ", "help"), ("❤️‍🩹 ᴀ ᴘʀᴏᴘᴏs", "about")],
                    [("⚙️ ᴘᴀʀᴀᴍᴇ̀ᴛʀᴇs", "settings"), ("📊 sᴛᴀᴛᴜs", "status")]
                ]
            )

            kb1 = create_web_kb(
                {
                    "📢 ᴍɪsᴇs ᴀ ᴊᴏᴜʀs": "https://t.me/hyoshcoder/",
                    "💬 sᴜᴘᴘᴏʀᴛ": "https://t.me/hyoshassistantbot"
                }
            )

            kb2 = create_web_kb(
                {"🧑‍💻 ᴅᴇᴠᴇʟᴏᴘᴇᴜʀ": "https://t.me/hyoshcoder/"}
            )

            kbs = concat_kbs([kb1, kb, kb2, close_kb])
            await send_media(
            client=client,
            media_type="photo",
            chat_id=message.chat.id,
            media=MEDIA_MAP["start"],
            caption=BotMessage.HOMME.format(mention=message.from_user.mention),
            reply_markup=kbs,
            parse_mode=ParseMode.HTML,
            reply_to=message.id
        )

        elif query_data == "back_settings":
            await show_setting(callback_query)
            return

        else:
            await callback_query.answer(
                "❌ Action non reconnue ou non implémentée", show_alert=True
            )
            return

    except Exception as e:
        logger.error(f"Callback error: {e}", exc_info=True)
        await callback_query.answer(
            "❌ Erreur lors du traitement de la demande", show_alert=True
        )

    await callback_query.answer()