"""
track_selection.py
==================
Gestion de la sélection interactive des pistes audio et sous-titres.

Flux :
  1. handle_video envoie la vidéo → téléchargement immédiat (encoder_flow)
  2. État 0 : Réglages de la tâche (CRF, Codec, Res, etc.) spécifiquement pour ce fichier
  3. MediaInfo analyse en profondeur le fichier local → listes des pistes
  4. État 1 : l'utilisateur choisit quelles pistes audio garder + laquelle est par défaut
  5. État 2 : l'utilisateur choisit quelles pistes sous-titres garder + laquelle est
             par défaut + laquelle hardsub
  6. Bouton "Confirmer" → la tâche est ajoutée au queue_system
"""

import asyncio
import os
import time
from typing import Any, Dict, List, Optional

from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from isocode import logger, download_dir
from isocode.utils.isoutils.progress import stylize_value
from isocode.utils.telegram.message import edit_msg, send_msg
from isocode.plugins.data import SETTING_CYCLE_OPTIONS


SELECTION_TIMEOUT = 150  # 2 minutes 30 secondes

# ─── Stockage des sessions de sélection en mémoire ─────────────────────────────
# { message_id : session_dict }
_sessions: Dict[int, Dict[str, Any]] = {}


# ─── Analyse des pistes via ffprobe ────────────────────────────────────────────

async def probe_with_mediainfo(file_path: str) -> Dict[str, List[Dict]]:
    """
    Analyse profonde d'un fichier avec MediaInfo (via pymediainfo).
    Bien supérieur à ffprobe pour les pistes MKA internes, TrueHD, DTS-MA, etc.

    Retourne { 'audio': [...], 'subtitle': [...] }
    """
    try:
        from pymediainfo import MediaInfo

        # L'analyse MediaInfo est synchrone — on la lance dans un executor
        loop = asyncio.get_event_loop()
        media_info: MediaInfo = await loop.run_in_executor(
            None, MediaInfo.parse, file_path
        )

        audio_tracks: List[Dict] = []
        subtitle_tracks: List[Dict] = []

        # MediaInfo numérote ses pistes par type (Audio #1, Audio #2...)
        # On calcule l'index FFmpeg global (stream index) en parcourant
        # toutes les pistes dans l'ordre MediaInfo
        ffmpeg_index = 0
        for track in media_info.tracks:
            track_type = track.track_type

            # Sauter la piste "General" et "Video"
            if track_type == "General":
                continue
            if track_type == "Video":
                ffmpeg_index += 1
                continue

            if track_type == "Audio":
                # Récupérer un maximum de méta
                info = {
                    "index": ffmpeg_index,  # index global ffmpeg (pour -map 0:N)
                    "mediainfo_id": track.track_id,
                    "codec": track.format or "?",
                    "profile": track.format_profile or "",
                    "channels": track.channel_s or "",
                    "channel_layout": track.channel_layout or "",
                    "language": (track.language or "und").lower()[:3],
                    "title": track.title or "",
                    "default": track.default == "Yes",
                    "forced": track.forced == "Yes",
                    "bit_depth": track.bit_depth or "",
                    "sampling_rate": track.sampling_rate or "",
                    "bitrate": track.bit_rate or "",
                    "compression": track.compression_mode or "",
                }
                # Label affiché dans l'interface Telegram
                info["label"] = _build_audio_label(info)
                audio_tracks.append(info)
                ffmpeg_index += 1

            elif track_type == "Text":
                info = {
                    "index": ffmpeg_index,
                    "mediainfo_id": track.track_id,
                    "codec": track.format or "?",
                    "language": (track.language or "und").lower()[:3],
                    "title": track.title or "",
                    "default": track.default == "Yes",
                    "forced": track.forced == "Yes",
                }
                info["label"] = _build_subtitle_label(info)
                subtitle_tracks.append(info)
                ffmpeg_index += 1

            else:
                # Image tracks, Menu, etc.
                ffmpeg_index += 1

        logger.info(
            f"MediaInfo → {len(audio_tracks)} pistes audio, "
            f"{len(subtitle_tracks)} pistes sous-titres dans {os.path.basename(file_path)}"
        )
        return {"audio": audio_tracks, "subtitle": subtitle_tracks}

    except ImportError:
        logger.error("pymediainfo n'est pas installé — pip install pymediainfo")
        return {"audio": [], "subtitle": []}
    except Exception as e:
        logger.error(f"probe_with_mediainfo error: {e}")
        return {"audio": [], "subtitle": []}


