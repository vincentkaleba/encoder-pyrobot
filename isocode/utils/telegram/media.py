from pyrogram import Client
from pyrogram.types import InputMedia, Message, InlineKeyboardMarkup
from pyrogram.enums import ParseMode
from pyrogram.errors import (
    FloodWait,
    BadRequest,
    RPCError,
    FileIdInvalid,
    FilePartMissing,
    MessageNotModified,
)
from pyrogram.types import (
    InputMediaPhoto,
    InputMediaVideo,
    InputMediaDocument,
    InputMediaAnimation,
)
from isocode import logger, settings
from isocode.utils.isoutils.progress import create_progress_bar, humanbytes
from isocode.utils.telegram.message import send_msg, send_log, send_progress
from typing import Optional, Union, List, Callable, BinaryIO
import asyncio
import os
import time
import tempfile
from isocode.utils.isoutils.ffmpeg import (
    encode_video,
    get_ffmpeg_video_width_and_height,
    get_thumbnail,
    get_duration,
    get_video_width_and_height,
)
from isocode.utils.isoutils.dbutils import get_or_create_user

MAX_DIRECT_SIZE = 2 * 1024 * 1024 * 1024  # 2 Go

MEDIA_TYPES = {
    "photo": InputMediaPhoto,
    "video": InputMediaVideo,
    "document": InputMediaDocument,
    "animation": InputMediaAnimation,
}


async def download_media(
    client: Client,
    message: Message,
    file_path: str,
    progress_callback: Optional[Callable] = None,
    progress_args: tuple = (),
    userbot: Optional[Client] = None,
) -> Optional[str]:
    """Télécharge un média avec gestion de la progression et des erreurs"""
    try:
        media = message.photo or message.video or message.document or message.audio
        if not media:
            logger.warning("Aucun média détecté dans le message")
            return None

        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        file_size = media.file_size

        # Choix du client pour le téléchargement
        download_client = client
        if file_size and file_size > MAX_DIRECT_SIZE and userbot:
            download_client = userbot
            logger.info(
                f"Utilisation de userbot pour télécharger un fichier de {humanbytes(file_size)}"
            )

        last_update = [0]

        async def _progress(current: int, total: int):
            now = time.time()
            if now - last_update[0] > 1 or current == total:
                last_update[0] = now
                if progress_callback:
                    await progress_callback(current, total, *progress_args)

        await download_client.download_media(
            message, file_name=file_path, progress=_progress
        )

        if not os.path.isfile(file_path):
            logger.error(f"Fichier manquant après téléchargement : {file_path}")
            return None

        logger.info(f"Média téléchargé avec succès : {file_path}")
        return file_path

    except (FileIdInvalid, FilePartMissing) as e:
        logger.error(f"Erreur de téléchargement: {type(e).__name__} - {e}")
    except FloodWait as e:
        logger.warning(f"FloodWait: Pause de {e.value}s")
        await asyncio.sleep(e.value)
        return await download_media(
            client, message, file_path, progress_callback, progress_args, userbot
        )
    except (BadRequest, RPCError) as e:
        logger.error(f"Erreur réseau: {type(e).__name__} - {e}")
    except Exception as e:
        logger.error(f"Erreur inattendue (download_media): {e}")
    return None


