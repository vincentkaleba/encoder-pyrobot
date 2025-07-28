from datetime import time, timedelta
from isocode import logger, settings
from isocode.utils.isoutils.progress import create_progress_bar
from pyrogram import Client
from pyrogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup, Message
from pyrogram.enums import ParseMode
from pyrogram.errors import (
    FloodWait,
    BadRequest,
    MessageNotModified,
    MessageIdInvalid
)
from pyrogram.errors import MessageDeleteForbidden, RPCError

from typing import Union, Optional
import asyncio
import traceback

async def send_msg(
    client: Client,
    cid: int,  # chat_id
    text: str,
    markup: Union[InlineKeyboardMarkup, ReplyKeyboardMarkup] = None,
    notify: bool = False,  # disable_notification
    reply_to: int = None,  # reply_to_message_id
    parse: ParseMode = ParseMode.HTML,
    preview: bool = False,  # disable_web_page_preview
):
    """Envoyer un message avec gestion FloodWait et erreurs"""
    try:
        return await client.send_message(
            chat_id=cid,
            text=text,
            reply_markup=markup,
            disable_notification=notify,
            reply_to_message_id=reply_to,
            parse_mode=parse,
            disable_web_page_preview=preview,
        )
    except FloodWait as e:
        logger.warning(f"FloodWait: Pause de {e.value}s")
        await asyncio.sleep(e.value)
        return await send_msg(client, cid, text, markup, notify, reply_to, parse, preview)
    except (BadRequest, RPCError) as e:
        logger.error(f"Erreur d'envoi à {cid}: {type(e).__name__} - {e}")
    except Exception as e:
        logger.error(f"Erreur inattendue (send_msg): {e}\n{traceback.format_exc()}")
    return None

async def edit_msg(
    client: Client,
    cid: int,
    mid: int,  # message_id
    text: str,
    markup: Union[InlineKeyboardMarkup, None] = None,
    parse: ParseMode = ParseMode.HTML,
    preview: bool = False,
):
    """Éditer un message avec vérification préalable des modifications"""
    try:
        # Vérifier si modification nécessaire
        current: Message = await client.get_messages(cid, mid)
        if (current.text or current.caption) == text and current.reply_markup == markup:
            return None

        return await client.edit_message_text(
            chat_id=cid,
            message_id=mid,
            text=text,
            reply_markup=markup,
            parse_mode=parse,
            disable_web_page_preview=preview,
        )
    except MessageNotModified:
        logger.debug(f"Message {mid} déjà à jour")
    except FloodWait as e:
        logger.warning(f"FloodWait: Pause de {e.value}s")
        await asyncio.sleep(e.value)
        return await edit_msg(client, cid, mid, text, markup, parse, preview)
    except (BadRequest, RPCError) as e:
        logger.error(f"Erreur édition {mid}@{cid}: {type(e).__name__} - {e}")
    except Exception as e:
        logger.error(f"Erreur inattendue (edit_msg): {e}\n{traceback.format_exc()}")
    return None

async def del_msg(
    client: Client,
    cid: int,
    mid: int,
):
    """Supprimer un message avec gestion d'erreurs spécifiques"""
    try:
        return await client.delete_messages(cid, mid)
    except MessageDeleteForbidden:
        logger.debug(f"Message {mid} déjà supprimé")
    except MessageIdInvalid:
        logger.warning(f"ID message {mid} invalide")
    except FloodWait as e:
        logger.warning(f"FloodWait: Pause de {e.value}s")
        await asyncio.sleep(e.value)
        return await del_msg(client, cid, mid)
    except (BadRequest, RPCError) as e:
        logger.error(f"Erreur suppression {mid}@{cid}: {type(e).__name__} - {e}")
    except Exception as e:
        logger.error(f"Erreur inattendue (del_msg): {e}\n{traceback.format_exc()}")
    return None