def _build_audio_label(t: Dict) -> str:
    """Construit un label lisible pour une piste audio à partir des méta MediaInfo."""
    parts = []

    lang = t["language"].upper() if t["language"] != "und" else "?"
    parts.append(f"#{t['index']} [{lang}]")

    codec = t["codec"]
    profile = t["profile"]
    if profile:
        parts.append(stylize_value(f"{codec} {profile}"))
    else:
        parts.append(stylize_value(codec))

    if t["channels"]:
        ch = str(t["channels"])
        layout = t["channel_layout"]
        parts.append(stylize_value(f"{ch}ch") + (f" ({layout})" if layout else ""))

    if t["compression"]:
        parts.append(stylize_value(t["compression"]))

    if t["title"]:
        parts.append(f'"{t["title"]}"')

    markers = []
    if t["default"]:
        markers.append(stylize_value("Default"))
    if t["forced"]:
        markers.append(stylize_value("Forced"))
    if markers:
        parts.append(" ".join(markers))

    return " · ".join(parts)


def _build_subtitle_label(t: Dict) -> str:
    """Construit un label lisible pour une piste sous-titre."""
    parts = []

    lang = t["language"].upper() if t["language"] != "und" else "?"
    parts.append(f"#{t['index']} [{lang}]")
    parts.append(stylize_value(t["codec"]))

    if t["title"]:
        parts.append(f'"{t["title"]}"')

    markers = []
    if t["default"]:
        markers.append(stylize_value("Default"))
    if t["forced"]:
        markers.append(stylize_value("Forced"))
    if markers:
        parts.append(" ".join(markers))

    return " · ".join(parts)


# ─── Construction des claviers ──────────────────────────────────────────────────

def _settings_keyboard(session: Dict) -> InlineKeyboardMarkup:
    """Génère le clavier des réglages de tâche (État 0)."""
    s = session["user_settings"]

    def btn(text, key):
        return InlineKeyboardButton(text, callback_data=f"trk_cfg_{key}")

    rows = [
        [
            btn(f"ᴄᴏᴅᴇᴄ: {stylize_value(s.get('video_codec', 'libx265'))}", "video_codec"),
            btn(f"ʀᴇs: {stylize_value(s.get('resolution', 'original'))}", "resolution"),
        ],
        [
            btn(f"ᴘʀᴇsᴇᴛ: {stylize_value(s.get('preset', 'medium'))}", "preset"),
            btn(f"ᴄʀғ: {stylize_value(str(s.get('crf', 22)))}", "crf"),
        ],
        [
            btn(f"ᴀ-ᴄᴏᴅᴇᴄ: {stylize_value(s.get('audio_codec', 'aac'))}", "audio_codec"),
            btn(f"ʙɪᴛʀᴀᴛᴇ: {stylize_value(s.get('audio_bitrate', '192k'))}", "audio_bitrate"),
        ],
        [
            btn(f"ɴᴏʀᴍ: {stylize_value('On' if s.get('normalize_audio') else 'Off')}", "normalize_audio"),
            btn(f"ᴄʜᴀɴ: {stylize_value(s.get('channels', 'stereo'))}", "channels"),
        ],
        [
            InlineKeyboardButton(text=stylize_value("✅ Valider Réglages → Pistes"), callback_data="trk_cfg_confirm"),
        ]
    ]
    return InlineKeyboardMarkup(rows)


def _settings_text(session: Dict) -> str:
    text = (
        "⚙️ **Étape 0 / 2 — Réglages de la Tâche**\n\n"
        f"📁 `{session['filename']}`\n\n"
        "_Ajustez les paramètres d'encodage pour ce fichier spécifique._\n"
        "_Ces réglages ne modifient pas vos paramètres globaux._"
    )
    return stylize_value(text)


