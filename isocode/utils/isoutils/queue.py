import asyncio
import logging
import os
import time
from collections import deque
from typing import Dict, Deque, List, Optional, Any, Union
from dataclasses import dataclass, field
from datetime import timedelta
from isocode import logger, settings
from isocode.utils.isoutils.ffmpeg import encode_video, get_thumbnail, get_duration
from isocode.utils.telegram.message import send_progress
import aiohttp
from urllib.parse import urlparse, unquote
from isocode.utils.isoutils.progress import stylize_value, humanbytes, create_progress_bar
from isocode.utils.telegram.media import send_media
from isocode.utils.telegram.message import send_msg, edit_msg, del_msg
from pyrogram.enums import ParseMode
from pyrogram.errors import RPCError
import re

def humanize_time(seconds: float) -> str:
    """
    Convertit un nombre de secondes en une durée lisible et compréhensible
    """
    if seconds < 1:
        return "moins d'une seconde"

    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)

    parts = []

    if days > 0:
        parts.append(f"{days} jour{'s' if days > 1 else ''}")
    if hours > 0:
        parts.append(f"{hours} heure{'s' if hours > 1 else ''}")
    if minutes > 0:
        parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")
    if seconds > 0 and days == 0 and hours == 0:
        parts.append(f"{seconds} seconde{'s' if seconds > 1 else ''}")

    if len(parts) == 0:
        return "0 seconde"
    elif len(parts) == 1:
        return parts[0]
    elif len(parts) == 2:
        return f"{parts[0]} et {parts[1]}"
    else:
        return ", ".join(parts[:-1]) + f" et {parts[-1]}"

def humanize_time_short(seconds: float) -> str:
    """
    Version courte pour l'affichage dans les barres de progression
    """
    if seconds < 60:
        return f"{int(seconds)}s"

    minutes, seconds = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}m {seconds:02d}s"

    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes:02d}m"

    days, hours = divmod(hours, 24)
    return f"{days}j {hours:02d}h"

def calculate_speed(current: int, total: int, start_time: float) -> Dict[str, Any]:
    """
    Calcule la vitesse de transfert et le temps restant
    """
    now = time.time()
    elapsed = now - start_time

    if elapsed > 0:
        speed = current / elapsed
        speed_human = f"{humanbytes(speed)}/s"
    else:
        speed = 0
        speed_human = "0 B/s"

    # Estimation du temps restant
    if speed > 0 and current > 0:
        if total and total > current:
            remaining_bytes = total - current
            remaining_time = remaining_bytes / speed
            remaining_str = humanize_time_short(remaining_time)
        else:
            remaining_time = 0
            remaining_str = "calcul..."
    else:
        remaining_time = 0
        remaining_str = "calcul..."

    return {
        'speed': speed,
        'speed_human': speed_human,
        'elapsed': elapsed,
        'elapsed_human': humanize_time_short(elapsed),
        'remaining': remaining_time,
        'remaining_human': remaining_str,
        'current_human': humanbytes(current),
        'total_human': humanbytes(total) if total else "inconnu"
    }

def sanitize_filename(filename: str) -> str:
    """
    Nettoie un nom de fichier pour qu'il soit compatible avec les systèmes de fichiers
    et Telegram
    """
    illegal_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
    for char in illegal_chars:
        filename = filename.replace(char, '_')

    if len(filename) > 100:
        name, ext = os.path.splitext(filename)
        filename = name[:100-len(ext)] + ext

    return filename

@dataclass
class EncodingTask:
    """Représente une tâche d'encodage avec tous ses attributs"""
    id: str
    data: Dict[str, Any]
    status: str = "QUEUED"
    position: int = 0
    progress: float = 0
    added_time: float = field(default_factory=time.time)
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    output_file: Optional[str] = None
    error: Optional[str] = None