async def reply_msg(
    client: Client,
    msg: Message,
    text: str,
    markup: Union[InlineKeyboardMarkup, ReplyKeyboardMarkup] = None,
    notify: bool = False,
    parse: ParseMode = ParseMode.HTML,
    preview: bool = False,
):
    """Répondre à un message existant"""
    return await send_msg(
        client,
        msg.chat.id,
        text,
        markup,
        notify,
        msg.id,
        parse,
        preview
    )

async def edit_markup(
    client: Client,
    cid: int,
    mid: int,
    markup: InlineKeyboardMarkup
):
    """Éditer uniquement le markup d'un message"""
    try:
        return await client.edit_message_reply_markup(cid, mid, reply_markup=markup)
    except MessageNotModified:
        logger.debug(f"Markup déjà à jour {mid}@{cid}")
    except FloodWait as e:
        logger.warning(f"FloodWait: Pause de {e.value}s")
        await asyncio.sleep(e.value)
        return await edit_markup(client, cid, mid, markup)
    except (BadRequest, RPCError) as e:
        logger.error(f"Erreur markup {mid}@{cid}: {type(e).__name__} - {e}")
    except Exception as e:
        logger.error(f"Erreur inattendue (edit_markup): {e}\n{traceback.format_exc()}")
    return None

async def pin_msg(
    client: Client,
    cid: int,
    mid: int,
    notify: bool = True,
    both_sides: bool = False
):
    """Épingler un message"""
    try:
        return await client.pin_chat_message(
            cid,
            mid,
            disable_notification=notify,
            both_sides=both_sides
        )
    except FloodWait as e:
        logger.warning(f"FloodWait: Pause de {e.value}s")
        await asyncio.sleep(e.value)
        return await pin_msg(client, cid, mid, notify, both_sides)
    except (BadRequest, RPCError) as e:
        logger.error(f"Erreur épinglage {mid}@{cid}: {type(e).__name__} - {e}")
    except Exception as e:
        logger.error(f"Erreur inattendue (pin_msg): {e}\n{traceback.format_exc()}")
    return None

async def unpin_msg(
    client: Client,
    cid: int,
    mid: int
):
    """Désépingler un message"""
    try:
        return await client.unpin_chat_message(cid, mid)
    except FloodWait as e:
        logger.warning(f"FloodWait: Pause de {e.value}s")
        await asyncio.sleep(e.value)
        return await unpin_msg(client, cid, mid)
    except (BadRequest, RPCError) as e:
        logger.error(f"Erreur désépinglage {mid}@{cid}: {type(e).__name__} - {e}")
    except Exception as e:
        logger.error(f"Erreur inattendue (unpin_msg): {e}\n{traceback.format_exc()}")
    return None