def _audio_keyboard(session: Dict) -> InlineKeyboardMarkup:
    """Génère le clavier de sélection des pistes audio (État 1)."""
    audio_tracks: List[Dict] = session["audio_tracks"]
    kept: List[int] = session["audio_kept"]       # indices globaux
    default_idx: Optional[int] = session["audio_default"]

    rows: List[List[InlineKeyboardButton]] = []

    for t in audio_tracks:
        idx = t["index"]
        # Utiliser le label riche construit par MediaInfo
        label = t.get("label") or f"#{idx} [{t['language'].upper()}] {t['codec']}"

        is_kept = idx in kept
        is_default = idx == default_idx

        keep_btn = InlineKeyboardButton(
            text=f"{'✅' if is_kept else '☐'} Garder",
            callback_data=f"trk_a_keep_{idx}",
        )
        default_btn = InlineKeyboardButton(
            text=f"{'⭐' if is_default else '☆'} Défaut",
            callback_data=f"trk_a_def_{idx}",
        )

        rows.append([InlineKeyboardButton(text=label, callback_data="trk_noop")])
        rows.append([keep_btn, default_btn])

    # Bouton confirmer
    rows.append([
        InlineKeyboardButton(text=stylize_value("✅ Confirmer → Sous-titres"), callback_data="trk_a_confirm"),
    ])
    rows.append([
        InlineKeyboardButton(text=stylize_value("⏭ Passer (tout garder)"), callback_data="trk_a_skip"),
    ])

    return InlineKeyboardMarkup(rows)


def _subtitle_keyboard(session: Dict) -> InlineKeyboardMarkup:
    """Génère le clavier de sélection des pistes de sous-titres (État 2)."""
    sub_tracks: List[Dict] = session["sub_tracks"]
    kept: List[int] = session["sub_kept"]
    default_idx: Optional[int] = session["sub_default"]
    hardsub_idx: Optional[int] = session["sub_hardsub"]

    rows: List[List[InlineKeyboardButton]] = []

    for t in sub_tracks:
        idx = t["index"]
        # Utiliser le label riche construit par MediaInfo
        label = t.get("label") or f"#{idx} [{t['language'].upper()}] {t['codec']}"

        is_kept = idx in kept
        is_default = idx == default_idx
        is_hardsub = idx == hardsub_idx

        keep_btn = InlineKeyboardButton(
            text=f"{'✅' if is_kept else '☐'} Garder",
            callback_data=f"trk_s_keep_{idx}",
        )
        default_btn = InlineKeyboardButton(
            text=f"{'⭐' if is_default else '☆'} Défaut",
            callback_data=f"trk_s_def_{idx}",
        )
        hardsub_btn = InlineKeyboardButton(
            text=f"{'🔥' if is_hardsub else '○'} Hardsub",
            callback_data=f"trk_s_hard_{idx}",
        )

        rows.append([InlineKeyboardButton(text=label, callback_data="trk_noop")])
        rows.append([keep_btn, default_btn, hardsub_btn])

    if not sub_tracks:
        rows.append([
            InlineKeyboardButton(text="ℹ️ Aucun sous-titre détecté", callback_data="trk_noop")
        ])

    rows.append([
        InlineKeyboardButton(text=stylize_value("🚀 Confirmer & Encoder"), callback_data="trk_s_confirm"),
    ])
    rows.append([
        InlineKeyboardButton(text=stylize_value("⏭ Passer (aucun sous-titre)"), callback_data="trk_s_skip"),
    ])

    return InlineKeyboardMarkup(rows)


def _audio_text(session: Dict) -> str:
    kept = session["audio_kept"]
    default_idx = session["audio_default"]
    total = len(session["audio_tracks"])
    text = (
        "🎵 **Étape 1 / 2 — Pistes Audio**\n\n"
        f"📁 `{session['filename']}`\n\n"
        f"**{total}** piste(s) détectée(s) — "
        f"**{len(kept)}** sélectionnée(s)\n"
    )
    if default_idx is not None:
        text += f"⭐ Piste par défaut : `#{default_idx}`\n"
    text += "\n_Sélectionnez les pistes à conserver et définissez la piste par défaut._"
    return stylize_value(text)