async def _upload_media_single(
    client: Client,
    chat_id: int,
    file_path: str,
    caption: str = "",
    thumb: Optional[str] = None,
    progress_callback: Optional[Callable] = None,
    progress_args: tuple = (),
    parse_mode: ParseMode = ParseMode.HTML,
    reply_to: Optional[int] = None,
    disable_notification: bool = False,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    delete_after_send: bool = True,
) -> Optional[Message]:
    """Fonction interne pour l'upload simple avec gestion des métadonnées vidéo"""
    if not os.path.exists(file_path):
        logger.error(f"Fichier introuvable: {file_path}")
        return None

    temp_thumb = None
    try:
        file_name = os.path.basename(file_path)
        file_ext = os.path.splitext(file_name)[1].lower()

        # Détermination du type de média
        if file_ext in (".jpg", ".jpeg", ".png"):
            media_type = "photo"
            send_func = client.send_photo
        elif file_ext in (".mp4", ".mov", ".mkv", ".avi", ".flv", ".webm"):
            media_type = "video"
            send_func = client.send_video
        elif file_ext in (".mp3", ".wav", ".flac", ".ogg", ".m4a"):
            media_type = "audio"
            send_func = client.send_audio
        else:
            media_type = "document"
            send_func = client.send_document

        last_update = [0]

        async def _progress(current: int, total: int):
            now = time.time()
            if now - last_update[0] > 1 or current == total:
                last_update[0] = now
                if progress_callback:
                    await progress_callback(current, total, *progress_args)

        # Récupération des métadonnées vidéo
        duration = None
        width = None
        height = None
        if media_type == "video":
            try:
                duration = await get_duration(file_path)
                width, height = await get_video_width_and_height(file_path)
                if width == 0 or height == 0:
                    width, height = await get_ffmpeg_video_width_and_height(file_path)
                
            except Exception as e:
                logger.error(f"Erreur métadonnées vidéo: {e}")

            if not thumb:
                try:
                    temp_dir = tempfile.gettempdir()
                    temp_thumb = await get_thumbnail(file_path, temp_dir, 5)
                    if temp_thumb and os.path.exists(temp_thumb):
                        thumb = temp_thumb
                        logger.info(f"Miniature générée automatiquement: {thumb}")
                    else:
                        logger.warning("Échec de génération de la miniature")
                except Exception as e:
                    logger.error(f"Erreur génération thumbnail: {e}")

        # Construction des paramètres
        kwargs = {
            "chat_id": chat_id,
            media_type: file_path,
            "caption": caption,
            "parse_mode": parse_mode,
            "progress": _progress,
            "reply_to_message_id": reply_to,
            "disable_notification": disable_notification,
            "file_name": file_name,
            "reply_markup": reply_markup,
        }

        # Paramètres spécifiques au type de média
        if media_type == "video":
            if thumb:
                kwargs["thumb"] = thumb
            if duration:
                kwargs["duration"] = int(duration)
            if width and height:
                kwargs["width"] = int(width)
                kwargs["height"] = int(height)

        if media_type == "document":
            kwargs["force_document"] = True

        # Envoi du média
        message = await send_func(**kwargs)

        # Suppression du fichier après envoi si demandé
        if delete_after_send and os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.info(f"Fichier supprimé après envoi: {file_path}")
            except Exception as e:
                logger.error(f"Erreur suppression fichier: {e}")

        return message

    except FloodWait as e:
        logger.warning(f"FloodWait: Pause de {e.value}s")
        await asyncio.sleep(e.value)
        return await _upload_media_single(
            client,
            chat_id,
            file_path,
            caption,
            thumb,
            progress_callback,
            progress_args,
            parse_mode,
            reply_to,
            disable_notification,
            reply_markup,
            delete_after_send,
        )
    except (BadRequest, RPCError) as e:
        logger.error(f"Erreur d'envoi: {type(e).__name__} - {e}")
    except Exception as e:
        logger.error(f"Erreur inattendue (upload_media): {e}")
    finally:
        # Nettoyage de la miniature temporaire
        if temp_thumb and os.path.exists(temp_thumb):
            try:
                os.remove(temp_thumb)
                logger.info(f"Miniature temporaire supprimée: {temp_thumb}")
            except Exception as e:
                logger.error(f"Erreur suppression thumbnail: {e}")
    return None


