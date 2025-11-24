#!/usr/bin/env python3
import asyncio
import signal
import time
from pyrogram import Client, filters
from pyrogram.types import BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeAllGroupChats
from isocode.plugins.video_hander import handle_video
from isocode.plugins.cmd import user as user_flt
from isocode.plugins.cmd import sudo as sudo_flt
from isocode.plugins.cmd import admin as admin_flt
from isocode.utils.isoutils.dbutils import initialize_database, get_auth_chat, close_database
from isocode.utils.isoutils.queue import queue_system, shutdown_queue_system
from isocode.utils.isoutils.routes import web_server
from isocode.utils.telegram.clients import initialize_clients, shutdown_clients, clients
from pyrogram.enums import ParseMode
from pyrogram.handlers import MessageHandler
from isocode import settings, logger
from isocode.utils.telegram.message import send_log
from aiohttp import web

log_chats = settings.LOG_CHANNELS if isinstance(settings.LOG_CHANNELS, list) else settings.LOG_CHANNELS.split(" ") if settings.LOG_CHANNELS else []


COMMON_CMDS = [
    BotCommand("start", "Démarrer le bot"),
    BotCommand("help", "Aide"),
]

USER_GROUP_CMDS = [
    BotCommand("encode", "Encoder une vidéo"),
    BotCommand("compress", "Compresser une vidéo"),
    BotCommand("merge", "Fusionner des vidéos"),
    BotCommand("split", "Couper une vidéo"),
    BotCommand("subs", "Gérer les sous-titres"),
    BotCommand("convert", "Convertir un média"),
]

ADMIN_GROUP_CMDS = [
    BotCommand("sudo_add", "Ajouter un sudo user"),
    BotCommand("sudo_remove", "Retirer un sudo user"),
    BotCommand("auth_chat", "Autoriser un chat"),
    BotCommand("remove_chat", "Retirer un chat"),
    BotCommand("shutdown", "Arrêter le bot"),
    BotCommand("restart", "Redémarrer le bot"),
]

ADMIN_PRIVATE_CMDS = [
    BotCommand("status", "Voir le statut"),
    BotCommand("ping", "Vérifier le bot"),
    BotCommand("logs", "Voir les logs"),
    BotCommand("info", "Infos du bot"),
    BotCommand("about", "À propos"),
    BotCommand("config", "Configurer le bot"),
    BotCommand("users", "Gérer les utilisateurs"),
    BotCommand("broadcast", "Envoyer un message global"),
    BotCommand("health", "État système"),
    BotCommand("encode_uri", "Encoder depuis un lien direct"),
]

async def set_bot_commands(botclient):
    await botclient.set_bot_commands(
        COMMON_CMDS + USER_GROUP_CMDS + ADMIN_GROUP_CMDS,
        scope=BotCommandScopeAllGroupChats()
    )

    await botclient.set_bot_commands(
        COMMON_CMDS + ADMIN_PRIVATE_CMDS + ADMIN_GROUP_CMDS,
        scope=BotCommandScopeAllPrivateChats()
    )

async def auth_group_filter(_, __, message):
    """Filtre personnalisé pour les groupes authentifiés"""
    if not message.chat or message.chat.type not in ["group", "supergroup"]:
        return False

    try:
        # get_auth_chat returns the authorized chat id(s) stored in DB (string)
        auth_chat = await get_auth_chat()
        if not auth_chat:
            return False

        # Support single id or space-separated ids
        try:
            auth_ids = [int(x) for x in str(auth_chat).split()]
        except Exception:
            # Fallback: compare as string
            return str(message.chat.id) == str(auth_chat)

        return message.chat.id in auth_ids
    except Exception as e:
        logger.error(f"Erreur vérification groupe authentifié: {e}")
        return False

# Création du filtre
auth_group_flt = filters.create(auth_group_filter)

async def main():
    """Fonction principale asynchrone"""
    logger.info("Démarrage de l'application IsoCode...")
    settings.START_TIME = time.time()
    await initialize_clients()
    asyncio.create_task(queue_system.start())

    botclient = clients.get_client()
    user_client = clients.get_client("userbot")

    if not botclient:
        logger.critical("Client bot non initialisé, arrêt.")
        return

    mebot = await botclient.get_me()
    logger.info(f"{mebot.first_name} ({mebot.id}) démarré avec succès")

    user_me = None
    if user_client:
        try:
            user_me = await user_client.get_me()
            logger.info(f"Userbot démarré: {user_me.first_name} ({user_me.id})")
        except Exception as e:
            logger.warning(f"Impossible d'obtenir userbot info: {e}")
    else:
        logger.info("Userbot désactivé ou non initialisé")
    await initialize_database()

    await set_bot_commands(botclient)
    apps = web.AppRunner(await web_server())
    await apps.setup()
    await web.TCPSite(apps, "0.0.0.0", 8080).start()

    # Handlers avec nouveau filtre pour groupes authentifiés
    botclient.add_handler(
        MessageHandler(
            handle_video,
            filters.private & (filters.video | filters.document) & (admin_flt | sudo_flt)
        )
    )

    # Nouveau handler pour groupes authentifiés
    botclient.add_handler(
        MessageHandler(
            handle_video,
            filters.group & (filters.video | filters.document) & auth_group_flt
        )
    )

    # Handler existant pour utilisateurs autorisés (gardé pour compatibilité)
    botclient.add_handler(
        MessageHandler(
            handle_video,
            filters.group & (filters.video | filters.document) & user_flt
        )
    )

    # Choisir le client à utiliser pour les opérations de log (userbot si disponible, sinon bot)
    client_for_logs = user_client or botclient

    for chat_id in log_chats:
        try:
            await client_for_logs.get_chat(int(chat_id))
        except Exception as e:
            logger.warning(f"Impossible de résoudre le chat {chat_id} : {e}")

    try:
        for chat in log_chats:
            # Construire le texte en tenant compte de l'absence possible du userbot
            user_info = f"Userbot: {user_me.first_name} ({user_me.id})" if user_me else "Userbot: (désactivé)"
            await send_log(
                client_for_logs,
                text=f"**Bot Version V.{settings.ISOCODE_VERSION}**\n\n"
                     f"Bot: {mebot.first_name} ({mebot.id})\n"
                     f"{user_info}",
                level="INFO",
                parse=ParseMode.MARKDOWN
            )
            logger.info(f"Message de démarrage envoyé à {chat}")
    except Exception as e:
        pass

    shutdown_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for signame in ('SIGINT', 'SIGTERM'):
        loop.add_signal_handler(
            getattr(signal, signame),
            lambda: shutdown_event.set()
        )

    try:
        await shutdown_event.wait()
    except asyncio.CancelledError:
        pass
    finally:
        await shutdown_queue_system()
        logger.info("Arrêt demandé, début du processus d'arrêt...")

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Interruption clavier détectée")
    except Exception as e:
        logger.error(f"Erreur inattendue: {e}")
    finally:
        logger.info("Arrêt des clients...")
        loop.run_until_complete(shutdown_clients())
        try:
            loop.run_until_complete(close_database())
        except Exception:
            logger.debug("Erreur lors de la fermeture de la base de données")
        loop.close()
        logger.info("Application arrêtée proprement")