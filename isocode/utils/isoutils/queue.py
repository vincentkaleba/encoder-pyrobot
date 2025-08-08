import asyncio
import logging
import os
import time
from collections import deque
from typing import Dict, Deque, List, Optional, Any
from dataclasses import dataclass, field
from pyrogram.enums import ParseMode

# Importe ta fonction d'encodage et fonctions telegram
from isocode.utils.isoutils.ffmpeg import encode_video
from isocode.utils.telegram.media import send_media
from isocode.utils.telegram.message import send_msg, edit_msg, del_msg
from isocode import logger


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
            logger.info("QueueProcessor démarré")

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
        logger.info("QueueProcessor arrêté")

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
            logger.info(f"Queue: {len(self.queue)} en attente, {len(self.running_tasks)} en cours")
            async with self.lock:
                available_slots = self.max_concurrent - len(self.running_tasks)
                tasks_to_start = min(available_slots, len(self.queue))

                if tasks_to_start == 0:
                    logger.info("Aucune tâche à démarrer pour le moment.")
                else:
                    logger.info(f"Démarrage de {tasks_to_start} tâche(s)")

                for _ in range(tasks_to_start):
                    task = self.queue.popleft()
                    task_id = task.id
                    logger.info(f"Démarrage tâche {task_id}")

                    for idx, queued_task in enumerate(self.queue):
                        queued_task.position = idx + 1

                    task.status = "PROCESSING"
                    task.start_time = time.time()

                    task_obj = asyncio.create_task(
                        self._execute_task(task),
                        name=task_id
                    )
                    self.active_tasks[task_id] = task
                    self.running_tasks[task_id] = task_obj

            try:
                async with self.queue_notifier:
                    timeout = 2.0 if not self.queue else 0.1
                    await asyncio.wait_for(self.queue_notifier.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                pass
        logger.info("Arrêt du processeur de file d'attente")

    async def _execute_task(self, task: EncodingTask) -> None:
        task_id = task.id
        logger.info(f"[TASK {task_id}] Début de l'encodage")
        try:
            output_file = await encode_video(
                task.data['filepath'],
                task.data['message'],
                task.data['msg'],
            )
            logger.info(f"[TASK {task_id}] Encodage terminé: {output_file}")

            task.status = "COMPLETED"
            task.output_file = output_file
            task.progress = 100
            task.end_time = time.time()

            await self._send_encoded_video(task)

        except asyncio.CancelledError:
            task.status = "CANCELLED"
            task.end_time = time.time()
            logger.warning(f"[TASK {task_id}] Tâche annulée")
            await self._notify_cancellation(task)

        except Exception as e:
            task.status = "FAILED"
            task.error = str(e)
            task.end_time = time.time()
            logger.error(f"[TASK {task_id}] Erreur pendant l'encodage: {e}", exc_info=True)
            await self._notify_failure(task)

        finally:
            await self._cleanup_files(task)
            async with self.lock:
                logger.info(f"[TASK {task_id}] Nettoyage, tâches en cours avant suppression : {list(self.running_tasks.keys())}")
                self.running_tasks.pop(task_id, None)
                self.active_tasks.pop(task_id, None)
                logger.info(f"[TASK {task_id}] Tâches en cours après suppression : {list(self.running_tasks.keys())}")

                async with self.queue_notifier:
                    self.queue_notifier.notify_all()

    async def _send_encoded_video(self, task: EncodingTask) -> None:
        try:
            client = task.data['client']
            userbot = task.data.get('userbot')
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

            await send_media(
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
            )

            await del_msg(client, message.chat.id, status_msg.id)

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
            await send_msg(
                client,
                message.chat.id,
                f"❌ Tâche d'encodage annulée: {task.id}",
                reply_to=message.id
            )
        except Exception as e:
            logger.error(f"Erreur de notification d'annulation: {e}")

    async def _notify_failure(self, task: EncodingTask) -> None:
        try:
            client = task.data['client']
            message = task.data['message']
            await send_msg(
                client,
                message.chat.id,
                f"❌ Échec de l'encodage: {task.error}\nID Tâche: {task.id}",
                reply_to=message.id
            )
        except Exception as e:
            logger.error(f"Erreur de notification d'échec: {e}")

    async def _cleanup_files(self, task: EncodingTask) -> None:
        try:
            if os.path.exists(task.data['filepath']):
                os.remove(task.data['filepath'])

            if task.output_file and os.path.exists(task.output_file):
                asyncio.create_task(self._delayed_cleanup(task.output_file))
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
        async with self.lock:
            if task_id in self.active_tasks:
                return self._format_task_info(self.active_tasks[task_id])

            for task in self.queue:
                if task.id == task_id:
                    return self._format_queued_info(task)

            return None

    async def get_queue_status(self) -> Dict[str, Any]:
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

    def _format_queued_info(self, task: EncodingTask) -> Dict[str, Any]:
        return {
            'id': task.id,
            'position': task.position,
            'wait_time': time.time() - task.added_time,
            'file': os.path.basename(task.data['filepath']),
            'status': task.status
        }

    async def get_task_position(self, task_id: str) -> int:
        async with self.lock:
            for idx, task in enumerate(self.queue):
                if task.id == task_id:
                    return idx + 1

            if task_id in self.active_tasks:
                return 0

            return -1

    async def notify_progress(self, task_id: str, progress: float) -> bool:
        async with self.lock:
            if task_id in self.active_tasks:
                self.active_tasks[task_id].progress = max(0, min(100, progress))
                return True
            return False

    async def cancel_task(self, task_id: str) -> bool:
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


# Instance globale
queue_system = EncodingQueue(max_concurrent=2)


async def initialize_queue_system():
    """Initialise et démarre le système de file d'attente"""
    await queue_system.start()
    logger.info("Système de file d'attente d'encodage initialisé")


async def shutdown_queue_system():
    """Arrête le système de file d'attente"""
    await queue_system.stop(cancel_active=True)
    logger.info("Système de file d'attente arrêté")