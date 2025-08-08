from pyrogram import Client
from pyrogram.errors import AuthKeyUnregistered, FloodWait, SessionPasswordNeeded
from isocode import logger, settings
from isocode.utils.isoutils.progress import create_progress_bar
from isocode.utils.telegram.message import send_msg
import asyncio
import time
import os
import sys

class ClientManager:
    """Gestionnaire centralisé pour les clients Telegram avec support des sessions strings"""

    def __init__(self):
        self.clientbot = None
        self.userbot = None
        self.is_running = False
        self._clients = {}

    async def initialize(self):
        """Initialisation asynchrone des clients"""
        await self._create_clientbot()
        if settings.USERBOT_ENABLED:
            await self._create_userbot()
        self.is_running = True

    async def _create_clientbot(self):
        """Créer et démarrer le client principal (bot)"""
        try:
            self.clientbot = await self._init_client(
                client_type="clientbot",
                session_name="clientbot",
                plugins=dict(root="isocode/plugins"),
                sleep_threshold=30
            )
            self._clients["clientbot"] = self.clientbot
        except Exception as e:
            logger.critical(f"Échec d'initialisation ClientBot: {e}")
            sys.exit(1)

    async def _create_userbot(self):
        """Créer et démarrer le userbot avec session string ou fichier"""
        try:
            if settings.SESSION_STRING:
                self.userbot = await self._init_client(
                    client_type="userbot",
                    session_string=settings.SESSION_STRING,
                    sleep_threshold=60
                )
            else:
                self.userbot = await self._init_client(
                    client_type="userbot",
                    session_name="userbot",
                    sleep_threshold=60
                )
            self._clients["userbot"] = self.userbot
        except Exception as e:
            logger.error(f"Échec d'initialisation UserBot: {e}")

    async def _init_client(self,
                          client_type: str,
                          session_name: str = None,
                          session_string: str = None,
                          **kwargs) -> Client:
        """Initialise un client Pyrogram"""
        assert session_name or session_string, "Session name ou string requis"

        client = Client(
            name=session_name,
            session_string=session_string,
            api_id=settings.API_ID,
            api_hash=settings.API_HASH,
            workdir=settings.SESSION_DIR,
            bot_token=settings.BOT_TOKEN if client_type == "clientbot" else None,
            **kwargs
        )

        try:
            await client.start()
            logger.info(f"{client_type} démarré avec succès")
            return client
        except AuthKeyUnregistered:
            logger.warning(f"Session {client_type} invalide, démarrage interactif...")
            await self._interactive_start(client, client_type)
            return client
        except FloodWait as e:
            wait_time = e.value
            logger.warning(f"FloodWait: Attente de {wait_time}s pour {client_type}")
            progress = create_progress_bar(wait_time)
            for i in range(wait_time):
                await asyncio.sleep(1)
                logger.info(f"Attente {progress(i+1)}")
            return await self._init_client(client_type, session_name, session_string, **kwargs)

    async def _interactive_start(self, client: Client, client_name: str):
        """Démarrage interactif avec entrée manuelle des informations"""
        logger.info(f"Configuration de {client_name}:")

        phone = input("Numéro de téléphone (format international): ").strip()
        sent_code = await client.send_code(phone)

        code = input("Code de vérification reçu par SMS: ").strip()
        try:
            await client.sign_in(
                phone_number=phone,
                phone_code=code,
                phone_code_hash=sent_code.phone_code_hash
            )
        except SessionPasswordNeeded:
            password = input("2FA activé. Entrez votre mot de passe: ").strip()
            await client.check_password(password=password)

        logger.info(f"{client_name} authentifié avec succès")

    async def broadcast(self, chat_id: int, text: str):
        """Envoyer un message à tous les clients actifs"""
        for name, client in self._clients.items():
            try:
                await send_msg(client, chat_id, f"**[{name}]**\n{text}")
            except Exception as e:
                logger.error(f"Erreur broadcast {name}: {e}")

    async def stop_all(self):
        """Arrêter tous les clients proprement"""
        logger.info("Arrêt des clients...")
        for name, client in list(self._clients.items()):
            try:
                await client.stop()
                logger.info(f"Client {name} arrêté")
                del self._clients[name]
            except Exception as e:
                logger.error(f"Erreur arrêt {name}: {e}")
        self.is_running = False

    def get_client(self, client_type: str = "clientbot") -> Client:
        """Obtenir un client par son type"""
        return self._clients.get(client_type)

    def get_active_clients(self) -> dict:
        """Obtenir tous les clients actifs"""
        return self._clients.copy()

    async def check_health(self) -> dict:
        """Vérifier l'état des clients"""
        health_report = {}
        for name, client in self._clients.items():
            try:
                start_time = time.time()
                me = await client.get_me()
                latency = round(time.time() - start_time, 3)
                health_report[name] = {
                    "status": "OK",
                    "user": f"{me.first_name} ({me.id})",
                    "latency": latency
                }
            except Exception as e:
                health_report[name] = {
                    "status": "ERROR",
                    "error": str(e)
                }
        return health_report

clients = ClientManager()

async def initialize_clients():
    """Initialiser les clients (point d'entrée principal)"""
    await clients.initialize()

async def shutdown_clients():
    """Arrêter tous les clients (nettoyage final)"""
    await clients.stop_all()