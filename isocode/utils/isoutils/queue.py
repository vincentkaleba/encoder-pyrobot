import asyncio
import logging
import os
import time
from collections import deque
from typing import Dict, Deque, List, Optional, Any, Union
from dataclasses import dataclass, field
from isocode import logger
from isocode.utils.isoutils.ffmpeg import encode_video, get_thumbnail, get_duration
from isocode.utils.isoutils.progress import stylize_value
from isocode.utils.telegram.media import send_media
from isocode.utils.telegram.message import send_msg, edit_msg, del_msg
from pyrogram.enums import ParseMode

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

    async def start(self) -> None:
        if self._queue_processor is None or self._queue_processor.done():
            self._stop_event.clear()
            self._queue_processor = asyncio.create_task(self._process_queue(), name="QueueProcessor")

    async def stop(self, cancel_active: bool = False) -> None:
        self._stop_event.set()
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

    async def add_task(self, task_data: Dict[str, Any]) -> str:
        async with self.lock:
            task_id = f"TASK-{self.task_counter}"
            self.task_counter += 1

            task = EncodingTask(
                id=task_id,
                data=task_data,
                position=len(self.queue) + 1
            )

            self.queue.append(task)
            logger.info(f"Nouvelle tâche ajoutée: {task_id} | Position: {len(self.queue)}")

            async with self.queue_notifier:
                self.queue_notifier.notify_all()

            return task_id

    async def _process_queue(self) -> None:
        logger.info("Démarrage du processeur de file d'attente")

        while not self._stop_event.is_set():
            tasks_to_start = []
            async with self.lock:
                available_slots = self.max_concurrent - len(self.running_tasks)
                tasks_to_start = [self.queue.popleft() for _ in range(min(available_slots, len(self.queue)))]

                for idx, queued_task in enumerate(self.queue):
                    queued_task.position = idx + 1

            for task in tasks_to_start:
                task.status = "PROCESSING"
                task.start_time = time.time()

                task_obj = asyncio.create_task(
                    self._execute_task(task),
                    name=task.id
                )

                async with self.lock:
                    self.active_tasks[task.id] = task
                    self.running_tasks[task.id] = task_obj

                logger.info(f"Tâche démarrée: {task.id}")

            try:
                async with self.queue_notifier:
                    if not self.queue:
                        await asyncio.wait_for(self.queue_notifier.wait(), timeout=5.0)
                    else:
                        await asyncio.wait_for(self.queue_notifier.wait(), timeout=0.1)
            except asyncio.TimeoutError:
                pass

        logger.info("Arrêt du processeur de file d'attente")

    async def _execute_task(self, task: EncodingTask) -> None:
        task_id = task.id
        try:
            output_file = await asyncio.wait_for(
                encode_video(
                    task.data['filepath'],
                    task.data['message'],
                    task.data['msg'],
                ),
                timeout=None
            )

            task.status = "COMPLETED"
            task.output_file = output_file
            task.progress = 100
            task.end_time = time.time()
            logger.info(f"Tâche terminée avec succès: {task_id}")

            await self._send_encoded_video(task)

        except asyncio.CancelledError:
            task.status = "CANCELLED"
            task.end_time = time.time()
            logger.warning(f"Tâche annulée: {task_id}")
            await self._notify_cancellation(task)

        except Exception as e:
            task.status = "FAILED"
            task.error = str(e)
            task.end_time = time.time()
            logger.error(f"Échec de la tâche {task_id}: {str(e)}", exc_info=True)
            await self._notify_failure(task)

        finally:
            await self._cleanup_files(task)

            async with self.lock:
                self.running_tasks.pop(task_id, None)
                self.active_tasks.pop(task_id, None)

                async with self.queue_notifier:
                    self.queue_notifier.notify_all()

    async def _send_encoded_video(self, task: EncodingTask) -> None:
        """Envoie la vidéo encodée à l'utilisateur"""
        try:
            client = task.data['client']
            userbot = task.data['userbot']
            message = task.data['message']
            status_msg = task.data['msg']
            output_file = task.output_file
            filename = os.path.basename(output_file)

            await edit_msg(
                client,
                message.chat.id,
                status_msg.id,
                "📤 Envoi de la vidéo encodée..."
            )

            asyncio.create_task(
                send_media(
                    client=client,
                    chat_id=message.chat.id,
                    media_type="video",
                    media=output_file,
                    caption=f"<b>{filename}</b>",
                    reply_to=message.id,
                    progress_msg=status_msg,
                    force_document=False,
                    userbot=userbot,
                    parse_mode=ParseMode.HTML
                ),
                name=f"send-media-{task.id}"
            )

        except Exception as e:
            logger.error(f"Erreur lors de l'envoi de la vidéo: {e}")
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
            asyncio.create_task(
                send_msg(
                    client,
                    message.chat.id,
                    f"❌ Tâche d'encodage annulée: {task.id}",
                    reply_to=message.id
                ),
                name=f"notify-cancel-{task.id}"
            )
        except Exception as e:
            logger.error(f"Erreur de notification d'annulation: {e}")

    async def _notify_failure(self, task: EncodingTask) -> None:
        try:
            client = task.data['client']
            message = task.data['message']
            asyncio.create_task(
                send_msg(
                    client,
                    message.chat.id,
                    f"❌ Échec de l'encodage: {task.error}\n"
                    f"ID Tâche: {task.id}",
                    reply_to=message.id
                ),
                name=f"notify-fail-{task.id}"
            )
        except Exception as e:
            logger.error(f"Erreur de notification d'échec: {e}")

    async def _cleanup_files(self, task: EncodingTask) -> None:
        try:
            if os.path.exists(task.data['filepath']):
                os.remove(task.data['filepath'])

            if task.output_file and os.path.exists(task.output_file):
                asyncio.create_task(
                    self._delayed_cleanup(task.output_file),
                    name=f"cleanup-{task.id}"
                )
        except Exception as e:
            logger.error(f"Erreur de nettoyage des fichiers: {e}")

    async def _delayed_cleanup(self, file_path: str, delay: int = 3600) -> None:
        await asyncio.sleep(delay)
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Fichier temporaire supprimé: {file_path}")
        except Exception as e:
            logger.error(f"Échec de suppression de {file_path}: {e}")

    async def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Récupère le statut d'une tâche spécifique

        :param task_id: ID de la tâche à rechercher
        :return: Dictionnaire d'information ou None si non trouvée
        """
        async with self.lock:
            if task_id in self.active_tasks:
                return self._format_task_info(self.active_tasks[task_id])

            for task in self.queue:
                if task.id == task_id:
                    return self._format_queued_info(task)

            return None

    async def get_queue_status(self) -> Dict[str, Any]:
        """
        Retourne l'état complet de la file d'attente

        :return: Dictionnaire avec l'état des tâches actives et en attente
        """
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
        return {
            'id': task.id,
            'status': task.status,
            'progress': task.progress,
            'file': os.path.basename(task.data['filepath']),
            'start_time': task.start_time,
            'duration': (task.end_time or time.time()) - task.start_time if task.start_time else None,
            'output_file': task.output_file,
            'error': task.error
        }

    async def get_task_position(self, task_id: str) -> int:
        async with self.lock:
            for idx, task in enumerate(self.queue):
                if task.id == task_id:
                    return idx + 1

            if task_id in self.active_tasks:
                return 0  # 0 = en cours de traitement

            return -1  # Non trouvée

    def _format_queued_info(self, task: EncodingTask) -> Dict[str, Any]:
        """Formate les informations d'une tâche en attente"""
        return {
            'id': task.id,
            'position': task.position,
            'wait_time': time.time() - task.added_time,
            'file': os.path.basename(task.data['filepath']),
            'status': task.status
        }

    async def notify_progress(self, task_id: str, progress: float) -> bool:
        """
        Met à jour la progression d'une tâche

        :param task_id: ID de la tâche
        :param progress: Valeur de progression (0-100)
        :return: True si mise à jour réussie, False sinon
        """
        async with self.lock:
            if task_id in self.active_tasks:
                self.active_tasks[task_id].progress = max(0, min(100, progress))
                return True
            return False

    async def cancel_task(self, task_id: str) -> bool:
        """
        Annule une tâche en cours ou en attente

        :param task_id: ID de la tâche à annuler
        :return: True si annulation réussie, False sinon
        """
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

queue_system = EncodingQueue(max_concurrent=2)

async def initialize_queue_system():
    """Initialise et démarre le système de file d'attente"""
    await queue_system.start()
    logger.info("Système de file d'attente d'encodage initialisé")

async def shutdown_queue_system():
    """Arrête le système de file d'attente"""
    await queue_system.stop(cancel_active=True)
    logger.info("Système de file d'attente d'encodage arrêté")