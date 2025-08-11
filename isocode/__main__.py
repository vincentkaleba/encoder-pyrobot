import asyncio
import signal
import time
from aiohttp import web
from pyrogram.enums import ParseMode
from pyrogram.types import BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeAllGroupChats
from pyrogram import filters

from isocode import settings, logger
from isocode.plugins.data import handle_callback_query, hw_accel_checker
from isocode.plugins.video_hander import handle_video
from isocode.plugins.cmd import user as user_flt
from isocode.plugins.cmd import sudo as sudo_flt
from isocode.plugins.cmd import admin as admin_flt
from isocode.utils.isoutils.dbutils import initialize_database, get_auth_chat
import isocode.utils.isoutils.queue as queue
from isocode.utils.isoutils.routes import web_server
from isocode.utils.telegram.clients import initialize_clients, shutdown_clients, clients
from isocode.utils.telegram.message import send_log
from pyrogram.handlers import MessageHandler, CallbackQueryHandler

log_chats = (
    settings.LOG_CHANNELS
    if isinstance(settings.LOG_CHANNELS, list)
    else settings.LOG_CHANNELS.split(" ")
    if settings.LOG_CHANNELS
    else []
)

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
        scope=BotCommandScopeAllGroupChats(),
    )
    await botclient.set_bot_commands(
        COMMON_CMDS + ADMIN_PRIVATE_CMDS + ADMIN_GROUP_CMDS,
        scope=BotCommandScopeAllPrivateChats(),
    )

async def auth_group_filter(_, __, message):
    """Filtre personnalisé pour les groupes authentifiés"""
    if not message.chat or message.chat.type not in ["group", "supergroup"]:
        return False
    try:
        auth_chat = await get_auth_chat(message.chat.id)
        return auth_chat is not None
    except Exception as e:
        logger.error(f"Erreur vérification groupe authentifié: {e}")
        return False

auth_group_flt = filters.create(auth_group_filter)

async def main():
    logger.info("Démarrage de l'application IsoCode...")
    settings.START_TIME = time.time()

    # Initialisation clients Pyrogram
    await initialize_clients()

    # Initialisation système file d'attente encoding
    try:
        await queue.initialize_queue_system(max_concurrent=2)
    except Exception as e:
        logger.error(f"Erreur lors de l'initialisation de la queue d'encodage : {e}")
    else:
        logger.info("Système de file d'attente d'encodage initialisé avec succès")

    # Vérification matériel accélération
    hw_accel_checker.check_all()

    botclient = clients.get_client()
    user_client = clients.get_client("userbot")
    mebot = await botclient.get_me()
    logger.info(f"{mebot.first_name} ({mebot.id}) démarré avec succès")
    user_me = await user_client.get_me()
    logger.info(f"Userbot démarré: {user_me.first_name} ({user_me.id})")

    await initialize_database()

    await set_bot_commands(botclient)

    # Démarrage serveur web aiohttp
    apps = web.AppRunner(await web_server())
    await apps.setup()
    await web.TCPSite(apps, "0.0.0.0", 8080).start()
    asyncio.create_task(queue.monitor_disk_space("/", 30))

    # Ajout des handlers Pyrogram
    botclient.add_handler(
        MessageHandler(
            handle_video,
            filters.private & (filters.video | filters.document) & (admin_flt | sudo_flt),
        )
    )
    botclient.add_handler(
        MessageHandler(
            handle_video,
            filters.group & (filters.video | filters.document) & auth_group_flt,
        )
    )
    botclient.add_handler(
        MessageHandler(
            handle_video,
            filters.group & (filters.video | filters.document) & user_flt,
        )
    )
    botclient.add_handler(CallbackQueryHandler(handle_callback_query))

    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    # Gestion propre des signaux sous Linux (Ubuntu)
    for signame in ("SIGINT", "SIGTERM"):
        loop.add_signal_handler(getattr(signal, signame), shutdown_event.set)

    logger.info("En attente d'un signal SIGINT ou SIGTERM...")

    try:
        await shutdown_event.wait()
    except asyncio.CancelledError:
        pass

    logger.info("Signal d'arrêt reçu, début du processus d'arrêt...")

    try:
        await queue.shutdown_queue_system()
    except Exception as e:
        logger.error(f"Erreur lors de l'arrêt de la queue : {e}")

    # Arrêt des clients Pyrogram
    await shutdown_clients()

    logger.info("Application arrêtée proprement")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