def _subtitle_text(session: Dict) -> str:
    kept = session["sub_kept"]
    default_idx = session["sub_default"]
    hardsub_idx = session["sub_hardsub"]
    total = len(session["sub_tracks"])
    text = (
        "📜 **Étape 2 / 2 — Sous-titres**\n\n"
        f"📁 `{session['filename']}`\n\n"
        f"**{total}** piste(s) détectée(s) — "
        f"**{len(kept)}** sélectionnée(s)\n"
    )
    if default_idx is not None:
        text += f"⭐ Défaut : `#{default_idx}`\n"
    if hardsub_idx is not None:
        text += f"🔥 Hardsub : `#{hardsub_idx}`\n"
    text += "\n_Cochez les pistes à intégrer. Hardsub incrustera les sous-titres dans la vidéo._"
    return stylize_value(text)

# ─── Démarrage de la session ────────────────────────────────────────────────────

async def start_track_selection(
    client: Client,
    message: Message,
    status_msg: Message,
    task_data: Dict[str, Any],
) -> None:
    """
    Point d'entrée appelé depuis encoder_flow après téléchargement.
    Affiche d'abord les réglages de la tâche (Étape 0).
    """
    user_id = message.from_user.id
    filename = task_data.get("filename", "video.mkv")
    file_path = task_data["filepath"]

    # Initialisation de la session
    session: Dict[str, Any] = {
        "state": "settings",         # "settings" | "audio" | "subtitle"
        "filename": filename,
        "file_path": file_path,
        "task_data": task_data,
        "user_settings": task_data.get("user_settings", {}).copy(), # copie pour modif locale
        "audio_tracks": [],
        "audio_kept": [],
        "audio_default": None,
        "sub_tracks": [],
        "sub_kept": [],
        "sub_default": None,
        "sub_hardsub": None,
        "status_msg_id": status_msg.id,
        "chat_id": message.chat.id,
        "client": client,
        "message": message,
        "expires_at": time.time() + SELECTION_TIMEOUT,
    }

    _sessions[status_msg.id] = session

    # Planifier le timeout
    asyncio.create_task(_timeout_watcher(client, status_msg.id, status_msg.id, message.chat.id))

    # Afficher l'État 0 (Réglages)
    await status_msg.edit_text(
        _settings_text(session),
        reply_markup=_settings_keyboard(session),
        parse_mode=ParseMode.MARKDOWN,
    )


# ─── Logique de cycle des paramètres ──────────────────────────────────────────


def _cycle_setting(current_val: str, key: str) -> str:
    options = SETTING_CYCLE_OPTIONS.get(key, [])
    if not options:
        return current_val
    try:
        idx = options.index(current_val)
        return options[(idx + 1) % len(options)]
    except ValueError:
        return options[0]


# ─── Timeout watcher ───────────────────────────────────────────────────────────

async def _timeout_watcher(client: Client, session_key: int, msg_id: int, chat_id: int) -> None:
    """Annule la session si l'utilisateur ne répond pas dans le délai imparti."""
    await asyncio.sleep(SELECTION_TIMEOUT + 2)
    session = _sessions.get(session_key)
    if session and session["status_msg_id"] == msg_id:
        _sessions.pop(session_key, None)
        try:
            await edit_msg(
                client, chat_id, msg_id,
                stylize_value("⏰ **Sélection expirée** — tâche annulée.\n_Renvoyez le fichier pour recommencer._"),
                parse=ParseMode.MARKDOWN,
            )
        except Exception:
            pass


# ─── Callback handler (doit être enregistré dans __init__ / main) ───────────────

