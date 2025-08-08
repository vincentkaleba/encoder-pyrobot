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
import signal


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

# Modifier la classe EncodingQueue
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
        self._init_time = time.time()  # Pour le débogage

    async def start(self) -> None:
        if self._queue_processor is None or self._queue_processor.done():
            self._stop_event.clear()
            self._queue_processor = asyncio.create_task(self._process_queue(), name="QueueProcessor")
            logger.info("Processeur de file démarré")

    async def _process_queue(self) -> None:
        logger.info("Démarrage du processeur de file d'attente")

        while not self._stop_event.is_set():
            async with self.lock:
                available_slots = self.max_concurrent - len(self.running_tasks)
                tasks_to_start = min(available_slots, len(self.queue))

                # Debug: vérifier l'état de la queue
                logger.debug(f"Slots disponibles: {available_slots}, Tâches en attente: {len(self.queue)}")

                for _ in range(tasks_to_start):
                    task = self.queue.popleft()
                    task_id = task.id

                    # Mettre à jour les positions
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
                    logger.info(f"Tâche démarrée: {task_id}")

            # Attendre soit une notification soit un timeout
            try:
                async with self.queue_notifier:
                    if not self.queue:
                        # Attendre indéfiniment si la queue est vide
                        await self.queue_notifier.wait()
                    else:
                        # Timeout court si des tâches sont en attente
                        await asyncio.wait_for(self.queue_notifier.wait(), timeout=0.5)
            except asyncio.TimeoutError:
                # Timeout normal, vérifier à nouveau la queue
                pass
            except Exception as e:
                logger.error(f"Erreur dans l'attente de queue: {e}")

        logger.info("Arrêt du processeur de file d'attente")

    async def _execute_task(self, task: EncodingTask) -> None:
        task_id = task.id
        try:
            # DEBUG: Vérifier si nous sommes dans le bon thread
            logger.debug(f"Début d'exécution de la tâche {task_id} dans {asyncio.current_task().get_name()}")

            # Exécution de la tâche d'encodage
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

            # Envoi de la vidéo encodée à l'utilisateur
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
            # Nettoyage des fichiers
            await self._cleanup_files(task)

            async with self.lock:
                if task_id in self.running_tasks:
                    del self.running_tasks[task_id]
                if task_id in self.active_tasks:
                    del self.active_tasks[task_id]

                # Notifier pour déclencher le traitement suivant
                async with self.queue_notifier:
                    self.queue_notifier.notify_all()

# Modifier l'initialisation globale
queue_system = EncodingQueue(max_concurrent=1)  # Commencer avec 1 seul slot concurrent

async def initialize_queue_system():
    """Initialise et démarre le système de file d'attente"""
    # Enregistrer un gestionnaire pour les signaux d'arrêt
    loop = asyncio.get_running_loop()
    for signame in {'SIGINT', 'SIGTERM'}:
        loop.add_signal_handler(
            getattr(signal, signame),
            lambda: asyncio.create_task(shutdown_queue_system())
        )
    await queue_system.start()
    logger.info("Système de file d'attente d'encodage initialisé")

async def shutdown_queue_system():
    """Arrête le système de file d'attente"""
    logger.info("Arrêt demandé, début du processus d'arrêt...")
    await queue_system.stop(cancel_active=True)
    logger.info("Système de file d'attente d'encodage arrêté")