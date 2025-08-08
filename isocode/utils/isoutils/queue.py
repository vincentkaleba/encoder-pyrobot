import asyncio
import logging
import os
import time
from collections import deque
from typing import Dict, Deque, Optional, Any
from dataclasses import dataclass, field
from pyrogram.enums import ParseMode

from isocode.utils.isoutils.ffmpeg import encode_video
from isocode.utils.telegram.media import send_media
from isocode.utils.telegram.message import send_msg, edit_msg, del_msg
from isocode import logger


@dataclass
class EncodingTask:
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


class EncodingQueueSequential:
    def __init__(self):
        self.queue: Deque[EncodingTask] = deque()
        self.active_task: Optional[EncodingTask] = None
        self.lock = asyncio.Lock()
        self.task_counter = 0
        self._stop_event = asyncio.Event()
        self._processor_task: Optional[asyncio.Task] = None

    async def start(self):
        if self._processor_task is None or self._processor_task.done():
            self._stop_event.clear()
            self._processor_task = asyncio.create_task(self._process_queue())
            logger.info("QueueProcessor (séquentiel) démarré")

    async def stop(self):
        self._stop_event.set()
        if self._processor_task and not self._processor_task.done():
            await self._processor_task
        logger.info("QueueProcessor (séquentiel) arrêté")

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
            logger.info(f"Tâche ajoutée à la queue séquentielle: {task_id} | Position: {len(self.queue)}")
            return task_id

    async def _process_queue(self):
        while not self._stop_event.is_set():
            async with self.lock:
                if self.active_task is not None or not self.queue:
                    # Soit une tâche est en cours soit la queue est vide, on attend
                    pass
                else:
                    # Prendre la première tâche dans la queue
                    self.active_task = self.queue.popleft()
                    self.active_task.status = "PROCESSING"
                    self.active_task.start_time = time.time()

            if self.active_task:
                task = self.active_task
                task_id = task.id
                logger.info(f"[QUEUE] Début encodage tâche {task_id}")
                try:
                    output_file = await encode_video(
                        task.data['filepath'],
                        task.data['message'],
                        task.data['msg'],
                    )
                    task.status = "COMPLETED"
                    task.output_file = output_file
                    task.progress = 100
                    task.end_time = time.time()
                    logger.info(f"[QUEUE] Encodage terminé tâche {task_id}")

                    await self._send_encoded_video(task)

                except Exception as e:
                    task.status = "FAILED"
                    task.error = str(e)
                    task.end_time = time.time()
                    logger.error(f"[QUEUE] Erreur encodage tâche {task_id}: {e}", exc_info=True)
                    await self._notify_failure(task)

                finally:
                    await self._cleanup_files(task)
                    async with self.lock:
                        self.active_task = None

            # Pause courte pour éviter boucle CPU excessive
            await asyncio.sleep(0.5)

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
            logger.error(f"Erreur nettoyage fichiers: {e}")

    async def _delayed_cleanup(self, file_path: str, delay: int = 3600) -> None:
        await asyncio.sleep(delay)
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Fichier temporaire supprimé: {file_path}")
        except Exception as e:
            logger.error(f"Échec suppression fichier {file_path}: {e}")


# Instance globale à utiliser dans le reste du bot
queue_system = EncodingQueueSequential()


async def initialize_queue_system():
    await queue_system.start()
    logger.info("Système de file d'attente séquentiel initialisé")


async def shutdown_queue_system():
    await queue_system.stop()
    logger.info("Système de file d'attente séquentiel arrêté")