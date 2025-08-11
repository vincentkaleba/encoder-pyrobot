import asyncio
import json
import shutil
import math
import os
import re
import subprocess
import time
from typing import Dict, List, Optional, Tuple
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


async def extract_subs(filepath: str, msg, user: User) -> Optional[str]:
    """Extract subtitles and handle fonts — version robuste."""
    subtitle_streams = await list_subtitle_streams(filepath)
    if not subtitle_streams:
        logger.info("Aucune piste subtitle trouvée.")
        return None

    output = os.path.join(encode_dir, f"{msg.id}.ass")

    sub_track_str = await get_setting(user.user_id, "selected_subtitle_track")
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
        """Construire la commande FFmpeg en fonction des paramètres utilisateur.

        Gère :
        - accélération matérielle
        - mappage des pistes vidéo/audio/sous-titres
        - encodage vidéo/audio (codec, crf, preset, pix_fmt, bitrate, channels)
        - filtres vidéo (scale, setdar pour l'aspect, subtitles pour hardsub, watermark)
        - threads
        - sortie
        """
        cmd = [
            'ffmpeg', '-hide_banner', '-loglevel', 'error',
            '-progress', 'pipe:1', '-y'
        ]

        # Accélération matérielle (si différente de 'none')
        hwaccel = user_settings.get('hwaccel', 'auto')
        if hwaccel != 'none':
            cmd.extend(['-hwaccel', hwaccel])

        # Fichier d'entrée
        cmd.extend(['-i', input_file])

        # Détection des pistes (vidéo, audio, sous-titres)
        has_video = await get_codec(input_file, channel='v:0')
        has_audio = await get_codec(input_file, channel='a:0')
        subtitle_streams = await list_subtitle_streams(input_file)

        if has_video:
            # Mapper la première piste vidéo
            cmd.extend(['-map', '0:v:0?'])
        else:
            logger.warning("Aucune piste vidéo détectée dans le fichier source")

        # Codec vidéo
        video_codec = VideoCodec(user_settings.get('video_codec', 'libx265'))
        cmd.extend(['-c:v', video_codec.ffmpeg_name])

        # Construction d'une liste de filtres vidéo
        vf_parts: List[str] = []

        # Paramètres vidéo
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

            # Format de pixel
            pix_fmt = user_settings.get('pix_fmt', 'yuv420p')
            cmd.extend(['-pix_fmt', pix_fmt])

            # Résolution -> on ajoute un filtre scale
            resolution = Resolution(user_settings.get('resolution', 'original'))
            if resolution != Resolution.ORIGINAL:
                vf_parts.append(f"scale={resolution.ffmpeg_name}")

        # CABAC pour h264/h265
        if user_settings.get('cabac', False) and video_codec in [VideoCodec.H264, VideoCodec.H265]:
            cmd.extend(['-coder', '1'])

        # -----------------------
        # Réglages audio
        # -----------------------
        audio_track_action = AudioTrackAction(user_settings.get('audio_track_action', 'first'))
        audio_codec = AudioCodec(user_settings.get('audio_codec', 'aac'))

        if audio_track_action != AudioTrackAction.NONE and has_audio:
            if audio_track_action == AudioTrackAction.ALL:
                cmd.extend(['-map', '0:a?'])
            elif audio_track_action == AudioTrackAction.FIRST:
                cmd.extend(['-map', '0:a:0?'])
            else:
                try:
                    track_num = int(audio_track_action.value.split('_')[1])
                    cmd.extend(['-map', f'0:a:{track_num - 1}?'])
                except Exception:
                    cmd.extend(['-map', '0:a:0?'])

            # Encodage audio
            if audio_codec != AudioCodec.COPY:
                cmd.extend(['-c:a', audio_codec.ffmpeg_name])

                # Bitrate audio
                audio_bitrate = user_settings.get('audio_bitrate', '192k')
                cmd.extend(['-b:a', audio_bitrate])

                # Normalisation audio
                if user_settings.get('normalize_audio', True):
                    cmd.extend(['-af', 'loudnorm'])

                channels = user_settings.get('channels', 'stereo')
                channel_mapping = {
                    "mono": "1",
                    "stereo": "2",
                    "2.1": "3",
                    "5.1": "6",
                    "7.1": "8"
                }
                channels_value = channel_mapping.get(str(channels).lower(), "2")
                cmd.extend(['-ac', channels_value])
            else:
                cmd.extend(['-c:a', 'copy'])
        else:
            # Pas de piste audio -> supprimer l'audio
            cmd.extend(['-an'])

        # -----------------------
        # Gestion des sous-titres
        # -----------------------
        subtitle_action = SubtitleAction(user_settings.get('subtitle_action', 'embed'))
        selected_subtitle_track = user_settings.get('selected_subtitle_track')

        if subtitle_action != SubtitleAction.NONE and subtitle_streams:
            selected_global_idx = None
            try:
                if selected_subtitle_track is not None:
                    selected_track = int(selected_subtitle_track)
                    if any(stream['index'] == selected_track for stream in subtitle_streams):
                        selected_global_idx = selected_track
            except (ValueError, TypeError):
                pass

            if selected_global_idx is None:
                selected_global_idx = subtitle_streams[0]['index']

            if subtitle_action == SubtitleAction.BURN and subtitle_path:
                escaped_path = subtitle_path.replace(':', '\\\\:').replace("'", "\\\\'")
                vf_parts.append(f"subtitles='{escaped_path}'")
            else:
                cmd.extend(['-map', f'0:{selected_global_idx}?'])
                if subtitle_action == SubtitleAction.EMBED:
                    cmd.extend(['-c:s', 'mov_text'])
                elif subtitle_action == SubtitleAction.COPY:
                    cmd.extend(['-c:s', 'copy'])
        else:
            # Pas de sous-titres -> désactiver
            cmd.extend(['-sn'])

        # -----------------------
        # ASPECT
        # -----------------------
        aspect = user_settings.get('aspect', 'original')
        if aspect and aspect != 'original':
            aspect_str = str(aspect).strip()
            if ':' in aspect_str:
                ratio = aspect_str.replace(':', '/')
            else:
                ratio = aspect_str
            vf_parts.append(f"setdar={ratio}")

        # -----------------------
        # Watermark
        # -----------------------
        if user_settings.get('watermark', False):
            watermark_filter = "subtitles='isocode/utils/extras/watermark.ass'"
            vf_parts.append(watermark_filter)

        if vf_parts:
            joined_vf = ",".join(vf_parts)
            cmd.extend(['-vf', joined_vf])

        # Threads
        threads = user_settings.get('threads', 0)
        if threads and threads > 0:
            cmd.extend(['-threads', str(threads)])

        # Fichier de sortie
        cmd.append(output_file)

        return cmd


