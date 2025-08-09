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
        progress_bar = '▬' * filled_len + '─' * (bar_len - filled_len)

        filename_display = self.filename if len(self.filename) <= 20 else f"{self.filename[:10]}...{self.filename[-10:]}"

        new_message = (
            f"⬇️ **Téléchargement en cours**\n\n"
            f"📁 `{filename_display}`\n\n"
            f"Progess |{progress_bar} |**{percent:.1f}%**\n\n"
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
    user = await get_or_create_user(user_id)

    video = message.video or message.document
    if not video:
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

    timestamp = int(time.time())
    unique_filename = f"{user_id}_{timestamp}_{filename}"
    full_path = os.path.join(user_dir, unique_filename)

    progress_tracker = DownloadProgress(
        client=client,
        chat_id=message.chat.id,
        msg_id=msg.id,
        filename=filename
    )

    file_path = await download_media(
        client=client,
        message=message,
        file_path=full_path,
        progress_callback=progress_tracker.update,
        userbot=userbot
    )

    if not file_path or not os.path.isfile(file_path):
        logger.error(f"Fichier introuvable après téléchargement : {file_path}")
        try:
            await edit_msg(
                client,
                message.chat.id,
                msg.id,
                stylize_value("❌ Échec du téléchargement : le fichier est introuvable."),
            )
        except Exception:
            pass

        return None

    try:
        parts = os.path.basename(file_path).split('_')

        if len(parts) >= 3:
            original_filename = '_'.join(parts[2:])
            new_path = os.path.join(os.path.dirname(file_path), original_filename)

            os.rename(file_path, new_path)
            file_path = new_path
            logger.info(f"Fichier renommé : {original_filename}")
        else:
            logger.warning("Impossible de renommer le fichier : format de nom invalide")
    except Exception as e:
        logger.error(f"Erreur lors du renommage du fichier : {e}")

    file_size = humanbytes(os.path.getsize(file_path))
    elapsed = time.time() - progress_tracker.start_time
    await edit_msg(
        client,
        message.chat.id,
        msg.id,
        stylize_value(
            f"✅ **Téléchargement réussi!**\n\n"
            f"📁 `{os.path.basename(file_path)}`\n"  # Utiliser le nouveau nom
            f"📦 Taille: {file_size}\n"
            f"⏱ Durée: {math.floor(elapsed)}s\n\n"
            f"⏳ Ajout à la file d'encodage..."
        ),
        parse=ParseMode.MARKDOWN
    )

    task_data = {
        'filepath': file_path,
        'message': message,
        'msg': msg,
        'user_settings': await get_user_settings(user_id),
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
            f"📁 `{os.path.basename(file_path)}`\n"  
            f"📦 Taille: {file_size}\n"
            f"🎬 Position: #{pos}\n"
            f"🔍 Suivre: /status_{task_id}"
        ),
        parse=ParseMode.MARKDOWN
    )

    return task_id