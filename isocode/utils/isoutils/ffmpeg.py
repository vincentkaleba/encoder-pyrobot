import asyncio
import json
import shutil
import math
import os
import re
import subprocess
import time
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse, unquote
from pyrogram.enums import ParseMode
from hachoir.metadata import extractMetadata
from hachoir.parser import createParser
from isocode.utils.database.database import Database, User
from isocode import logger, encode_dir, download_dir
from isocode.utils.isoutils.progress import stylize_value
from isocode.utils.isoutils.dbutils import (
    get_database,
    get_setting,
    get_resolution,
    get_video_codec,
    get_audio_codec,
    get_preset,
    get_crf,
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
    get_or_create_user
)
from isocode.utils.database.database import (
    VideoCodec, AudioCodec, Preset, Tune, Resolution,
    VideoFormat, SubtitleAction, AudioTrackAction, HWAccel
)
import ffmpeg


async def get_codec(filepath: str, channel: str = 'v:0') -> List[str]:
    """Get codec information using ffprobe"""
    try:
        output = subprocess.check_output([
            'ffprobe', '-v', 'error', '-select_streams', channel,
            '-show_entries', 'stream=codec_name,codec_tag_string', '-of',
            'default=nokey=1:noprint_wrappers=1', filepath
        ])
        return output.decode('utf-8').split()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []


async def list_subtitle_streams(filepath: str) -> list:
    """
    Retourne la liste des pistes subtitle dans l'ordre d'apparition.
    Chaque élément est un dict: {'index': <global stream index>, 'codec':..., 'language': ...}
    """
    try:
        out = subprocess.check_output([
            'ffprobe', '-v', 'error',
            '-select_streams', 's',
            '-show_entries', 'stream=index,codec_name:stream_tags=language',
            '-print_format', 'json',
            filepath
        ])
        data = json.loads(out.decode('utf-8') or "{}")
        streams = data.get('streams', []) or []
        result = []
        for s in streams:
            result.append({
                'index': s.get('index', None),
                'codec': s.get('codec_name'),
                'language': (s.get('tags') or {}).get('language') if isinstance(s.get('tags'), dict) else None
            })
        return result
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError) as e:
        logger.error(f"list_subtitle_streams error: {e}")
        return []