async def send_log(
    client: Client,
    text: str,
    level: str = "INFO",
    markup: Optional[Union[InlineKeyboardMarkup, ReplyKeyboardMarkup]] = None,
    notify: bool = False,
    parse: ParseMode = ParseMode.HTML,
    preview: bool = False,
    max_length: int = 3900,
    include_ts: bool = True,
    part_suffix: str = " (part {}/{}):"
):
    """
    Envoie un message de log dans les canaux configurés avec découpage des longs textes

    :param client: Client Pyrogram
    :param text: Contenu du log
    :param level: Niveau de log (INFO, WARNING, ERROR, DEBUG)
    :param markup: Clavier optionnel
    :param notify: Notifier les utilisateurs (défaut: False)
    :param parse: Mode de parsing (défaut: HTML)
    :param preview: Désactiver l'aperçu des liens
    :param max_length: Longueur max par partie (défaut: 3900)
    :param include_ts: Inclure un timestamp dans le message
    :param part_suffix: Suffixe pour indiquer les parties
    """
    from datetime import datetime

    log_chats = settings.LOG_CHANNEL.split(" ") if settings.LOG_CHANNEL else []

    if not log_chats:
        logger.warning("Aucun canal de log configuré!")
        return

    level_icon = {
        "INFO": "ℹ️",
        "WARNING": "⚠️",
        "ERROR": "❌",
        "DEBUG": "🐞",
        "CRITICAL": "🔥"
    }.get(level.upper(), "📝")

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S") if include_ts else ""
    base_header = f"{level_icon} **{level}** {timestamp}"

    parts = []
    while text:
        part_header = base_header
        if len(parts) > 0:
            part_header += part_suffix.format(len(parts) + 1, "?")

        header_len = len(part_header) + 20
        available_len = max_length - header_len

        segment = text[:available_len]

        last_newline = segment.rfind('\n')
        if last_newline > 0 and len(segment) > available_len * 0.8:
            segment = segment[:last_newline]

        parts.append(f"{part_header}\n```\n{segment}```")

        text = text[len(segment):].lstrip('\n')

    total_parts = len(parts)
    parts = [part.replace("?", str(total_parts)) for part in parts]

    for chat_id in log_chats:
        try:
            cid = int(chat_id.strip())
        except ValueError:
            logger.error(f"ID de log invalide: {chat_id}")
            continue

        for i, part_text in enumerate(parts):
            await send_msg(
                client=client,
                cid=cid,
                text=part_text,
                markup=markup if i == total_parts - 1 else None,
                notify=notify and i == 0,
                parse=parse,
                preview=preview
            )
            await asyncio.sleep(0.5)

async def send_progress(
    client: Client,
    chat_id: int,
    message_id: Optional[int] = None,
    text: str = "Traitement en cours...",
    percent: float = 0,
    total: int = 100,
    current: int = 0,
    show_stats: bool = True,
    show_time: bool = False,
    show_bar: bool = True,
    parse: ParseMode = ParseMode.HTML,
    markup: Optional[InlineKeyboardMarkup] = None,
    reply_to_message_id: Optional[int] = None,
) -> Optional[Message]:
    """
    Affiche ou met à jour un message avec une barre de progression.
    """
    if percent <= 0 and total > 0:
        percent = (current / total) * 100

    parts = []
    if text:
        parts.append(text)
    if show_bar:
        parts.append(create_progress_bar(percent))
    if show_stats:
        parts.append(f"{current}/{total} ({percent:.1f}%)")

    if show_time:
        now = time.time()
        if not hasattr(send_progress, "_start_times"):
            send_progress._start_times = {}
        start_times = send_progress._start_times

        if chat_id not in start_times:
            start_times[chat_id] = now

        elapsed = now - start_times[chat_id]

        if percent > 0:
            remaining = (elapsed / percent) * (100 - percent)
            parts.append(f"Temps: {timedelta(seconds=int(elapsed))} / {timedelta(seconds=int(remaining))}")
        else:
            parts.append(f"Temps écoulé: {timedelta(seconds=int(elapsed))}")

    full_text = "\n".join(parts)

    async def _safe_edit():
        try:
            return await client.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=full_text,
                reply_markup=markup,
                parse_mode=parse,
                disable_web_page_preview=True
            )
        except MessageNotModified:
            return None
        except (MessageIdInvalid, MessageNotModified):
            return None
        except FloodWait as e:
            await asyncio.sleep(e.value)
            return await _safe_edit()
        except RPCError as e:
            logger.error(f"Erreur édition progress: {e}")
            return None

    async def _safe_send():
        try:
            return await client.send_message(
                chat_id=chat_id,
                text=full_text,
                reply_markup=markup,
                reply_to_message_id=reply_to_message_id,
                parse_mode=parse,
                disable_web_page_preview=True
            )
        except FloodWait as e:
            await asyncio.sleep(e.value)
            return await _safe_send()
        except RPCError as e:
            logger.error(f"Erreur envoi progress: {e}")
            return None

    if message_id:
        msg = await _safe_edit()
        if msg is None:
            msg = await _safe_send()
        return msg
    else:
        return await _safe_send()