class EncodingQueue:
    def __init__(self, max_concurrent: int = 1):
        self.queue: Deque[EncodingTask] = deque()
        self.active_tasks: Dict[str, EncodingTask] = {}
        self.running_tasks: Dict[str, asyncio.Task] = {}
        self.max_concurrent = max(max_concurrent, 1)
        self.lock = asyncio.Lock()
        self.task_counter = 0
        self.queue_notifier = asyncio.Condition()
        self._stop_event = asyncio.Event()
        self._queue_processor: Optional[asyncio.Task] = None
        self._started = False

    async def start(self) -> None:
        """Démarre le processeur de file d'attente"""
        if self._queue_processor is None or self._queue_processor.done():
            self._stop_event.clear()
            self._queue_processor = asyncio.create_task(self._process_queue(), name="QueueProcessor")
            self._started = True
            logger.info("✅ Processeur de file d'attente démarré")

    async def stop(self, cancel_active: bool = False) -> None:
        """Arrête le processeur de file d'attente"""
        self._stop_event.set()
        self._started = False

        if cancel_active:
            async with self.lock:
                for task_id, task in list(self.running_tasks.items()):
                    task.cancel()
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass

        if self._queue_processor and not self._queue_processor.done():
            await self._queue_processor
            self._queue_processor = None

    async def add_task(self, task_data: Dict[str, Any]) -> str:
        """Ajoute une tâche à la file d'attente et démarre le processeur si nécessaire"""
        async with self.lock:
            task_id = f"TASK-{self.task_counter}"
            self.task_counter += 1

            task = EncodingTask(
                id=task_id,
                data=task_data,
                position=len(self.queue) + 1
            )

            self.queue.append(task)
            logger.info(f"📥 Nouvelle tâche ajoutée: {task_id} | Position: {len(self.queue)}")

            # Démarrer le processeur de file s'il ne l'est pas déjà
            if not self._started:
                logger.info("🚀 Démarrage automatique du processeur de file...")
                await self.start()

            # Envoi du message de progression initial pour la file d'attente
            client = task_data.get('client')
            message = task_data.get('message')
            status_msg = task_data.get('msg')

            if client and message and status_msg:
                await send_progress(
                    client=client,
                    chat_id=message.chat.id,
                    message_id=status_msg.id,
                    text="⏳ **Tâche en file d'attente**",
                    percent=0,
                    total=100,
                    current=task.position,
                    show_stats=True,
                    show_time=False,
                    show_bar=True,
                    parse=ParseMode.HTML
                )

            async with self.queue_notifier:
                self.queue_notifier.notify_all()

            return task_id

    async def _process_queue(self) -> None:
        """Processus principal de traitement de la file d'attente"""
        logger.info("🔄 Démarrage du processeur de file d'attente")

        while not self._stop_event.is_set():
            try:
                async with self.lock:
                    available_slots = self.max_concurrent - len(self.running_tasks)
                    tasks_to_start = min(available_slots, len(self.queue))

                    if tasks_to_start > 0:
                        logger.info(f"🎯 Démarrage de {tasks_to_start} tâche(s) - Slots disponibles: {available_slots}")

                    for _ in range(tasks_to_start):
                        if not self.queue:
                            break

                        task = self.queue.popleft()
                        task_id = task.id

                        # Mise à jour des positions des tâches restantes
                        for idx, queued_task in enumerate(self.queue):
                            queued_task.position = idx + 1
                            await self._update_queued_task_progress(queued_task)

                        task.status = "PROCESSING"
                        task.start_time = time.time()

                        # Calcul du temps d'attente en file
                        wait_duration = time.time() - task.added_time
                        wait_time_str = humanize_time(wait_duration)
                        logger.info(f"⏱️  Tâche {task_id} a attendu {wait_time_str} en file")

                        await self._update_task_progress(task, f"🚀 **Démarrage du traitement...** (Attente: {wait_time_str})")

                        task_obj = asyncio.create_task(
                            self._execute_task(task),
                            name=task_id
                        )
                        self.active_tasks[task_id] = task
                        self.running_tasks[task_id] = task_obj
                        logger.info(f"▶️ Tâche démarrée: {task_id}")

                # Attendre une notification ou un timeout
                try:
                    async with self.queue_notifier:
                        if self.queue:
                            timeout = 0.5
                        else:
                            timeout = 2.0

                        await asyncio.wait_for(self.queue_notifier.wait(), timeout=timeout)
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.error(f"❌ Erreur dans l'attente de la file: {e}")
                    await asyncio.sleep(1)

            except Exception as e:
                logger.error(f"❌ Erreur dans le processeur de file: {e}", exc_info=True)
                await asyncio.sleep(1)

        logger.info("🛑 Arrêt du processeur de file d'attente")

    async def _update_queued_task_progress(self, task: EncodingTask) -> None:
        """Met à jour la progression d'une tâche en file d'attente"""
        try:
            client = task.data.get('client')
            message = task.data.get('message')
            status_msg = task.data.get('msg')

            if client and message and status_msg:
                wait_duration = time.time() - task.added_time
                wait_time_str = humanize_time_short(wait_duration)

                await send_progress(
                    client=client,
                    chat_id=message.chat.id,
                    message_id=status_msg.id,
                    text=f"⏳ **En attente** - Position {task.position} (depuis {wait_time_str})",
                    percent=0,
                    total=100,
                    current=task.position,
                    show_stats=True,
                    show_time=False,
                    show_bar=True,
                    parse=ParseMode.HTML
                )
        except Exception as e:
            logger.debug(f"⚠️ Erreur lors de la mise à jour de la progression en file: {e}")

    async def _update_task_progress(self, task: EncodingTask, text: str = None) -> None:
        """Met à jour la progression d'une tâche active"""
        try:
            client = task.data.get('client')
            message = task.data.get('message')
            status_msg = task.data.get('msg')

            if client and message and status_msg:
                default_text = "🚀 **Traitement en cours...**"

                # Ajouter le temps écoulé depuis le début du traitement
                if task.start_time:
                    elapsed = time.time() - task.start_time
                    elapsed_str = humanize_time_short(elapsed)
                    default_text += f" ({elapsed_str})"

                await send_progress(
                    client=client,
                    chat_id=message.chat.id,
                    message_id=status_msg.id,
                    text=text or default_text,
                    percent=task.progress,
                    total=100,
                    current=int(task.progress),
                    show_stats=True,
                    show_time=True,
                    show_bar=True,
                    parse=ParseMode.MARKDOWN
                )
        except Exception as e:
            logger.debug(f"⚠️ Erreur lors de la mise à jour de la progression: {e}")

    async def _execute_task(self, task: EncodingTask) -> None:
        """Exécute une tâche d'encodage"""
        task_id = task.id
        try:
            client = task.data.get('client')
            userbot = task.data.get('userbot')
            message = task.data.get('message')
            status_msg = task.data.get('msg')

            if not all([client, message, status_msg]):
                raise ValueError("Données de tâche incomplètes")

            # Configuration du chemin de fichier
            # Si encoder_flow a déjà téléchargé le fichier, on utilise ce chemin directement
            if task.data.get('filepath') and os.path.exists(task.data['filepath']):
                file_path = task.data['filepath']
                logger.info(f"✅ Fichier pré-téléchargé détecté: {file_path}")
            else:
                task_dir = task.data.get('task_dir') or os.path.dirname(task.data.get('filepath', ''))
                os.makedirs(task_dir, exist_ok=True)
                unique_filename = task.data.get('unique_filename') or task.data.get('filename')
                file_path = os.path.join(task_dir, unique_filename)

            # Classe de progression pour le téléchargement avec vitesse et estimation
            class _DownloadProgress:
                def __init__(self, client, chat_id, msg_id, filename):
                    self.client = client
                    self.chat_id = chat_id
                    self.msg_id = msg_id
                    self.filename = filename
                    self.start_time = time.time()
                    self.last_update = self.start_time
                    self.last_speed_calculation = self.start_time
                    self.last_bytes = 0

                async def update(self, current: int, total: int):
                    now = time.time()
                    # Limiter les mises à jour à toutes les 2 secondes maximum
                    if now - self.last_update < 10.0:
                        return

                    self.last_update = now
                    percent = (current / total) * 100 if total else 0

                    # Calcul de la vitesse et du temps restant
                    speed_info = calculate_speed(current, total, self.start_time)

                    # Texte détaillé avec toutes les informations
                    text = (
                        f"⬇️ **Téléchargement en cours**\n"
                        f"`{self.filename}`\n"
                        f"**Progression:** {speed_info['current_human']} / {speed_info['total_human']}\n"
                        f"**Vitesse:** {speed_info['speed_human']}\n"
                        f"**Temps écoulé:** {speed_info['elapsed_human']}\n"
                        f"**Temps restant:** {speed_info['remaining_human']}"
                    )

                    await send_progress(
                        client=self.client,
                        chat_id=self.chat_id,
                        message_id=self.msg_id,
                        text=text,
                        percent=percent,
                        total=total,
                        current=current,
                        show_stats=False,
                        show_time=False,
                        show_bar=True,
                        parse=ParseMode.HTML
                    )

            # Mise à jour avant le téléchargement
            await self._update_task_progress(task, "⬇️ **Préparation du téléchargement...**")

            # Téléchargement du fichier si nécessaire
            if not os.path.exists(file_path):

                source_url = task.data.get('source_url')
                if source_url:
                    try:
                        parsed = urlparse(source_url)
                        url_path = unquote(parsed.path or '')
                        ext = os.path.splitext(url_path)[1].lstrip('.').lower()

                        async with aiohttp.ClientSession() as session:
                            try:
                                async with session.head(source_url, timeout=15) as head_resp:
                                    content_type = head_resp.headers.get('Content-Type', '')
                                    content_length = head_resp.headers.get('Content-Length')
                            except Exception:
                                content_type = ''
                                content_length = None

                            is_stream = False
                            if ext == 'm3u8' or 'mpegurl' in content_type or 'application/vnd.apple.mpegurl' in content_type:
                                is_stream = True

                            if is_stream:
                                task.data['filepath'] = source_url
                                logger.info(f"📡 Source stream détectée, utilisation directe de l'URL")
                            else:
                                total_size = int(content_length) if content_length and content_length.isdigit() else 0
                                progress = _DownloadProgress(client, message.chat.id, status_msg.id, task.data.get('filename'))

                                async with session.get(source_url) as resp:
                                    if resp.status != 200:
                                        raise Exception(f"HTTP {resp.status} pour {source_url}")

                                    os.makedirs(os.path.dirname(file_path), exist_ok=True)
                                    downloaded = 0
                                    with open(file_path, 'wb') as fd:
                                        async for chunk in resp.content.iter_chunked(64 * 1024):
                                            if not chunk:
                                                break
                                            fd.write(chunk)
                                            downloaded += len(chunk)
                                            try:
                                                await progress.update(downloaded, total_size)
                                            except Exception as e:
                                                logger.debug(f"Erreur mise à jour progression: {e}")

                                    download_time = time.time() - progress.start_time
                                    avg_speed = downloaded / download_time if download_time > 0 else 0
                                    logger.info(f"✅ Téléchargement HTTP terminé en {humanize_time(download_time)} "
                                              f"({humanbytes(avg_speed)}/s): {humanbytes(downloaded)}")

                                task.data['filepath'] = file_path

                    except Exception as e:
                        task.status = "FAILED"
                        task.error = str(e)
                        task.end_time = time.time()
                        logger.error(f"❌ Échec téléchargement HTTP pour {task_id}: {e}")
                        await self._notify_failure(task)
                        return
                else:
                    try:
                        progress = _DownloadProgress(client, message.chat.id, status_msg.id, task.data.get('filename'))
                        from isocode.utils.telegram.media import download_media

                        downloaded = await download_media(
                            client=client,
                            message=message,
                            file_path=file_path,
                            progress_callback=progress.update,
                            userbot=userbot,
                        )

                        if not downloaded:
                            raise FileNotFoundError("Échec du téléchargement")

                        download_time = time.time() - progress.start_time
                        file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
                        avg_speed = file_size / download_time if download_time > 0 else 0

                        task.data['filepath'] = file_path
                        logger.info(f"✅ Téléchargement Telegram terminé en {humanize_time(download_time)} "
                                  f"({humanbytes(avg_speed)}/s): {humanbytes(file_size)}")

                    except Exception as e:
                        task.status = "FAILED"
                        task.error = str(e)
                        task.end_time = time.time()
                        logger.error(f"❌ Échec téléchargement Telegram pour {task_id}: {e}")
                        await self._notify_failure(task)
                        return
            else:
                file_size = os.path.getsize(file_path)
                logger.info(f"✅ Fichier déjà existant: {humanbytes(file_size)}")

            # Synchroniser le chemin dans task.data pour la suite (encode, cleanup, etc.)
            task.data['filepath'] = file_path

            # Vérifier que le fichier a été correctement téléchargé / pré-chargé
            if not os.path.exists(task.data['filepath']):
                raise FileNotFoundError(f"Fichier non trouvé: {task.data['filepath']}")

            file_size = os.path.getsize(task.data['filepath'])
            logger.info(f"📊 Taille du fichier à encoder: {humanbytes(file_size)}")


            # Mise à jour avant l'encodage
            await self._update_task_progress(task, "🎬 **Préparation de l'encodage...**")

            # Injecter la sélection de pistes dans user_settings
            user_settings = task.data.get('user_settings') or {}
            track_selection = task.data.get('track_selection')
            if track_selection:
                user_settings['track_selection'] = track_selection

            # Exécution de la tâche d'encodage
            encode_start_time = time.time()
            output_file = await encode_video(
                task.data['filepath'],
                task.data['message'],
                task.data['msg'],
                user_settings=user_settings,
                user_obj=task.data.get('user')
            )
            encode_time = time.time() - encode_start_time

            # Renommer le fichier de sortie avec un nom propre
            if output_file and os.path.exists(output_file):
                # Générer un nom de fichier final propre
                original_filename = task.data.get('filename', 'video_encodee')
                clean_name = sanitize_filename(original_filename)

                # S'assurer que l'extension est .mkv
                name_without_ext, _ = os.path.splitext(clean_name)
                final_filename = f"{name_without_ext}.mkv"

                # Chemin final pour le fichier
                output_dir = os.path.dirname(output_file)
                final_output_path = os.path.join(output_dir, final_filename)

                # Renommer le fichier
                if output_file != final_output_path:
                    os.rename(output_file, final_output_path)
                    output_file = final_output_path
                    logger.info(f"📝 Fichier renommé: {final_filename}")

                output_size = os.path.getsize(output_file)
                compression_ratio = (1 - output_size / file_size) * 100 if file_size > 0 else 0
                logger.info(f"📊 Taille fichier encodé: {humanbytes(output_size)} "
                          f"(compression: {compression_ratio:.1f}%)")

            task.status = "COMPLETED"
            task.output_file = output_file
            task.progress = 100
            task.end_time = time.time()

            total_time = task.end_time - task.start_time
            logger.info(f"✅ Tâche terminée avec succès en {humanize_time(total_time)} (encodage: {humanize_time(encode_time)}): {task_id}")

            await self._update_task_progress(task, f"✅ **Encodage terminé en {humanize_time_short(encode_time)}!**")

            await self._send_encoded_video(task)

        except asyncio.CancelledError:
            task.status = "CANCELLED"
            task.end_time = time.time()
            if task.start_time:
                total_time = task.end_time - task.start_time
                logger.warning(f"⏹️ Tâche annulée après {humanize_time(total_time)}: {task_id}")
            else:
                logger.warning(f"⏹️ Tâche annulée: {task_id}")
            await self._notify_cancellation(task)

        except Exception as e:
            task.status = "FAILED"
            task.error = str(e)
            task.end_time = time.time()
            if task.start_time:
                total_time = task.end_time - task.start_time
                logger.error(f"❌ Échec de la tâche après {humanize_time(total_time)} {task_id}: {str(e)}", exc_info=True)
            else:
                logger.error(f"❌ Échec de la tâche {task_id}: {str(e)}", exc_info=True)
            await self._notify_failure(task)

        finally:
            await self._cleanup_files(task)

            async with self.lock:
                self.running_tasks.pop(task_id, None)
                self.active_tasks.pop(task_id, None)

                async with self.queue_notifier:
                    self.queue_notifier.notify_all()

    async def _send_encoded_video(self, task: EncodingTask) -> None:
        """Envoie la vidéo encodée à l'utilisateur avec progression détaillée"""
        try:
            client = task.data['client']
            userbot = task.data['userbot']
            message = task.data['message']
            status_msg = task.data['msg']
            output_file = task.output_file

            if not output_file or not os.path.exists(output_file):
                raise FileNotFoundError(f"Fichier de sortie non trouvé: {output_file}")

            final_filename = os.path.basename(output_file)
            output_size = os.path.getsize(output_file)
            logger.info(f"📤 Préparation envoi: {final_filename} ({humanbytes(output_size)})")

            await send_progress(
                client=client,
                chat_id=message.chat.id,
                message_id=status_msg.id,
                text=(
                    f"📤 **Envoi en cours**\n"
                    f"`{final_filename}`\n"
                    f"**Taille:** {humanbytes(output_size)}\n"
                    f"**Préparation de l'envoi...**"
                ),
                percent=100,
                total=100,
                current=100,
                show_stats=False,
                show_time=False,
                show_bar=False,
                parse=ParseMode.MARKDOWN
            )


            try:
                await send_media(
                    client=client,
                    chat_id=message.chat.id,
                    media_type="video",
                    media=output_file,
                    caption=f"<b>{final_filename}</b>",
                    reply_to=message.id,
                    progress_msg=status_msg,
                    force_document=False,
                    userbot=userbot,
                    parse_mode=ParseMode.HTML
                )
            except TypeError as e:
                if "unexpected keyword argument 'progress_msg'" in str(e):
                    logger.warning("⚠️ progress_msg non supporté, utilisation sans progression détaillée")
                    await send_media(
                        client=client,
                        chat_id=message.chat.id,
                        media_type="video",
                        media=output_file,
                        caption=f"<b>{final_filename}</b>",
                        reply_to=message.id,
                        force_document=False,
                        userbot=userbot,
                        parse_mode=ParseMode.HTML
                    )
                else:
                    raise

            logger.info(f"✅ Envoi terminé: {final_filename}")

            await del_msg(client, message.chat.id, status_msg.id)

        except Exception as e:
            logger.error(f"❌ Erreur lors de l'envoi de la vidéo: {e}")
            await send_msg(
                client,
                message.chat.id,
                f"❌ Échec de l'envoi de la vidéo: {e}",
                reply_to=message.id
            )

    async def _notify_cancellation(self, task: EncodingTask) -> None:
        try:
            client = task.data['client']
            message = task.data['message']
            total_time = humanize_time(task.end_time - task.start_time) if task.start_time else "temps inconnu"
            await send_msg(
                client,
                message.chat.id,
                f"❌ Tâche d'encodage annulée après {total_time}: {task.id}",
                reply_to=message.id
            )
        except Exception as e:
            logger.error(f"❌ Erreur de notification d'annulation: {e}")

    async def _notify_failure(self, task: EncodingTask) -> None:
        try:
            client = task.data['client']
            message = task.data['message']
            total_time = humanize_time(task.end_time - task.start_time) if task.start_time else "temps inconnu"
            await send_msg(
                client,
                message.chat.id,
                f"❌ Échec de l'encodage après {total_time}: {task.error}\n"
                f"ID Tâche: {task.id}",
                reply_to=message.id
            )
        except Exception as e:
            logger.error(f"❌ Erreur de notification d'échec: {e}")

    async def _cleanup_files(self, task: EncodingTask) -> None:
        try:
            # Supprimer le fichier source téléchargé
            if task.data.get('filepath') and os.path.exists(task.data['filepath']):
                file_size = os.path.getsize(task.data['filepath'])
                os.remove(task.data['filepath'])
                logger.info(f"🧹 Fichier source supprimé: {humanbytes(file_size)}")

            # Supprimer le répertoire temporaire de la tâche si vide
            try:
                if task.data.get('filepath'):
                    task_parent = os.path.dirname(task.data['filepath'])
                    if os.path.basename(task_parent).startswith('task_'):
                        if os.path.isdir(task_parent) and not os.listdir(task_parent):
                            os.rmdir(task_parent)
                            logger.info(f"🗂️ Répertoire temporaire supprimé: {task_parent}")
            except Exception as e:
                logger.debug(f"⚠️ Erreur suppression répertoire temporaire: {e}")

            if task.output_file and os.path.exists(task.output_file):
                asyncio.create_task(self._delayed_cleanup(task.output_file))
        except Exception as e:
            logger.error(f"❌ Erreur de nettoyage des fichiers: {e}")

    async def _delayed_cleanup(self, file_path: str, delay: int = 3600) -> None:
        await asyncio.sleep(delay)
        try:
            if os.path.exists(file_path):
                file_size = os.path.getsize(file_path)
                os.remove(file_path)
                logger.info(f"🧹 Fichier temporaire supprimé: {humanbytes(file_size)}")
        except Exception as e:
            logger.error(f"❌ Échec de suppression de {file_path}: {e}")

    async def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Récupère le statut d'une tâche spécifique"""
        async with self.lock:
            if task_id in self.active_tasks:
                return self._format_task_info(self.active_tasks[task_id])

            for task in self.queue:
                if task.id == task_id:
                    return self._format_queued_info(task)

            return None

    async def get_queue_status(self) -> Dict[str, Any]:
        """Retourne l'état complet de la file d'attente"""
        async with self.lock:
            return {
                'active': [self._format_task_info(t) for t in self.active_tasks.values()],
                'queued': [self._format_queued_info(t) for t in self.queue],
                'stats': {
                    'active_count': len(self.active_tasks),
                    'queued_count': len(self.queue),
                    'max_concurrent': self.max_concurrent,
                    'processed_count': self.task_counter - len(self.queue) - len(self.active_tasks)
                }
            }

    def _format_task_info(self, task: EncodingTask) -> Dict[str, Any]:
        """Formate les informations d'une tâche en cours"""
        duration = None
        if task.start_time:
            duration = humanize_time((task.end_time or time.time()) - task.start_time)

        file_size = None
        if task.data.get('filepath') and os.path.exists(task.data['filepath']):
            file_size = humanbytes(os.path.getsize(task.data['filepath']))

        return {
            'id': task.id,
            'status': task.status,
            'progress': task.progress,
            'file': os.path.basename(task.data.get('filepath', task.data.get('filename', ''))),
            'file_size': file_size,
            'start_time': task.start_time,
            'duration': duration,
            'output_file': task.output_file,
            'error': task.error
        }

    async def get_task_position(self, task_id: str) -> int:
        async with self.lock:
            for idx, task in enumerate(self.queue):
                if task.id == task_id:
                    return idx + 1

            if task_id in self.active_tasks:
                return 0

            return -1

    def _format_queued_info(self, task: EncodingTask) -> Dict[str, Any]:
        """Formate les informations d'une tâche en attente"""
        wait_time = humanize_time(time.time() - task.added_time)

        file_size = None
        if task.data.get('filepath') and os.path.exists(task.data['filepath']):
            file_size = humanbytes(os.path.getsize(task.data['filepath']))

        return {
            'id': task.id,
            'position': task.position,
            'wait_time': wait_time,
            'file': os.path.basename(task.data.get('filepath', task.data.get('filename', ''))),
            'file_size': file_size,
            'status': task.status
        }

    async def notify_progress(self, task_id: str, progress: float) -> bool:
        """Met à jour la progression d'une tâche"""
        async with self.lock:
            if task_id in self.active_tasks:
                self.active_tasks[task_id].progress = max(0, min(100, progress))
                return True
            return False

    async def cancel_task(self, task_id: str) -> bool:
        """Annule une tâche en cours ou en attente"""
        async with self.lock:
            if task_id in self.running_tasks:
                self.running_tasks[task_id].cancel()
                return True

            for idx, task in enumerate(self.queue):
                if task.id == task_id:
                    self.queue.remove(task)
                    for i, t in enumerate(self.queue[idx:]):
                        t.position = idx + i + 1
                    return True

            return False

# Initialisation globale de la file d'attente
queue_system = EncodingQueue(max_concurrent=getattr(settings, 'ENCODER_MAX_CONCURRENT', 2))

async def initialize_queue_system():
    """Initialise et démarre le système de file d'attente"""
    await queue_system.start()
    logger.info("✅ Système de file d'attente d'encodage initialisé")

async def shutdown_queue_system():
    """Arrête le système de file d'attente"""
    await queue_system.stop(cancel_active=True)
    logger.info("🛑 Système de file d'attente d'encodage arrêté")