async def upload_media(
    client: Client,
    chat_id: int,
    file_path: str,
    caption: str = "",
    thumb: Optional[str] = None,
    progress_callback: Optional[Callable] = None,
    progress_args: tuple = (),
    parse_mode: ParseMode = ParseMode.HTML,
    reply_to: Optional[int] = None,
    disable_notification: bool = False,
    userbot: Optional[Client] = None,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    delete_after_send: bool = True,
) -> Optional[Message]:
    """Envoie un fichier média avec gestion des fichiers >2Go via dump_chat"""
    if not os.path.exists(file_path):
        logger.error(f"Fichier introuvable: {file_path}")
        return None

    file_size = os.path.getsize(file_path)

    # Utilisation de userbot pour les gros fichiers
    if file_size > MAX_DIRECT_SIZE and userbot:
        logger.info(
            f"Utilisation de userbot pour upload fichier de {humanbytes(file_size)}"
        )

        # Upload vers le chat de dump
        dump_msg = await _upload_media_single(
            client=userbot,
            chat_id=settings.DUMP_CHAT,
            file_path=file_path,
            caption=caption,
            thumb=thumb,
            progress_callback=progress_callback,
            progress_args=progress_args,
            parse_mode=parse_mode,
            reply_to=None,
            disable_notification=True,
            reply_markup=None,
            delete_after_send=delete_after_send,
        )

        if not dump_msg:
            logger.error("Échec de l'upload vers dump_chat")
            return None

        try:
            # Copie vers le chat destination
            return await client.copy_message(
                chat_id=chat_id,
                from_chat_id=settings.DUMP_CHAT,
                message_id=dump_msg.id,
                caption=caption,
                parse_mode=parse_mode,
                reply_to_message_id=reply_to,
                disable_notification=disable_notification,
                reply_markup=reply_markup,
            )
        except FloodWait as e:
            logger.warning(f"FloodWait lors de la copie: Pause de {e.value}s")
            await asyncio.sleep(e.value)
            return await upload_media(
                client,
                chat_id,
                file_path,
                caption,
                thumb,
                progress_callback,
                progress_args,
                parse_mode,
                reply_to,
                disable_notification,
                userbot,
                reply_markup,
                delete_after_send,
            )
        except (BadRequest, RPCError) as e:
            logger.error(f"Erreur lors de la copie: {type(e).__name__} - {e}")
            return None

    # Upload direct pour les petits fichiers
    return await _upload_media_single(
        client,
        chat_id,
        file_path,
        caption,
        thumb,
        progress_callback,
        progress_args,
        parse_mode,
        reply_to,
        disable_notification,
        reply_markup,
        delete_after_send,
    )


async def send_media(
    client: Client,
    chat_id: int,
    media_type: str,
    media: Union[str, BinaryIO],
    caption: str = "",
    thumb: Optional[str] = None,
    parse_mode: ParseMode = ParseMode.HTML,
    reply_to: Optional[int] = None,
    disable_notification: bool = False,
    progress_msg: Optional[Message] = None,
    force_document: bool = False,
    userbot: Optional[Client] = None,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    delete_after_send: bool = True,
) -> Optional[Message]:
    """Envoie un média avec barre de progression intégrée"""

    async def update_progress(current: int, total: int):
        nonlocal progress_msg
        percent = (current / total) * 100
        text = (
            f"**Téléversement en cours...**\n"
            f"`{os.path.basename(media) if isinstance(media, str) else 'fichier'}`\n"
            f"{create_progress_bar(percent)}\n"
            f"**{humanbytes(current)} / {humanbytes(total)}** ({percent:.1f}%)"
        )
        try:
            if progress_msg:
                await progress_msg.edit_text(text)
            else:
                progress_msg = await send_progress(
                    client, chat_id, text=text, percent=percent
                )
        except Exception:
            pass

    # Gestion du type de document forcé
    if force_document:
        media_type = "document"

    # Envoi de fichier local
    if isinstance(media, str) and os.path.exists(media):
        return await upload_media(
            client=client,
            chat_id=chat_id,
            file_path=media,
            caption=caption,
            thumb=thumb,
            progress_callback=update_progress,
            parse_mode=parse_mode,
            reply_to=reply_to,
            disable_notification=disable_notification,
            userbot=userbot,
            reply_markup=reply_markup,
            delete_after_send=delete_after_send,
        )

    # Envoi de données binaires
    send_func = {
        "photo": client.send_photo,
        "video": client.send_video,
        "audio": client.send_audio,
        "document": client.send_document,
    }.get(media_type)

    if not send_func:
        logger.error(f"Type de média invalide: {media_type}")
        return None

    try:
        kwargs = {
            "chat_id": chat_id,
            media_type: media,
            "caption": caption,
            "parse_mode": parse_mode,
            "progress": update_progress,
            "reply_to_message_id": reply_to,
            "disable_notification": disable_notification,
            "reply_markup": reply_markup,
        }

        if media_type in ("video", "document") and thumb:
            kwargs["thumb"] = thumb

        return await send_func(**kwargs)
    except FloodWait as e:
        logger.warning(f"FloodWait: Pause de {e.value}s")
        await asyncio.sleep(e.value)
        return await send_media(
            client,
            chat_id,
            media_type,
            media,
            caption,
            thumb,
            parse_mode,
            reply_to,
            disable_notification,
            progress_msg,
            force_document,
            userbot,
            reply_markup,
            delete_after_send,
        )
    except (BadRequest, RPCError) as e:
        logger.error(f"Erreur d'envoi: {type(e).__name__} - {e}")
    finally:
        if progress_msg:
            await progress_msg.delete()
    return None