async def extract_subs(filepath: str, msg, user_or_settings: "User | dict") -> Optional[str]:
    """Extract subtitles and handle fonts — version robuste."""
    subtitle_streams = await list_subtitle_streams(filepath)
    if not subtitle_streams:
        logger.info("Aucune piste subtitle trouvée.")
        return None

    output = os.path.join(encode_dir, f"{msg.id}.ass")

    # Support either a User object or a pre-fetched settings dict
    if isinstance(user_or_settings, dict):
        sub_track_str = user_or_settings.get('selected_subtitle_track')
    else:
        sub_track_str = getattr(user_or_settings, 'selected_subtitle_track', None)
    selected_track = None
    try:
        if sub_track_str is not None:
            selected_track = int(sub_track_str)
    except ValueError:
        pass

    chosen_stream = None
    if selected_track is not None:
        for stream in subtitle_streams:
            if stream['index'] == selected_track:
                chosen_stream = stream
                break

    if chosen_stream is None:
        chosen_stream = subtitle_streams[0]

    try:
        success, error = await run_async_command([
            'ffmpeg', '-y', '-i', filepath,
            '-map', f'0:{chosen_stream["index"]}',
            output
        ])

        if not success:
            logger.error(f"Subtitle extraction failed for track {chosen_stream['index']}: {error}")
            chosen_stream = subtitle_streams[0]
            success, error = await run_async_command([
                'ffmpeg', '-y', '-i', filepath,
                '-map', f'0:{chosen_stream["index"]}',
                output
            ])
            if not success:
                logger.error(f"Fallback subtitle extraction also failed: {error}")
                return None

    except Exception as e:
        logger.error(f"extract_subs exception during ffmpeg extraction: {e}")
        return None

    # Gestion des polices avec l'ancienne méthode qui fonctionnait
    try:
        # Extraction des pièces jointes avec mkvextract
        if shutil.which('mkvextract'):
            await run_async_command([
                'mkvextract', 'attachments', filepath,
                *[str(i) for i in range(1, 41)]
            ])
            logger.info("mkvextract attachments executed")
        else:
            logger.warning("mkvextract n'est pas installé, extraction des polices ignorée")

        # Déplacement des polices - version originale
        await run_async_command([
            "sh", "-c",
            "mv -f *.JFPROJ *.FNT *.PFA *.ETX *.WOFF *.FOT *.TTF *.SFD *.VLW "
            "*.VFB *.PFB *.OTF *.GXF *.WOFF2 *.ODTTF *.BF *.CHR *.TTC *.BDF "
            "*.FON *.GF *.PMT *.AMFM  *.MF *.PFM *.COMPOSITEFONT *.PF2 *.GDR "
            "*.ABF *.VNF *.PCF *.SFP *.MXF *.DFONT *.UFO *.PFR *.TFM *.GLIF "
            "*.XFN *.AFM *.TTE *.XFT *.ACFM *.EOT *.FFIL *.PK *.SUIT *.NFTR "
            "*.EUF *.TXF *.CHA *.LWFN *.T65 *.MCF *.YTF *.F3F *.FEA *.SFT *.PFT "
            "/usr/share/fonts/ 2>/dev/null"
        ])

        await run_async_command([
            "sh", "-c",
            "mv -f *.jfproj *.fnt *.pfa *.etx *.woff *.fot *.ttf *.sfd *.vlw "
            "*.vfb *.pfb *.otf *.gxf *.woff2 *.odttf *.bf *.chr *.ttc *.bdf "
            "*.fon *.gf *.pmt *.amfm  *.mf *.pfm *.compositefont *.pf2 *.gdr "
            "*.abf *.vnf *.pcf *.sfp *.mxf *.dfont *.ufo *.pfr *.tfm *.glif "
            "*.xfn *.afm *.tte *.xft *.acfm *.eot *.ffil *.pk *.suit *.nftr "
            "*.euf *.txf *.cha *.lwfn *.t65 *.mcf *.ytf *.f3f *.fea *.sft *.pft "
            "/usr/share/fonts/ && fc-cache -f"
        ])
        logger.info("Fonts déplacées et cache mis à jour")

    except Exception as e:
        logger.warning(f"Erreur lors de la gestion des polices: {str(e)}")

    return output

async def run_async_command(cmd: List[str]) -> Tuple[bool, str]:
    """Run command asynchronously with error handling"""
    # Vérifier si la commande est disponible
    if not shutil.which(cmd[0]):
        return False, f"Command not found: {cmd[0]}"

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode().strip()
            logger.error(f"Command failed: {' '.join(cmd)}\nError: {error_msg}")
            return False, error_msg

        return True, ""
    except Exception as e:
        logger.error(f"Command execution error: {str(e)}")
        return False, str(e)