async def get_user_settings(user_id: int) -> Dict[str, any]:
    """Get all user settings in one call"""
    return {
        "video_codec": await get_video_codec(user_id),
        "audio_codec": await get_audio_codec(user_id),
        "preset": await get_preset(user_id),
        "crf": await get_crf(user_id),
        "resolution": await get_resolution(user_id),
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


async def encode_video(filepath: str, message, msg) -> str:
    """
    Fonction principale d'encodage vidéo avec FFmpeg.
    - Ajoute les sous-titres si activé.
    - Applique les paramètres de l'utilisateur.
    - Gère l'encodage et la progression.
    """
    user_id = message.from_user.id
    ex = await get_extensions(user_id)
    path, _ = os.path.splitext(filepath)
    name = os.path.basename(path)

    user = await get_or_create_user(user_id)

    output_ext = ex.lower() if ex and ex.upper() in ['MP4', 'AVI'] else 'mkv'
    output_filepath = os.path.join(encode_dir, f"{name}.{output_ext}")

    if not os.path.exists(filepath):
        logger.error(f"Fichier introuvable après téléchargement : {filepath}")
        raise FileNotFoundError(f"Fichier non trouvé : {filepath}")

    subtitle_path = None
    if await get_hardsub(user_id):
        subtitle_path = await extract_subs(filepath, msg, user)

    user_settings = await get_user_settings(user_id)

    command = await FFmpegCommandBuilder.build_command(
        user_settings,
        filepath,
        output_filepath,
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

    if not os.path.exists(output_filepath):
        logger.error(f"Fichier manquant après encodage : {output_filepath}")
        raise FileNotFoundError("Fichier de sortie introuvable après encodage")

    return output_filepath


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
        progress_bar = '▬' * filled_len + '─' * (bar_len - filled_len)

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