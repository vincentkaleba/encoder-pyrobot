import asyncio
import logging
import os
import time
from collections import deque
from typing import Dict, Deque, List, Optional, Any
from dataclasses import dataclass, field
from isocode import logger
from isocode.utils.isoutils.ffmpeg import encode_video
from isocode.utils.telegram.media import send_media
from isocode.utils.telegram.message import send_msg, edit_msg
from pyrogram.enums import ParseMode

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

class EncodingQueue:
    def __init__(self, max_concurrent: int = 1):
        self.queue: Deque[EncodingTask] = deque()
        self.active_tasks: Dict[str, EncodingTask] = {}
        self.running_tasks: Dict[str, asyncio.Task] = {}
        self.max_concurrent = max(max_concurrent, 1)
        self.task_counter = 0
        self.queue_notifier = asyncio.Condition()
        self._stop_event = asyncio.Event()
        self._queue_processor: Optional[asyncio.Task] = None

    async def start(self) -> None:
        if self._queue_processor is None or self._queue_processor.done():
            self._stop_event.clear()
            self._queue_processor = asyncio.create_task(
                self._process_queue(),
                name="QueueProcessor"
            )

    async def stop(self, cancel_active: bool = False) -> None:
        # Demande d'arrêt et réveil du processeur
        self._stop_event.set()

        # Réveille toutes les tâches en attente
        async with self.queue_notifier:
            self.queue_notifier.notify_all()

        # Annule les tâches actives si demandé
        if cancel_active:
            async with self.queue_notifier:
                for task_id, t in list(self.running_tasks.items()):
                    t.cancel()

            # Attend que les tâches se terminent
            for t in list(self.running_tasks.values()):
                try:
                    await asyncio.wait_for(t, timeout=5.0)
                except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                    pass

        # Attend l'arrêt du processeur de file
        if self._queue_processor and not self._queue_processor.done():
            try:
                await asyncio.wait_for(self._queue_processor, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                self._queue_processor.cancel()
                try:
                    await self._queue_processor
                except asyncio.CancelledError:
                    pass

    async def add_task(self, task_data: Dict[str, Any]) -> str:
        async with self.queue_notifier:
            task_id = f"TASK-{self.task_counter}"
            self.task_counter += 1

            task = EncodingTask(
                id=task_id,
                data=task_data,
                position=len(self.queue) + 1
            )

            self.queue.append(task)
            logger.info(f"Nouvelle tâche ajoutée: {task_id} | Position: {len(self.queue)}")
            self.queue_notifier.notify_all()
            return task_id

    async def _process_queue(self) -> None:
        logger.info("Démarrage du processeur de file d'attente")
        try:
            while not self._stop_event.is_set():
                tasks_to_start: List[EncodingTask] = []

                async with self.queue_notifier:
                    # Vérifier si on doit s'arrêter avant de continuer
                    if self._stop_event.is_set():
                        break

                    available_slots = self.max_concurrent - len(self.running_tasks)
                    for _ in range(min(available_slots, len(self.queue))):
                        tasks_to_start.append(self.queue.popleft())

                    # Mettre à jour les positions des tâches restantes
                    for idx, queued_task in enumerate(self.queue):
                        queued_task.position = idx + 1

                # Démarrer les tâches extraites
                for task in tasks_to_start:
                    task.status = "PROCESSING"
                    task.start_time = time.time()
                    task_obj = asyncio.create_task(
                        self._execute_task(task),
                        name=task.id
                    )

                    async with self.queue_notifier:
                        self.active_tasks[task.id] = task
                        self.running_tasks[task.id] = task_obj

                    logger.info(f"Tâche démarrée: {task.id}")

                try:
                    async with self.queue_notifier:
                        if self._stop_event.is_set():
                            break
                        await asyncio.wait_for(
                            self.queue_notifier.wait(),
                            timeout=0.5
                        )
                except asyncio.TimeoutError:
                    pass
                except asyncio.CancelledError:
                    logger.info("Traitement de file annulé")
                    raise

        except asyncio.CancelledError:
            logger.info("Processeur de file arrêté (annulé)")
            raise
        except Exception as e:
            logger.exception(f"Erreur inattendue dans _process_queue: {e}")
        finally:
            logger.info("Arrêt du processeur de file d'attente")

    async def _execute_task(self, task: EncodingTask) -> None:
        task_id = task.id
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
            try:
                await self._cleanup_files(task)
            except Exception as e:
                logger.error(f"Erreur lors du nettoyage des fichiers: {e}")

            # Nettoyage des structures partagées
            async with self.queue_notifier:
                if task_id in self.running_tasks:
                    del self.running_tasks[task_id]
                if task_id in self.active_tasks:
                    del self.active_tasks[task_id]
                self.queue_notifier.notify_all()

    async def _send_encoded_video(self, task: EncodingTask) -> None:
        try:
            client = task.data['client']
            userbot = task.data.get('userbot')
            message = task.data['message']
            status_msg = task.data['msg']
            output_file = task.output_file
            filename = os.path.basename(output_file)

            await edit_msg(client, message.chat.id, status_msg.id, "📤 Envoi de la vidéo encodée...")

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
            await send_msg(client, message.chat.id, f"❌ Échec de l'envoi de la vidéo: {e}", reply_to=message.id)

    async def _notify_cancellation(self, task: EncodingTask) -> None:
        try:
            client = task.data['client']
            message = task.data['message']
            asyncio.create_task(
                send_msg(client, message.chat.id, f"❌ Tâche d'encodage annulée: {task.id}", reply_to=message.id),
                name=f"notify-cancel-{task.id}"
            )
        except Exception as e:
            logger.error(f"Erreur de notification d'annulation: {e}")

    async def _notify_failure(self, task: EncodingTask) -> None:
        try:
            client = task.data['client']
            message = task.data['message']
            asyncio.create_task(
                send_msg(client, message.chat.id,
                         f"❌ Échec de l'encodage: {task.error}\nID Tâche: {task.id}",
                         reply_to=message.id),
                name=f"notify-fail-{task.id}"
            )
        except Exception as e:
            logger.error(f"Erreur de notification d'échec: {e}")

    async def _cleanup_files(self, task: EncodingTask) -> None:
        try:
            # Supprimer le fichier source
            source_file = task.data.get('filepath')
            if source_file and os.path.exists(source_file):
                try:
                    os.remove(source_file)
                    logger.info(f"Fichier source supprimé: {source_file}")
                except Exception as e:
                    logger.error(f"Échec de suppression du fichier source: {source_file} - {e}")

            # Planifier la suppression du fichier de sortie
            output_file = task.output_file
            if output_file and os.path.exists(output_file):
                asyncio.create_task(
                    self._delayed_cleanup(output_file),
                    name=f"cleanup-{task.id}"
                )
        except Exception as e:
            logger.error(f"Erreur générale de nettoyage: {e}")

    async def _delayed_cleanup(self, file_path: str, delay: int = 3600) -> None:
        await asyncio.sleep(delay)
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Fichier temporaire supprimé: {file_path}")
        except Exception as e:
            logger.error(f"Échec de suppression de {file_path}: {e}")

    # --- méthodes d'information ---
    async def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        async with self.queue_notifier:
            if task_id in self.active_tasks:
                return self._format_task_info(self.active_tasks[task_id])
            for task in self.queue:
                if task.id == task_id:
                    return self._format_queued_info(task)
            return None

    async def get_queue_status(self) -> Dict[str, Any]:
        async with self.queue_notifier:
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
            'file': os.path.basename(task.data.get('filepath') or ""),
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
            'file': os.path.basename(task.data.get('filepath') or ""),
            'status': task.status
        }

    async def get_task_position(self, task_id: str) -> int:
        async with self.queue_notifier:
            for idx, task in enumerate(self.queue):
                if task.id == task_id:
                    return idx + 1
            if task_id in self.active_tasks:
                return 0
            return -1

    async def notify_progress(self, task_id: str, progress: float) -> bool:
        async with self.queue_notifier:
            if task_id in self.active_tasks:
                self.active_tasks[task_id].progress = max(0, min(100, progress))
                return True
            return False

    async def cancel_task(self, task_id: str) -> bool:
        async with self.queue_notifier:
            # Tâche en cours d'exécution
            if task_id in self.running_tasks:
                self.running_tasks[task_id].cancel()
                return True

            # Tâche dans la file d'attente
            for idx, task in enumerate(self.queue):
                if task.id == task_id:
                    self.queue.remove(task)
                    # Réindexer les positions
                    for i, t in enumerate(self.queue):
                        t.position = i + 1
                    self.queue_notifier.notify_all()
                    return True
            return False

# Système global de file d'attente
queue_system: Optional[EncodingQueue] = None

async def initialize_queue_system(max_concurrent: int = 2):
    global queue_system
    if queue_system is None:
        queue_system = EncodingQueue(max_concurrent=max_concurrent)
        await queue_system.start()
        logger.info("Système de file d'attente d'encodage initialisé")

async def shutdown_queue_system():
    global queue_system
    if queue_system is not None:
        logger.info("Début de l'arrêt du système de file...")

        await asyncio.sleep(5)

        await queue_system.stop(cancel_active=True)
        queue_system = None
        logger.info("Système de file d'attente d'encodage arrêté")