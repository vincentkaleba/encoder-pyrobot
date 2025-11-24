import os
import time
import math
from pyrogram.enums import ParseMode
from pyrogram.types import Message
from isocode.utils.isoutils.dbutils import get_or_create_user
from isocode.utils.isoutils.progress import stylize_value, humanbytes
from isocode.utils.telegram.media import download_media
from isocode.utils.telegram.message import send_msg, edit_msg
from isocode.utils.isoutils.queue import queue_system
from isocode.utils.isoutils.ffmpeg import get_user_settings
from isocode import logger, download_dir

ALOED_EXTENSIONS = ["mp4", "mkv", "avi", "mov", "flv", "webm", "mpeg", "mpg"]

class DownloadProgress:
    """Classe pour suivre et afficher la progression du téléchargement"""
    def __init__(self, client, chat_id, msg_id, filename):
        self.client = client
        self.chat_id = chat_id
        self.msg_id = msg_id
        self.filename = filename
        self.start_time = time.time()
        self.last_update = self.start_time
        self.last_downloaded = 0
        self.last_message = ""
        self.last_percent = -1

    async def update(self, current: int, total: int):
        """Mettre à jour l'affichage de progression avec cooldown"""
        now = time.time()
        elapsed = now - self.start_time

        percent = (current / total) * 100 if total > 0 else 0

        if now - self.last_update < 8 and abs(percent - self.last_percent) < 5:
            return

        if now > self.last_update:
            speed = (current - self.last_downloaded) / (now - self.last_update) / 1024 / 1024
        else:
            speed = 0

        if current > 0 and elapsed > 0:
            remaining = (total - current) / (current / elapsed)
            remaining_str = f"{math.floor(remaining / 60):02d}:{math.floor(remaining % 60):02d}"
        else:
            remaining_str = "Calcul..."

        speed_str = f"{speed:.1f} MB/s" if speed > 0 else "Calcul..."
        size_str = f"{humanbytes(current)} / {humanbytes(total)}"

        bar_len = 10
        filled_len = int(bar_len * percent / 100)
        progress_bar = '━' * filled_len + '─' * (bar_len - filled_len)

        filename_display = self.filename if len(self.filename) <= 20 else f"{self.filename[:10]}...{self.filename[-10:]}"

        new_message = (
            f"⬇️ **Téléchargement en cours**\n\n"
            f"📁 `{filename_display}`\n\n"
            f"Progess{progress_bar}**{percent:.1f}%**\n\n"
            f"⚡ **Vitesse:** {speed_str}\n"
            f"📦 **Taille:** {size_str}\n"
            f"⏱ **Temps écoulé:** {math.floor(elapsed):02d}s\n"
            f"⏳ **Temps restant:** {remaining_str}"
        )

        if new_message != self.last_message:
            try:
                await edit_msg(
                    self.client,
                    self.chat_id,
                    self.msg_id,
                    stylize_value(new_message),
                    parse=ParseMode.MARKDOWN
                )
                self.last_message = new_message
            except Exception as e:
                logger.warning(f"Erreur mise à jour progression: {e}")

        self.last_update = now
        self.last_downloaded = current
        self.last_percent = percent

async def encoder_flow(message: Message, msg: Message, userbot, client) -> str:
    user_id = message.from_user.id
    user = await get_or_create_user(user_id)  # Fetch user object

    video = message.video or message.document

    # If there is no direct media, check for a URL in the message text/caption
    if not video:
        import re

        text_src = getattr(message, 'text', None) or getattr(message, 'caption', '') or ''
        url_match = re.search(r"(https?://\S+)", text_src)
        if url_match:
            source_url = url_match.group(1).rstrip(')')
            # derive a filename from the URL path
            from urllib.parse import urlparse, unquote
            parsed = urlparse(source_url)
            path_name = unquote(parsed.path or '')
            base_name = os.path.basename(path_name) or f"source_{int(time.time())}.mp4"

            user_dir = os.path.join(download_dir, str(user_id))
            os.makedirs(user_dir, exist_ok=True)
            timestamp = int(time.time())
            task_dir = os.path.join(user_dir, f"task_{timestamp}")
            os.makedirs(task_dir, exist_ok=True)

            unique_filename = f"{user_id}_{timestamp}_{base_name}"

            task_data = {
                'task_dir': task_dir,
                'unique_filename': unique_filename,
                'filename': base_name,
                'source_url': source_url,
                'message': message,
                'msg': msg,
                'user_settings': await get_user_settings(user),
                'user': user,
                'client': client,
                'userbot': userbot
            }

            task_id = await queue_system.add_task(task_data)
            pos = await queue_system.get_task_position(task_id)

            await edit_msg(
                client,
                message.chat.id,
                msg.id,
                stylize_value(
                    f"📥 **Source URL ajoutée à la file d'attente**\n\n"
                    f"🔗 `{source_url}`\n"
                    f"🎬 Position: #{pos}\n"
                    f"🔍 Suivre: /status_{task_id}"
                ),
                parse=ParseMode.MARKDOWN
            )

            return task_id

        return await send_msg(
            client,
            message.chat.id,
            "❌ Aucun fichier vidéo trouvé dans le message.",
            reply_to=message.id
        )

    filename = video.file_name or f"video_{int(time.time())}.mp4"
    file_ext = filename.split('.')[-1].lower()

    if file_ext not in ALOED_EXTENSIONS:
        return await send_msg(
            client,
            message.chat.id,
            stylize_value(
                f"❌ Format de fichier non supporté (.{file_ext}).\n"
                f"Extensions valides: {', '.join(ALOED_EXTENSIONS)}"
            ),
            reply_to=message.id
        )

    user_dir = os.path.join(download_dir, str(user_id))
    logger.info(f"Création du répertoire utilisateur : {user_dir}")
    os.makedirs(user_dir, exist_ok=True)

    # Utiliser un répertoire temporaire par tâche pour isoler les fichiers
    # et éviter de supprimer accidentellement le dossier racine de l'utilisateur.
    timestamp = int(time.time())
    task_dir = os.path.join(user_dir, f"task_{timestamp}")
    os.makedirs(task_dir, exist_ok=True)

    # build a unique filename to avoid collisions. The actual download
    # will be performed in the worker to centralize concurrency control.
    unique_filename = f"{user_id}_{timestamp}_{filename}"

    # We enqueue only metadata here. The worker (_execute_task) will
    # perform the download into `task_dir/unique_filename` and then
    # continue to encoding. This centralizes downloads + encodes under
    # queue concurrency limits.
    task_data = {
        'task_dir': task_dir,
        'unique_filename': unique_filename,
        'filename': filename,
        'message': message,
        'msg': msg,
        'user_settings': await get_user_settings(user),  # Use the already fetched User object
        'user': user,
        'client': client,
        'userbot': userbot
    }

    task_id = await queue_system.add_task(task_data)
    pos = await queue_system.get_task_position(task_id)

    await edit_msg(
        client,
        message.chat.id,
        msg.id,
        stylize_value(
            f"📥 **Vidéo ajoutée à la file d'attente**\n\n"
            f"📁 `{filename}`\n"
            f"🎬 Position: #{pos}\n"
            f"🔍 Suivre: /status_{task_id}"
        ),
        parse=ParseMode.MARKDOWN
    )

    return task_id