class FFmpegCommandBuilder:
    @staticmethod
    async def build_command(
        user_settings: Dict[str, any],
        input_file: str,
        output_file: str,
        subtitle_path: Optional[str] = None
    ) -> List[str]:
        """Build FFmpeg command based on user settings"""
        cmd = [
            'ffmpeg', '-hide_banner', '-loglevel', 'error',
            '-progress', 'pipe:1', '-y'
        ]

        # Hardware acceleration
        hwaccel = user_settings.get('hwaccel', 'auto')
        if hwaccel != 'none':
            cmd.extend(['-hwaccel', hwaccel])

        # Ajout de l'input file
        cmd.extend(['-i', input_file])

        # Détection des pistes
        has_video = await get_codec(input_file, channel='v:0')
        has_audio = await get_codec(input_file, channel='a:0')
        subtitle_streams = await list_subtitle_streams(input_file)

        if has_video:
            cmd.extend(['-map', '0:v:0?'])
        else:
            logger.warning("Aucune piste vidéo détectée dans le fichier source")

        # Video codec
        video_codec = VideoCodec(user_settings.get('video_codec', 'libx265'))
        cmd.extend(['-c:v', video_codec.ffmpeg_name])

        # Video settings
        if video_codec != VideoCodec.COPY:
            # CRF
            crf = user_settings.get('crf', 22)
            cmd.extend(['-crf', str(crf)])

            # Preset
            preset = Preset(user_settings.get('preset', 'medium'))
            cmd.extend(['-preset', preset.ffmpeg_name])

            # Tune
            tune = Tune(user_settings.get('tune', 'none'))
            if tune != Tune.NONE:
                cmd.extend(['-tune', tune.ffmpeg_name])

            # Pixel format
            pix_fmt = user_settings.get('pix_fmt', 'yuv420p')
            cmd.extend(['-pix_fmt', pix_fmt])

            # Resolution
            resolution = Resolution(user_settings.get('resolution', 'original'))
            if resolution != Resolution.ORIGINAL:
                cmd.extend(['-vf', f'scale={resolution.ffmpeg_name}'])

        # CABAC (if applicable)
        if user_settings.get('cabac', False) and video_codec in [VideoCodec.H264, VideoCodec.H265]:
            cmd.extend(['-coder', '1'])

        # Audio settings
        audio_track_action = AudioTrackAction(user_settings.get('audio_track_action', 'first'))
        audio_codec = AudioCodec(user_settings.get('audio_codec', 'aac'))

        if audio_track_action != AudioTrackAction.NONE and has_audio:
            # Audio mapping
            if audio_track_action == AudioTrackAction.ALL:
                cmd.extend(['-map', '0:a'])
            elif audio_track_action == AudioTrackAction.FIRST:
                cmd.extend(['-map', '0:a:0'])
            else:
                track_num = int(audio_track_action.value.split('_')[1])
                cmd.extend(['-map', f'0:a:{track_num - 1}'])

            # Audio codec
            if audio_codec != AudioCodec.COPY:
                cmd.extend(['-c:a', audio_codec.ffmpeg_name])

                # Audio bitrate
                audio_bitrate = user_settings.get('audio_bitrate', '192k')
                cmd.extend(['-b:a', audio_bitrate])

                # Normalize audio
                if user_settings.get('normalize_audio', True):
                    cmd.extend(['-af', 'loudnorm'])

                # Channels mapping
                channels = user_settings.get('channels', 'stereo')
                channel_mapping = {
                    "mono": "1",
                    "stereo": "2",
                    "2.1": "3",
                    "5.1": "6",
                    "7.1": "8"
                }
                channels_value = channel_mapping.get(channels.lower(), "2")
                cmd.extend(['-ac', channels_value])
            else:
                cmd.extend(['-c:a', 'copy'])
        else:
            cmd.extend(['-an'])

        # Subtitles
        subtitle_action = SubtitleAction(user_settings.get('subtitle_action', 'embed'))
        selected_subtitle_track = user_settings.get('selected_subtitle_track')

        if subtitle_action != SubtitleAction.NONE and subtitle_streams:
            selected_global_idx = None
            try:
                # Convertir le track sélectionné en index global
                if selected_subtitle_track is not None:
                    selected_track = int(selected_subtitle_track)
                    if any(stream['index'] == selected_track for stream in subtitle_streams):
                        selected_global_idx = selected_track
            except (ValueError, TypeError):
                pass

            # Fallback sur la première piste si nécessaire
            if selected_global_idx is None:
                selected_global_idx = subtitle_streams[0]['index']

            if subtitle_action == SubtitleAction.BURN and subtitle_path:
                # Hardsub: appliquer via filtre vidéo
                escaped_path = subtitle_path.replace(':', '\\\\:').replace("'", "\\\\'")
                vf = f"subtitles='{escaped_path}'"

                if '-vf' in cmd:
                    vf_index = cmd.index('-vf') + 1
                    cmd[vf_index] = f"{cmd[vf_index]},{vf}"
                else:
                    cmd.extend(['-vf', vf])
            else:
                # Embed ou copy: mapper la piste spécifique
                cmd.extend(['-map', f'0:{selected_global_idx}'])

                if subtitle_action == SubtitleAction.EMBED:
                    cmd.extend(['-c:s', 'mov_text'])
                elif subtitle_action == SubtitleAction.COPY:
                    cmd.extend(['-c:s', 'copy'])
        else:
            cmd.extend(['-sn'])

        # Threads
        threads = user_settings.get('threads', 0)
        if threads > 0:
            cmd.extend(['-threads', str(threads)])

        # Watermark
        if user_settings.get('watermark', False):
            watermark_filter = "subtitles='isocode/utils/extras/watermark.ass'"

            if '-vf' in cmd:
                vf_index = cmd.index('-vf') + 1
                cmd[vf_index] = f"{cmd[vf_index]},{watermark_filter}"
            else:
                cmd.extend(['-vf', watermark_filter])

        # Output file
        cmd.append(output_file)

        return cmd

async def get_user_settings(user_or_id: "User | int") -> Dict[str, any]:
    """Get all user settings in one call.

    Accept either a `User` instance (preferred) or a `user_id`.
    When a `User` is provided, this avoids multiple DB roundtrips.
    """
    # If caller passed a user_id, fetch user once
    if isinstance(user_or_id, int):
        user = await get_or_create_user(user_or_id)
    else:
        user = user_or_id

    # Build settings from the User object directly (no extra DB calls)
    return {
        "video_codec": user.video_codec.ffmpeg_name if hasattr(user, 'video_codec') else 'libx265',
        "audio_codec": user.audio_codec.ffmpeg_name if hasattr(user, 'audio_codec') else 'aac',
        "preset": user.preset.ffmpeg_name if hasattr(user, 'preset') else 'medium',
        "crf": getattr(user, 'crf', 22),
        "resolution": getattr(user, 'resolution', Resolution.ORIGINAL).value,
        "audio_bitrate": getattr(user, 'audio_bitrate', '192k'),
        "threads": getattr(user, 'threads', 0),
        "hwaccel": getattr(user, 'hwaccel', HWAccel.AUTO).ffmpeg_name if hasattr(user, 'hwaccel') else 'auto',
        "subtitle_action": getattr(user, 'subtitle_action', SubtitleAction.EMBED).ffmpeg_name,
        "selected_subtitle_track": getattr(user, 'selected_subtitle_track', None),
        "audio_track_action": getattr(user, 'audio_track_action', AudioTrackAction.FIRST).ffmpeg_name,
        "extensions": getattr(user, 'extensions', VideoFormat.MKV).value,
        "tune": getattr(user, 'tune', Tune.NONE).ffmpeg_name,
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


async def encode_video(filepath: str, message, msg, user_settings: Dict[str, any] = None, user_obj: User = None) -> str:
    """
    Fonction principale d'encodage vidéo avec FFmpeg.
    - Ajoute les sous-titres si activé.
    - Applique les paramètres de l'utilisateur.
    - Gère l'encodage et la progression.
    """
    user_id = message.from_user.id
    user = None

    # Determine extension either from provided settings, provided user object, or DB
    if user_obj is not None:
        user = user_obj
        ex = getattr(user, 'extensions', VideoFormat.MKV).value
    elif user_settings is not None:
        ex = user_settings.get('extensions', VideoFormat.MKV.value)
    else:
        user = await get_or_create_user(user_id)
        ex = getattr(user, 'extensions', VideoFormat.MKV).value
    # If input is a URL, parse the path to derive a filename base
    input_is_url = False
    if isinstance(filepath, str) and filepath.startswith(('http://', 'https://')):
        input_is_url = True
        parsed = urlparse(filepath)
        path = parsed.path or ''
        name = os.path.splitext(os.path.basename(unquote(path)))[0] or f"remote_{int(time.time())}"
    else:
        path, _ = os.path.splitext(filepath)
        name = os.path.basename(path)
    output_ext = ex.lower() if ex and ex.upper() in ['MP4', 'AVI'] else 'mkv'
    # Prepare a task-local temporary output path and a final per-user output dir
    final_user_dir = os.path.join(encode_dir, str(user_id))
    os.makedirs(final_user_dir, exist_ok=True)

    final_output_filepath = os.path.join(final_user_dir, f"{name}.{output_ext}")
    # write to a .part temporary file in the same task dir as the input to keep atomic moves fast
    # Use a temp name that preserves the real extension at the end so
    # ffmpeg can infer the muxer from the file extension. Example:
    #   name.part.mkv  -> final extension is .mkv
    # Choose a temporary output path. For local inputs, use the task dir
    # (same dir as input) for fast atomic moves. For URL inputs, write
    # the temp file into the final user encode dir and then leave it
    # in place (it's already in the final dir).
    if input_is_url:
        temp_output_filepath = os.path.join(final_user_dir, f"{name}.part.{output_ext}")
    else:
        temp_output_filepath = os.path.join(os.path.dirname(filepath), f"{name}.part.{output_ext}")

    if not input_is_url and not os.path.exists(filepath):
        logger.error(f"Fichier introuvable après téléchargement : {filepath}")
        raise FileNotFoundError(f"Fichier non trouvé : {filepath}")

    subtitle_path = None
    # Check for hard-sub configuration from user object or settings
    hardsub_flag = None
    if user is not None:
        hardsub_flag = getattr(user, 'hardsub', False)
    elif user_settings is not None:
        hardsub_flag = user_settings.get('hardsub', False)

    if hardsub_flag and not input_is_url:
        # Pass either the user object or the settings dict to extract_subs
        if user is not None:
            subtitle_path = await extract_subs(filepath, msg, user)
        else:
            subtitle_path = await extract_subs(filepath, msg, user_settings)
    elif hardsub_flag and input_is_url:
        # Hard-sub extraction from a remote stream is not supported;
        # skip hardsub for URL inputs unless the file is first downloaded.
        logger.info("Hardsub ignored for remote input (stream/URL)")

    # Build or reuse user_settings to avoid DB calls
    if user_settings is None:
        if user is None:
            user = await get_or_create_user(user_id)
        user_settings = await get_user_settings(user)

    command = await FFmpegCommandBuilder.build_command(
        user_settings,
        filepath,
        temp_output_filepath,
        subtitle_path
    )

    logger.info(f"Commande FFmpeg : {' '.join(command)}")

    try:
        proc = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
    except Exception as e:
        # Fallback: écrire la commande dans un script shell
        command_file = f"/tmp/ffmpeg_cmd_{msg.id}.sh"
        with open(command_file, 'w') as f:
            f.write("#!/bin/sh\n")
            f.write(" ".join(command) + "\n")
        os.chmod(command_file, 0o755)
        logger.warning(f"Utilisation du script fallback: {command_file}")
        proc = await asyncio.create_subprocess_exec(
            command_file,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

    await handle_progress(proc, msg, message, filepath, user_settings)

    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        error_msg = stderr.decode().strip()
        logger.error(f"Erreur d'encodage : {error_msg}")
        raise Exception(f"Échec d'encodage FFmpeg : {error_msg}")

    # Ensure the temp output exists, then atomically move to final location
    if not os.path.exists(temp_output_filepath):
        logger.error(f"Fichier manquant après encodage : {temp_output_filepath}")
        raise FileNotFoundError("Fichier de sortie introuvable après encodage")

    try:
        # Atomic move/replace to final location
        os.replace(temp_output_filepath, final_output_filepath)
        logger.info(f"Fichier déplacé atomiquement vers: {final_output_filepath}")
    except Exception as e:
        logger.error(f"Erreur déplacement fichier encodé: {e}")
        # Attempt fallback copy
        shutil.copy2(temp_output_filepath, final_output_filepath)
        os.remove(temp_output_filepath)

    return final_output_filepath


async def handle_progress(proc, msg, message, filepath, user_settings: dict):
    """Handle progress updates during encoding with rich information"""
    COMPRESSION_START_TIME = time.time()
    total_time = await get_duration(filepath) or 0
    file_size = os.path.getsize(filepath)
    filename = os.path.basename(filepath)

    # Get encoding settings
    video_codec = VideoCodec(user_settings.get("video_codec", "libx265")).display_name
    audio_codec = AudioCodec(user_settings.get("audio_codec", "aac")).display_name
    resolution = Resolution(user_settings.get("resolution", "original")).display_name

    last_update = 0
    frame_count = None
    bitrate = None
    speed = None
    elapsed_time_us = None
    last_message_text = None

    while True:
        if proc.returncode is not None:
            break

        line = await proc.stdout.readline()
        if not line:
            if proc.returncode is not None:
                break
            await asyncio.sleep(0.1)
            continue

        line = line.decode(errors="ignore").strip()

        if m := re.match(r"frame=(\d+)", line):
            frame_count = int(m.group(1))
        elif m := re.match(r"bitrate=([\d\.kKmM]+k?b/s)", line, re.I):
            bitrate = m.group(1)
        elif m := re.match(r"speed=([\d\.]+)x", line):
            try:
                speed = float(m.group(1))
            except:
                speed = None
        elif m := re.match(r"out_time_ms=(\d+)", line):
            elapsed_time_us = int(m.group(1))
        elif m := re.match(r"progress=(\w+)", line):
            if m.group(1) == "end":
                break

        now = time.time()
        if now - last_update < 10:
            continue
        last_update = now

        elapsed_time = (elapsed_time_us / 1_000_000) if elapsed_time_us else (now - COMPRESSION_START_TIME)
        percentage = (elapsed_time / total_time * 100) if total_time > 0 else 0
        percentage = min(percentage, 100.0)

        remaining_time = math.floor((total_time - elapsed_time) / speed) if speed and speed > 0 else None

        if speed and elapsed_time > 0:
            processed_size = min(file_size, (elapsed_time / total_time) * file_size) if total_time > 0 else 0
            size_progress = f"{processed_size / (1024*1024):.1f}/{file_size / (1024*1024):.1f} MB"
        else:
            size_progress = "Calculating..."

        bar_len = 10
        filled_len = int(bar_len * percentage / 100)
        progress_bar = '━' * filled_len + '─' * (bar_len - filled_len)

        speed_str = f"{speed:.1f}x" if speed is not None else "N/A"
        remaining_str = format_duration(remaining_time) if remaining_time and remaining_time > 0 else "Calcul..."

        elapsed_str = format_duration(int(elapsed_time))
        total_str = format_duration(int(total_time))


        new_message_text = (
            f"<b>🎬 Encodage de:</b> <code>{filename}</code>\n"
            f"<b>⚙️ Param:</b> {video_codec} | {audio_codec} | {resolution}\n\n"
            f"<b>{percentage:.1f}%</b> |{progress_bar}|\n\n"
            f"<b>⏱ Progress:</b> {elapsed_str} / {total_str}\n"
            f"<b>⏳ Lapsis:</b> {remaining_str} | <b>🚀 Speed:</b> {speed_str}\n"
            f"<b>📊 Taille:</b> {size_progress}\n"
            f"<b>🔢 Frames:</b> {frame_count if frame_count is not None else 'N/A'} | <b>📶 Débit:</b> {bitrate or 'N/A'}\n"
        )

        if new_message_text != last_message_text:
            try:
                await msg.edit(
                    text=stylize_value(new_message_text),
                    parse_mode=ParseMode.HTML
                )
                last_message_text = new_message_text
            except Exception as e:
                if "MESSAGE_NOT_MODIFIED" in str(e):
                    pass


def format_duration(seconds: int) -> str:
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h}h {m}m {s}s"
    elif m > 0:
        return f"{m}m {s}s"
    else:
        return f"{s}s"

async def get_thumbnail(in_filename: str, path: str, ttl: int) -> str:
    """Generate thumbnail from video"""
    out_filename = os.path.join(path, f"{time.time()}.jpg")
    try:
        (
            ffmpeg
            .input(in_filename, ss=ttl)
            .output(out_filename, vframes=1)
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )
        return out_filename
    except ffmpeg.Error as e:
        logger.error(f"Thumbnail generation error: {e.stderr.decode()}")
        return ""


async def get_duration(filepath: str) -> float:
    """Get video duration in seconds"""
    try:
        metadata = extractMetadata(createParser(filepath))
        if metadata and metadata.has("duration"):
            return metadata.get('duration').seconds
        return 0
    except Exception as e:
        logger.error(f"Duration detection error: {str(e)}")
        return 0

async def get_video_width_and_height(filepath: str) -> Tuple[int, int]:
    """Get video width and height"""
    try:
        metadata = extractMetadata(createParser(filepath))
        if metadata and metadata.has("width") and metadata.has("height"):
            return metadata.get('width'), metadata.get('height')
        return 0, 0
    except Exception as e:
        logger.error(f"Width/Height detection error: {str(e)}")
        return 0, 0

async def get_ffmpeg_video_width_and_height(filepath: str) -> Tuple[int, int]:
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=p=0:s=x",
            filepath
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0:
            dims = stdout.decode().strip()
            if dims:
                width, height = dims.split('x')
                return int(width), int(height)
        return 0, 0
    except Exception as e:
        logger.error(f"Width/Height detection error: {str(e)}")
        return 0, 0