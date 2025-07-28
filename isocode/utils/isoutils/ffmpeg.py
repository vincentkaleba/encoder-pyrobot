import asyncio
import concurrent.futures
import json
import math
import os
import re
import subprocess
import threading
import time
import queue
from typing import Dict, Any, Callable, Optional, Tuple, List
import logging
from dataclasses import dataclass
import ffmpeg
from isocode import settings, logger
# Configuration du logger
@dataclass
class EncodeSettings:
    """Paramètres d'encodage avec support des sous-titres"""
    extensions: str = 'MKV'
    hevc: bool = False
    aspect: bool = False
    cabac: bool = False
    reframe: str = 'pass'
    tune: bool = True
    frame: str = 'source'
    audio: str = 'aac'
    sample: str = 'source'
    bitrate: str = 'source'
    bits: bool = False
    channels: str = 'source'
    drive: bool = False
    preset: str = 'sf'
    metadata: bool = True
    hardsub: bool = False
    watermark: bool = False
    subtitles: bool = True
    resolution: str = 'OG'
    upload_as_doc: bool = False
    crf: int = 22
    resize: bool = False
    subs_id: int = 0

class EncodingClient:
    def __init__(self, max_workers: int = 2,
                 download_dir: str = "downloads",
                 encode_dir: str = "encoded"):
        self.download_dir = download_dir
        self.encode_dir = encode_dir
        self.max_workers = max_workers
        self.task_queue = queue.Queue(maxsize=100)
        self.worker_threads = []
        self.active_tasks = {}
        self.shutdown_flag = threading.Event()
        self.task_counter = 0
        self.lock = threading.RLock()
        self.progress_files = {}

        os.makedirs(download_dir, exist_ok=True)
        os.makedirs(encode_dir, exist_ok=True)

        self._start_workers()

    def _start_workers(self):
        for i in range(self.max_workers):
            thread = threading.Thread(
                target=self._worker_loop,
                name=f"EncoderWorker-{i+1}",
                daemon=True
            )
            thread.start()
            self.worker_threads.append(thread)
        logger.info(f"Démarré avec {self.max_workers} workers")

    def _worker_loop(self):
        while not self.shutdown_flag.is_set():
            try:
                task_id, task_data = self.task_queue.get(timeout=1)
                with self.lock:
                    self.active_tasks[task_id] = {
                        'status': 'processing',
                        'start_time': time.time(),
                        'progress': 0
                    }

                try:
                    logger.info(f"Début encodage tâche #{task_id}")
                    result = self._process_task(task_id, task_data)

                    with self.lock:
                        self.active_tasks[task_id]['status'] = 'completed'
                        self.active_tasks[task_id]['result'] = result
                        self.active_tasks[task_id]['end_time'] = time.time()

                    if task_data.get('completion_callback'):
                        asyncio.run_coroutine_threadsafe(
                            task_data['completion_callback'](task_id, result),
                            asyncio.get_event_loop()
                        )

                    logger.info(f"Tâche #{task_id} terminée avec succès")
                except Exception as e:
                    logger.exception(f"Erreur tâche #{task_id}")
                    with self.lock:
                        self.active_tasks[task_id]['status'] = 'failed'
                        self.active_tasks[task_id]['error'] = str(e)

                    if task_data.get('error_callback'):
                        asyncio.run_coroutine_threadsafe(
                            task_data['error_callback'](task_id, e),
                            asyncio.get_event_loop()
                        )
                finally:
                    self.task_queue.task_done()
                    if task_id in self.progress_files:
                        try:
                            os.remove(self.progress_files[task_id])
                        except:
                            pass
            except queue.Empty:
                continue

    def _process_task(self, task_id: int, task_data: Dict[str, Any]) -> str:
        ffmpeg_util = FFmpegUtils(
            self.download_dir,
            self.encode_dir
        )

        def progress_callback(percentage: float, eta: str):
            with self.lock:
                if task_id in self.active_tasks:
                    self.active_tasks[task_id]['progress'] = percentage
                    self.active_tasks[task_id]['eta'] = eta

            if task_data.get('progress_callback'):
                asyncio.run_coroutine_threadsafe(
                    task_data['progress_callback'](task_id, percentage, eta),
                    asyncio.get_event_loop()
                )

        settings = task_data['settings']
        input_path = task_data['filepath']

        progress_file = os.path.join(self.download_dir, f"progress_{task_id}.txt")
        self.progress_files[task_id] = progress_file
        open(progress_file, 'w').close()

        # Extraction des sous-titres si nécessaire
        subs_path = None
        if settings.subtitles and (settings.hardsub or settings.subtitles):
            try:
                subs_path = ffmpeg_util.get_subs(
                    input_path,
                    subs_id=settings.subs_id,
                    task_id=task_id
                )
            except Exception as e:
                logger.error(f"Erreur extraction sous-titres: {e}")
                if settings.hardsub:
                    raise RuntimeError("Échec extraction sous-titres pour hardsub")

        output_path = ffmpeg_util.encode(
            input_path,
            settings,
            progress_callback,
            progress_file,
            subs_path=subs_path
        )

        # Nettoyage des sous-titres temporaires
        if subs_path and os.path.exists(subs_path):
            try:
                os.remove(subs_path)
            except Exception as e:
                logger.warning(f"Échec suppression subs temporaires: {e}")

        return output_path

    def add_task(
        self,
        filepath: str,
        settings: EncodeSettings,
        progress_callback: Optional[Callable] = None,
        completion_callback: Optional[Callable] = None,
        error_callback: Optional[Callable] = None
    ) -> int:
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Fichier source introuvable: {filepath}")

        with self.lock:
            self.task_counter += 1
            task_id = self.task_counter

        task_data = {
            'task_id': task_id,
            'filepath': filepath,
            'settings': settings,
            'progress_callback': progress_callback,
            'completion_callback': completion_callback,
            'error_callback': error_callback
        }

        if self.task_queue.full():
            raise RuntimeError("File d'attente d'encodage saturée")

        self.task_queue.put((task_id, task_data))

        with self.lock:
            self.active_tasks[task_id] = {
                'status': 'queued',
                'added_time': time.time(),
                'progress': 0,
                'file': os.path.basename(filepath),
                'settings': {
                    'codec': 'HEVC' if settings.hevc else 'H.264',
                    'resolution': settings.resolution,
                    'crf': settings.crf,
                    'audio': settings.audio,
                    'subs_id': settings.subs_id,
                    'hardsub': settings.hardsub
                }
            }

        logger.info(f"Tâche #{task_id} ajoutée à la file d'attente")
        return task_id

    def get_task_status(self, task_id: int) -> Dict[str, Any]:
        with self.lock:
            return self.active_tasks.get(task_id, {'status': 'unknown'})

    def list_tasks(self) -> Dict[int, Dict[str, Any]]:
        with self.lock:
            expired = []
            now = time.time()
            for tid, task in self.active_tasks.items():
                if task['status'] in ('completed', 'failed') and (now - task.get('end_time', now)) > 3600:
                    expired.append(tid)

            for tid in expired:
                del self.active_tasks[tid]

            return self.active_tasks.copy()

    def shutdown(self, wait: bool = True):
        self.shutdown_flag.set()
        logger.info("Arrêt du client d'encodage demandé")

        if wait:
            self.task_queue.join()
            logger.info("Toutes les tâches terminées")

        logger.info("Client d'encodage arrêté")