async def handle_track_callback(client: Client, callback_query: CallbackQuery) -> bool:
    """
    Traite les callbacks `trk_*`.
    Retourne True si le callback a été consommé, False sinon.
    """
    data = callback_query.data or ""
    if not data.startswith("trk_"):
        return False

    message_id = callback_query.message.id
    session = _sessions.get(message_id)

    if not session:
        await callback_query.answer("⏰ Session expirée ou introuvable.", show_alert=True)
        return True

    # Rafraîchir le timeout
    session["expires_at"] = time.time() + SELECTION_TIMEOUT

    # ── No-op ──
    if data == "trk_noop":
        await callback_query.answer()
        return True

    # ────────────── État 0 : Réglages ──────────────
    if session["state"] == "settings":
        if data == "trk_cfg_confirm":
            # Passer à l'étape suivante : Analyse et Sélection Audio
            session["state"] = "audio"
            
            await callback_query.message.edit_text(
                stylize_value(f"🔍 **Analyse MediaInfo en cours...**\n\n📁 `{session['filename']}`"),
                parse_mode=ParseMode.MARKDOWN
            )

            tracks = await probe_with_mediainfo(session["file_path"])
            session["audio_tracks"] = tracks["audio"]
            session["sub_tracks"] = tracks["subtitle"]
            session["audio_kept"] = [t["index"] for t in tracks["audio"]]
            session["audio_default"] = tracks["audio"][0]["index"] if tracks["audio"] else None
            session["sub_default"] = tracks["subtitle"][0]["index"] if tracks["subtitle"] else None

            await callback_query.message.edit_text(
                _audio_text(session),
                reply_markup=_audio_keyboard(session),
                parse_mode=ParseMode.MARKDOWN
            )
            await callback_query.answer("✅ Réglages confirmés")
            return True

        # Gestion des cycles de réglages
        key = data.replace("trk_cfg_", "")
        s = session["user_settings"]

        if key == "crf":
            current = s.get("crf", 22)
            # Cycle simple pour le CRF en mode rapide
            options = [18, 20, 22, 24, 26, 28]
            try:
                idx = options.index(int(current))
                s["crf"] = options[(idx + 1) % len(options)]
            except:
                s["crf"] = 22
        elif key == "normalize_audio":
            s["normalize_audio"] = not s.get("normalize_audio", True)
        elif key == "audio_bitrate":
            options = ["128k", "192k", "256k", "320k"]
            curr = s.get("audio_bitrate", "192k")
            try:
                idx = options.index(curr)
                s["audio_bitrate"] = options[(idx + 1) % len(options)]
            except:
                s["audio_bitrate"] = "192k"
        elif key == "channels":
            from isocode.plugins.data import CHANNEL_OPTIONS
            curr = s.get("channels", "stereo")
            try:
                idx = CHANNEL_OPTIONS.index(curr)
                s["channels"] = CHANNEL_OPTIONS[(idx + 1) % len(CHANNEL_OPTIONS)]
            except:
                s["channels"] = "stereo"
        else:
            # Cycle standard via SETTING_CYCLE_OPTIONS
            s[key] = _cycle_setting(s.get(key), key)

        await callback_query.message.edit_text(
            _settings_text(session),
            reply_markup=_settings_keyboard(session),
            parse_mode=ParseMode.MARKDOWN
        )
        await callback_query.answer()
        return True

    # ────────────── État 1 : Audio ──────────────
    if session["state"] == "audio":

        if data.startswith("trk_a_keep_"):
            idx = int(data.split("_")[-1])
            if idx in session["audio_kept"]:
                session["audio_kept"].remove(idx)
                # Si c'était le défaut, reset
                if session["audio_default"] == idx:
                    remaining = session["audio_kept"]
                    session["audio_default"] = remaining[0] if remaining else None
            else:
                session["audio_kept"].append(idx)
            await callback_query.answer()

        elif data.startswith("trk_a_def_"):
            idx = int(data.split("_")[-1])
            # S'assurer qu'elle est dans la liste "kept"
            if idx not in session["audio_kept"]:
                session["audio_kept"].append(idx)
            session["audio_default"] = idx
            await callback_query.answer(f"⭐ Piste #{idx} définie par défaut")

        elif data == "trk_a_confirm":
            if not session["audio_kept"]:
                await callback_query.answer("⚠️ Sélectionnez au moins une piste audio !", show_alert=True)
                return True
            session["state"] = "subtitle"
            await callback_query.message.edit_text(
                _subtitle_text(session),
                reply_markup=_subtitle_keyboard(session),
                parse_mode=ParseMode.MARKDOWN,
            )
            await callback_query.answer("✅ Pistes audio confirmées")
            return True

        elif data == "trk_a_skip":
            # Garder toutes les pistes audio
            session["audio_kept"] = [t["index"] for t in session["audio_tracks"]]
            if session["audio_tracks"]:
                session["audio_default"] = session["audio_tracks"][0]["index"]
            session["state"] = "subtitle"
            await callback_query.message.edit_text(
                _subtitle_text(session),
                reply_markup=_subtitle_keyboard(session),
                parse_mode=ParseMode.MARKDOWN,
            )
            await callback_query.answer("⏭ Toutes les pistes audio gardées")
            return True

        # Rafraîchir le clavier État 1
        try:
            await callback_query.message.edit_text(
                _audio_text(session),
                reply_markup=_audio_keyboard(session),
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass

    # ────────────── État 2 : Sous-titres ──────────────
    elif session["state"] == "subtitle":

        if data.startswith("trk_s_keep_"):
            idx = int(data.split("_")[-1])
            if idx in session["sub_kept"]:
                session["sub_kept"].remove(idx)
                if session["sub_default"] == idx:
                    session["sub_default"] = session["sub_kept"][0] if session["sub_kept"] else None
                if session["sub_hardsub"] == idx:
                    session["sub_hardsub"] = None
            else:
                session["sub_kept"].append(idx)
            await callback_query.answer()

        elif data.startswith("trk_s_def_"):
            idx = int(data.split("_")[-1])
            if idx not in session["sub_kept"]:
                session["sub_kept"].append(idx)
            session["sub_default"] = idx
            await callback_query.answer(f"⭐ Sous-titre #{idx} défini par défaut")

        elif data.startswith("trk_s_hard_"):
            idx = int(data.split("_")[-1])
            if session["sub_hardsub"] == idx:
                # Désactiver le hardsub
                session["sub_hardsub"] = None
                await callback_query.answer("🔥 Hardsub désactivé")
            else:
                if idx not in session["sub_kept"]:
                    session["sub_kept"].append(idx)
                session["sub_hardsub"] = idx
                await callback_query.answer(f"🔥 Hardsub sur piste #{idx}")

        elif data in ("trk_s_confirm", "trk_s_skip"):
            if data == "trk_s_skip":
                session["sub_kept"] = []
                session["sub_default"] = None
                session["sub_hardsub"] = None

            await _finalize_and_enqueue(client, callback_query, session, message_id)
            return True

        # Rafraîchir le clavier État 2
        try:
            await callback_query.message.edit_text(
                _subtitle_text(session),
                reply_markup=_subtitle_keyboard(session),
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass

    return True


# ─── Finalisation et ajout à la file ───────────────────────────────────────────

async def _finalize_and_enqueue(
    client: Client,
    callback_query: CallbackQuery,
    session: Dict[str, Any],
    session_key: int,
) -> None:
    """Prépare task_data avec les sélections et l'envoie au queue_system."""
    from isocode.utils.isoutils.queue import queue_system
    
    _sessions.pop(session_key, None)

    task_data: Dict[str, Any] = session["task_data"]

    # Injecter les sélections dans task_data
    task_data["track_selection"] = {
        "audio_kept": session["audio_kept"],          # [global_stream_index, ...]
        "audio_default": session["audio_default"],    # global_stream_index | None
        "sub_kept": session["sub_kept"],              # [global_stream_index, ...]
        "sub_default": session["sub_default"],        # global_stream_index | None
        "sub_hardsub": session["sub_hardsub"],        # global_stream_index | None
    }
    
    # Injecter les réglages spécifiques de cette tâche
    task_data["user_settings"] = session["user_settings"]

    try:
        await callback_query.answer("🚀 Ajout à la file d'encodage...")
        await callback_query.message.edit_text(
            stylize_value(
                f"✅ **Sélection confirmée !**\n\n"
                f"📁 `{session['filename']}`\n"
                f"🎵 Audio gardé: {session['audio_kept']}\n"
                f"📜 Sous-titres gardés: {session['sub_kept']}\n"
                f"🔥 Hardsub: {session['sub_hardsub']}\n\n"
                "_Ajout à la file d'encodage..._"
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        logger.warning(f"_finalize_and_enqueue edit error: {e}")

    try:
        task_id = await queue_system.add_task(task_data)
        pos = await queue_system.get_task_position(task_id)

        await callback_query.message.edit_text(
            stylize_value(
                f"📥 **Vidéo ajoutée à la file d'attente**\n\n"
                f"📁 `{session['filename']}`\n"
                f"🎬 Position: #{pos}\n"
                f"🔍 Suivre: /status_{task_id}"
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        logger.error(f"_finalize_and_enqueue queue error: {e}")
        try:
            await callback_query.message.edit_text(
                stylize_value(f"❌ Erreur lors de l'ajout à la file: `{e}`"),
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass
