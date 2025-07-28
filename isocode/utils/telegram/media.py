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
from isocode import logger, settings
from isocode.utils.isoutils.progress import create_progress_bar, humanbytes
from isocode.utils.telegram.message import send_msg, send_log, send_progress
from typing import Optional, Union, List, Callable, BinaryIO
import asyncio
import os
import time

MAX_DIRECT_SIZE = 2 * 1024 * 1024 * 1024  # 2 Go


async def download_media(
    client: Client,
    message: Message,
    file_path: str,
    progress_callback: Optional[Callable] = None,
    progress_args: tuple = (),
    userbot: Optional[Client] = None,
) -> Optional[str]:
    """
    Télécharge un média avec gestion de la progression et des erreurs
    Utilise userbot pour les fichiers > 2Go si disponible
    """
    try:
        media = message.photo or message.video or message.document or message.audio
        if not media:
            logger.warning("Aucun média détecté dans le message")
            return None

        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        file_size = media.file_size
        actual_client = client
        if file_size and file_size > MAX_DIRECT_SIZE and userbot:
            actual_client = userbot
            logger.info(
                f"Utilisation de userbot pour télécharger un fichier de {file_size} octets"
            )

        last_update = [0]

        async def _progress(current: int, total: int):
            nonlocal last_update
            now = time.time()
            if now - last_update[0] > 1 or current == total:
                if progress_callback:
                    await progress_callback(current, total, *progress_args)
                last_update[0] = now

        await actual_client.download_media(
            message, file_name=file_path, progress=_progress
        )
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
    show_caption_above_media: bool = False,
) -> Optional[Message]:
    """Fonction interne pour l'upload simple sans gestion du dump"""
    if not os.path.exists(file_path):
        logger.error(f"Fichier introuvable: {file_path}")
        return None

    try:
        file_name = os.path.basename(file_path)

        if file_name.lower().endswith((".jpg", ".jpeg", ".png")):
            media_type = "photo"
            send_func = client.send_photo
        elif file_name.lower().endswith((".mp4", ".mov", ".mkv")):
            media_type = "video"
            send_func = client.send_video
        elif file_name.lower().endswith((".mp3", ".wav", ".flac")):
            media_type = "audio"
            send_func = client.send_audio
        else:
            media_type = "document"
            send_func = client.send_document

        last_update = [0]

        async def _progress(current: int, total: int):
            nonlocal last_update
            now = time.time()
            if now - last_update[0] > 1 or current == total:
                if progress_callback:
                    await progress_callback(current, total, *progress_args)
                last_update[0] = now

        kwargs = {
            "chat_id": chat_id,
            "caption": caption,
            "parse_mode": parse_mode,
            "progress": _progress,
            "reply_to_message_id": reply_to,
            "disable_notification": disable_notification,
            "file_name": file_name,
            "show_caption_above_media": show_caption_above_media,
        }

        if media_type == "video":
            kwargs["thumb"] = thumb
        elif media_type == "document":
            kwargs["thumb"] = thumb
            kwargs["force_document"] = True

        return await send_func(file_path, **kwargs)

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
            show_caption_above_media,
        )
    except (BadRequest, RPCError) as e:
        logger.error(f"Erreur d'envoi: {type(e).__name__} - {e}")
    except Exception as e:
        logger.error(f"Erreur inattendue (upload_media): {e}")
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
    show_caption_above_media: bool = False,
    userbot: Optional[Client] = None,
) -> Optional[Message]:
    """
    Envoie un fichier média avec gestion des fichiers >2Go via dump_chat
    Utilise userbot pour l'upload et client pour la copie si nécessaire
    """
    if not os.path.exists(file_path):
        logger.error(f"Fichier introuvable: {file_path}")
        return None

    file_size = os.path.getsize(file_path)

    if file_size > MAX_DIRECT_SIZE and userbot:
        logger.info(f"Utilisation de userbot pour upload fichier de {file_size} octets")

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
            show_caption_above_media=show_caption_above_media,
        )

        if not dump_msg:
            logger.error("Échec de l'upload vers dump_chat")
            return None

        try:
            copied_msg = await client.copy_message(
                chat_id=chat_id,
                from_chat_id=settings.DUMP_CHAT,
                message_id=dump_msg.id,
                caption=caption,
                parse_mode=parse_mode,
                reply_to_message_id=reply_to,
                disable_notification=disable_notification,
                show_caption_above_media=show_caption_above_media,
            )
            return copied_msg
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
                show_caption_above_media,
                userbot,
            )
        except (BadRequest, RPCError) as e:
            logger.error(f"Erreur lors de la copie: {type(e).__name__} - {e}")
            return None

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
        show_caption_above_media,
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
    show_caption_above_media: bool = False,
    userbot: Optional[Client] = None,
) -> Optional[Message]:
    """
    Envoie un média avec barre de progression intégrée et gestion des fichiers volumineux
    """

    async def update_progress(current: int, total: int):
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
                nonlocal progress_msg
                progress_msg = await send_progress(
                    client, chat_id, text=text, percent=percent
                )
        except Exception:
            pass

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
            show_caption_above_media=show_caption_above_media,
            userbot=userbot,
        )

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
            "show_caption_above_media": show_caption_above_media,
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
            show_caption_above_media,
            userbot,
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
    show_caption_above_media: Optional[bool] = None,
) -> bool:
    """
    Modifie la légende d'un média existant
    """
    try:
        kwargs = {
            "chat_id": chat_id,
            "message_id": message_id,
            "caption": caption,
            "parse_mode": parse_mode,
            "reply_markup": markup,
        }

        if show_caption_above_media is not None:
            kwargs["show_caption_above_media"] = show_caption_above_media

        await client.edit_message_caption(**kwargs)
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
            show_caption_above_media,
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
    show_caption_above_media: Optional[bool] = None,
) -> Optional[List[Message]]:
    """
    Envoie un groupe de médias (album) avec gestion de la position des légendes
    """
    try:
        if show_caption_above_media is not None:
            for media in media_list:
                media.show_caption_above_media = show_caption_above_media

        return await client.send_media_group(
            chat_id=chat_id,
            media=media_list,
            disable_notification=disable_notification,
            reply_to_message_id=reply_to,
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
            show_caption_above_media,
        )
    except (BadRequest, RPCError) as e:
        logger.error(f"Erreur envoi groupe média: {type(e).__name__} - {e}")
    return None