class FFmpegUtils:
    RESOLUTIONS = {
        "1920": (1920, 1080),
        "20560": (2560, 1440),
        "3840": (3840, 2160),
        '1080': (1920, 1080),
        '720': (1280, 720),
        '576': (768, 576),
        '480': (852, 480),
        '360': (640, 360),
        '240': (426, 240),
        '144': (256, 144),
        'OG': None  # Résolution originale
    }

    AUDIO_CODECS = {
        'aac': 'aac',
        'ac3': 'ac3',
        'source': 'copy',
        'opus': 'libopus',
        'vorbis': 'libvorbis',
        'alac': 'alac'
    }

    SAMPLE_RATES = {
        '44.1K': '44100',
        '48K': '48000',
        'source': None
    }

    PRESET_MAP = {
        'uf': 'ultrafast',
        'sf': 'superfast',
        'vf': 'veryfast',
        'f': 'fast',
        'm': 'medium',
        's': 'slow',
        'ss': 'slower',
        'vss': 'veryslow',
        'placebo': 'placebo'
    }

    CHANNELS_MAP = {
        '1.0': '1',
        '2.0': '2',
        '2.1': '3',
        '5.1': '6',
        '7.1': '8',
        'source': None
    }

    def __init__(self, download_dir: str, encode_dir: str):
        self.download_dir = download_dir
        self.encode_dir = encode_dir

    def _run_command(self, command: List[str], task: str = "Commande") -> Tuple[int, str]:
        try:
            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True
            )
            return 0, result.stdout
        except subprocess.CalledProcessError as e:
            logger.error(f"{task} échouée: {e.stderr}")
            return e.returncode, e.stderr

    def get_duration(self, filepath: str) -> float:
        cmd = [
            'ffprobe', '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'json',
            filepath
        ]

        status, output = self._run_command(cmd, "Récupération durée")
        if status == 0:
            try:
                data = json.loads(output)
                return float(data['format']['duration'])
            except (KeyError, ValueError):
                pass
        return 0.0

    def get_dimensions(self, filepath: str) -> Tuple[int, int]:
        cmd = [
            'ffprobe', '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height',
            '-of', 'json',
            filepath
        ]

        status, output = self._run_command(cmd, "Récupération dimensions")
        if status == 0:
            try:
                data = json.loads(output)
                stream = data['streams'][0]
                return int(stream['width']), int(stream['height'])
            except (KeyError, IndexError, ValueError):
                pass
        return (1280, 720)

    def get_subs(self, filepath: str, subs_id: int = 0, task_id: int = 0) -> Optional[str]:
        """Extraire les sous-titres d'un fichier vidéo"""
        try:
            # Vérifier si le fichier contient des sous-titres
            cmd = [
                'ffprobe', '-v', 'error',
                '-select_streams', f's:{subs_id}',
                '-show_entries', 'stream=codec_name',
                '-of', 'json',
                filepath
            ]

            status, output = self._run_command(cmd, "Détection sous-titres")
            if status != 0 or not output.strip():
                logger.warning(f"Aucun flux de sous-titres trouvé avec ID {subs_id}")
                return None

            # Créer un fichier temporaire pour les sous-titres
            subs_path = os.path.join(self.download_dir, f"subs_{task_id}_{subs_id}.ass")

            # Commande d'extraction
            cmd = [
                'ffmpeg', '-y', '-i', filepath,
                '-map', f'0:s:{subs_id}',
                '-c:s', 'ass',
                subs_path
            ]

            status, output = self._run_command(cmd, "Extraction sous-titres")
            if status != 0:
                raise RuntimeError(f"Échec extraction sous-titres: {output}")

            if not os.path.exists(subs_path) or os.path.getsize(subs_path) == 0:
                raise RuntimeError("Fichier de sous-titres vide")

            logger.info(f"Sous-titres extraits: {subs_path}")
            return subs_path
        except Exception as e:
            logger.error(f"Erreur extraction sous-titres: {str(e)}")
            return None

    def encode(
        self,
        filepath: str,
        settings: EncodeSettings,
        progress_callback: Callable = None,
        progress_file: str = "progress.txt",
        subs_path: Optional[str] = None
    ) -> str:
        base_name = os.path.splitext(os.path.basename(filepath))[0]
        output_ext = f".{settings.extensions.lower()}"
        output_path = os.path.join(self.encode_dir, f"{base_name}{output_ext}")

        # Construction de la commande FFmpeg
        input_args = ['ffmpeg', '-y', '-hide_banner', '-loglevel', 'info', '-i', filepath]
        output_args = []

        # === Paramètres vidéo ===
        # Codec vidéo
        video_codec = 'libx265' if settings.hevc else 'libx264'
        output_args += ['-c:v', video_codec]

        # CRF - Paramètre de qualité (ajouté ici)
        output_args += ['-crf', str(settings.crf)]

        # Présélection
        if settings.preset in self.PRESET_MAP:
            output_args += ['-preset', self.PRESET_MAP[settings.preset]]

        # Tuning
        if settings.tune:
            output_args += ['-tune', 'animation']

        # CABAC (H.264 seulement)
        if not settings.hevc and settings.cabac:
            output_args += ['-coder', '1']

        # Format de pixels (10 bits)
        if settings.bits and settings.hevc:
            output_args += ['-pix_fmt', 'yuv420p10le']
        else:
            output_args += ['-pix_fmt', 'yuv420p']

        # Frame rate
        if settings.frame != 'source':
            output_args += ['-r', settings.frame]

        # Aspect ratio
        if settings.aspect:
            output_args += ['-aspect', '16:9']

        # === Gestion des sous-titres ===
        # Sous-titres incrustés (hardsub)
        vf_filters = []
        if settings.hardsub and subs_path:
            vf_filters.append(f"subtitles='{subs_path.replace('\\', '/').replace(':', '\\\\:')}'")

        # Redimensionnement
        if settings.resize and settings.resolution != 'OG' and settings.resolution in self.RESOLUTIONS:
            w, h = self.RESOLUTIONS[settings.resolution]
            vf_filters.append(f'scale={w}:{h}')

        # Appliquer les filtres vidéo
        if vf_filters:
            output_args += ['-vf', ','.join(vf_filters)]

        # Sous-titres mous
        if settings.subtitles and not settings.hardsub:
            output_args += ['-c:s', 'copy']

        # === Paramètres audio ===
        # Codec audio
        if settings.audio in self.AUDIO_CODECS:
            audio_codec = self.AUDIO_CODECS[settings.audio]
            output_args += ['-c:a', audio_codec]

            # Bitrate audio
            if settings.bitrate != 'source' and audio_codec != 'copy':
                output_args += ['-b:a', f"{settings.bitrate}k"]

            # Taux d'échantillonnage
            if settings.sample != 'source' and settings.sample in self.SAMPLE_RATES:
                output_args += ['-ar', self.SAMPLE_RATES[settings.sample]]

            # Canaux audio
            if settings.channels != 'source' and settings.channels in self.CHANNELS_MAP:
                output_args += ['-ac', self.CHANNELS_MAP[settings.channels]]
        else:
            output_args += ['-c:a', 'copy']

        # === Autres paramètres ===
        # Métadonnées
        if settings.metadata:
            output_args += [
                '-metadata', f'title=Encodé le {time.strftime("%Y-%m-%d")}'
            ]

        # Watermark (exemple simplifié)
        if settings.watermark:
            output_args += ['-i', 'watermark.png', '-filter_complex', 'overlay=10:10']

        # Options finales
        output_args += [
            '-map', '0',
            '-map_chapters', '0',
            '-progress', progress_file,
            '-threads', str(os.cpu_count() or 4),
            output_path
        ]

        # Exécution
        cmd = input_args + output_args
        logger.info(f"Exécution encodage: {' '.join(cmd)}")

        # Démarrer le processus
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )

        # Démarrer le monitoring de progression
        if progress_callback:
            threading.Thread(
                target=self._monitor_progress,
                args=(proc, filepath, progress_file, progress_callback),
                daemon=True
            ).start()

        # Attendre la fin du processus
        while proc.poll() is None:
            time.sleep(1)

        if proc.returncode != 0:
            raise RuntimeError(f"Échec de l'encodage (code {proc.returncode})")

        logger.info(f"Encodage réussi: {output_path}")
        return output_path

    def _monitor_progress(
        self,
        proc: subprocess.Popen,
        input_path: str,
        progress_file: str,
        callback: Callable
    ):
        duration = self.get_duration(input_path)
        start_time = time.time()

        while proc.poll() is None:
            time.sleep(1)

            try:
                if not os.path.exists(progress_file):
                    continue

                with open(progress_file, 'r') as f:
                    content = f.read()

                time_match = re.search(r"out_time_ms=(\d+)", content)
                speed_match = re.search(r"speed=([\d.]+)", content)

                if time_match and speed_match:
                    elapsed_us = int(time_match.group(1))
                    speed = float(speed_match.group(1))

                    if duration > 0 and speed > 0:
                        elapsed_sec = elapsed_us / 1_000_000
                        percentage = min(99.9, (elapsed_sec / duration) * 100)

                        remaining = (duration - elapsed_sec) / speed
                        eta = time.strftime('%H:%M:%S', time.gmtime(remaining))

                        callback(percentage, eta)
            except Exception as e:
                logger.warning(f"Erreur monitoring: {str(e)}")