async def edit_media_caption(
    client: Client,
    chat_id: int,
    message_id: int,
    caption: str,
    parse_mode: ParseMode = ParseMode.HTML,
    markup: Optional[InlineKeyboardMarkup] = None,
) -> bool:
    """Modifie la légende d'un média existant"""
    try:
        await client.edit_message_caption(
            chat_id=chat_id,
            message_id=message_id,
            caption=caption,
            parse_mode=parse_mode,
            reply_markup=markup,
        )
        return True
    except MessageNotModified:
        logger.debug(f"Légende déjà à jour {message_id}@{chat_id}")
    except FloodWait as e:
        logger.warning(f"FloodWait: Pause de {e.value}s")
        await asyncio.sleep(e.value)
        return await edit_media_caption(
            client,
            chat_id,
            message_id,
            caption,
            parse_mode,
            markup,
        )
    except (BadRequest, RPCError) as e:
        logger.error(f"Erreur modification légende: {type(e).__name__} - {e}")
    return False


async def send_media_group(
    client: Client,
    chat_id: int,
    media_list: List[InputMedia],
    disable_notification: bool = False,
    reply_to: Optional[int] = None,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> Optional[List[Message]]:
    """Envoie un groupe de médias (album)"""
    try:
        return await client.send_media_group(
            chat_id=chat_id,
            media=media_list,
            disable_notification=disable_notification,
            reply_to_message_id=reply_to,
            reply_markup=reply_markup,
        )
    except FloodWait as e:
        logger.warning(f"FloodWait: Pause de {e.value}s")
        await asyncio.sleep(e.value)
        return await send_media_group(
            client,
            chat_id,
            media_list,
            disable_notification,
            reply_to,
            reply_markup,
        )
    except (BadRequest, RPCError) as e:
        logger.error(f"Erreur envoi groupe média: {type(e).__name__} - {e}")
    return None


async def edit_media(
    client: Client,
    chat_id: int,
    message_id: int,
    media: Union[str, BinaryIO],
    media_type: str = "photo",
    caption: str = "",
    parse_mode: ParseMode = ParseMode.HTML,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> bool:
    """Modifie un média dans un message existant"""
    media_class = MEDIA_TYPES.get(media_type.lower())
    if not media_class:
        logger.error(f"Type de média non supporté: {media_type}")
        return False

    try:
        input_media = media_class(media, caption=caption, parse_mode=parse_mode)
        await client.edit_message_media(
            chat_id=chat_id,
            message_id=message_id,
            media=input_media,
            reply_markup=reply_markup,
        )
        return True
    except FloodWait as e:
        logger.warning(f"FloodWait: Pause de {e.value}s")
        await asyncio.sleep(e.value)
        return await edit_media(
            client,
            chat_id,
            message_id,
            media,
            media_type,
            caption,
            parse_mode,
            reply_markup,
        )
    except (BadRequest, RPCError) as e:
        logger.error(f"Erreur modification média: {type(e).__name__} - {e}")
        return False
